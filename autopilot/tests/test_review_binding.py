from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.models import (
    ExecutionResult,
    InvalidTransition,
    ReviewResult,
    ReviewVerdict,
    TaskStatus,
)
from autopilot.tests.support import Stack, approved, build_stack, changes, task


class ReviewBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def _review_ready(self, task_id: str, head_sha: str) -> Stack:
        stack = build_stack(
            self.tmp_path,
            tasks=[],
            exec_plans={},
            review_plans={},
        )
        self.addCleanup(stack.close)
        now = stack.clock()
        stack.store.enqueue_task(task(task_id), now)
        fence = stack.store.acquire_lease("test-owner", 60.0, now)
        self.assertIsNotNone(fence)
        claimed = stack.store.claim_next("test-owner", now, fence)
        self.assertIsNotNone(claimed)
        stack.fence = fence  # type: ignore[attr-defined]
        stack.store.record_execution_result(
            task_id,
            head_sha,
            "ready for review",
            now,
            fence=fence,
            claim_token=claimed.claim_token,
        )
        return stack

    def test_stale_head_review_is_recorded_but_cannot_pass(self) -> None:
        stack = self._review_ready("T1", "head-a")
        stale = stack.store.submit_review(
            "T1",
            ReviewResult(ReviewVerdict.APPROVED, "head-b", reviewer="r1"),
            stack.clock(),
            fence=stack.fence,
        )
        self.assertTrue(stale.stale)
        self.assertFalse(stale.accepted)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.REVIEW)
        self.assertEqual(stack.store.review_count("T1"), 1)

        accepted = stack.store.submit_review(
            "T1",
            approved("T1", "head-a", reviewer="r1"),
            stack.clock(),
            fence=stack.fence,
        )
        self.assertTrue(accepted.accepted)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.DONE)

    def test_old_review_cannot_pass_after_new_head_is_committed(self) -> None:
        stack = self._review_ready("T1", "head-a")
        first = stack.store.submit_review(
            "T1",
            changes("T1", "head-a", "fix me", reviewer="r1"),
            stack.clock(),
            fence=stack.fence,
        )
        self.assertEqual(first.status, TaskStatus.CHANGES_REQUESTED)
        self.assertEqual(stack.store.get_task("T1").rework_rounds, 1)

        rework = stack.store.claim_next("test-owner", stack.clock(), fence=stack.fence)
        self.assertIsNotNone(rework)
        stack.store.record_execution_result("T1", "head-b", "rework", stack.clock(), fence=stack.fence, claim_token=rework.claim_token)
        stale = stack.store.submit_review(
            "T1",
            approved("T1", "head-a", reviewer="r2"),
            stack.clock(),
            fence=stack.fence,
        )
        self.assertTrue(stale.stale)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.REVIEW)

        final = stack.store.submit_review(
            "T1",
            approved("T1", "head-b", reviewer="r2"),
            stack.clock(),
            fence=stack.fence,
        )
        self.assertTrue(final.accepted)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.DONE)

    def test_scheduler_pauses_when_reviewer_returns_wrong_head(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={"T1": [ExecutionResult("t1-head")]},
            review_plans={
                ("T1", "t1-head"): ReviewResult(
                    ReviewVerdict.APPROVED, "wrong-head", reviewer="bad-reviewer"
                )
            },
        )
        self.addCleanup(stack.close)

        result = stack.scheduler.run_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.NEEDS_OWNER)
        self.assertEqual(stack.store.counts()["done"], 0)

    def test_invalid_transition_is_rejected(self) -> None:
        stack = build_stack(
            self.tmp_path,
            tasks=[task("T1")],
            exec_plans={},
            review_plans={},
        )
        self.addCleanup(stack.close)
        stack.store.enqueue_task(task("T1"), stack.clock())
        with self.assertRaises(InvalidTransition):
            stack.store.transition(
                "T1", TaskStatus.DONE, "illegal shortcut", stack.clock()
            )
        self.assertEqual(stack.store.get_task("T1").status, TaskStatus.READY)
