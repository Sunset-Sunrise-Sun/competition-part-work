from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from autopilot.fakes import FakeClock, FakeExecutor, FakeReviewer, FakeTaskSource
from autopilot.models import (
    ExecutionResult,
    LeaseLost,
    ReviewResult,
    ReviewVerdict,
    TaskStatus,
)
from autopilot.scheduler import Scheduler, SchedulerConfig
from autopilot.store import SqliteStore
from autopilot.tests.support import approved, build_stack, changes, task


class ReworkRecoveryRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "rework-recovery.sqlite3"
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()

    def test_interrupted_rework_is_reexecuted_not_reviewed_on_old_head(self) -> None:
        clock = FakeClock()
        store = SqliteStore(self.db_path)
        store.enqueue_task(task("T1"), clock())
        fence = store.acquire_lease("crasher", 60.0, clock())
        self.assertIsNotNone(fence)
        initial = store.claim_next("crasher", clock(), fence)
        self.assertIsNotNone(initial)
        store.record_execution_result(
            "T1",
            "head-A",
            "initial",
            clock(),
            fence=fence,
            claim_token=initial.claim_token,
        )
        store.submit_review(
            "T1",
            changes("T1", "head-A", "fix it", reviewer="r1"),
            clock(),
            fence=fence,
        )
        rework = store.claim_next("crasher", clock(), fence)
        self.assertIsNotNone(rework)
        self.assertEqual(rework.status, TaskStatus.WORKING)
        self.assertEqual(rework.head_sha, "head-A")
        store.close()

        clock.advance(61.0)
        recovered = SqliteStore(self.db_path)
        self.addCleanup(recovered.close)
        counts = recovered.recover(clock())
        self.assertEqual(counts["requeued"], 1)
        self.assertEqual(counts["review"], 0)
        self.assertEqual(recovered.get_task("T1").status, TaskStatus.READY)  # type: ignore[union-attr]

        executor = FakeExecutor({"T1": [ExecutionResult("head-B")]})
        reviewer = FakeReviewer({("T1", "head-B"): approved("T1", "head-B", reviewer="r2")})
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
        self.assertEqual(reviewer.calls, [("T1", "head-B")])
        final = recovered.get_task("T1")
        self.assertEqual(final.status, TaskStatus.DONE)  # type: ignore[union-attr]
        self.assertEqual(final.head_sha, "head-B")  # type: ignore[union-attr]


class BlockingExecutor:
    def __init__(self, started: threading.Event, release: threading.Event, active: dict, lock: threading.Lock, head: str) -> None:
        self.started = started
        self.release = release
        self.active = active
        self.lock = lock
        self.head = head
        self.calls: list[tuple[str, int]] = []

    def execute(self, task, attempt, workspace, timeout_seconds):
        self.calls.append((task.task_id, attempt))
        with self.lock:
            self.active["now"] += 1
            self.active["max"] = max(self.active["max"], self.active["now"])
        self.started.set()
        self.release.wait(timeout=5.0)
        with self.lock:
            self.active["now"] -= 1
        return ExecutionResult(self.head)


class QuickExecutor:
    def __init__(self, active: dict, lock: threading.Lock, head: str) -> None:
        self.active = active
        self.lock = lock
        self.head = head
        self.calls: list[tuple[str, int]] = []

    def execute(self, task, attempt, workspace, timeout_seconds):
        self.calls.append((task.task_id, attempt))
        with self.lock:
            self.active["now"] += 1
            self.active["max"] = max(self.active["max"], self.active["now"])
        time.sleep(0.03)
        with self.lock:
            self.active["now"] -= 1
        return ExecutionResult(self.head)


class LeaseExpiryRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "lease-expiry.sqlite3"
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()

    def _scheduler(self, name: str, executor, reviewer, source) -> tuple[SqliteStore, Scheduler]:
        store = SqliteStore(self.db_path)
        self.addCleanup(store.close)
        scheduler = Scheduler(
            store,
            source,
            executor,
            reviewer,
            self.workspace,
            config=SchedulerConfig(
                lease_ttl_seconds=0.8,
                execution_timeout_seconds=5.0,
                review_timeout_seconds=5.0,
                lease_heartbeat_enabled=True,
            ),
            owner=name,
        )
        return store, scheduler

    def test_active_execution_renews_lease_so_second_scheduler_cannot_take_over(self) -> None:
        active = {"now": 0, "max": 0}
        lock = threading.Lock()
        started = threading.Event()
        release = threading.Event()
        executor_a = BlockingExecutor(started, release, active, lock, "head-A")
        executor_b = QuickExecutor(active, lock, "head-B")
        store_a, scheduler_a = self._scheduler(
            "worker-a",
            executor_a,
            FakeReviewer({("T1", "head-A"): approved("T1", "head-A")}),
            FakeTaskSource([task("T1")]),
        )
        store_b, scheduler_b = self._scheduler(
            "worker-b",
            executor_b,
            FakeReviewer({("T1", "head-B"): approved("T1", "head-B")}),
            FakeTaskSource([]),
        )
        result_a: dict[str, object] = {}
        error_a: dict[str, BaseException] = {}

        def run_a() -> None:
            try:
                result_a["value"] = scheduler_a.run_once()
            except BaseException as error:  # pragma: no cover - failure path
                error_a["value"] = error

        thread = threading.Thread(target=run_a, daemon=True)
        thread.start()
        try:
            self.assertTrue(started.wait(timeout=3), "executor A did not start")
            # The blocked execution has now outlived the 0.8s TTL.
            time.sleep(1.2)
            result_b = scheduler_b.run_once()
            self.assertIsNone(result_b)
            self.assertEqual(executor_b.calls, [])
        finally:
            release.set()
            thread.join(timeout=5)
        self.assertEqual(error_a, {})
        result = result_a.get("value")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.DONE)  # type: ignore[union-attr]
        self.assertEqual(executor_a.calls, [("T1", 1)])
        self.assertEqual(active["max"], 1)
        self.assertEqual(store_a.get_task("T1").status, TaskStatus.DONE)  # type: ignore[union-attr]

    def test_stale_generation_cannot_commit_or_pause_after_takeover(self) -> None:
        clock = FakeClock()
        store_a = SqliteStore(self.db_path)
        store_b = SqliteStore(self.db_path)
        self.addCleanup(store_a.close)
        self.addCleanup(store_b.close)
        now = clock()
        store_a.enqueue_task(task("T1"), now)
        fence_a = store_a.acquire_lease("worker-a", 60.0, now)
        self.assertIsNotNone(fence_a)
        claimed_a = store_a.claim_next("worker-a", now, fence_a)  # type: ignore[arg-type]
        self.assertIsNotNone(claimed_a)
        with store_a.transaction():
            store_a.conn.execute(
                "UPDATE lease SET expires_at = ? WHERE singleton = 1", (now - 1.0,)
            )
        counts = store_b.recover(now)
        self.assertEqual(counts["requeued"], 1)
        fence_b = store_b.acquire_lease("worker-b", 60.0, now)
        self.assertIsNotNone(fence_b)
        claimed_b = store_b.claim_next("worker-b", now, fence_b)  # type: ignore[arg-type]
        self.assertIsNotNone(claimed_b)

        with self.assertRaises(LeaseLost):
            store_a.record_execution_result(
                "T1",
                "head-stale",
                "must be discarded",
                now,
                fence=fence_a,  # type: ignore[arg-type]
                claim_token=claimed_a.claim_token,  # type: ignore[union-attr]
            )
        with self.assertRaises(LeaseLost):
            store_a.pause("T1", "stale pause", now, fence=fence_a)  # type: ignore[arg-type]

        unchanged = store_a.get_task("T1")
        self.assertEqual(unchanged.status, TaskStatus.WORKING)  # type: ignore[union-attr]
        self.assertIsNone(unchanged.head_sha)  # type: ignore[union-attr]

        store_b.record_execution_result(
            "T1",
            "head-B",
            "new worker result",
            now,
            fence=fence_b,  # type: ignore[arg-type]
            claim_token=claimed_b.claim_token,  # type: ignore[union-attr]
        )
        self.assertEqual(store_b.get_task("T1").status, TaskStatus.REVIEW)  # type: ignore[union-attr]
        with self.assertRaises(LeaseLost):
            store_a.submit_review(
                "T1",
                approved("T1", "head-B", reviewer="stale-r"),
                now,
                fence=fence_a,  # type: ignore[arg-type]
            )
        self.assertEqual(store_b.get_task("T1").status, TaskStatus.REVIEW)  # type: ignore[union-attr]
        outcome = store_b.submit_review(
            "T1",
            approved("T1", "head-B", reviewer="r-b"),
            now,
            fence=fence_b,  # type: ignore[arg-type]
        )
        self.assertTrue(outcome.accepted)
        self.assertEqual(store_b.get_task("T1").status, TaskStatus.DONE)  # type: ignore[union-attr]
