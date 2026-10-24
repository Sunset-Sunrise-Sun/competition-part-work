"""Read-only status/recovery CLI for the Phase 1A skeleton.

This is not the long-running scheduler daemon. It is intentionally limited to
inspection and crash recovery so nobody mistakes the skeleton for a deployed
unattended system.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .store import SqliteStore


def _status(args: argparse.Namespace) -> int:
    store = SqliteStore(args.db)
    try:
        payload = {
            "db": str(Path(args.db)),
            "counts": store.counts(),
            "lease": store.get_lease(),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status.value,
                    "head_sha": task.head_sha,
                    "rework_rounds": task.rework_rounds,
                    "attempts": task.attempts,
                    "last_error": task.last_error,
                }
                for task in store.list_tasks()
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


def _recover(args: argparse.Namespace) -> int:
    store = SqliteStore(args.db)
    try:
        counts = store.recover(time.time())
        print(json.dumps({"recovered": counts}, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m autopilot.cli")
    parser.add_argument("--db", default="data/autopilot.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print task/lease status")
    sub.add_parser("recover", help="clear an expired lease and requeue interrupted work")
    args = parser.parse_args(argv)
    if args.command == "status":
        return _status(args)
    if args.command == "recover":
        return _recover(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
