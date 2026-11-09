"""Runtime domain: evaluation labels are deliberately absent."""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    task_type: str
    instruction: str
    reward: float
    check: str
    task_dir: Path
    workspace: Path


class Status(str, Enum):
    SOLVABLE = 'SOLVABLE'
    UNSOLVABLE = 'UNSOLVABLE'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class Evidence:
    source: str
    detail: str
    possible_answers: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeasibilityResult:
    status: Status
    reason_code: str
    evidence: tuple[Evidence, ...] = ()
    scope_complete: bool = False
    required_information: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    alternatives_checked: tuple[str, ...] = ()
    parser_version: str = 'offline-v1'
    answer: str | None = None
