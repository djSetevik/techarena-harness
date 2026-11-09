"""Print an installed SDK API fingerprint, not configuration or credentials."""
import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, '/app')
from src.oj_adapter import configure_sdk_logging
configure_sdk_logging()
from openjiuwen.core.foundation.llm import Model, ModelClientConfig, ModelRequestConfig
from openjiuwen.core.foundation.llm.schema.message import UsageMetadata

root = Path(inspect.getfile(Model)).parent
files = ('model.py', 'schema/config.py', 'schema/message.py', 'model_clients/openai_model_client.py')
print(json.dumps(dict(version=importlib.metadata.version('openjiuwen'),
    model_invoke_signature=str(inspect.signature(Model.invoke)),
    model_source=str(inspect.getfile(Model)), invoke_line=inspect.getsourcelines(Model.invoke)[1],
    client_config_fields=sorted(ModelClientConfig.model_fields),
    request_config_fields=sorted(ModelRequestConfig.model_fields),
    usage_fields=sorted(UsageMetadata.model_fields),
    default_max_retries=ModelClientConfig.model_fields['max_retries'].default,
    source_sha256={file: hashlib.sha256((root / file).read_bytes()).hexdigest() for file in files}), indent=2))
