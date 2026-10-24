from __future__ import annotations

import tempfile
import threading
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

    def test_request_stop_cancels_active_cancellable_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            store = SqliteStore(root / "autopilot.sqlite3")
            entered = threading.Event()
            output = []

            class WaitingExecutor:
                def execute(self, task, attempt, workspace, timeout_seconds):
                    raise AssertionError("cancellable execution should be used")

                def execute_cancellable(self, task, attempt, workspace, timeout_seconds, cancel_event):
                    entered.set()
                    if not cancel_event.wait(timeout=3.0):
                        raise AssertionError("shutdown did not signal cancellation")
                    raise LeaseLost("cancelled by scheduler shutdown")

            try:
                scheduler = Scheduler(
                    store,
                    FakeTaskSource([task("T-stop")]),
                    WaitingExecutor(),
                    FakeReviewer({}),
                    workspace,
                    config=SchedulerConfig(lease_ttl_seconds=2.0),
                    owner="stop-test",
                )
                worker = threading.Thread(target=lambda: output.append(scheduler.run_once()))
                worker.start()
                self.assertTrue(entered.wait(timeout=2.0))
                scheduler.request_stop()
                worker.join(timeout=3.0)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(output), 1)
                self.assertTrue(output[0].lease_lost)
                self.assertEqual(output[0].status, TaskStatus.WORKING)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
