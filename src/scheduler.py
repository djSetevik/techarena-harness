"""Value/cost heuristic; UNKNOWN remains eligible. No implicit retries."""
from dataclasses import dataclass
from src.budget import BudgetExceeded
from src.domain import FeasibilityResult, Status, TaskSpec
from src.estimator import Prediction


@dataclass(frozen=True)
class Candidate:
    task: TaskSpec
    feasibility: FeasibilityResult
    prediction: Prediction


def ranked(candidates):
    # No calibrated success probabilities are available yet; equal weight.
    return sorted((c for c in candidates if c.feasibility.status != Status.UNSOLVABLE),
                  key=lambda c: c.task.reward / max(1, c.prediction.expected_units), reverse=True)


def select(candidates, budget, adapter, recorder, *, max_calls, adapter_missing_reason='adapter_unavailable'):
    """Lazy selection rechecks remaining budget after each attempted request."""
    calls = 0
    for candidate in ranked(candidates):
        task = candidate.task
        scope = str(task.task_dir)
        # Prevent an adapter invocation before its original forecast exists.
        recorder.initial(scope)
        reason = None
        if getattr(adapter, 'calls', calls) >= max_calls:
            reason = 'call_limit'
        elif candidate.prediction.high_units > budget.snapshot()['available_units'] or budget.closed:
            reason = 'budget'
        elif adapter is None:
            reason = adapter_missing_reason
        if reason:
            recorder.emit('task_end', scope, skip_reason=reason)
            continue
        calls += 1
        yield candidate


async def run_paid(candidates, budget, adapter, recorder, *, max_calls):
    """Adapter's single-attempt method must use this same BudgetManager."""
    results = []
    for candidate in select(candidates, budget, adapter, recorder, max_calls=max_calls):
        task = candidate.task
        scope = str(task.task_dir)
        try:
            answer = await adapter(candidate, budget)
        except BudgetExceeded:
            recorder.emit('task_end', scope, skip_reason='budget')
            continue
        results.append((task, answer))
    return results
