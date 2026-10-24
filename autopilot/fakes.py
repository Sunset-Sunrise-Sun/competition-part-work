"""Fake, credential-free adapters used by the Phase 1A tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .models import ExecutionResult, ReviewResult, TaskRecord, TaskSpec


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeTaskSource:
    """Returns each queued task once, in order."""

    def __init__(self, tasks: list[TaskSpec]) -> None:
        self._tasks = list(tasks)
        self.calls = 0

    def next_ready(self) -> TaskSpec | None:
        self.calls += 1
        if not self._tasks:
            return None
        return self._tasks.pop(0)


PlanItem = ExecutionResult | BaseException | Callable[[TaskRecord, int], ExecutionResult]
ReviewItem = ReviewResult | BaseException | Callable[[TaskRecord, str], ReviewResult]


class FakeExecutor:
    """Scripted executor; never touches the real system or model."""

    def __init__(self, plans: dict[str, list[PlanItem]]) -> None:
        self._plans = {task_id: list(items) for task_id, items in plans.items()}
        self.calls: list[tuple[str, int]] = []

    def execute(
        self,
        task: TaskRecord,
        attempt: int,
        workspace: Path,
        timeout_seconds: float,
    ) -> ExecutionResult:
        self.calls.append((task.task_id, attempt))
        queue = self._plans.get(task.task_id)
        if not queue:
            raise AssertionError(f"no fake execution plan for {task.task_id}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(task, attempt)
        return item


class FakeReviewer:
    """Scripted structured reviewer; reviews are keyed by (task, head SHA)."""

    def __init__(self, plans: dict[tuple[str, str], ReviewItem]) -> None:
        self._plans = dict(plans)
        self.calls: list[tuple[str, str]] = []

    def review(
        self,
        task: TaskRecord,
        head_sha: str,
        timeout_seconds: float,
    ) -> ReviewResult:
        self.calls.append((task.task_id, head_sha))
        key = (task.task_id, head_sha)
        if key not in self._plans:
            raise AssertionError(f"no fake review plan for {key}")
        item: Any = self._plans[key]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(task, head_sha)
        return item
