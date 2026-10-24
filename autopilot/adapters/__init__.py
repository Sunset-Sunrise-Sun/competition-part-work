"""Adapters package for the autopilot skeleton."""

from .dsh import DshHeadlessAdapter
from .github import GitHubRestAdapter

__all__ = ["DshHeadlessAdapter", "GitHubRestAdapter"]
