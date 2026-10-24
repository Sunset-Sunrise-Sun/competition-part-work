from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.models import ReviewResult, ReviewVerdict, TaskSpec, TaskStatus
from autopilot.store import SqliteStore


class ReviewFeedbackPersistenceTests(unittest.TestCase):
    def test_changes_requested_feedback_is_available_to_rework_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(Path(directory) / "autopilot.sqlite3")
            try:
                store.enqueue_task(
                    TaskSpec(
                        task_id="issue-27",
                        title="Example",
                        base_sha="a" * 40,
                        payload={"issue_number": 27, "issue_body": "fix it"},
                    ),
                    1.0,
                )
                fence = store.acquire_lease("owner", 60.0, 1.0)
                self.assertIsNotNone(fence)
                claimed = store.claim_next("owner", 1.0, fence)
                self.assertIsNotNone(claimed)
                store.record_execution_result(
                    "issue-27", "b" * 40, "tests passed", 2.0,
                    fence=fence, claim_token=claimed.claim_token,
                    artifact="https://github.com/example/pull/27",
                )
                outcome = store.submit_review(
                    "issue-27",
                    ReviewResult(
                        verdict=ReviewVerdict.CHANGES_REQUESTED,
                        head_sha="b" * 40,
                        defects=("stale session acceptance is not rejected",),
                        reviewer="codex-cli",
                        notes="Add a regression test.",
                    ),
                    3.0,
                    fence=fence,
                )
                self.assertEqual(outcome.status, TaskStatus.CHANGES_REQUESTED)
                rework = store.claim_next("owner", 4.0, fence)
                self.assertIsNotNone(rework)
                self.assertEqual(
                    rework.payload["last_review"]["defects"],
                    ["stale session acceptance is not rejected"],
                )
                self.assertEqual(rework.payload["last_execution"]["artifact"], "https://github.com/example/pull/27")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
