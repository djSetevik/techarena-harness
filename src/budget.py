"""Shared integer ledger. One attempt per execute(); no implicit retries.

Units are tenths of an output token. Estimates are approximate, not a proven
provider charge cap. Uncertain sent requests retain their whole reservation.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Awaitable, Callable, TypeVar


class BudgetExceeded(RuntimeError):
    pass


class ProxyExhausted(RuntimeError):
    """Adapter maps only a confirmed proxy budget-exhaustion response here."""


def limit_units(value: str | None, *, offline: bool = False) -> int:
    if value is None:
        if offline:
            return 0
        raise ValueError('BUDGET is required for model calls')
    try:
        number = Decimal(value)
        units = number * 10
        if not units.is_finite() or units < 0 or units != units.to_integral_value():
            raise ValueError('BUDGET must be nonnegative in tenths of a token')
        return int(units)
    except InvalidOperation as exc:
        raise ValueError('Invalid BUDGET') from exc


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError('Token counts must be nonnegative integers')
    return value


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int  # includes reasoning after normalization
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    def __post_init__(self):
        for value in (self.input_tokens, self.output_tokens, self.reasoning_tokens, self.cached_tokens):
            count(value)
        if self.reasoning_tokens > self.output_tokens or self.cached_tokens > self.input_tokens:
            raise ValueError('Inconsistent usage details')

    @property
    def units(self):
        return self.input_tokens + 10 * self.output_tokens


def normalize_usage(raw: dict, *, reasoning_in_output: bool) -> Usage:
    """Explicit OpenAI-style schema; the adapter must confirm its semantics.

    A separate-reasoning fixture sets reasoning_in_output=False. Cached input
    is informational only and never subtracted from prompt_tokens.
    """
    prompt = count(raw['prompt_tokens'])
    output = count(raw['completion_tokens'])
    reasoning = count((raw.get('completion_tokens_details') or {}).get('reasoning_tokens', 0))
    cached = count((raw.get('prompt_tokens_details') or {}).get('cached_tokens', 0))
    return Usage(prompt, output if reasoning_in_output else output + reasoning, reasoning, cached)


T = TypeVar('T')


class BudgetManager:
    def __init__(self, total_units: int, safety_units: int = 0):
        self.limit = count(total_units)
        self.safety = count(safety_units)
        self.actual = 0
        self.unresolved = 0
        self.closed = False
        self._lock = RLock()
        self._active = {}
        self._next = 0

    def snapshot(self):
        with self._lock:
            active = sum(amount for amount, _ in self._active.values())
            return dict(limit_units=self.limit, actual_units=self.actual,
                        unresolved_units=self.unresolved, reserved_units=active,
                        available_units=max(0, self.limit - self.safety - self.actual - self.unresolved - active),
                        closed=self.closed)

    def reserve(self, units: int) -> int:
        count(units)
        if units == 0:
            raise ValueError('A paid attempt needs a positive reservation')
        with self._lock:
            if self.closed or units > self.snapshot()['available_units']:
                raise BudgetExceeded('Insufficient budget or ledger stopped')
            self._next += 1
            self._active[self._next] = (units, False)
            return self._next

    def sent(self, ticket: int):
        with self._lock:
            amount, sent = self._active[ticket]
            if sent:
                raise ValueError('Attempt already sent')
            self._active[ticket] = amount, True

    def finish(self, ticket: int, usage: Usage | None = None):
        if usage is not None and not isinstance(usage, Usage):
            raise ValueError('Normalization must return Usage or None')
        with self._lock:
            amount, sent = self._active.pop(ticket)
            if usage is not None:
                self.actual += usage.units
                if usage.units > amount:
                    # Approximate reservation underestimated: record the real
                    # charge and stop, never hide it by clipping to the reserve.
                    self.closed = True
            elif sent:
                self.unresolved += amount
                # Unknown charge may exceed the estimate. Fail closed rather
                # than risk continuing with a falsely precise remaining budget.
                self.closed = True

    async def execute(self, units: int, request: Callable[[], Awaitable[T]],
                      usage_of: Callable[[T], Usage | None]) -> T:
        ticket = self.reserve(units)
        self.sent(ticket)
        try:
            response = await request()
            usage = usage_of(response)
            if usage is not None and not isinstance(usage, Usage):
                raise ValueError('Normalization must return Usage or None')
        except BaseException as exc:
            self.finish(ticket)
            if isinstance(exc, ProxyExhausted):
                with self._lock:
                    self.closed = True
            raise
        self.finish(ticket, usage)
        # Parsing/compiling/testing of the response happens after usage settles.
        return response
