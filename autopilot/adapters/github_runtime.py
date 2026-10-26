"""Opt-in GitHub issue queue and draft-PR publisher.

All writes are scoped to the configured repository and the task's dedicated
`autopilot/*` branch. There is deliberately no merge or default-branch push
operation. Enable only after a least-privilege token and base branch are set.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..interfaces import TaskSource
from ..models import ExecutionResult, ReviewResult, ReviewVerdict, TaskRecord, TaskSpec, TaskStatus
from ..redaction import redact

if TYPE_CHECKING:
    from ..scheduler import RunResult

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_GIT_EXECUTABLE = shutil.which("git") or "git"
_LABELS: dict[str, tuple[str, str]] = {
    "agent:ready": ("0e8a16", "Ready for bounded agent execution"),
    "agent:working": ("1d76db", "An agent task is being processed"),
    "agent:changes-requested": ("d93f0b", "Automated review requested changes"),
    "agent:done": ("5319e7", "Automated task and draft PR created"),
    "needs-owner": ("b60205", "Automation paused for owner decision"),
}


class GitHubRuntimeError(RuntimeError):
    """A GitHub API or publication operation failed safely."""


class GitHubApiError(GitHubRuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_branch(task_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-.")[:48] or "task"
    return f"autopilot/{slug}"


def resolve_github_token() -> str:
    """Resolve the existing GitHub credential without logging its value."""
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token:
        return token
    gh_cli = shutil.which("gh")
    if not gh_cli:
        return ""
    try:
        result = subprocess.run(
            [gh_cli, "auth", "token", "--hostname", "github.com"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git(repo_root: Path, *args: str, token: str | None = None, timeout: float = 60.0) -> str:
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if upper in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}:
            env.pop(key, None)
        elif upper.startswith("GIT_CONFIG_KEY_") or upper.startswith("GIT_CONFIG_VALUE_"):
            env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    with tempfile.TemporaryDirectory(prefix="autopilot-git-config-") as directory:
        empty_config = Path(directory) / "empty.gitconfig"
        empty_config.write_text("", encoding="utf-8")
        env["GIT_CONFIG_GLOBAL"] = str(empty_config)
        env["GIT_CONFIG_SYSTEM"] = str(empty_config)
        entries = [
            ("credential.helper", ""),
            ("http.extraheader", ""),
            ("http.https://github.com/.extraheader", ""),
        ]
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
            entries.append(("http.https://github.com/.extraheader", f"AUTHORIZATION: basic {basic}"))
        env["GIT_CONFIG_COUNT"] = str(len(entries))
        for index, (key, value) in enumerate(entries):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        result = subprocess.run(
            [_GIT_EXECUTABLE, "-C", str(repo_root), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    if result.returncode:
        message = redact(result.stderr.strip())[-2000:]
        raise GitHubRuntimeError(f"git operation failed ({result.returncode}): {message}")
    return result.stdout.strip()


class GitHubIssueAdapter(TaskSource):
    """Read `agent:ready` issues and publish reviewed commits as Draft PRs."""

    def __init__(
        self,
        *,
        repository: str,
        base_branch: str,
        repo_root: str | Path,
        token: str,
        enabled: bool = False,
        poll_interval_seconds: float = 30.0,
        request_timeout_seconds: float = 15.0,
    ) -> None:
        if not enabled:
            raise GitHubRuntimeError("GitHub automation is disabled; set AUTOPILOT_GITHUB_ENABLED=1")
        if not _REPO_RE.fullmatch(repository):
            raise ValueError("repository must use owner/name format")
        if not _BRANCH_RE.fullmatch(base_branch) or ".." in base_branch or base_branch.startswith("/"):
            raise ValueError("base branch contains invalid ref characters")
        if not token.strip():
            raise ValueError("GitHub token must be non-empty")
        self.repository = repository
        self.owner = repository.split("/", 1)[0]
        self.base_branch = base_branch
        self.repo_root = Path(repo_root).resolve()
        self.token = token
        self.poll_interval_seconds = max(5.0, float(poll_interval_seconds))
        self.request_timeout_seconds = float(request_timeout_seconds)
        self._pending: deque[TaskSpec] = deque()
        self._next_poll_at = 0.0
        self._ensured_labels: set[str] = set()
        self._published_prs: dict[str, str] = {}
        if not self.repo_root.is_dir():
            raise ValueError(f"repository working directory does not exist: {self.repo_root}")
        root = Path(_git(self.repo_root, "rev-parse", "--show-toplevel")).resolve()
        if root != self.repo_root:
            raise ValueError(f"repo_root must be the Git repository root: {self.repo_root} != {root}")

    @classmethod
    def from_env(cls, repo_root: str | Path, *, enabled: bool | None = None) -> "GitHubIssueAdapter":
        enabled_value = _truthy("AUTOPILOT_GITHUB_ENABLED") if enabled is None else enabled
        if not enabled_value:
            raise GitHubRuntimeError("GitHub automation is disabled by default")
        token = resolve_github_token()
        repository = os.environ.get("AUTOPILOT_GITHUB_REPOSITORY", "").strip()
        base_branch = os.environ.get("AUTOPILOT_GITHUB_BASE_BRANCH", "").strip()
        missing = [
            name for name, value in (
                ("GitHub token (GITHUB_TOKEN/GH_TOKEN or authenticated gh CLI)", token),
                ("AUTOPILOT_GITHUB_REPOSITORY", repository),
                ("AUTOPILOT_GITHUB_BASE_BRANCH", base_branch),
            ) if not value
        ]
        if missing:
            raise GitHubRuntimeError("missing required environment settings: " + ", ".join(missing))
        return cls(
            repository=repository,
            base_branch=base_branch,
            repo_root=repo_root,
            token=token,
            enabled=True,
            poll_interval_seconds=float(os.environ.get("AUTOPILOT_POLL_SECONDS", "30")),
        )

    @property
    def api_root(self) -> str:
        return f"https://api.github.com/repos/{self.repository}"

    def check_repository_access(self) -> dict[str, Any]:
        """Read-only probe: GET the configured repository."""
        response = self._request("GET", "")
        if not isinstance(response, dict):
            raise GitHubRuntimeError("GitHub repository probe returned a non-object response")
        return response

    def check_base_branch(self) -> dict[str, Any]:
        """Read-only probe: GET the configured base branch."""
        response = self._request("GET", f"/branches/{quote(self.base_branch, safe='')}")
        if not isinstance(response, dict):
            raise GitHubRuntimeError("GitHub branch probe returned a non-object response")
        return response

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.api_root + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "LocalFit-Autopilot",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            detail = redact(error.read().decode("utf-8", errors="replace"))[:500]
            raise GitHubApiError(
                f"GitHub API {method} {path} returned HTTP {error.code}: {detail}",
                status_code=error.code,
            ) from error
        except URLError as error:
            raise GitHubApiError(f"GitHub API {method} {path} failed: {type(error).__name__}") from error
        except json.JSONDecodeError as error:
            raise GitHubApiError(f"GitHub API {method} {path} returned invalid JSON") from error

    def _ensure_label(self, name: str) -> None:
        if name in self._ensured_labels:
            return
        if name not in _LABELS:
            raise ValueError(f"unknown automation label: {name}")
        try:
            self._request("GET", f"/labels/{quote(name, safe='')}")
        except GitHubApiError as error:
            if error.status_code != 404:
                raise
            color, description = _LABELS[name]
            try:
                self._request("POST", "/labels", {"name": name, "color": color, "description": description})
            except GitHubApiError as create_error:
                if create_error.status_code != 422:
                    raise
                # A concurrent worker may have created the same label.
                self._request("GET", f"/labels/{quote(name, safe='')}")
        self._ensured_labels.add(name)

    def _fetch_base_sha(self) -> str:
        # Fetch to a private remote-tracking ref; do not switch the user's checkout.
        _git(
            self.repo_root,
            "fetch",
            "--no-tags",
            "--depth=1",
            f"https://github.com/{self.repository}.git",
            f"+refs/heads/{self.base_branch}:refs/remotes/autopilot/base",
            token=self.token,
            timeout=90.0,
        )
        sha = _git(self.repo_root, "rev-parse", "refs/remotes/autopilot/base")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            raise GitHubRuntimeError("fetched base ref did not resolve to a full commit SHA")
        return sha

    def _ready_issues(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for page in range(1, 6):
            query = urlencode({
                "state": "open",
                "labels": "agent:ready",
                "per_page": 100,
                "page": page,
                "sort": "created",
                "direction": "asc",
            })
            batch = self._request("GET", f"/issues?{query}")
            if not isinstance(batch, list):
                raise GitHubRuntimeError("GitHub issues endpoint returned a non-list response")
            results.extend(item for item in batch if isinstance(item, dict) and "pull_request" not in item)
            if len(batch) < 100:
                break
        return results

    def next_ready(self) -> TaskSpec | None:
        if not self._pending:
            now = time.monotonic()
            if now < self._next_poll_at:
                return None
            self._next_poll_at = now + self.poll_interval_seconds
            self._ensure_label("agent:ready")
            base_sha = self._fetch_base_sha()
            issues = self._ready_issues()
            for issue in issues:
                number = issue.get("number")
                title = issue.get("title")
                body = issue.get("body") or ""
                labels = {
                    item.get("name") for item in issue.get("labels", [])
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                }
                if "agent:ready" not in labels or not isinstance(number, int) or not isinstance(title, str):
                    continue
                payload = {
                    "issue_number": number,
                    "issue_url": issue.get("html_url", ""),
                    "repository": self.repository,
                    "base_branch": self.base_branch,
                    "repo_root": str(self.repo_root),
                    "instructions": body.strip() or title,
                }
                self._pending.append(TaskSpec(
                    task_id=f"gh-issue-{number}",
                    title=title,
                    base_sha=base_sha,
                    payload=payload,
                ))
        return self._pending.popleft() if self._pending else None

    def _issue_number(self, task: TaskRecord) -> int:
        number = task.payload.get("issue_number")
        if not isinstance(number, int) or number < 1:
            raise GitHubRuntimeError(f"task {task.task_id} has no valid GitHub issue number")
        if task.payload.get("repository") != self.repository:
            raise GitHubRuntimeError("task repository does not match configured repository")
        return number

    def _add_comment_once(self, issue_number: int, marker: str, body: str) -> None:
        comments = self._request("GET", f"/issues/{issue_number}/comments?per_page=100")
        if isinstance(comments, list):
            for comment in comments:
                if isinstance(comment, dict) and marker in str(comment.get("body") or ""):
                    return
        self._request("POST", f"/issues/{issue_number}/comments", {"body": f"{marker}\n{body}"})

    def _set_labels(self, issue_number: int, *, add: list[str], remove: list[str]) -> None:
        for label in add + remove:
            self._ensure_label(label)
        if add:
            self._request("POST", f"/issues/{issue_number}/labels", {"labels": add})
        for label in remove:
            try:
                self._request("DELETE", f"/issues/{issue_number}/labels/{quote(label, safe='')}")
            except GitHubApiError as error:
                if error.status_code != 404:
                    raise

    def _push_branch(self, branch: str) -> None:
        if not branch.startswith("autopilot/"):
            raise GitHubRuntimeError("refusing to publish a branch outside autopilot/*")
        _git(self.repo_root, "check-ref-format", "--branch", branch)
        _git(
            self.repo_root,
            "push",
            f"https://github.com/{self.repository}.git",
            f"refs/heads/{branch}:refs/heads/{branch}",
            token=self.token,
            timeout=120.0,
        )

    def _pull_query(self, branch: str) -> list[dict[str, Any]]:
        query = urlencode({
            "state": "open",
            "head": f"{self.owner}:{branch}",
            "base": self.base_branch,
            "per_page": 100,
        })
        response = self._request("GET", f"/pulls?{query}")
        if not isinstance(response, list):
            raise GitHubRuntimeError("GitHub pull request search returned a non-list response")
        return [item for item in response if isinstance(item, dict)]

    def _validate_pr_identity(self, pr: dict[str, Any], branch: str) -> None:
        head = pr.get("head")
        base = pr.get("base")
        if not isinstance(head, dict) or not isinstance(base, dict):
            raise GitHubRuntimeError("existing pull request is missing head/base metadata")
        if head.get("ref") != branch or base.get("ref") != self.base_branch:
            raise GitHubRuntimeError("existing pull request branch/base does not match this task")
        head_repo = head.get("repo")
        if not isinstance(head_repo, dict) or head_repo.get("full_name") != self.repository:
            raise GitHubRuntimeError("existing pull request head repository does not match configuration")

    def _validate_pr_head(self, pr: dict[str, Any], branch: str, head_sha: str) -> str:
        self._validate_pr_identity(pr, branch)
        if pr.get("draft") is not True:
            raise GitHubRuntimeError("matching pull request is no longer a Draft; owner review required")
        head = pr["head"]
        if str(head.get("sha", "")).lower() != head_sha.lower():
            raise GitHubRuntimeError("published pull request head does not match the reviewed SHA")
        url = pr.get("html_url")
        if not isinstance(url, str):
            raise GitHubRuntimeError("GitHub did not return a valid pull request URL")
        return url

    def publish_approved(
        self,
        task: TaskRecord,
        review: ReviewResult,
        execution: ExecutionResult | None,
    ) -> str:
        if review.verdict is not ReviewVerdict.APPROVED:
            raise GitHubRuntimeError("only an approved review may be published")
        number = self._issue_number(task)
        branch = execution.artifact if execution and execution.artifact else _safe_branch(task.task_id)
        if not branch.startswith("autopilot/"):
            raise GitHubRuntimeError("executor returned a branch outside autopilot/*")

        existing = self._pull_query(branch)
        if existing:
            pr = existing[0]
            self._validate_pr_identity(pr, branch)
            if str(pr["head"].get("sha", "")).lower() == review.head_sha.lower():
                pr_url = self._validate_pr_head(pr, branch, review.head_sha)
            else:
                local_head = _git(self.repo_root, "rev-parse", f"refs/heads/{branch}")
                if local_head.lower() != review.head_sha.lower():
                    raise GitHubRuntimeError("local task branch does not match the approved head SHA")
                self._push_branch(branch)
                refreshed = self._pull_query(branch)
                if not refreshed:
                    raise GitHubRuntimeError("existing Draft PR disappeared after branch publication")
                pr_url = self._validate_pr_head(refreshed[0], branch, review.head_sha)
        else:
            local_head = _git(self.repo_root, "rev-parse", f"refs/heads/{branch}")
            if local_head.lower() != review.head_sha.lower():
                raise GitHubRuntimeError("local task branch does not match the approved head SHA")
            self._push_branch(branch)
            title = f"[Autopilot] {task.title}"[:240]
            body = (
                f"Automated draft for issue #{number}.\n\n"
                f"- Task ID: `{task.task_id}`\n"
                f"- Base SHA: `{task.base_sha}`\n"
                f"- Approved head SHA: `{review.head_sha}`\n"
                f"- Automated review: {redact(review.notes)[:3000]}\n\n"
                f"Closes #{number} after this PR is merged.\n\n"
                "This PR was created as a Draft. No automatic merge is performed."
            )
            try:
                pr = self._request("POST", "/pulls", {
                    "title": title,
                    "head": branch,
                    "base": self.base_branch,
                    "body": body,
                    "draft": True,
                    "maintainer_can_modify": False,
                })
            except GitHubApiError as error:
                if error.status_code != 422:
                    raise
                raced = self._pull_query(branch)
                if not raced:
                    raise
                pr = raced[0]
            if not isinstance(pr, dict):
                raise GitHubRuntimeError("GitHub did not return a valid pull request object")
            pr_url = self._validate_pr_head(pr, branch, review.head_sha)

        self._published_prs[task.task_id] = pr_url
        return pr_url

    def on_task_result(self, task: TaskRecord, result: "RunResult") -> None:
        number = self._issue_number(task)
        head_sha = (
            result.review.head_sha if result.review is not None
            else result.execution.head_sha if result.execution is not None
            else task.head_sha
        )
        if result.status is TaskStatus.DONE:
            # Reconciliation is idempotent: ensure an approved task has a published Draft PR.
            pr_url = ""
            if head_sha:
                pr_url = self.publish_approved(
                    task,
                    ReviewResult(
                        verdict=ReviewVerdict.APPROVED,
                        head_sha=head_sha,
                        reviewer="autopilot-reconciliation",
                        notes="Previously approved task; publication reconciliation.",
                    ),
                    result.execution,
                )
            self._set_labels(
                number,
                add=["agent:done"],
                remove=["agent:ready", "agent:working", "agent:changes-requested", "needs-owner"],
            )
            if head_sha and pr_url:
                notes = result.review.notes if result.review is not None else "Previously approved task; publication reconciliation."
                marker = f"<!-- autopilot:published {task.task_id} {head_sha} -->"
                self._add_comment_once(
                    number,
                    marker,
                    f"Automated review approved `{head_sha}`. Draft PR: {pr_url}\n"
                    f"Review summary: {redact(notes)[:2000]}",
                )
        elif result.status is TaskStatus.CHANGES_REQUESTED:
            self._set_labels(
                number,
                add=["agent:changes-requested"],
                remove=["agent:ready", "agent:working", "needs-owner"],
            )
            defects = result.review.defects if result.review is not None else ()
            details = "\n".join(f"- {redact(item)[:1000]}" for item in defects) or "- Review requested changes; inspect the task record."
            sha_text = f" for head `{head_sha}`" if head_sha else ""
            self._add_comment_once(
                number,
                f"<!-- autopilot:changes {task.task_id} {head_sha or 'unknown'} -->",
                f"Automated review requested changes{sha_text}:\n{details}",
            )
        elif result.status is TaskStatus.NEEDS_OWNER:
            self._set_labels(
                number,
                add=["needs-owner"],
                remove=["agent:ready", "agent:working", "agent:changes-requested"],
            )
            reason = redact(result.error or (task.last_error or "A task requires owner review."))[:3000]
            self._add_comment_once(
                number,
                f"<!-- autopilot:needs-owner {task.task_id} {head_sha or 'unknown'} -->",
                f"Automation paused for owner action.\n\nReason: {reason}",
            )
        # READY is a bounded retry state; keep agent:ready so the task is visible.
