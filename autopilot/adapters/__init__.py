"""Adapters package for the autopilot runtime."""

from .dsh import DshHeadlessAdapter
from .dsh_runtime import DshDiffReviewer, DshRuntimeError, DshWorktreeExecutor, UnsafeTaskChange
from .github import GitHubRestAdapter
from .github_runtime import GitHubApiError, GitHubIssueAdapter, GitHubRuntimeError

__all__ = [
    "DshHeadlessAdapter",
    "DshDiffReviewer",
    "DshRuntimeError",
    "DshWorktreeExecutor",
    "GitHubRestAdapter",
    "GitHubApiError",
    "GitHubIssueAdapter",
    "GitHubRuntimeError",
    "UnsafeTaskChange",
]
