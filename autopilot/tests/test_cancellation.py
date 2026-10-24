from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.models import ExecutionResult, TaskStatus
from autopilot.tests.support import approved, build_stack, task


class CancellationAwareExecutor:
    def __init__(self) -> None:
        self.received_cancel_event = False

    def execute(self, task, attempt, workspace, timeout_seconds):
        raise AssertionError("scheduler should use execute_with_cancel")

    def execute_with_cancel(self, task, attempt, workspace, timeout_seconds, cancel_event):
        self.received_cancel_event = cancel_event is not None
        cancel_event.set()
        return ExecutionResult("must-not-commit")


class LeaseCancellationTests(unittest.TestCase):
    def test_cancelled_child_result_is_discarded_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stack = build_stack(
                Path(directory),
                tasks=[task("T1")],
                exec_plans={"T1": [ExecutionResult("unused")]},
                review_plans={("T1", "unused"): approved("T1", "unused")},
            )
            self.addCleanup(stack.close)
            executor = CancellationAwareExecutor()
            stack.scheduler.executor = executor

            result = stack.scheduler.run_once()

            self.assertTrue(executor.received_cancel_event)
            self.assertIsNotNone(result)
            self.assertTrue(result.lease_lost)
            self.assertEqual(result.status, TaskStatus.WORKING)
            persisted = stack.store.get_task("T1")
            self.assertEqual(persisted.status, TaskStatus.WORKING)
            self.assertIsNone(persisted.head_sha)


if __name__ == "__main__":
    unittest.main()
