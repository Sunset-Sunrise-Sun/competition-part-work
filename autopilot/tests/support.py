"""Shared test helpers for the autopilot skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autopilot.fakes import FakeClock, FakeExecutor, FakeReviewer, FakeTaskSource
from autopilot.models import ReviewResult, ReviewVerdict, TaskSpec
from autopilot.scheduler import Scheduler, SchedulerConfig
from autopilot.store import SqliteStore


def task(task_id: str, title: str = "dummy task", base_sha: str = "base-sha") -> TaskSpec:
    return TaskSpec(task_id=task_id, title=title, base_sha=base_sha)


def approved(task_id: str, head_sha: str, reviewer: str = "fake-reviewer") -> ReviewResult:
    return ReviewResult(
        verdict=ReviewVerdict.APPROVED,
        head_sha=head_sha,
        reviewer=reviewer,
    )


def changes(
    task_id: str,
    head_sha: str,
    *defects: str,
    reviewer: str = "fake-reviewer",
) -> ReviewResult:
    return ReviewResult(
        verdict=ReviewVerdict.CHANGES_REQUESTED,
        head_sha=head_sha,
        defects=tuple(defects),
        reviewer=reviewer,
    )


@dataclass
class Stack:
    store: SqliteStore
    scheduler: Scheduler
    source: FakeTaskSource
    executor: FakeExecutor
    reviewer: FakeReviewer
    clock: FakeClock
    workspace: Path

    def close(self) -> None:
        self.store.close()


def build_stack(
    tmp_path: Path,
    *,
    tasks: list[TaskSpec],
    exec_plans: dict[str, list],
    review_plans: dict[tuple[str, str], ReviewResult],
    owner: str = "scheduler-a",
    max_attempts: int = 2,
    max_rework_rounds: int = 3,
    config: SchedulerConfig | None = None,
    db_path: Path | None = None,
) -> Stack:
    db_path = db_path or (tmp_path / "autopilot.sqlite3")
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    store = SqliteStore(
        db_path,
        max_attempts=max_attempts,
        max_rework_rounds=max_rework_rounds,
    )
    clock = FakeClock()
    source = FakeTaskSource(list(tasks))
    executor = FakeExecutor(exec_plans)
    reviewer = FakeReviewer(review_plans)
    scheduler = Scheduler(
        store,
        source,
        executor,
        reviewer,
        workspace,
        config=config
        or SchedulerConfig(
            lease_ttl_seconds=60.0,
            execution_timeout_seconds=5.0,
            review_timeout_seconds=5.0,
        ),
        owner=owner,
        clock=clock,
    )
    return Stack(
        store=store,
        scheduler=scheduler,
        source=source,
        executor=executor,
        reviewer=reviewer,
        clock=clock,
        workspace=workspace,
    )
