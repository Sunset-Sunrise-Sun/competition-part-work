from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.models import (
    ExecutionResult,
    ExecutionTimeout,
    ReviewTimeout,
    TaskStatus,
)
from autopilot.tests.support import Stack, approved, build_stack, changes, task


class FailureModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def test_execution_timeout_pauses_for_owner_without_review(self) -> None:
        stack: Stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [ExecutionTimeout("simulated timeout")]},
            review_plans={},
        )
        self.addCleanup(stack.close)

        result = stack.scheduler.run_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.executor.calls, [("T1", 1)])
        self.assertEqual(stack.reviewer.calls, [])
        self.assertEqual(stack.store.review_count(), 0)

    def test_unexpected_executor_exception_pauses_for_owner(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [RuntimeError("boom")]},
            review_plans={},
        )
        self.addCleanup(stack.close)
        result = stack.scheduler.run_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.executor.calls, [("T1", 1)])
        self.assertEqual(stack.reviewer.calls, [])

    def test_retryable_executor_error_is_bounded_then_succeeds(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [OSError("transient"), ExecutionResult("t1-head")]},
            review_plans={("T1", "t1-head"): approved("T1", "t1-head")},
            max_attempts=2,
        )
        self.addCleanup(stack.close)

        results = stack.scheduler.run_until_idle(max_steps=10)

        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.DONE)
        self.assertEqual(stack.executor.calls, [("T1", 1), ("T1", 2)])
        self.assertEqual(len(results), 2)

    def test_retry_limit_pauses_instead_of_looping(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [OSError("always failing"), OSError("still failing")]},
            review_plans={},
            max_attempts=2,
        )
        self.addCleanup(stack.close)
        results = stack.scheduler.run_until_idle(max_steps=10)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.executor.calls, [("T1", 1), ("T1", 2)])
        self.assertEqual(results[-1].status, TaskStatus.NEEDS_OWNER)

    def test_three_rework_rounds_then_needs_owner(self) -> None:
        heads = [f"t1-r{index}" for index in range(1, 5)]
        review_plans = {
            ("T1", head): changes("T1", head, f"defect {index}", reviewer="r")
            for index, head in enumerate(heads, start=1)
        }
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [ExecutionResult(head) for head in heads]},
            review_plans=review_plans,
            max_rework_rounds=3,
        )
        self.addCleanup(stack.close)

        results = stack.scheduler.run_until_idle(max_steps=10)

        task_record = stack.store.get_task("T1")
        self.assertEqual(task_record.status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(task_record.rework_rounds, 3)
        self.assertEqual(stack.executor.calls, [("T1", 1), ("T1", 1), ("T1", 1), ("T1", 1)])
        self.assertEqual(len(stack.reviewer.calls), 4)
        self.assertEqual(results[-1].status, TaskStatus.NEEDS_OWNER)

    def test_review_timeout_pauses_for_owner(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [ExecutionResult("t1-head")]},
            review_plans={("T1", "t1-head"): ReviewTimeout("simulated review timeout")},
        )
        self.addCleanup(stack.close)
        result = stack.scheduler.run_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.store.review_count(), 0)

    def test_empty_head_is_rejected_safely(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [ExecutionResult("")]},
            review_plans={},
        )
        self.addCleanup(stack.close)
        result = stack.scheduler.run_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.store.counts()["done"], 0)
