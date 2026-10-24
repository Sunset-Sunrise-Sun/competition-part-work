"""Long-running Windows-local autopilot service entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .adapters.local_runtime import (
    CodexCliReviewer,
    DshGitExecutor,
    GitHubCli,
    GitHubIssueTaskSource,
    ExternalCommandError,
    run_preflight,
)
from .models import TaskStatus
from .scheduler import Scheduler, SchedulerConfig
from .store import SqliteStore


def configure_logging(log_root: Path) -> None:
    log_root.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(
        RotatingFileHandler(
            log_root / "runner.log",
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LocalFit unattended task runner")
    parser.add_argument("--repo", default=os.environ.get(
        "AUTOPILOT_GITHUB_REPO", "Sunset-Sunrise-Sun/competition-part-work"
    ))
    parser.add_argument("--base-branch", default=os.environ.get(
        "AUTOPILOT_BASE_BRANCH", "wjy/three-day-delivery"
    ))
    parser.add_argument("--repo-path", default=os.environ.get("AUTOPILOT_REPO_PATH"))
    parser.add_argument("--task-root", default=os.environ.get("AUTOPILOT_TASK_ROOT"))
    parser.add_argument("--log-root", default=os.environ.get("AUTOPILOT_LOG_ROOT"))
    parser.add_argument("--db", default=os.environ.get("AUTOPILOT_DB_PATH"))
    parser.add_argument("--dsh-cli", default=os.environ.get("AUTOPILOT_DSH_CLI"))
    parser.add_argument("--dsh-profile", default=os.environ.get("AUTOPILOT_DSH_PROFILE", "headless"))
    parser.add_argument("--codex-cli", default=os.environ.get("AUTOPILOT_CODEX_CLI", "codex"))
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--execution-timeout", type=int, default=900)
    parser.add_argument("--review-timeout", type=int, default=240)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--once", action="store_true", help="run one scheduler step and exit")
    parser.add_argument("--status", action="store_true", help="print persisted scheduler state")
    parser.add_argument("--clear-halt", action="store_true", help="owner-only: clear the local halt marker")
    return parser


def _require_config(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, str]:
    required = {
        "repo-path": args.repo_path,
        "task-root": args.task_root,
        "log-root": args.log_root,
        "db": args.db,
        "dsh-cli": args.dsh_cli,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ExternalCommandError(
            "missing runtime configuration: " + ", ".join(missing)
            + "; run scripts/setup-autopilot.ps1 first"
        )
    repo_path = Path(args.repo_path).resolve()
    task_root = Path(args.task_root).resolve()
    log_root = Path(args.log_root).resolve()
    db_path = Path(args.db).resolve()
    dsh_cli = str(Path(args.dsh_cli).resolve())
    if not repo_path.is_dir():
        raise ExternalCommandError("configured repository path does not exist")
    if not Path(dsh_cli).is_file():
        raise ExternalCommandError("configured DSH CLI path does not exist")
    if args.base_branch != "wjy/three-day-delivery":
        raise ExternalCommandError("only wjy/three-day-delivery is an allowed task base")
    return repo_path, task_root, log_root, db_path, dsh_cli


def _status_label(github: GitHubCli, task, status: TaskStatus, result) -> None:
    number = task.payload.get("issue_number")
    if not isinstance(number, int):
        return
    all_status_labels = [
        "agent:ready", "agent:working", "agent:review",
        "agent:changes-requested", "agent:done", "agent:needs-owner",
    ]
    target = {
        TaskStatus.WORKING: "agent:working",
        TaskStatus.REVIEW: "agent:review",
        TaskStatus.CHANGES_REQUESTED: "agent:changes-requested",
        TaskStatus.DONE: "agent:done",
        TaskStatus.NEEDS_OWNER: "agent:needs-owner",
    }.get(status)
    if target is not None:
        github.set_issue_labels(
            number,
            add=[target],
            remove=[label for label in all_status_labels if label != target],
        )
    if status is TaskStatus.DONE:
        execution = task.payload.get("last_execution") or {}
        github.run([
            "issue", "comment", str(number), "--repo", github.repository,
            "--body",
            "Autopilot task completed and the independent Codex review passed.\n\n"
            f"Head SHA: {task.head_sha}\n"
            f"Draft PR: {execution.get('artifact', 'see task branch')}\n"
            f"Evidence: {execution.get('summary', 'see local runner logs')}\n\n"
            "No merge or upstream push was attempted.",
        ])
    elif status is TaskStatus.NEEDS_OWNER:
        reason = (result.error if result else None) or task.last_error or "unspecified blocker"
        github.run([
            "issue", "comment", str(number), "--repo", github.repository,
            "--body",
            "Autopilot paused and requires owner review.\n\n"
            f"Current state: {status.value}\nReason: {reason}\n"
            "The runner will not start another task until the blocker is resolved. "
            "No merge or upstream push was attempted.",
        ])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    halt_file: Path | None = None
    try:
        repo_path, task_root, log_root, db_path, dsh_cli = _require_config(args)
        configure_logging(log_root)
        log = logging.getLogger("autopilot.runner")
        halt_file = log_root / "HALT"
        if args.clear_halt:
            if halt_file.exists():
                halt_file.unlink()
            log.warning("Local halt marker removed by explicit owner command.")
            return 0
        if halt_file.exists() and not args.preflight and not args.status:
            log.error("Autopilot is halted: %s. Resolve the issue and use --clear-halt explicitly.", halt_file)
            return 3

        github = GitHubCli(args.repo)
        if args.preflight:
            run_preflight(
                github=github,
                repo_path=repo_path,
                task_root=task_root,
                dsh_cli=dsh_cli,
                dsh_profile=args.dsh_profile,
                codex_cli=args.codex_cli,
                base_branch=args.base_branch,
            )
            return 0

        task_root.mkdir(parents=True, exist_ok=True)
        store = SqliteStore(db_path)
        try:
            if args.status:
                import json
                lease = store.get_lease()
                lease_value = lease.__dict__ if hasattr(lease, "__dict__") else lease
                print(json.dumps({
                    "counts": store.counts(),
                    "lease": lease_value,
                    "tasks": [
                        {
                            "task_id": item.task_id,
                            "status": item.status.value,
                            "head_sha": item.head_sha,
                            "attempts": item.attempts,
                            "rework_rounds": item.rework_rounds,
                            "last_error": item.last_error,
                        }
                        for item in store.list_tasks()
                    ],
                }, ensure_ascii=False, indent=2))
                return 0

            source = GitHubIssueTaskSource(github, repo_path, args.base_branch)
            executor = DshGitExecutor(
                github=github, repo_path=repo_path, task_root=task_root,
                log_root=log_root, dsh_cli=dsh_cli,
                dsh_profile=args.dsh_profile, base_branch=args.base_branch,
            )
            reviewer = CodexCliReviewer(
                github=github, task_root=task_root,
                timeout_seconds=float(args.review_timeout),
                codex_cli=args.codex_cli, base_branch=args.base_branch,
            )
            scheduler = Scheduler(
                store, source, executor, reviewer, task_root,
                config=SchedulerConfig(
                    lease_ttl_seconds=60.0,
                    execution_timeout_seconds=float(args.execution_timeout),
                    review_timeout_seconds=float(args.review_timeout),
                    max_source_batch=50,
                    max_steps_per_run=1,
                    lease_heartbeat_enabled=True,
                ),
            )
            log.info(
                "Runner started: repo=%s base=%s poll=%ss db=%s",
                args.repo, args.base_branch, args.poll_seconds, db_path,
            )
            while True:
                result = scheduler.run_once()
                if result is not None:
                    task = store.get_task(result.task_id)
                    if task is not None:
                        effective_status = TaskStatus.NEEDS_OWNER if result.lease_lost else result.status
                        _status_label(github, task, effective_status, result)
                    log.info(
                        "task=%s stage=%s status=%s head=%s error=%s",
                        result.task_id, result.stage, result.status.value,
                        task.head_sha if task else None, result.error,
                    )
                    if result.lease_lost or result.status is TaskStatus.NEEDS_OWNER:
                        halt_file.write_text(
                            f"halted at {time.strftime('%Y-%m-%dT%H:%M:%S')} "
                            f"task={result.task_id} reason={result.error or result.status.value}\n",
                            encoding="utf-8",
                        )
                        log.error("Safety halt written to %s", halt_file)
                        return 2
                if args.once:
                    return 0
                time.sleep(max(5, args.poll_seconds))
        finally:
            store.close()
    except KeyboardInterrupt:
        logging.getLogger("autopilot.runner").warning("Runner interrupted by operator.")
        return 130
    except Exception as error:  # noqa: BLE001 - fail closed, do not loop on an unknown error
        if halt_file is not None:
            try:
                halt_file.parent.mkdir(parents=True, exist_ok=True)
                halt_file.write_text(
                    f"halted at {time.strftime('%Y-%m-%dT%H:%M:%S')} unexpected_error={type(error).__name__}\n",
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
        logging.getLogger("autopilot.runner").exception("Runner stopped safely: %s", error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
