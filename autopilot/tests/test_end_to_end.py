from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.models import ExecutionResult, TaskStatus
from autopilot.tests.support import Stack, approved, build_stack, changes, task


class EndToEndSkeletonTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def test_two_dummy_tasks_advance_automatically_with_one_rework(self) -> None:
        stack: Stack = build_stack(
            self.tmp_path,
            tasks=[task("T1"), task("T2")],
            exec_plans={
                "T1": [ExecutionResult("t1-r1"), ExecutionResult("t1-r2")],
                "T2": [ExecutionResult("t2-r1")],
            },
            review_plans={
                ("T1", "t1-r1"): changes("T1", "t1-r1", "fix the failing check"),
                ("T1", "t1-r2"): approved("T1", "t1-r2"),
                ("T2", "t2-r1"): approved("T2", "t2-r1"),
            },
        )
        self.addCleanup(stack.close)

        results = stack.scheduler.run_until_idle(max_steps=10)

        tasks = {item.task_id: item for item in stack.store.list_tasks()}
        self.assertEqual(tasks["T1"].status, TaskStatus.DONE)
        self.assertEqual(tasks["T2"].status, TaskStatus.DONE)
        self.assertEqual(tasks["T1"].rework_rounds, 1)
        self.assertEqual(tasks["T1"].head_sha, "t1-r2")
        self.assertEqual(tasks["T2"].head_sha, "t2-r1")
        self.assertEqual(
            stack.executor.calls,
            [("T1", 1), ("T1", 1), ("T2", 1)],
        )
        self.assertEqual(
            stack.reviewer.calls,
            [("T1", "t1-r1"), ("T1", "t1-r2"), ("T2", "t2-r1")],
        )
        self.assertEqual(stack.store.review_count(), 3)
        self.assertEqual(len(results), 3)
        self.assertEqual(stack.store.counts()["done"], 2)

    def test_duplicate_poll_and_duplicate_events_do_not_reexecute(self) -> None:
        stack: Stack = build_stack(
            self.tmp_path,
            tasks=[task("T1"), task("T1"), task("T1")],
            exec_plans={"T1": [ExecutionResult("t1-r1")]},
            review_plans={("T1", "t1-r1"): approved("T1", "t1-r1")},
        )
        self.addCleanup(stack.close)

        stack.scheduler.run_until_idle(max_steps=10)
        self.assertEqual(stack.executor.calls, [("T1", 1)])
        self.assertEqual(stack.store.review_count(), 1)
        self.assertEqual(stack.scheduler.run_once(), None)
        self.assertEqual(stack.executor.calls, [("T1", 1)])

        now = stack.clock()
        self.assertTrue(stack.store.record_event("evt-1", "T1", "poll", {}, now))
        self.assertFalse(stack.store.record_event("evt-1", "T1", "poll", {}, now))
        self.assertFalse(stack.store.enqueue_task(task("T1"), now))
        self.assertEqual(stack.store.counts()["done"], 1)
