from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autopilot.fakes import FakeReviewer, FakeTaskSource
from autopilot.models import LeaseLost, TaskStatus
from autopilot.scheduler import Scheduler, SchedulerConfig
from autopilot.store import SqliteStore
from autopilot.tests.support import task


class CancellingExecutor:
    def execute(self, task, attempt, workspace, timeout_seconds):
        raise AssertionError("scheduler should use execute_cancellable when a lease signal exists")

    def execute_cancellable(self, task, attempt, workspace, timeout_seconds, cancel_event):
        cancel_event.set()
        raise LeaseLost("simulated heartbeat loss")


class SchedulerCancellationTest(unittest.TestCase):
    def test_scheduler_passes_lease_cancellation_to_cancellable_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            store = SqliteStore(root / "autopilot.sqlite3")
            try:
                scheduler = Scheduler(
                    store,
                    FakeTaskSource([task("T-cancel")]),
                    CancellingExecutor(),
                    FakeReviewer({}),
                    workspace,
                    config=SchedulerConfig(lease_ttl_seconds=2.0),
                    owner="cancel-test",
                )
                result = scheduler.run_once()
                self.assertIsNotNone(result)
                self.assertTrue(result.lease_lost)
                self.assertEqual(result.status, TaskStatus.WORKING)
                self.assertEqual(store.counts()["done"], 0)
                self.assertEqual(store.counts()["needs-owner"], 0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
