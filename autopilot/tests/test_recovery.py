from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.fakes import FakeClock, FakeExecutor, FakeReviewer, FakeTaskSource
from autopilot.models import ExecutionResult, TaskStatus
from autopilot.scheduler import Scheduler, SchedulerConfig
from autopilot.store import SqliteStore
from autopilot.tests.support import approved, task


class RestartRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "recovery.sqlite3"
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()

    def test_committed_execution_is_resumed_at_review_without_reexecution(self) -> None:
        clock = FakeClock()
        store = SqliteStore(self.db_path)
        store.enqueue_task(task("T1"), clock())
        self.assertTrue(store.acquire_lease("crasher", 60.0, clock()))
        claimed = store.claim_next("crasher", clock())
        self.assertIsNotNone(claimed)
        store.record_execution_result("T1", "t1-head", "committed before crash", clock())
        store.close()

        clock.advance(61.0)
        recovered = SqliteStore(self.db_path)
        self.addCleanup(recovered.close)
        executor = FakeExecutor({"T1": [AssertionError("must not execute")]})
        reviewer = FakeReviewer({("T1", "t1-head"): approved("T1", "t1-head")})
        scheduler = Scheduler(
            recovered,
            FakeTaskSource([]),
            executor,
            reviewer,
            self.workspace,
            config=SchedulerConfig(lease_ttl_seconds=60.0),
            owner="recovery-scheduler",
            clock=clock,
        )

        result = scheduler.run_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.DONE)
        self.assertEqual(executor.calls, [])
        self.assertEqual(reviewer.calls, [("T1", "t1-head")])
        self.assertEqual(recovered.counts()["done"], 1)
        self.assertEqual(recovered.review_count("T1"), 1)

    def test_uncommitted_working_task_is_retried_after_lease_expiry(self) -> None:
        clock = FakeClock()
        store = SqliteStore(self.db_path)
        store.enqueue_task(task("T1"), clock())
        self.assertTrue(store.acquire_lease("crasher", 60.0, clock()))
        self.assertIsNotNone(store.claim_next("crasher", clock()))
        store.close()

        clock.advance(61.0)
        recovered = SqliteStore(self.db_path)
        self.addCleanup(recovered.close)
        executor = FakeExecutor({"T1": [ExecutionResult("t1-head")]})
        reviewer = FakeReviewer({("T1", "t1-head"): approved("T1", "t1-head")})
        scheduler = Scheduler(
            recovered,
            FakeTaskSource([]),
            executor,
            reviewer,
            self.workspace,
            config=SchedulerConfig(lease_ttl_seconds=60.0),
            owner="recovery-scheduler",
            clock=clock,
        )

        result = scheduler.run_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.DONE)
        self.assertEqual(executor.calls, [("T1", 2)])
        self.assertEqual(recovered.get_task("T1").attempts, 0)  # type: ignore[union-attr]

    def test_active_lease_is_not_stolen_by_recovery(self) -> None:
        clock = FakeClock()
        owner_store = SqliteStore(self.db_path)
        other_store = SqliteStore(self.db_path)
        self.addCleanup(owner_store.close)
        self.addCleanup(other_store.close)
        owner_store.enqueue_task(task("T1"), clock())
        self.assertTrue(owner_store.acquire_lease("owner-a", 60.0, clock()))

        counts = other_store.recover(clock())
        self.assertEqual(counts["lease_cleared"], 0)
        self.assertEqual(other_store.get_lease()["owner"], "owner-a")  # type: ignore[index]

        scheduler = Scheduler(
            other_store,
            FakeTaskSource([]),
            FakeExecutor({}),
            FakeReviewer({}),
            self.workspace,
            config=SchedulerConfig(lease_ttl_seconds=60.0),
            owner="owner-b",
            clock=clock,
        )
        self.assertIsNone(scheduler.run_once())
        self.assertEqual(other_store.counts()["ready"], 1)
