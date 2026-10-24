"""Interfaces for task sources, executors and reviewers.

Real adapters are deliberately not wired in Phase 1A. The scheduler only depends
on these protocols so fake, local implementations can drive the whole loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import ExecutionResult, ReviewResult, TaskRecord, TaskSpec


class TaskSource(Protocol):
    """Supplies ready task specs; implementations must be idempotent by task_id."""

    def next_ready(self) -> TaskSpec | None:
        """Return the next task spec, or None when this source has nothing ready."""


class Executor(Protocol):
    """Executes one task attempt in the isolated workspace."""

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
        """Return a structured review bound to ``head_sha``."""
