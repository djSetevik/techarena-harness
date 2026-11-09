"""Uncalibrated static baseline: no labels, identifiers or reward as features."""
from dataclasses import dataclass
from src.domain import TaskSpec


@dataclass(frozen=True)
class Prediction:
    task_type: str
    instruction_bytes: int
    expected_units: int
    high_units: int
    output_cap: int
    version: str = 'static-v1-uncalibrated'
    approximate: bool = True


def predict(task: TaskSpec) -> Prediction:
    size = len(task.instruction.encode('utf-8'))
    cap = 2048 if task.task_type == 'coding' else 512
    # UTF-8 byte count + overhead is an explicit rough input estimate; this
    # is not an exact tokenizer. Adapter must re-estimate the full prompt.
    return Prediction(task.task_type, size, size + 10 * (cap // 2),
                      2 * (size + 1024) + 10 * cap, cap)
