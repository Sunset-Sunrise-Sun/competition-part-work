"""Protocols for task sources, execution, review and publication hooks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .models import ExecutionResult, ReviewResult, TaskRecord, TaskSpec

if TYPE_CHECKING:
    from .scheduler import RunResult


class TaskSource(Protocol):
    """Supplies ready task specs; implementations must be idempotent by task_id."""

    def next_ready(self) -> TaskSpec | None:
        """Return the next task spec, or None when this source has nothing ready."""


class Executor(Protocol):
    """Executes one task attempt in an isolated workspace."""

    def execute(
        self,
        task: TaskRecord,
        attempt: int,
        workspace: Path,
        timeout_seconds: float,
    ) -> ExecutionResult:
        """Return the committed head SHA, or raise for failure/timeout."""


class Reviewer(Protocol):
    """Reviews one exact head SHA; must never infer a pass from free text."""

    def review(
        self,
        task: TaskRecord,
        head_sha: str,
        timeout_seconds: float,
    ) -> ReviewResult:
        """Return a structured review bound to head_sha."""


class ApprovedPublisher(Protocol):
    """Publishes a reviewed commit without merging it."""

    def publish_approved(
        self,
        task: TaskRecord,
        review: ReviewResult,
        execution: ExecutionResult | None,
    ) -> str:
        """Push a dedicated branch and return the Draft PR URL."""


class TaskResultNotifier(Protocol):
    """Synchronizes task state back to its external queue."""

    def on_task_result(self, task: TaskRecord, result: RunResult) -> None:
        """Update labels/comments after the local state transition."""
