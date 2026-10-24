"""Foreground runner for the opt-in GitHub/DSH automation loop.

Run manually first. A Windows Task Scheduler installer is provided separately,
but registration is never performed automatically by this module.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

from .adapters.dsh_runtime import DshDiffReviewer, DshWorktreeExecutor
from .adapters.github_runtime import GitHubIssueAdapter
from .models import TaskStatus
from .redaction import redact
from .scheduler import RunResult, Scheduler, SchedulerConfig
from .store import SqliteStore


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _emit(event: dict[str, object]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _result_event(result: RunResult) -> dict[str, object]:
    head_sha = (
        result.review.head_sha if result.review is not None
        else result.execution.head_sha if result.execution is not None
        else None
    )
    return {
        "task_id": result.task_id,
        "stage": result.stage,
        "status": result.status.value,
        "head_sha": head_sha,
        "error": redact(result.error or "")[:2000] or None,
        "lease_lost": result.lease_lost,
    }


def _reconcile_terminal_tasks(store: SqliteStore, adapter: GitHubIssueAdapter) -> None:
    for task in store.list_tasks():
        if task.status not in {
            TaskStatus.DONE,
            TaskStatus.CHANGES_REQUESTED,
            TaskStatus.NEEDS_OWNER,
        }:
            continue
        result = RunResult(
            task_id=task.task_id,
            stage="startup-reconcile",
            status=task.status,
        )
        adapter.on_task_result(task, result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m autopilot.daemon")
    parser.add_argument("--repo-root", required=True, help="Local Git repository root")
    parser.add_argument("--db", default="data/autopilot.sqlite3", help="SQLite state database")
    parser.add_argument("--poll-interval", type=float, default=None, help="Override AUTOPILOT_POLL_SECONDS")
    parser.add_argument("--once", action="store_true", help="Process ready tasks once, then exit")
    args = parser.parse_args(argv)

    for name in ("AUTOPILOT_GITHUB_ENABLED", "AUTOPILOT_DSH_ENABLED", "AUTOPILOT_REVIEW_ENABLED"):
        if not _truthy(name):
            _emit({"event": "startup_blocked", "reason": f"{name} must be set to 1"})
            return 2
    if not (os.environ.get("AUTOPILOT_DSH_CLI") or shutil.which("dsh")):
        _emit({"event": "startup_blocked", "reason": "DSH CLI not found; set AUTOPILOT_DSH_CLI"})
        return 2

    repo_root = Path(args.repo_root).resolve()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = repo_root / db_path
    try:
        adapter = GitHubIssueAdapter.from_env(repo_root)
        if args.poll_interval is not None:
            adapter.poll_interval_seconds = max(5.0, args.poll_interval)
        store = SqliteStore(db_path)
    except Exception as error:  # noqa: BLE001 - startup must fail visibly
        _emit({"event": "startup_failed", "error": redact(f"{type(error).__name__}: {error}")[:2000]})
        return 2

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, request_stop)
        except (ValueError, OSError):
            pass

    scheduler = Scheduler(
        store,
        adapter,
        DshWorktreeExecutor(),
        DshDiffReviewer(repo_root=repo_root),
        repo_root,
        config=SchedulerConfig(),
        publisher=adapter,
        notifier=adapter,
    )
    try:
        _reconcile_terminal_tasks(store, adapter)
        _emit({
            "event": "started",
            "repository": adapter.repository,
            "base_branch": adapter.base_branch,
            "repo_root": str(repo_root),
            "db": str(db_path),
            "mode": "once" if args.once else "polling",
        })
        while not stop_event.is_set():
            results = scheduler.run_until_idle()
            for result in results:
                _emit({"event": "task_result", **_result_event(result)})
            if any(result.status is TaskStatus.NEEDS_OWNER for result in results):
                _emit({"event": "paused", "reason": "task requires owner review"})
                return 2
            if args.once:
                _emit({"event": "cycle_complete", "processed": len(results)})
                return 0
            if stop_event.wait(adapter.poll_interval_seconds):
                break
        _emit({"event": "stopped"})
        return 0
    except Exception as error:  # noqa: BLE001 - let Task Scheduler restart after visible failure
        _emit({"event": "runner_failed", "error": redact(f"{type(error).__name__}: {error}")[:2000]})
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
