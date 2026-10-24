"""Single-slot scheduler loop for the Phase 1A skeleton.

The scheduler is deliberately local and credential-free. It polls a TaskSource,
executes at most one task per ``run_once`` while holding the SQLite global
lease, and reviews the exact head it committed. Real GitHub/DSH adapters are
not wired here.
"""

from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .interfaces import Executor, Reviewer, TaskSource
from .models import (
    AutopilotError,
    ExecutionResult,
    ExecutionTimeout,
    InvalidTransition,
    ReviewOutcome,
    ReviewResult,
    ReviewTimeout,
    TaskRecord,
    TaskStatus,
)
from .store import SqliteStore


@dataclass(frozen=True)
class SchedulerConfig:
    lease_ttl_seconds: float = 60.0
    execution_timeout_seconds: float = 300.0
    review_timeout_seconds: float = 60.0
    max_source_batch: int = 50
    max_steps_per_run: int = 50


@dataclass(frozen=True)
class RunResult:
    task_id: str
    stage: str
    status: TaskStatus
    execution: ExecutionResult | None = None
    review: ReviewResult | None = None
    outcome: ReviewOutcome | None = None
    error: str | None = None


class Scheduler:
    """A single-task-at-a-time scheduler with a SQLite-backed global lease."""

    def __init__(
        self,
        store: SqliteStore,
        source: TaskSource,
        executor: Executor,
        reviewer: Reviewer,
        workspace: str | Path,
        *,
        config: SchedulerConfig | None = None,
        owner: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.source = source
        self.executor = executor
        self.reviewer = reviewer
        self.workspace = Path(workspace)
        if not self.workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {self.workspace}")
        self.config = config or SchedulerConfig()
        self.clock = clock
        self.owner = owner or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )

    # ------------------------------------------------------------------ leases
    def _recover_if_expired(self, now: float) -> dict[str, int] | None:
        lease = self.store.get_lease()
        if (
            lease is not None
            and lease["owner"] is not None
            and lease["expires_at"] is not None
            and float(lease["expires_at"]) > now
        ):
            return None
        return self.store.recover(now)

    def run_once(self) -> RunResult | None:
        """Acquire the lease and process at most one task/stage.

        Returns None when another scheduler owns the lease or no work is ready.
        """
        now = self.clock()
        self._recover_if_expired(now)
        if not self.store.acquire_lease(self.owner, self.config.lease_ttl_seconds, now):
            return None
        try:
            self._poll_source(now)
            task = self.store.claim_next(self.owner, now)
            if task is not None:
                return self._execute_and_review(task, now)
            pending_review = self.store.next_review_task()
            if pending_review is not None:
                return self._review(pending_review, now)
            return None
        finally:
            self.store.release_lease(self.owner)

    def run_until_idle(self, *, max_steps: int | None = None) -> list[RunResult]:
        """Process tasks until no work remains or a task needs its owner.

        A ``needs-owner`` result stops the loop deliberately: further automatic
        execution is unsafe until the owner inspects the task.
        """
        limit = max_steps if max_steps is not None else self.config.max_steps_per_run
        results: list[RunResult] = []
        for _ in range(max(1, limit)):
            result = self.run_once()
            if result is None:
                break
            results.append(result)
            if result.status is TaskStatus.NEEDS_OWNER:
                break
        return results

    def _poll_source(self, now: float) -> None:
        for _ in range(self.config.max_source_batch):
            spec = self.source.next_ready()
            if spec is None:
                break
            self.store.enqueue_task(spec, now)

    # ------------------------------------------------------------- execution
    def _execute_and_review(self, task: TaskRecord, now: float) -> RunResult:
        attempt = task.attempts
        try:
            result = self.executor.execute(
                task,
                attempt,
                self.workspace,
                self.config.execution_timeout_seconds,
            )
        except ExecutionTimeout as error:
            updated = self.store.record_execution_failure(
                task.task_id, f"timeout: {error}", self.clock(), retryable=False, timeout=True
            )
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=updated.status,
                error=f"execution timeout: {error}",
            )
        except OSError as error:
            updated = self.store.record_execution_failure(
                task.task_id,
                f"retryable executor error: {error}",
                self.clock(),
                retryable=True,
            )
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=updated.status,
                error=f"executor error: {error}",
            )
        except Exception as error:  # noqa: BLE001 - fail closed on unknown errors
            updated = self.store.record_execution_failure(
                task.task_id,
                f"unexpected executor error: {type(error).__name__}: {error}",
                self.clock(),
                retryable=False,
            )
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=updated.status,
                error=f"executor error: {error}",
            )

        if not isinstance(result, ExecutionResult):
            updated = self.store.record_execution_failure(
                task.task_id,
                "executor returned an invalid result object",
                self.clock(),
                retryable=False,
            )
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=updated.status,
                error="invalid execution result",
            )
        if not isinstance(result.head_sha, str) or not result.head_sha.strip():
            updated = self.store.record_execution_failure(
                task.task_id,
                "executor returned an empty head_sha",
                self.clock(),
                retryable=False,
            )
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=updated.status,
                error="empty head_sha",
            )

        try:
            updated = self.store.record_execution_result(
                task.task_id, result.head_sha, result.summary, self.clock()
            )
        except InvalidTransition as error:
            paused = self.store.pause(task.task_id, str(error), self.clock())
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=paused.status,
                error=str(error),
            )
        return self._review(updated, now, execution=result)

    # ---------------------------------------------------------------- review
    def _review(
        self,
        task: TaskRecord,
        now: float,
        *,
        execution: ExecutionResult | None = None,
    ) -> RunResult:
        head_sha = task.head_sha
        if not head_sha:
            paused = self.store.pause(task.task_id, "review without head SHA", self.clock())
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=paused.status,
                error="missing head SHA",
            )
        try:
            review = self.reviewer.review(
                task, head_sha, self.config.review_timeout_seconds
            )
        except ReviewTimeout as error:
            updated = self.store.mark_review_failure(
                task.task_id, f"review timeout: {error}", self.clock()
            )
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=updated.status,
                error=f"review timeout: {error}",
            )
        except Exception as error:  # noqa: BLE001 - fail closed on unknown errors
            updated = self.store.mark_review_failure(
                task.task_id,
                f"reviewer error: {type(error).__name__}: {error}",
                self.clock(),
            )
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=updated.status,
                error=f"reviewer error: {error}",
            )

        if not isinstance(review, ReviewResult) or review.head_sha != head_sha:
            paused = self.store.pause(
                task.task_id,
                "review result does not match current head SHA",
                self.clock(),
            )
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=paused.status,
                error="stale or malformed review",
            )

        event_key = f"review:{task.task_id}:{head_sha}:{review.reviewer}"
        outcome = self.store.submit_review(
            task.task_id, review, self.clock(), event_key=event_key
        )
        if outcome.stale:
            paused = self.store.pause(task.task_id, outcome.message, self.clock())
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=paused.status,
                outcome=outcome,
                review=review,
                execution=execution,
                error=outcome.message,
            )
        return RunResult(
            task_id=task.task_id,
            stage="review" if execution is None else "execute-review",
            status=outcome.status,
            execution=execution,
            review=review,
            outcome=outcome,
        )

    # ------------------------------------------------------------- diagnostics
    def snapshot(self) -> dict[str, object]:
        lease = self.store.get_lease()
        return {
            "owner": self.owner,
            "lease": lease,
            "counts": self.store.counts(),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "head_sha": task.head_sha,
                    "rework_rounds": task.rework_rounds,
                    "attempts": task.attempts,
                    "last_error": task.last_error,
                }
                for task in self.store.list_tasks()
            ],
        }
