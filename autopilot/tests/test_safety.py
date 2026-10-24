from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from autopilot import __file__ as autopilot_file
from autopilot.adapters import DshHeadlessAdapter, GitHubRestAdapter
from autopilot.adapters.dsh_runtime import _agent_env
from autopilot.cli import main as cli_main
from autopilot.models import (
    AdapterCredentialMissing,
    AdapterDisabledError,
    AdapterNotImplementedError,
    ExecutionResult,
    TaskRecord,
    TaskStatus,
)
from autopilot.redaction import redact
from autopilot.store import SqliteStore
from autopilot.tests.support import approved, build_stack, task


class AdapterSafetyTest(unittest.TestCase):
    def test_adapters_are_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AdapterDisabledError):
                DshHeadlessAdapter.from_env()
            with self.assertRaises(AdapterDisabledError):
                GitHubRestAdapter.from_env()

    def test_enabled_adapter_without_credential_fails_closed(self) -> None:
        with patch.dict(os.environ, {"AUTOPILOT_DSH_ENABLED": "1"}, clear=True):
            with self.assertRaises(AdapterCredentialMissing):
                DshHeadlessAdapter.from_env()
        with patch.dict(os.environ, {"AUTOPILOT_GITHUB_ENABLED": "1"}, clear=True):
            with self.assertRaises(AdapterCredentialMissing):
                GitHubRestAdapter.from_env()

    def test_enabled_placeholders_never_execute_real_work(self) -> None:
        dsh_env = {
            "AUTOPILOT_DSH_ENABLED": "1",
            "DEEPSEEK_API_KEY": "dummy-test-only",
            "AUTOPILOT_DSH_CLI": "C:/fake/dsh.cmd",
        }
        with patch.dict(os.environ, dsh_env, clear=True):
            adapter = DshHeadlessAdapter.from_env()
            self.assertTrue(adapter.enabled)
            self.assertNotIn("dummy-test-only", repr(adapter))
            workspace = Path.cwd()
            record = TaskRecord(
                task_id="T1",
                title="dummy",
                status=TaskStatus.READY,
                base_sha="base",
                head_sha=None,
                payload={},
                rework_rounds=0,
                attempts=0,
                last_error=None,
                branch=None,
                created_at=0.0,
                updated_at=0.0,
            )
            command = adapter.build_command(record, workspace)
            self.assertIn("--profile", command)
            self.assertIn("headless", command)
            with self.assertRaises(AdapterNotImplementedError):
                adapter.execute(record, 1, workspace, 1.0)

        github_env = {
            "AUTOPILOT_GITHUB_ENABLED": "1",
            "GITHUB_TOKEN": "dummy-test-only",
        }
        with patch.dict(os.environ, github_env, clear=True):
            github = GitHubRestAdapter.from_env()
            self.assertTrue(github.enabled)
            self.assertNotIn("dummy-test-only", repr(github))
            self.assertFalse(hasattr(github, "merge_pull_request"))
            self.assertFalse(hasattr(github, "auto_merge"))
            with self.assertRaises(AdapterNotImplementedError):
                github.fetch_ready_tasks()
            with self.assertRaises(AdapterNotImplementedError):
                github.push_branch()
            with self.assertRaises(AdapterNotImplementedError):
                github.open_draft_pull_request()
            with self.assertRaises(AdapterNotImplementedError):
                github.post_review(
                    TaskRecord(
                        task_id="T1",
                        title="dummy",
                        status=TaskStatus.REVIEW,
                        base_sha="base",
                        head_sha="head",
                        payload={},
                        rework_rounds=0,
                        attempts=0,
                        last_error=None,
                        branch=None,
                        created_at=0.0,
                        updated_at=0.0,
                    ),
                    approved("T1", "head"),
                )

    def test_dsh_child_environment_strips_secret_variables_but_keeps_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "empty-git-config"
            config_path.write_text("", encoding="utf-8")
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(Path(directory)),
                "AUTOPILOT_DSH_CLI": "dsh",
                "AUTOPILOT_DSH_ENABLED": "1",
                "DEEPSEEK_API_KEY": "sk-123456789012345678901234567890",
                "GITHUB_TOKEN": "ghp_123456789012345678901234567890",
                "AWS_ACCESS_KEY_ID": "AKIA_TEST",
                "AWS_SECRET_ACCESS_KEY": "aws-secret-test",
                "DATABASE_URL": "postgres://user:password@localhost/db",
            }
            with patch.dict(os.environ, environment, clear=True):
                child_env = _agent_env(config_path)

            self.assertIn("PATH", child_env)
            self.assertIn("AUTOPILOT_DSH_CLI", child_env)
            self.assertIn("AUTOPILOT_DSH_ENABLED", child_env)
            self.assertEqual(child_env["GIT_CONFIG_COUNT"], "3")
            self.assertEqual(child_env["GIT_CONFIG_KEY_0"], "credential.helper")
            self.assertEqual(child_env["GIT_CONFIG_VALUE_0"], "")
            self.assertEqual(child_env["GIT_CONFIG_KEY_1"], "http.extraheader")
            self.assertEqual(child_env["GIT_CONFIG_VALUE_1"], "")
            self.assertEqual(child_env["GIT_CONFIG_KEY_2"], "http.https://github.com/.extraheader")
            self.assertEqual(child_env["GIT_CONFIG_VALUE_2"], "")
            for name in (
                "DEEPSEEK_API_KEY", "GITHUB_TOKEN", "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY", "DATABASE_URL",
            ):
                self.assertNotIn(name, child_env)

    def test_redaction_masks_likely_secrets(self) -> None:
        text = (
            "DEEPSEEK_API_KEY=sk-do-not-log\n"
            "GITHUB_TOKEN=ghp_do_not_log\n"
            "Authorization: Bearer abc.def\n"
            "Authorization: Basic dXNlci10b2tlbjpleGFtcGxl\n"
            "X-Hub-Signature-256: deadbeef\n"
            "raw token ghp_123456789012345678901234567890\n"
            "remote https://x-access-token:ghp_123456789012345678901234567890@github.com/acme/repo.git"
        )
        masked = redact(text)
        for secret in (
            "sk-do-not-log", "ghp_do_not_log", "abc.def",
            "dXNlci10b2tlbjpleGFtcGxl", "deadbeef",
            "ghp_123456789012345678901234567890",
        ):
            self.assertNotIn(secret, masked)
        self.assertIn("<redacted>", masked)

    def test_source_has_no_merge_or_automatic_main_push_surface(self) -> None:
        package_root = Path(autopilot_file).parent
        forbidden = (
            "merge_pull_request", "auto_merge", "push_main", "gh pr merge",
            "git push --force", "git push --force-with-lease",
        )
        for path in package_root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, source, f"{marker} found in {path.name}")

    def test_cli_status_is_read_only_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "status.sqlite3"
            store = SqliteStore(db)
            store.enqueue_task(task("T1"), 1.0)
            store.close()
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["--db", str(db), "status"])
            self.assertEqual(code, 0)
            self.assertIn('"T1"', output.getvalue())
            self.assertIn('"ready"', output.getvalue())


class NoMergePathTest(unittest.TestCase):
    def test_scheduler_exposes_no_merge_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stack = build_stack(
                Path(directory),
                tasks=[task("T1")],
                exec_plans={"T1": [ExecutionResult("t1-head")]},
                review_plans={("T1", "t1-head"): approved("T1", "t1-head")},
            )
            try:
                for name in ("merge", "merge_pull_request", "auto_merge", "push_main"):
                    self.assertFalse(hasattr(stack.scheduler, name))
                    self.assertFalse(hasattr(stack.store, name))
            finally:
                stack.close()
