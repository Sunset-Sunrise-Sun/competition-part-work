from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from autopilot.models import ExecutionResult, TaskStatus
from autopilot.store import SqliteStore
from autopilot.tests.support import approved, build_stack, task


class LeaseAndIdempotencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "shared.sqlite3"

    def test_only_one_scheduler_can_hold_the_global_lease(self) -> None:
        store_a = SqliteStore(self.db_path)
        store_b = SqliteStore(self.db_path)
        self.addCleanup(store_a.close)
        self.addCleanup(store_b.close)
        now = 1_000.0
        fence_a = store_a.acquire_lease("scheduler-a", 60.0, now)
        self.assertIsNotNone(fence_a)
        self.assertIsNone(store_b.acquire_lease("scheduler-b", 60.0, now))
        self.assertIsNone(store_a.acquire_lease("scheduler-a", 60.0, now))
        self.assertTrue(store_a.release_lease("scheduler-a", fence_a))
        fence_b = store_b.acquire_lease("scheduler-b", 60.0, now + 1.0)
        self.assertIsNotNone(fence_b)
        self.assertTrue(store_b.release_lease("scheduler-b", fence_b))

    def test_concurrent_lease_acquisition_has_exactly_one_winner(self) -> None:
        store_a = SqliteStore(self.db_path)
        store_b = SqliteStore(self.db_path)
        self.addCleanup(store_a.close)
        self.addCleanup(store_b.close)
        barrier = threading.Barrier(2)
        results: dict[str, int | None] = {}

        def acquire(name: str, store: SqliteStore) -> None:
            barrier.wait(timeout=5)
            results[name] = store.acquire_lease(name, 60.0, 2_000.0)

        threads = [
            threading.Thread(target=acquire, args=("a", store_a)),
            threading.Thread(target=acquire, args=("b", store_b)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        winners = [value for value in results.values() if value is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(sum(1 for value in winners), 1)

    def test_two_scheduler_instances_do_not_execute_the_same_task_twice(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [ExecutionResult("t1-r1")]},
            review_plans={("T1", "t1-r1"): approved("T1", "t1-r1")},
        )
        self.addCleanup(stack.close)
        other = build_stack(
            self.tmp_path,
            tasks=[],
            exec_plans={},
            review_plans={},
            owner="scheduler-b",
        )
        self.addCleanup(other.close)

        first = stack.scheduler.run_once()
        second = other.scheduler.run_once()
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(stack.executor.calls, [("T1", 1)])
        self.assertEqual(stack.store.counts()["done"], 1)
        self.assertEqual(stack.store.review_count(), 1)
