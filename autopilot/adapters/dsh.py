"""Placeholder adapters for future real integrations.

Phase 1A deliberately does not execute real DSH or call GitHub. Both adapters
fail closed unless explicitly enabled AND a credential reference is present;
even then they only raise ``AdapterNotImplementedError``. No token value is
read into attributes or logs.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..models import (
    AdapterCredentialMissing,
    AdapterDisabledError,
    AdapterNotImplementedError,
    ExecutionResult,
    TaskRecord,
)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class DshHeadlessAdapter:
    """Reserved adapter for `dsh --profile headless --json` execution."""

    def __init__(self, cli_path: Path | None, *, enabled: bool) -> None:
        self.cli_path = cli_path
        self.enabled = enabled

    @classmethod
    def from_env(cls) -> "DshHeadlessAdapter":
        if not _env_truthy("AUTOPILOT_DSH_ENABLED"):
            raise AdapterDisabledError(
                "DshHeadlessAdapter is disabled by default; "
                "set AUTOPILOT_DSH_ENABLED only after explicit owner approval"
            )
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise AdapterCredentialMissing(
                "DshHeadlessAdapter enabled but DEEPSEEK_API_KEY is not configured "
                "for the launching environment"
            )
        cli = os.environ.get("AUTOPILOT_DSH_CLI")
        return cls(Path(cli) if cli else None, enabled=True)

    def build_command(self, task: TaskRecord, workspace: Path) -> list[str]:
        if self.cli_path is None:
            raise AdapterNotImplementedError(
                "AUTOPILOT_DSH_CLI must name the dsh launcher before real execution"
            )
        prompt = (
            "Autopilot task "
            f"{task.task_id} ({task.title}). Work only inside {workspace}."
        )
        return [
            str(self.cli_path),
            "--profile",
            "headless",
            "--json",
            prompt,
        ]

    def execute(
        self,
        task: TaskRecord,
        attempt: int,
        workspace: Path,
        timeout_seconds: float,
    ) -> ExecutionResult:
        raise AdapterNotImplementedError(
            "Phase 1A does not execute a real DSH headless process"
        )
