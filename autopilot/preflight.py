"""Read-only preflight for the LocalFit autopilot runner.

This module deliberately does not import the SQLite store, scheduler, executors,
reviewers or publishers. It only reads configuration, local Git state, GitHub
read-only endpoints and DSH launcher metadata. It never starts a model, creates
a worktree, writes a database, or mutates GitHub.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .adapters.dsh_runtime import (
    DshRuntimeError,
    resolve_dsh_cli,
    resolve_dsh_command,
)
from .adapters.github_runtime import (
    GitHubApiError,
    GitHubIssueAdapter,
    GitHubRuntimeError,
    resolve_github_token,
)
from .redaction import redact

PASS = "pass"
FAIL = "fail"
WARNING = "warning"
NOT_CHECKED = "not_checked"

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_MIN_PYTHON = (3, 11)


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "status": self.status, "message": self.message}


@dataclass(frozen=True)
class GitHubProbeResult:
    repository_accessible: bool
    base_branch_exists: bool | None = None
    repository_error: str | None = None
    repository_error_kind: str | None = None
    base_branch_error: str | None = None
    base_branch_error_kind: str | None = None


@dataclass(frozen=True)
class DshCommandInfo:
    path: str
    command: tuple[str, ...]
    launcher: str


@dataclass
class PreflightReport:
    checks: list[CheckResult] = field(default_factory=list)
    read_only: bool = True

    @property
    def counts(self) -> dict[str, int]:
        counts = {PASS: 0, FAIL: 0, WARNING: 0, NOT_CHECKED: 0}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return counts

    @property
    def blocking(self) -> bool:
        return self.counts[FAIL] > 0

    @property
    def status(self) -> str:
        if self.blocking:
            return "blocked"
        if self.counts[WARNING] or self.counts[NOT_CHECKED]:
            return "ready_with_warnings"
        return "ready"

    @property
    def exit_code(self) -> int:
        return 2 if self.blocking else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "preflight",
            "read_only": self.read_only,
            "status": self.status,
            "exit_code": self.exit_code,
            "summary": self.counts,
            "checks": [check.to_dict() for check in self.checks],
            "limitations": [
                "Read-only preflight cannot prove GitHub write permissions.",
                "Read-only preflight does not invoke DSH or a model; model access is not_checked.",
                "Read-only preflight does not register or start Windows Task Scheduler tasks.",
            ],
        }

    def render_text(self) -> str:
        lines = ["LocalFit Autopilot preflight (READ-ONLY)"]
        for check in self.checks:
            lines.append(f"[{check.status.upper():<11}] {check.check}: {check.message}")
        counts = self.counts
        lines.append(
            "Summary: "
            f"{counts[PASS]} pass, {counts[FAIL]} fail, "
            f"{counts[WARNING]} warning, {counts[NOT_CHECKED]} not_checked"
        )
        lines.append(f"Overall: {self.status} (exit {self.exit_code})")
        lines.append(
            "Read-only limits: GitHub write permissions and DSH model availability are not tested; "
            "not_checked is not a pass."
        )
        if self.status == "ready_with_warnings":
            lines.append(
                "Warnings/not_checked items are NOT passes; review them before a real run."
            )
        return "\n".join(lines)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe(text: str, token: str) -> str:
    cleaned = redact(text or "")
    if token:
        cleaned = cleaned.replace(token, "<redacted>")
    return cleaned[:1000]


def _normalize_path(value: str) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _git_executable() -> str:
    return shutil.which("git") or "git"


def _preflight_git_env() -> dict[str, str]:
    """Copy the parent environment and disable Git's optional index locks.

    ``git status`` may otherwise refresh and write back the index stat cache.
    The parent process environment is never mutated.
    """
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _default_git_runner(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        [_git_executable(), "-C", str(repo_root), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        env=_preflight_git_env(),
    )
    if result.returncode:
        raise RuntimeError(redact(result.stderr.strip())[-500:])
    return result.stdout.strip()


def _default_git_version() -> str:
    result = subprocess.run(
        [_git_executable(), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        env=_preflight_git_env(),
    )
    if result.returncode:
        return ""
    return result.stdout.strip()


def _default_token_resolver() -> str:
    try:
        return resolve_github_token()
    except Exception:  # noqa: BLE001 - absence of a credential is reported as a check
        return ""


def _default_dsh_resolver() -> DshCommandInfo:
    path = resolve_dsh_cli()
    command = tuple(resolve_dsh_command(["--version"]))
    launcher = (
        "cmd-wrapper" if path.lower().endswith((".cmd", ".bat")) else "direct"
    )
    return DshCommandInfo(path=path, command=command, launcher=launcher)


def _github_error_kind(error: BaseException) -> str:
    if isinstance(error, GitHubApiError):
        if error.status_code in (401, 403):
            return "permission"
        if error.status_code == 404:
            return "not_found"
        if error.status_code is None:
            return "network"
        return "api"
    if isinstance(error, (TimeoutError, OSError)):
        return "network"
    if isinstance(error, (GitHubRuntimeError, ValueError)):
        return "configuration"
    return "unexpected"


def _probe_github(
    repo_root: Path,
    repository: str,
    base_branch: str,
    token: str,
) -> GitHubProbeResult:
    """Read-only GitHub adapter probe. No labels, comments, branches or PRs."""
    adapter = GitHubIssueAdapter(
        repository=repository,
        base_branch=base_branch,
        repo_root=repo_root,
        token=token,
        enabled=True,
    )
    try:
        adapter.check_repository_access()
    except Exception as error:  # noqa: BLE001 - classify and report
        return GitHubProbeResult(
            repository_accessible=False,
            repository_error=f"{type(error).__name__}: {error}",
            repository_error_kind=_github_error_kind(error),
        )
    try:
        adapter.check_base_branch()
    except Exception as error:  # noqa: BLE001 - classify and report
        return GitHubProbeResult(
            repository_accessible=True,
            base_branch_exists=False,
            base_branch_error=f"{type(error).__name__}: {error}",
            base_branch_error_kind=_github_error_kind(error),
        )
    return GitHubProbeResult(repository_accessible=True, base_branch_exists=True)


def run_preflight(
    repo_root: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    git_runner: Callable[..., str] | None = None,
    git_version: Callable[[], str] | None = None,
    python_version: tuple[int, ...] | None = None,
    token_resolver: Callable[[], str] | None = None,
    github_probe: Callable[[Path, str, str, str], GitHubProbeResult] | None = None,
    dsh_resolver: Callable[[], DshCommandInfo] | None = None,
) -> PreflightReport:
    """Run checks without initializing any stateful component or calling a model."""
    env_map = os.environ if env is None else env
    git_runner = git_runner or _default_git_runner
    git_version = git_version or _default_git_version
    token_resolver = token_resolver or _default_token_resolver
    github_probe = github_probe or _probe_github
    dsh_resolver = dsh_resolver or _default_dsh_resolver
    python_info = tuple(python_version or sys.version_info[:2])

    report = PreflightReport()

    def add(check: str, status: str, message: str) -> None:
        report.checks.append(CheckResult(check=check, status=status, message=message))

    # ---------------------------------------------------------------- config
    enabled: dict[str, bool] = {}
    for label, name in (
        ("github", "AUTOPILOT_GITHUB_ENABLED"),
        ("dsh", "AUTOPILOT_DSH_ENABLED"),
        ("review", "AUTOPILOT_REVIEW_ENABLED"),
    ):
        enabled[label] = _truthy(env_map.get(name))
        add(
            f"config.{label}.enabled",
            PASS if enabled[label] else FAIL,
            f"{name}=1" if enabled[label] else f"{name} is not explicitly enabled (set to 1)",
        )

    repository = (env_map.get("AUTOPILOT_GITHUB_REPOSITORY") or "").strip()
    repository_valid = bool(_REPO_RE.fullmatch(repository))
    add(
        "config.github.repository",
        PASS if repository_valid else FAIL,
        (
            f"{repository} (owner/name)"
            if repository_valid
            else "AUTOPILOT_GITHUB_REPOSITORY is missing or not owner/name"
        ),
    )

    base_branch = (env_map.get("AUTOPILOT_GITHUB_BASE_BRANCH") or "").strip()
    branch_valid = bool(
        base_branch
        and _BRANCH_RE.fullmatch(base_branch)
        and ".." not in base_branch
        and not base_branch.startswith("/")
    )
    add(
        "config.github.base_branch",
        PASS if branch_valid else FAIL,
        (
            base_branch
            if branch_valid
            else "AUTOPILOT_GITHUB_BASE_BRANCH is missing or invalid"
        ),
    )

    token = ""
    try:
        token = (token_resolver() or "").strip()
        add(
            "github.credentials",
            PASS if token else FAIL,
            (
                "GitHub credential resolved (value not printed)"
                if token
                else "GitHub credential unavailable (GITHUB_TOKEN/GH_TOKEN or authenticated gh CLI)"
            ),
        )
    except Exception as error:  # noqa: BLE001 - report without exposing details
        add("github.credentials", FAIL, _safe(f"credential resolution failed: {error}", token))

    # ----------------------------------------------------------- local repo
    try:
        repo_path = Path(repo_root).expanduser().resolve()
    except Exception as error:  # noqa: BLE001
        repo_path = None
        add("local.repo_root", FAIL, _safe(f"repository path is invalid: {error}", token))

    repo_confirmed = False
    if repo_path is not None:
        if not repo_path.is_dir():
            add("local.repo_root", FAIL, "repository path does not exist or is not a directory")
        else:
            try:
                root = git_runner(repo_path, "rev-parse", "--show-toplevel")
                if _normalize_path(root) != _normalize_path(str(repo_path)):
                    add(
                        "local.repo_root",
                        FAIL,
                        "provided path is not the Git repository root",
                    )
                else:
                    repo_confirmed = True
                    add("local.repo_root", PASS, f"Git repository root: {repo_path}")
            except Exception as error:  # noqa: BLE001
                add("local.repo_root", FAIL, _safe(f"not a readable Git repository: {error}", token))

    try:
        version = (git_version() or "").strip()
        if version:
            add("local.git", PASS, version)
        else:
            add("local.git", FAIL, "git executable did not report a version")
    except Exception as error:  # noqa: BLE001
        add("local.git", FAIL, _safe(f"git check failed: {error}", token))

    py_text = ".".join(str(part) for part in python_info)
    add(
        "local.python",
        PASS if python_info >= _MIN_PYTHON else FAIL,
        f"Python {py_text} (requires >= {'.'.join(map(str, _MIN_PYTHON))})",
    )

    if repo_confirmed:
        try:
            status = git_runner(
                repo_path, "status", "--porcelain", "--untracked-files=all"
            )
            changed = len([line for line in status.splitlines() if line.strip()])
            if changed:
                add(
                    "local.workspace_state",
                    WARNING,
                    f"working tree has {changed} changed/untracked entries; inspect before a real run",
                )
            else:
                add("local.workspace_state", PASS, "working tree is clean")
        except Exception as error:  # noqa: BLE001
            add(
                "local.workspace_state",
                WARNING,
                _safe(f"could not read git status; not verified: {error}", token),
            )

        if branch_valid:
            try:
                git_runner(
                    repo_path,
                    "rev-parse",
                    "--verify",
                    f"refs/heads/{base_branch}^{{commit}}",
                )
                add("local.base_branch", PASS, f"local base branch {base_branch} exists")
            except Exception:
                add(
                    "local.base_branch",
                    WARNING,
                    f"local base branch {base_branch} not found; remote check may still pass",
                )
        else:
            add("local.base_branch", NOT_CHECKED, "base branch configuration is invalid")
    else:
        add(
            "local.workspace_state",
            NOT_CHECKED,
            "not checked because the repository root was not confirmed",
        )
        add(
            "local.base_branch",
            NOT_CHECKED,
            "not checked because the repository root was not confirmed",
        )

    # ------------------------------------------------------------------ DSH
    dsh_info: DshCommandInfo | None = None
    try:
        dsh_info = dsh_resolver()
        add("dsh.cli", PASS, f"DSH launcher resolved: {dsh_info.path}")
        if dsh_info.launcher == "cmd-wrapper":
            if os.name != "nt":
                add(
                    "dsh.windows_entrypoint",
                    WARNING,
                    "launcher is .cmd/.bat but this host is not Windows; entrypoint not exercised",
                )
            else:
                launcher = Path(dsh_info.command[0]) if dsh_info.command else None
                resolved = (
                    launcher
                    if launcher is not None and launcher.is_file()
                    else shutil.which(dsh_info.command[0]) if dsh_info.command else None
                )
                add(
                    "dsh.windows_entrypoint",
                    PASS if resolved else FAIL,
                    (
                        "COM/cmd wrapper resolves for the Windows entrypoint"
                        if resolved
                        else "Windows .cmd/.bat entrypoint could not resolve COMSPEC/cmd.exe"
                    ),
                )
        else:
            add(
                "dsh.windows_entrypoint",
                PASS,
                "direct executable launcher resolves; .cmd/.bat wrapper not required",
            )
    except DshRuntimeError as error:
        add("dsh.cli", FAIL, _safe(str(error), token))
        add("dsh.windows_entrypoint", NOT_CHECKED, "not checked because DSH CLI did not resolve")
    except Exception as error:  # noqa: BLE001
        add("dsh.cli", FAIL, _safe(f"DSH CLI resolution failed: {error}", token))
        add("dsh.windows_entrypoint", NOT_CHECKED, "not checked because DSH CLI did not resolve")

    add(
        "dsh.model_access",
        NOT_CHECKED,
        "preflight does not invoke DSH or a model; availability and credentials are unverified",
    )
    add(
        "dsh.environment_isolation",
        NOT_CHECKED,
        "executor strips provider/token/SSH variables before spawning DSH; preflight does not start a child to verify it",
    )

    # -------------------------------------------------------------- GitHub API
    can_probe = (
        enabled.get("github")
        and repository_valid
        and branch_valid
        and bool(token)
        and repo_confirmed
    )
    if not can_probe:
        reason = (
            "GitHub automation is disabled"
            if not enabled.get("github")
            else "GitHub configuration or credential is incomplete"
        )
        add("github.repository_access", NOT_CHECKED, f"not checked: {reason}")
        add("github.base_branch", NOT_CHECKED, f"not checked: {reason}")
    else:
        try:
            probe = github_probe(repo_path, repository, base_branch, token)  # type: ignore[arg-type]
            if not isinstance(probe, GitHubProbeResult):
                raise TypeError("GitHub probe returned an invalid result")
        except Exception as error:  # noqa: BLE001
            kind = _github_error_kind(error)
            add(
                "github.repository_access",
                FAIL,
                _safe(f"read-only repository probe failed ({kind}): {error}", token),
            )
            add(
                "github.base_branch",
                NOT_CHECKED,
                "not checked because the repository probe failed",
            )
        else:
            if probe.repository_accessible:
                add(
                    "github.repository_access",
                    PASS,
                    "repository is reachable via a read-only GET",
                )
            else:
                kind = probe.repository_error_kind or "api"
                add(
                    "github.repository_access",
                    FAIL,
                    _safe(
                        f"read-only repository probe failed ({kind}): {probe.repository_error or 'unknown error'}",
                        token,
                    ),
                )
            if not probe.repository_accessible:
                add(
                    "github.base_branch",
                    NOT_CHECKED,
                    "not checked because the repository probe failed",
                )
            elif probe.base_branch_exists is True:
                add(
                    "github.base_branch",
                    PASS,
                    f"base branch {base_branch} exists via a read-only GET",
                )
            elif probe.base_branch_exists is False:
                kind = probe.base_branch_error_kind or "api"
                add(
                    "github.base_branch",
                    FAIL,
                    _safe(
                        f"read-only base-branch probe failed ({kind}): {probe.base_branch_error or 'branch not found'}",
                        token,
                    ),
                )
            else:
                add(
                    "github.base_branch",
                    NOT_CHECKED,
                    "base branch existence was not reported by the probe",
                )

    add(
        "github.write_capability",
        NOT_CHECKED,
        "read-only preflight cannot prove Contents/Issues/Pull-request write permissions",
    )

    return report
