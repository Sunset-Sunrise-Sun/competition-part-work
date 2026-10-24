"""Domain types and the allowed task-state transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class TaskStatus(StrEnum):
    """Persisted task states required by Issue #3 / Phase 1A."""

    READY = "ready"
    WORKING = "working"
    REVIEW = "review"
    CHANGES_REQUESTED = "changes-requested"
    DONE = "done"
    NEEDS_OWNER = "needs-owner"


class ReviewVerdict(StrEnum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes-requested"
    NEEDS_OWNER = "needs-owner"


# The only transitions the store may persist. Anything else is a bug or an
# external-integrity failure and must pause rather than guess.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.READY: frozenset({TaskStatus.WORKING, TaskStatus.NEEDS_OWNER}),
    TaskStatus.WORKING: frozenset(
        {TaskStatus.REVIEW, TaskStatus.READY, TaskStatus.NEEDS_OWNER}
    ),
    TaskStatus.REVIEW: frozenset(
        {TaskStatus.DONE, TaskStatus.CHANGES_REQUESTED, TaskStatus.NEEDS_OWNER}
    ),
    TaskStatus.CHANGES_REQUESTED: frozenset(
        {TaskStatus.WORKING, TaskStatus.NEEDS_OWNER}
    ),
    TaskStatus.DONE: frozenset(),
    TaskStatus.NEEDS_OWNER: frozenset(),
}


class AutopilotError(RuntimeError):
    """Base error for the skeleton."""


class LeaseNotHeld(AutopilotError):
    """A scheduler tried to claim work without holding the global lease."""


class LeaseLost(AutopilotError):
    """A worker's lease generation/fence is no longer current."""


class StaleClaim(AutopilotError):
    """A worker tried to mutate a task claimed by a newer attempt."""


class InvalidTransition(AutopilotError):
    """A state transition was not allowed by the state machine."""


class ExecutionTimeout(AutopilotError):
    """The executor did not finish within the configured timeout."""


class ReviewTimeout(AutopilotError):
    """The reviewer did not finish within the configured timeout."""


class AdapterDisabledError(AutopilotError):
    """A real external adapter is disabled (the default in Phase 1A)."""


class AdapterCredentialMissing(AutopilotError):
    """A real adapter was enabled but its credential is not configured."""


class AdapterNotImplementedError(AutopilotError):
    """An adapter is deliberately only a placeholder in this phase."""


@dataclass(frozen=True)
class TaskSpec:
    """A task supplied by a TaskSource."""

    task_id: str
    title: str
    base_sha: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskRecord:
    """A task as persisted in SQLite."""

    task_id: str
    title: str
    status: TaskStatus
    base_sha: str
    head_sha: str | None
    payload: Mapping[str, Any]
    rework_rounds: int
    attempts: int
    last_error: str | None
    branch: str | None
    created_at: float
    updated_at: float
    claim_token: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """The executor's committed result for one attempt."""

    head_sha: str
    summary: str = ""
    artifact: str = ""


@dataclass(frozen=True)
class ReviewResult:
    """A review that must be bound to an exact head SHA."""

    verdict: ReviewVerdict
    head_sha: str
    defects: tuple[str, ...] = ()
    reviewer: str = "fake-reviewer"
    notes: str = ""


@dataclass(frozen=True)
class ReviewOutcome:
    """How the state machine consumed a review."""

    accepted: bool
    stale: bool
    status: TaskStatus
    message: str
