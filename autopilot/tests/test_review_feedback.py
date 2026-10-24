from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.models import ReviewResult, ReviewVerdict, TaskSpec, TaskStatus
from autopilot.store import SqliteStore


BASE = "a" * 40
HEAD = "b" * 40


class ReviewFeedbackPersistenceTest(unittest.TestCase):
    def test_changes_requested_feedback_is_available_to_the_rework_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(Path(directory) / "state.sqlite3", max_rework_rounds=3)
            try:
                store.enqueue_task(
                    TaskSpec("T-review-feedback", "Fix review findings", BASE),
                    now=1.0,
                )
                fence = store.acquire_lease("feedback-test", 30.0, 1.0)
                self.assertIsNotNone(fence)
                claimed = store.claim_next("feedback-test", 1.0, fence)
                self.assertIsNotNone(claimed)
                self.assertIsNotNone(claimed.claim_token)

                reviewed_task = store.record_execution_result(
                    claimed.task_id,
                    HEAD,
                    "one file changed",
                    2.0,
                    fence=fence,
                    claim_token=claimed.claim_token,
                )
                self.assertEqual(reviewed_task.status, TaskStatus.REVIEW)

                outcome = store.submit_review(
                    reviewed_task.task_id,
                    ReviewResult(
                        verdict=ReviewVerdict.CHANGES_REQUESTED,
                        head_sha=HEAD,
                        defects=("Missing regression test for empty input",),
                        reviewer="test-reviewer",
                        notes="Add a focused test and rerun the suite.",
                    ),
                    3.0,
                    fence=fence,
                )
                self.assertEqual(outcome.status, TaskStatus.CHANGES_REQUESTED)

                pending = store.get_task("T-review-feedback")
                self.assertEqual(pending.status, TaskStatus.CHANGES_REQUESTED)
                self.assertEqual(pending.rework_rounds, 1)
                self.assertIn("Missing regression test for empty input", pending.last_error)
                self.assertIn("Add a focused test", pending.last_error)

                rework = store.claim_next("feedback-test", 3.1, fence)
                self.assertIsNotNone(rework)
                self.assertEqual(rework.status, TaskStatus.WORKING)
                self.assertIn("Missing regression test for empty input", rework.last_error)
                self.assertIn("Add a focused test", rework.last_error)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
