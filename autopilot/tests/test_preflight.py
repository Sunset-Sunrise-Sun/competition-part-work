from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autopilot import daemon, preflight
from autopilot.adapters.dsh_runtime import DshRuntimeError
from autopilot.adapters.github_runtime import GitHubApiError
from autopilot.preflight import (
    DshCommandInfo,
    GitHubProbeResult,
    PreflightReport,
    run_preflight,
)

TOKEN = "super-secret-token-123"


def good_env() -> dict[str, str]:
    return {
        "AUTOPILOT_GITHUB_ENABLED": "1",
        "AUTOPILOT_DSH_ENABLED": "1",
        "AUTOPILOT_REVIEW_ENABLED": "1",
        "AUTOPILOT_GITHUB_REPOSITORY": "acme/repo",
        "AUTOPILOT_GITHUB_BASE_BRANCH": "feat/integration",
    }


def fake_git(root: Path, *args: str) -> str:
    if args[:2] == ("rev-parse", "--show-toplevel"):
        return str(root)
    if args and args[0] == "status":
        return ""
    if args and args[0] == "rev-parse":
        return "a" * 40
    raise RuntimeError(f"unexpected fake git args: {args}")


def fake_dsh() -> DshCommandInfo:
    return DshCommandInfo(
        path="C:/fake/dsh.exe",
        command=("C:/fake/dsh.exe",),
        launcher="direct",
    )


def fake_probe(
    root: Path, repository: str, base_branch: str, token: str
) -> GitHubProbeResult:
    return GitHubProbeResult(repository_accessible=True, base_branch_exists=True)


def run_fake(tmp: Path, **overrides):
    kwargs = dict(
        env=good_env(),
        git_runner=fake_git,
        git_version=lambda: "git version 2.45.0",
        python_version=(3, 14),
        token_resolver=lambda: TOKEN,
        github_probe=fake_probe,
        dsh_resolver=fake_dsh,
    )
    kwargs.update(overrides)
    return run_preflight(tmp, **kwargs)


def checks(report: PreflightReport) -> dict[str, object]:
    return {check.check: check for check in report.checks}


class PreflightChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_all_configured_environment_is_structured_and_ready_with_warnings(self) -> None:
        report = run_fake(self.root)
        by_name = checks(report)

        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.status, "ready_with_warnings")
        self.assertTrue(report.read_only)
        for name in (
            "config.github.enabled",
            "config.dsh.enabled",
            "config.review.enabled",
            "config.github.repository",
            "config.github.base_branch",
            "github.credentials",
            "local.repo_root",
            "local.git",
            "local.python",
            "local.workspace_state",
            "local.base_branch",
            "dsh.cli",
            "github.repository_access",
            "github.base_branch",
        ):
            self.assertEqual(by_name[name].status, "pass", name)
        self.assertEqual(by_name["dsh.model_access"].status, "not_checked")
        self.assertEqual(by_name["github.write_capability"].status, "not_checked")
        self.assertNotIn(TOKEN, report.render_text())
        self.assertNotIn(TOKEN, json.dumps(report.to_dict()))

    def test_missing_switches_and_github_configuration_are_reported_individually(self) -> None:
        probe = Mock(side_effect=AssertionError("GitHub probe must not run"))
        report = run_fake(
            self.root,
            env={},
            token_resolver=lambda: "",
            github_probe=probe,
        )
        by_name = checks(report)

        self.assertEqual(report.exit_code, 2)
        self.assertEqual(report.status, "blocked")
        for name in (
            "config.github.enabled",
            "config.dsh.enabled",
            "config.review.enabled",
            "config.github.repository",
            "config.github.base_branch",
            "github.credentials",
        ):
            self.assertEqual(by_name[name].status, "fail", name)
        self.assertEqual(by_name["github.repository_access"].status, "not_checked")
        self.assertEqual(by_name["github.base_branch"].status, "not_checked")
        probe.assert_not_called()

    def test_missing_dsh_cli_is_a_focused_failure(self) -> None:
        def missing_dsh() -> DshCommandInfo:
            raise DshRuntimeError("DSH CLI not found; set AUTOPILOT_DSH_CLI")

        report = run_fake(self.root, dsh_resolver=missing_dsh)
        by_name = checks(report)
        self.assertEqual(report.exit_code, 2)
        self.assertEqual(by_name["dsh.cli"].status, "fail")
        self.assertIn("DSH CLI", by_name["dsh.cli"].message)
        self.assertEqual(by_name["dsh.windows_entrypoint"].status, "not_checked")

    def test_github_repository_permission_and_base_branch_failures_are_distinct(self) -> None:
        def no_access(root, repository, base_branch, token):
            return GitHubProbeResult(
                repository_accessible=False,
                repository_error="HTTP 403 forbidden",
                repository_error_kind="permission",
            )

        report = run_fake(self.root, github_probe=no_access)
        by_name = checks(report)
        self.assertEqual(by_name["github.repository_access"].status, "fail")
        self.assertIn("permission", by_name["github.repository_access"].message)
        self.assertEqual(by_name["github.base_branch"].status, "not_checked")

    def test_github_missing_base_branch_is_reported(self) -> None:
        def no_branch(root, repository, base_branch, token):
            return GitHubProbeResult(
                repository_accessible=True,
                base_branch_exists=False,
                base_branch_error="HTTP 404 Not Found",
                base_branch_error_kind="not_found",
            )

        report = run_fake(self.root, github_probe=no_branch)
        by_name = checks(report)
        self.assertEqual(by_name["github.repository_access"].status, "pass")
        self.assertEqual(by_name["github.base_branch"].status, "fail")
        self.assertIn("not_found", by_name["github.base_branch"].message)

    def test_github_network_failure_is_reported(self) -> None:
        def network_error(root, repository, base_branch, token):
            raise GitHubApiError("connection timed out", status_code=None)

        report = run_fake(self.root, github_probe=network_error)
        by_name = checks(report)
        self.assertEqual(by_name["github.repository_access"].status, "fail")
        self.assertIn("network", by_name["github.repository_access"].message)
        self.assertEqual(by_name["github.base_branch"].status, "not_checked")

    def test_token_is_redacted_even_when_an_error_contains_it(self) -> None:
        def leaky_probe(root, repository, base_branch, token):
            raise GitHubApiError(f"bad token {TOKEN}", status_code=403)

        report = run_fake(self.root, github_probe=leaky_probe)
        rendered = report.render_text() + json.dumps(report.to_dict())
        self.assertNotIn(TOKEN, rendered)
        self.assertIn("<redacted>", rendered)

    def test_preflight_writes_no_files_and_does_not_initialize_stateful_components(self) -> None:
        before = sorted(path.name for path in self.root.iterdir())
        report = run_fake(self.root)
        after = sorted(path.name for path in self.root.iterdir())
        self.assertEqual(before, after)
        self.assertFalse(hasattr(preflight, "SqliteStore"))
        self.assertFalse(hasattr(preflight, "Scheduler"))
        self.assertFalse(hasattr(preflight, "DshWorktreeExecutor"))
        self.assertEqual(report.exit_code, 0)

    def test_missing_git_tool_is_reported(self) -> None:
        report = run_fake(self.root, git_version=lambda: "")
        by_name = checks(report)
        self.assertEqual(by_name["local.git"].status, "fail")
        self.assertEqual(report.exit_code, 2)

    def test_preflight_does_not_call_task_or_publish_methods(self) -> None:
        with (
            patch(
                "autopilot.adapters.github_runtime.GitHubIssueAdapter.next_ready",
                side_effect=AssertionError("task claim must not run"),
            ),
            patch(
                "autopilot.adapters.github_runtime.GitHubIssueAdapter.publish_approved",
                side_effect=AssertionError("publish must not run"),
            ),
            patch(
                "autopilot.adapters.dsh_runtime.DshWorktreeExecutor.execute",
                side_effect=AssertionError("execution must not run"),
            ),
            patch(
                "autopilot.adapters.dsh_runtime.DshDiffReviewer.review",
                side_effect=AssertionError("review must not run"),
            ),
        ):
            report = run_fake(self.root)
        self.assertEqual(report.exit_code, 0)

    def test_repository_root_mismatch_is_a_failure(self) -> None:
        def wrong_root(root: Path, *args: str) -> str:
            if args[:2] == ("rev-parse", "--show-toplevel"):
                return str(root / "not-the-root")
            return fake_git(root, *args)

        report = run_fake(self.root, git_runner=wrong_root)
        by_name = checks(report)
        self.assertEqual(by_name["local.repo_root"].status, "fail")
        self.assertEqual(by_name["github.repository_access"].status, "not_checked")


class RealGitReadOnlyTest(unittest.TestCase):
    """Real-index regression: preflight status must not refresh/write .git/index."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git = shutil.which("git") or "git"
        self._git("init")
        self._git("config", "user.email", "preflight-test@example.invalid")
        self._git("config", "user.name", "Preflight Test")
        self.tracked = self.repo / "tracked.txt"
        self.tracked.write_text("one\n", encoding="utf-8")
        self._git("add", "tracked.txt")
        self._git("commit", "-m", "init")

    def _git(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.git, "-C", str(self.repo), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )

    def _index_hash(self) -> str:
        return hashlib.sha256((self.repo / ".git" / "index").read_bytes()).hexdigest()

    def _make_mtime_mismatch(self, seconds: float) -> None:
        stat = self.tracked.stat()
        os.utime(
            self.tracked,
            (stat.st_atime + seconds, stat.st_mtime + seconds),
        )

    def test_preflight_status_preserves_index_and_still_reports_dirty_workspace(self) -> None:
        index_path = self.repo / ".git" / "index"
        original_index = index_path.read_bytes()
        before_control = self._index_hash()

        # Control: prove this Git version would refresh the index on a
        # timestamp-only mismatch when optional locks are not disabled.
        self._make_mtime_mismatch(10)
        control = self._git("status", "--porcelain")
        self.assertEqual(control.returncode, 0, control.stderr)
        if self._index_hash() == before_control:
            self.skipTest(
                "This Git version did not rewrite .git/index for a timestamp-only "
                "mismatch; cannot prove the optional-lock regression on this host."
            )

        # Restore the original index, then make a real dirty workspace state.
        index_path.write_bytes(original_index)
        self.tracked.write_text("two\n", encoding="utf-8")
        self._make_mtime_mismatch(20)
        before_preflight = self._index_hash()
        env_before = dict(os.environ)

        report = run_preflight(
            self.repo,
            env={},
            token_resolver=lambda: "",
            github_probe=Mock(side_effect=AssertionError("GitHub must not be called")),
            dsh_resolver=fake_dsh,
        )

        after_preflight = self._index_hash()
        self.assertEqual(
            before_preflight,
            after_preflight,
            ".git/index was rewritten by the read-only preflight Git status check",
        )
        self.assertEqual(dict(os.environ), env_before)
        self.assertEqual(
            os.environ.get("GIT_OPTIONAL_LOCKS"),
            env_before.get("GIT_OPTIONAL_LOCKS"),
        )

        by_name = checks(report)
        self.assertEqual(by_name["local.repo_root"].status, "pass")
        self.assertEqual(by_name["local.workspace_state"].status, "warning")
        self.assertIn("changed/untracked", by_name["local.workspace_state"].message)


class DaemonPreflightIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_preflight_and_once_combination_is_rejected_without_initializing_runner(self) -> None:
        output = io.StringIO()
        with (
            patch("autopilot.daemon.SqliteStore") as store,
            patch("autopilot.daemon.Scheduler") as scheduler,
            patch("autopilot.daemon.DshWorktreeExecutor") as executor,
            patch("autopilot.daemon.DshDiffReviewer") as reviewer,
            redirect_stdout(output),
        ):
            code = daemon.main(["--repo-root", str(self.root), "--preflight", "--once"])
        self.assertEqual(code, 2)
        self.assertIn("cannot be combined", output.getvalue())
        store.assert_not_called()
        scheduler.assert_not_called()
        executor.assert_not_called()
        reviewer.assert_not_called()

    def test_preflight_branch_does_not_construct_runner_components(self) -> None:
        report = PreflightReport(
            checks=[preflight.CheckResult(check="test", status="pass", message="ok")]
        )
        output = io.StringIO()
        with (
            patch("autopilot.daemon.run_preflight", return_value=report) as preflight_mock,
            patch("autopilot.daemon.SqliteStore") as store,
            patch("autopilot.daemon.Scheduler") as scheduler,
            patch("autopilot.daemon.DshWorktreeExecutor") as executor,
            patch("autopilot.daemon.DshDiffReviewer") as reviewer,
            patch("autopilot.daemon.GitHubIssueAdapter") as github_adapter,
            redirect_stdout(output),
        ):
            code = daemon.main(["--repo-root", str(self.root), "--preflight"])
        self.assertEqual(code, 0)
        self.assertIn("LocalFit Autopilot preflight", output.getvalue())
        preflight_mock.assert_called_once_with(self.root)
        store.assert_not_called()
        scheduler.assert_not_called()
        executor.assert_not_called()
        reviewer.assert_not_called()
        github_adapter.assert_not_called()

    def test_json_mode_is_explicitly_preflight_only(self) -> None:
        output = io.StringIO()
        with (
            patch("autopilot.daemon.SqliteStore") as store,
            patch("autopilot.daemon.Scheduler") as scheduler,
            redirect_stdout(output),
        ):
            code = daemon.main(["--repo-root", str(self.root), "--once", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("only supported with --preflight", output.getvalue())
        store.assert_not_called()
        scheduler.assert_not_called()

    def test_normal_mode_keeps_switch_check_before_state_creation(self) -> None:
        output = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("autopilot.daemon.run_preflight") as preflight_mock,
            patch("autopilot.daemon.SqliteStore") as store,
            redirect_stdout(output),
        ):
            code = daemon.main(["--repo-root", str(self.root), "--once"])
        self.assertEqual(code, 2)
        self.assertIn("AUTOPILOT_GITHUB_ENABLED", output.getvalue())
        preflight_mock.assert_not_called()
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
