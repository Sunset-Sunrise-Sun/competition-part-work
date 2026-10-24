"""Reserved GitHub REST adapter.

There is intentionally no merge method and no network call in Phase 1A. The
adapter only exposes the fail-closed credential gate used by future phases.
"""

from __future__ import annotations

import os
from typing import Any

from ..models import (
    AdapterCredentialMissing,
    AdapterDisabledError,
    AdapterNotImplementedError,
    ReviewResult,
    TaskRecord,
    TaskSpec,
)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class GitHubRestAdapter:
    """Placeholder source/executor/reviewer bridge; no real writes."""

    def __init__(self, *, enabled: bool, token_present: bool) -> None:
        self.enabled = enabled
        self.token_present = token_present

    @classmethod
    def from_env(cls) -> "GitHubRestAdapter":
        if not _env_truthy("AUTOPILOT_GITHUB_ENABLED"):
            raise AdapterDisabledError(
                "GitHubRestAdapter is disabled by default; enable only after "
                "owner-approved least-privilege automation credentials exist"
            )
        if not os.environ.get("GITHUB_TOKEN"):
            raise AdapterCredentialMissing(
                "GitHubRestAdapter enabled but GITHUB_TOKEN is not configured"
            )
        return cls(enabled=True, token_present=True)

    def fetch_ready_tasks(self) -> list[TaskSpec]:
        raise AdapterNotImplementedError("GitHub polling is not implemented in Phase 1A")

    def push_branch(self, *args: Any, **kwargs: Any) -> None:
        raise AdapterNotImplementedError("Git push is not implemented in Phase 1A")

    def open_draft_pull_request(self, *args: Any, **kwargs: Any) -> None:
        raise AdapterNotImplementedError(
            "Draft PR creation is not implemented in Phase 1A"
        )

    def post_review(self, task: TaskRecord, review: ReviewResult) -> None:
        raise AdapterNotImplementedError(
            "Posting GitHub reviews is not implemented in Phase 1A"
        )
