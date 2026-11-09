"""Single paid-call boundary around openJiuwen Model.invoke.

The SDK is lazy and fixed-version; offline tests inject a fake Model handle.
No provider SDK, alternate model, automatic retry, or background model call.
"""
import asyncio
from dataclasses import asdict
from importlib.metadata import version
import json
from urllib.parse import urlsplit

from src.budget import Usage, BudgetExceeded, count


def configure_sdk_logging():
    # Configure before importing Model: connector registration initializes lazy
    # SDK logging during import. Keep SDK prompt/config payloads out of logs;
    # harness telemetry is the explicit whitelist for usage and diagnostics.
    from openjiuwen.core.common.logging.log_config import configure_log_config
    configure_log_config(dict(backend='default', level='CRITICAL', log_path='/tmp/techarena-sdk',
                             output=[], interface_output=[], performance_output=[], propagate=False))


def sdk_model(*, model_name, api_base, api_key, timeout):
    if version('openjiuwen') != '0.1.19':
        raise ValueError('SDK version differs from configured pin openjiuwen==0.1.19')
    configure_sdk_logging()
    from openjiuwen.core.foundation.llm import Model, ModelClientConfig, ModelRequestConfig
    return Model(
        model_client_config=ModelClientConfig(client_provider='OpenAI', api_base=api_base,
            api_key=api_key, timeout=timeout, max_retries=0, verify_ssl=True),
        model_config=ModelRequestConfig(model=model_name, temperature=0))


class OJAdapter:
    def __init__(self, budget, recorder, *, model_name, model=None, api_base=None,
                 api_key=None, timeout=60, reasoning_in_output=True, max_calls=3,
                 allowed_models=None, model_factory=None):
        if not model_name or timeout <= 0 or type(max_calls) is not int or max_calls < 0:
            raise ValueError('Explicit fixed model, positive timeout and nonnegative call limit required')
        self.budget, self.recorder = budget, recorder
        self.model_name, self.timeout = model_name, timeout
        self.reasoning_in_output = reasoning_in_output
        self.max_calls, self.calls = max_calls, 0
        self.allowed_models = frozenset((model_name,)) if allowed_models is None else frozenset(allowed_models)
        if model_name not in self.allowed_models or any(not isinstance(name, str) or not name for name in self.allowed_models):
            raise ValueError('Explicit nonempty model allowlist must include the primary model')
        if model is None:
            parsed = urlsplit(api_base or '')
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError('Explicit proxy base URL required')
            if not api_key:
                raise ValueError('Proxy credentials missing')
            model = sdk_model(model_name=model_name, api_base=api_base,
                              api_key=api_key, timeout=timeout)
            self._factory = lambda name: sdk_model(model_name=name, api_base=api_base, api_key=api_key, timeout=timeout)
        else:
            self._factory = model_factory or (lambda name: model)
        self.model = model
        self._models = {model_name: model}

    async def invoke(self, scope, messages, *, output_cap, model_name=None):
        self.recorder.initial(scope)
        selected = self.model_name if model_name is None else model_name
        if selected not in self.allowed_models:
            raise ValueError('Model selection violates the explicit adapter allowlist')
        count(output_cap)
        if output_cap == 0:
            raise ValueError('Positive output cap required')
        # Reserve from the complete prompt, including files and repair feedback.
        # UTF-8 bytes are an approximate estimate, not a Qwen tokenizer.
        size = len(json.dumps(messages, ensure_ascii=False).encode('utf-8'))
        reserve = 2 * (size + 1024) + 10 * output_cap
        if self.calls >= self.max_calls:
            raise BudgetExceeded('Global model call limit')
        if selected not in self._models:
            self._models[selected] = self._factory(selected)
        handle = self._models[selected]
        self.recorder.emit('reestimate', scope, high_units=reserve, approximate=True)
        normalized, raw_counts = None, {}
        started = False

        async def request():
            nonlocal started
            # There is no await between checking and incrementing the call cap.
            if self.calls >= self.max_calls:
                raise BudgetExceeded('Global model call limit')
            started = True
            self.calls += 1
            self.recorder.emit('llm_request', scope, model=selected,
                               output_cap=output_cap, reservation_units=reserve)
            return await asyncio.wait_for(handle.invoke(messages=messages,
                model=selected, max_tokens=output_cap, temperature=0,
                timeout=self.timeout), timeout=self.timeout)

        def usage_of(response):
            nonlocal normalized, raw_counts
            metadata = getattr(response, 'usage_metadata', None)
            if metadata is None:
                return None
            if hasattr(metadata, 'model_dump'):
                metadata = metadata.model_dump()
            if not isinstance(metadata, dict):
                return None
            try:
                inp, out = count(metadata['input_tokens']), count(metadata['output_tokens'])
                reasoning_value = metadata.get('reasoning_tokens')
                cached_value = metadata.get('cache_tokens')
                reasoning = count(0 if reasoning_value is None else reasoning_value)
                cached = count(0 if cached_value is None else cached_value)
                usage = Usage(inp, out if self.reasoning_in_output else out + reasoning,
                              reasoning, cached)
            except (KeyError, ValueError, TypeError):
                return None
            normalized = usage
            raw_counts = {key: metadata[key] for key in ('input_tokens', 'output_tokens',
                          'reasoning_tokens', 'cache_tokens') if key in metadata}
            return usage

        try:
            response = await self.budget.execute(reserve, request, usage_of)
            # The ledger already owns the known charge. Disk-full/stream errors
            # here must never turn actual usage into an uncertain reservation.
            if normalized is not None:
                self.recorder.emit('llm_usage', scope, **asdict(normalized),
                                   cost_units=normalized.units, raw_usage=raw_counts, model=selected)
        finally:
            if started and normalized is None:
                self.recorder.emit('unresolved_usage', scope, units=reserve)
        text = getattr(response, 'content', None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Model returned no text')
        if len(text.encode('utf-8')) > 1024 * 1024:
            raise ValueError('Model output too large')
        return text.strip()
