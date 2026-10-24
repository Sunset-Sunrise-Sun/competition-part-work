"""Single-slot scheduler loop for the Phase 1A skeleton.

The scheduler is deliberately local and credential-free. It polls a TaskSource,
executes at most one task per ``run_once`` while holding the SQLite global
lease, and reviews the exact head it committed. Real GitHub/DSH adapters are
not wired here.

Two lease protections are used:

* a background heartbeat renews the lease while a long execution/review runs;
* every write carries the lease generation (fence) and execution writes also
  carry the per-claim token, so a stale worker cannot mutate a newer attempt.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .interfaces import Executor, Reviewer, TaskSource
from .models import (
    ExecutionResult,
    ExecutionTimeout,
    InvalidTransition,
    LeaseLost,
    ReviewOutcome,
    ReviewResult,
    ReviewTimeout,
    StaleClaim,
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
    lease_heartbeat_enabled: bool = True


@dataclass(frozen=True)
class RunResult:
    task_id: str
    stage: str
    status: TaskStatus
    execution: ExecutionResult | None = None
    review: ReviewResult | None = None
    outcome: ReviewOutcome | None = None
    error: str | None = None
    lease_lost: bool = False


class LeaseHeartbeat:
    """Renews a held lease from a separate SQLite connection.

    The main worker's calls are long-running (executor/reviewer); without this
    heartbeat a 60s TTL would expire during a 300s execution.
    """

    def __init__(
        self,
        db_path: str | Path,
        owner: str,
        fence: int,
        ttl_seconds: float,
        *,
        clock: Callable[[], float] = time.time,
        interval_seconds: float | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._owner = owner
        self._fence = fence
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._interval = interval_seconds or max(
            0.02, min(ttl_seconds / 3.0, 5.0)
        )
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread: threading.Thread | None = None
        self._store: SqliteStore | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def lost_event(self) -> threading.Event:
        """Cancellation signal for subprocess adapters when the lease is lost."""
        return self._lost

    def start(self) -> None:
        self._store = SqliteStore(self._db_path)
        self._thread = threading.Thread(
            target=self._run,
            name="autopilot-lease-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        assert self._store is not None
        while not self._stop.wait(self._interval):
            try:
                renewed = self._store.renew_lease(
                    self._owner,
                    self._ttl_seconds,
                    self._clock(),
                    self._fence,
                )
            except Exception:  # noqa: BLE001 - loss of heartbeat is fail-closed
                self._lost.set()
                return
            if not renewed:
                self._lost.set()
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval * 3.0))
        if self._store is not None:
            self._store.close()
            self._store = None


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
        fence = self.store.acquire_lease(
            self.owner, self.config.lease_ttl_seconds, now
        )
        if fence is None:
            return None

        heartbeat: LeaseHeartbeat | None = None
        if self.config.lease_heartbeat_enabled:
            heartbeat = LeaseHeartbeat(
                self.store.db_path,
                self.owner,
                fence,
                self.config.lease_ttl_seconds,
                clock=self.clock,
            )
            heartbeat.start()
        try:
            self._poll_source(now)
            cancel_event = heartbeat.lost_event if heartbeat is not None else None
            task = self.store.claim_next(self.owner, self.clock(), fence)
            if task is not None:
                return self._execute_and_review(
                    task, now, fence, cancel_event=cancel_event
                )
            pending_review = self.store.next_review_task()
            if pending_review is not None:
                return self._review(
                    pending_review, now, fence, cancel_event=cancel_event
                )
            return None
        except (LeaseLost, StaleClaim):
            # The fence already failed; another worker owns the next attempt.
            return None
        finally:
            if heartbeat is not None:
                heartbeat.stop()
            self.store.release_lease(self.owner, fence)

    def run_until_idle(self, *, max_steps: int | None = None) -> list[RunResult]:
        """Process tasks until no work remains or a task needs its owner.

        A ``needs-owner`` result stops the loop deliberately: further automatic
        execution is unsafe until the owner inspects the task. A stale worker
        result also stops the loop rather than interfering with a newer worker.
        """
        limit = max_steps if max_steps is not None else self.config.max_steps_per_run
        results: list[RunResult] = []
        for _ in range(max(1, limit)):
            result = self.run_once()
            if result is None:
                break
            results.append(result)
            if result.status is TaskStatus.NEEDS_OWNER or result.lease_lost:
                break
        return results

    def _poll_source(self, now: float) -> None:
        for _ in range(self.config.max_source_batch):
            spec = self.source.next_ready()
            if spec is None:
                break
            self.store.enqueue_task(spec, now)

    # ------------------------------------------------------------- execution
    def _execute_and_review(
        self,
        task: TaskRecord,
        now: float,
        fence: int,
        *,
        cancel_event: threading.Event | None = None,
    ) -> RunResult:
        attempt = task.attempts
        try:
            execute_cancellable = getattr(self.executor, "execute_cancellable", None)
            if cancel_event is not None and callable(execute_cancellable):
                result = execute_cancellable(
                    task,
                    attempt,
                    self.workspace,
                    self.config.execution_timeout_seconds,
                    cancel_event,
                )
            else:
                result = self.executor.execute(
                    task,
                    attempt,
                    self.workspace,
                    self.config.execution_timeout_seconds,
                )
        except (LeaseLost, StaleClaim) as error:
            return self._stale_result(task.task_id, "execute", error)
        except ExecutionTimeout as error:
            return self._record_failure(
                task,
                stage="execute",
                fence=fence,
                message=f"timeout: {error}",
                retryable=False,
                timeout=True,
                label=f"execution timeout: {error}",
            )
        except OSError as error:
            return self._record_failure(
                task,
                stage="execute",
                fence=fence,
                message=f"retryable executor error: {error}",
                retryable=True,
                label=f"executor error: {error}",
            )
        except Exception as error:  # noqa: BLE001 - fail closed on unknown errors
            return self._record_failure(
                task,
                stage="execute",
                fence=fence,
                message=f"unexpected executor error: {type(error).__name__}: {error}",
                retryable=False,
                label=f"executor error: {error}",
            )

        if not isinstance(result, ExecutionResult):
            return self._record_failure(
                task,
                stage="execute",
                fence=fence,
                message="executor returned an invalid result object",
                retryable=False,
                label="invalid execution result",
            )
        if not isinstance(result.head_sha, str) or not result.head_sha.strip():
            return self._record_failure(
                task,
                stage="execute",
                fence=fence,
                message="executor returned an empty head_sha",
                retryable=False,
                label="empty head_sha",
            )

        try:
            updated = self.store.record_execution_result(
                task.task_id,
                result.head_sha,
                result.summary,
                self.clock(),
                fence=fence,
                claim_token=task.claim_token,
            )
        except (LeaseLost, StaleClaim) as error:
            return self._stale_result(task.task_id, "execute", error)
        except InvalidTransition as error:
            try:
                paused = self.store.pause(
                    task.task_id, str(error), self.clock(), fence=fence
                )
            except (LeaseLost, StaleClaim) as stale:
                return self._stale_result(task.task_id, "execute", stale)
            return RunResult(
                task_id=task.task_id,
                stage="execute",
                status=paused.status,
                error=str(error),
            )
        if cancel_event is not None and cancel_event.is_set():
            return self._stale_result(
                task.task_id, "execute", LeaseLost("lease heartbeat lost before result commit")
            )
        return self._review(
            updated, now, fence, execution=result, cancel_event=cancel_event
        )

    def _record_failure(
        self,
        task: TaskRecord,
        *,
        stage: str,
        fence: int,
        message: str,
        retryable: bool,
        label: str,
        timeout: bool = False,
    ) -> RunResult:
        try:
            updated = self.store.record_execution_failure(
                task.task_id,
                message,
                self.clock(),
                fence=fence,
                claim_token=task.claim_token,
                retryable=retryable,
                timeout=timeout,
            )
        except (LeaseLost, StaleClaim) as error:
            return self._stale_result(task.task_id, stage, error)
        return RunResult(
            task_id=task.task_id,
            stage=stage,
            status=updated.status,
            error=label,
        )

    # ---------------------------------------------------------------- review
    def _review(
        self,
        task: TaskRecord,
        now: float,
        fence: int,
        *,
        execution: ExecutionResult | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RunResult:
        head_sha = task.head_sha
        if not head_sha:
            try:
                paused = self.store.pause(
                    task.task_id,
                    "review without head SHA",
                    self.clock(),
                    fence=fence,
                )
            except (LeaseLost, StaleClaim) as error:
                return self._stale_result(task.task_id, "review", error)
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=paused.status,
                error="missing head SHA",
            )
        try:
            review_cancellable = getattr(self.reviewer, "review_cancellable", None)
            if cancel_event is not None and callable(review_cancellable):
                review = review_cancellable(
                    task, head_sha, self.config.review_timeout_seconds, cancel_event
                )
            else:
                review = self.reviewer.review(
                    task, head_sha, self.config.review_timeout_seconds
                )
        except (LeaseLost, StaleClaim) as error:
            return self._stale_result(task.task_id, "review", error)
        except ReviewTimeout as error:
            return self._record_review_failure(
                task,
                fence=fence,
                message=f"review timeout: {error}",
                label=f"review timeout: {error}",
            )
        except Exception as error:  # noqa: BLE001 - fail closed on unknown errors
            return self._record_review_failure(
                task,
                fence=fence,
                message=f"reviewer error: {type(error).__name__}: {error}",
                label=f"reviewer error: {error}",
            )

        if not isinstance(review, ReviewResult) or review.head_sha != head_sha:
            try:
                paused = self.store.pause(
                    task.task_id,
                    "review result does not match current head SHA",
                    self.clock(),
                    fence=fence,
                )
            except (LeaseLost, StaleClaim) as error:
                return self._stale_result(task.task_id, "review", error)
            return RunResult(
                task_id=task.task_id,
                stage="review",
                status=paused.status,
                error="stale or malformed review",
            )

        event_key = f"review:{task.task_id}:{head_sha}:{review.reviewer}"
        try:
            outcome = self.store.submit_review(
                task.task_id,
                review,
                self.clock(),
                fence=fence,
                event_key=event_key,
            )
        except (LeaseLost, StaleClaim) as error:
            return self._stale_result(task.task_id, "review", error)
        if outcome.stale:
            try:
                paused = self.store.pause(
                    task.task_id, outcome.message, self.clock(), fence=fence
                )
            except (LeaseLost, StaleClaim) as error:
                return self._stale_result(task.task_id, "review", error)
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

    def _record_review_failure(
        self,
        task: TaskRecord,
        *,
        fence: int,
        message: str,
        label: str,
    ) -> RunResult:
        try:
            updated = self.store.mark_review_failure(
                task.task_id, message, self.clock(), fence=fence
            )
        except (LeaseLost, StaleClaim) as error:
            return self._stale_result(task.task_id, "review", error)
        return RunResult(
            task_id=task.task_id,
            stage="review",
            status=updated.status,
            error=label,
        )

    def _stale_result(
        self, task_id: str, stage: str, error: Exception
    ) -> RunResult:
        current = self.store.get_task(task_id)
        return RunResult(
            task_id=task_id,
            stage=stage,
            status=current.status if current is not None else TaskStatus.NEEDS_OWNER,
            error=f"lease lost; stale worker result discarded: {error}",
            lease_lost=True,
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
