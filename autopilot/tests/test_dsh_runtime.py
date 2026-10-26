from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot.adapters.dsh_runtime import (
    DshDiffReviewer,
    DshRuntimeError,
    DshWorktreeExecutor,
    UnsafeTaskChange,
    _agent_env,
)
from autopilot.models import (
    ExecutionTimeout,
    LeaseLost,
    ReviewTimeout,
    ReviewVerdict,
    TaskRecord,
    TaskStatus,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "Autopilot Test")
    git(repo, "config", "user.email", "autopilot-test@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def fake_dsh(root: Path, body: str) -> Path:
    path = root / "fake_dsh.py"
    path.write_text(
        "import json, sys\n"
        "prompt = sys.stdin.read()\n"
        + body
        + "\n",
        encoding="utf-8",
    )
    return path


def task_record(
    task_id: str,
    base_sha: str,
    *,
    head_sha: str | None = None,
    payload: dict | None = None,
) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        title="Add a small test artifact",
        status=TaskStatus.WORKING,
        base_sha=base_sha,
        head_sha=head_sha,
        payload=payload or {"instructions": "Add generated.txt containing the word ok."},
        rework_rounds=0,
        attempts=1,
        last_error=None,
        branch=None,
        created_at=0.0,
        updated_at=0.0,
    )


class DshWorktreeExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo, self.base_sha = make_repo(self.root)

    def test_execution_commits_in_isolated_worktree_without_touching_checkout(self) -> None:
        cli = fake_dsh(
            self.root,
            "from pathlib import Path\n"
            "Path('generated.txt').write_text('ok\\n', encoding='utf-8')\n"
            "print(json.dumps({'type': 'final', 'text': 'completed'}))",
        )
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)

        result = executor.execute(
            task_record("T1", self.base_sha),
            1,
            self.repo,
            5.0,
        )

        self.assertNotEqual(result.head_sha, self.base_sha)
        self.assertEqual(git(self.repo, "show", f"{result.head_sha}:generated.txt"), "ok")
        self.assertFalse((self.repo / "generated.txt").exists())
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(git(self.repo, "branch", "--list", "autopilot/T1").strip(), "autopilot/T1")
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_execution_uses_temporary_patch_and_cleans_it(self) -> None:
        record_path = self.root / "exec-overlay-record.json"
        cli = fake_dsh(
            self.root,
            "import json, sys\n"
            "from pathlib import Path\n"
            "record = Path(r'" + record_path.as_posix() + "')\n"
            "patch = Path(sys.argv[sys.argv.index('--patch') + 1])\n"
            "record.write_text(json.dumps({'argv': sys.argv, 'overlay': patch.read_text()}), encoding='utf-8')\n"
            "Path('generated.txt').write_text('ok\\n', encoding='utf-8')\n"
            "print(json.dumps({'type': 'final', 'text': 'completed'}))",
        )
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)

        executor.execute(task_record("T-overlay", self.base_sha), 1, self.repo, 5.0)

        captured = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertIn("--patch", captured["argv"])
        self.assertIn("- id: credentials", captured["overlay"])
        self.assertIn("disabled: false", captured["overlay"])
        self.assertIn("mode: workspace-write", captured["overlay"])
        self.assertIn("workspaceRoot:", captured["overlay"])
        self.assertNotIn("- id: tool-fs\n  disabled: true", captured["overlay"])
        self.assertNotIn("- id: tool-fs-search\n  disabled: true", captured["overlay"])
        self.assertIn("- id: tool-bash\n  disabled: true", captured["overlay"])
        self.assertNotIn("- id: tool-web\n  disabled: false", captured["overlay"])
        self.assertIsNotNone(executor.last_overlay_summary)
        self.assertEqual(executor.last_overlay_summary["sandbox_mode"], "workspace-write")
        self.assertEqual(executor.last_overlay_summary["allowed_tool_ids"], ["tool-fs", "tool-fs-search"])
        self.assertEqual(executor.last_overlay_summary["credentials_enabled"], True)
        self.assertEqual(executor.last_overlay_summary["authorization_enabled"], False)
        self.assertIsNotNone(executor.last_overlay_sha256)
        self.assertEqual(len(executor.last_overlay_sha256), 64)
        self.assertIsNotNone(executor.last_overlay_path)
        self.assertFalse(Path(executor.last_overlay_path).exists())

    def test_execution_cleans_overlay_on_timeout(self) -> None:
        cli = fake_dsh(self.root, "import time\ntime.sleep(5)")
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
        with self.assertRaises(ExecutionTimeout):
            executor.execute(task_record("T-timeout-overlay", self.base_sha), 1, self.repo, 0.15)
        self.assertIsNotNone(executor.last_overlay_path)
        self.assertFalse(Path(executor.last_overlay_path).exists())

    def test_execution_cleans_overlay_on_cancel(self) -> None:
        cli = fake_dsh(self.root, "import time\ntime.sleep(5)")
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
        cancel = threading.Event()
        timer = threading.Timer(0.25, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(LeaseLost):
            executor.execute_cancellable(
                task_record("T-cancel-overlay", self.base_sha), 1, self.repo, 5.0, cancel
            )
        self.assertIsNotNone(executor.last_overlay_path)
        self.assertFalse(Path(executor.last_overlay_path).exists())

    def test_execution_fails_safely_on_invalid_or_missing_final_event(self) -> None:
        for task_id, body in (
            ("T-invalid-json", "print('not a JSON event')"),
            ("T-missing-final", "print(json.dumps({'type': 'error', 'message': 'boom'}))"),
        ):
            with self.subTest(task_id=task_id):
                cli = fake_dsh(self.root, body)
                executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
                with self.assertRaises(DshRuntimeError):
                    executor.execute(task_record(task_id, self.base_sha), 1, self.repo, 5.0)
                self.assertIsNotNone(executor.last_overlay_path)
                self.assertFalse(Path(executor.last_overlay_path).exists())
                self.assertEqual(git(self.repo, "rev-parse", f"autopilot/{task_id}"), self.base_sha)

    def test_agent_env_strips_publishing_and_ssh_secrets(self) -> None:
        config_path = self.root / "empty-git-config"
        config_path.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {
            "GITHUB_TOKEN": "dummy-github-token",
            "GH_TOKEN": "dummy-gh-token",
            "SSH_AUTH_SOCK": "dummy-ssh-sock",
            "DEEPSEEK_API_KEY": "dummy-model-key",
            "UNRELATED_SETTING": "keep-me",
        }, clear=False):
            env = _agent_env(config_path)
        for key in ("GITHUB_TOKEN", "GH_TOKEN", "SSH_AUTH_SOCK", "DEEPSEEK_API_KEY"):
            self.assertNotIn(key, env)
        self.assertEqual(env["UNRELATED_SETTING"], "keep-me")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_default_disabled_behavior_is_unchanged(self) -> None:
        cli = fake_dsh(self.root, "print(json.dumps({'type': 'final', 'text': 'ok'}))")
        with patch.dict(os.environ, {}, clear=True):
            executor = DshWorktreeExecutor(cli_path=str(cli))
            reviewer = DshDiffReviewer(cli_path=str(cli), repo_root=self.repo)
        self.assertFalse(executor.enabled)
        self.assertFalse(reviewer.enabled)
        with self.assertRaises(DshRuntimeError):
            executor.execute(task_record("T-disabled", self.base_sha), 1, self.repo, 5.0)

    def test_protected_path_change_is_discarded_and_not_committed(self) -> None:
        cli = fake_dsh(
            self.root,
            "from pathlib import Path\n"
            "Path('.env').write_text('FAKE_SECRET=do-not-commit', encoding='utf-8')\n"
            "print(json.dumps({'type': 'final', 'text': 'completed'}))",
        )
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
        with self.assertRaises(UnsafeTaskChange):
            executor.execute(task_record("T-secret", self.base_sha), 1, self.repo, 5.0)
        self.assertEqual(git(self.repo, "rev-parse", "autopilot/T-secret"), self.base_sha)
        self.assertFalse((self.repo / ".env").exists())

    def test_timeout_terminates_dsh_and_does_not_commit(self) -> None:
        cli = fake_dsh(self.root, "import time\ntime.sleep(5)")
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
        started = time.monotonic()
        with self.assertRaises(ExecutionTimeout):
            executor.execute(task_record("T-timeout", self.base_sha), 1, self.repo, 0.15)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(git(self.repo, "rev-parse", "autopilot/T-timeout"), self.base_sha)

    def test_lease_loss_terminates_dsh_and_does_not_commit(self) -> None:
        cli = fake_dsh(self.root, "import time\ntime.sleep(5)")
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
        cancel = threading.Event()
        timer = threading.Timer(0.25, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(LeaseLost):
            executor.execute_cancellable(
                task_record("T-cancel", self.base_sha),
                1,
                self.repo,
                5.0,
                cancel,
            )
        self.assertEqual(git(self.repo, "rev-parse", "autopilot/T-cancel"), self.base_sha)

    def test_agent_direct_commit_is_rejected(self) -> None:
        cli = fake_dsh(
            self.root,
            "from pathlib import Path\n"
            "Path('generated.txt').write_text('ok', encoding='utf-8')\n"
            "import subprocess\n"
            "subprocess.run(['git', 'add', 'generated.txt'], check=True)\n"
            "subprocess.run(['git', 'commit', '-m', 'agent bypass'], check=True)\n"
            "print(json.dumps({'type': 'final', 'text': 'completed'}))",
        )
        executor = DshWorktreeExecutor(cli_path=str(cli), enabled=True)
        with self.assertRaises(UnsafeTaskChange):
            executor.execute(task_record("T-bypass", self.base_sha), 1, self.repo, 5.0)
        self.assertEqual(git(self.repo, "rev-parse", "autopilot/T-bypass"), self.base_sha)


class DshDiffReviewerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo, self.base_sha = make_repo(self.root)
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "change")
        self.head_sha = git(self.repo, "rev-parse", "HEAD")

    def test_review_parses_structured_verdict_bound_to_exact_head(self) -> None:
        cli = fake_dsh(
            self.root,
            "import re\n"
            "match = re.search(r'Head SHA: ([0-9a-f]{40,64})', prompt)\n"
            "head = match.group(1)\n"
            "review = {'verdict': 'approved', 'head_sha': head, 'defects': [], 'notes': 'Looks good'}\n"
            "print(json.dumps({'type': 'final', 'text': json.dumps(review)}))",
        )
        reviewer = DshDiffReviewer(cli_path=str(cli), enabled=True, repo_root=self.repo)
        review = reviewer.review(
            task_record("T-review", self.base_sha, head_sha=self.head_sha),
            self.head_sha,
            5.0,
        )
        self.assertEqual(review.verdict, ReviewVerdict.APPROVED)
        self.assertEqual(review.head_sha, self.head_sha)
        self.assertEqual(review.defects, ())

    def test_review_rejects_wrong_head_sha(self) -> None:
        cli = fake_dsh(
            self.root,
            "review = {'verdict': 'approved', 'head_sha': '0'*40, 'defects': [], 'notes': 'wrong head'}\n"
            "print(json.dumps({'type': 'final', 'text': json.dumps(review)}))",
        )
        reviewer = DshDiffReviewer(cli_path=str(cli), enabled=True, repo_root=self.repo)
        with self.assertRaises(DshRuntimeError):
            reviewer.review(
                task_record("T-review-wrong", self.base_sha, head_sha=self.head_sha),
                self.head_sha,
                5.0,
            )

    def test_review_uses_read_only_overlay_with_all_tools_disabled(self) -> None:
        record_path = self.root / "review-overlay-record.json"
        cli = fake_dsh(
            self.root,
            "import json, sys\n"
            "from pathlib import Path\n"
            "record = Path(r'" + record_path.as_posix() + "')\n"
            "patch = Path(sys.argv[sys.argv.index('--patch') + 1])\n"
            "record.write_text(json.dumps({'argv': sys.argv, 'overlay': patch.read_text()}), encoding='utf-8')\n"
            "import re\n"
            "head = re.search(r'Head SHA: ([0-9a-f]{40,64})', prompt).group(1)\n"
            "review = {'verdict': 'approved', 'head_sha': head, 'defects': [], 'notes': 'read-only review'}\n"
            "print(json.dumps({'type': 'final', 'text': json.dumps(review)}))",
        )
        reviewer = DshDiffReviewer(cli_path=str(cli), enabled=True, repo_root=self.repo)
        reviewer.review(
            task_record("T-review-overlay", self.base_sha, head_sha=self.head_sha),
            self.head_sha,
            5.0,
        )
        captured = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertIn("--patch", captured["argv"])
        self.assertIn("mode: read-only", captured["overlay"])
        self.assertIn("- id: tool-fs\n  disabled: true", captured["overlay"])
        self.assertIn("- id: tool-bash\n  disabled: true", captured["overlay"])
        self.assertIn("- id: credentials\n  disabled: false", captured["overlay"])
        self.assertIsNotNone(reviewer.last_overlay_summary)
        self.assertEqual(reviewer.last_overlay_summary["sandbox_mode"], "read-only")
        self.assertEqual(reviewer.last_overlay_summary["allowed_tool_ids"], [])
        self.assertEqual(len(reviewer.last_overlay_summary["disabled_tool_ids"]), 17)
        self.assertIsNotNone(reviewer.last_overlay_sha256)
        self.assertEqual(len(reviewer.last_overlay_sha256), 64)
        self.assertIsNotNone(reviewer.last_overlay_path)
        self.assertFalse(Path(reviewer.last_overlay_path).exists())

    def test_review_cleans_overlay_on_timeout(self) -> None:
        cli = fake_dsh(self.root, "import time\ntime.sleep(5)")
        reviewer = DshDiffReviewer(cli_path=str(cli), enabled=True, repo_root=self.repo)
        with self.assertRaises(ReviewTimeout):
            reviewer.review(
                task_record("T-review-timeout", self.base_sha, head_sha=self.head_sha),
                self.head_sha,
                0.15,
            )
        self.assertIsNotNone(reviewer.last_overlay_path)
        self.assertFalse(Path(reviewer.last_overlay_path).exists())

    def test_review_fails_safely_on_invalid_json_or_nonzero_exit(self) -> None:
        for body in ("print('not json')", "import sys\nsys.exit(2)"):
            with self.subTest(body=body):
                cli = fake_dsh(self.root, body)
                reviewer = DshDiffReviewer(cli_path=str(cli), enabled=True, repo_root=self.repo)
                with self.assertRaises(DshRuntimeError):
                    reviewer.review(
                        task_record("T-review-invalid", self.base_sha, head_sha=self.head_sha),
                        self.head_sha,
                        5.0,
                    )
                self.assertIsNotNone(reviewer.last_overlay_path)
                self.assertFalse(Path(reviewer.last_overlay_path).exists())

    def test_changes_requested_requires_actionable_defect(self) -> None:
        cli = fake_dsh(
            self.root,
            "import re\n"
            "head = re.search(r'Head SHA: ([0-9a-f]{40,64})', prompt).group(1)\n"
            "review = {'verdict': 'changes-requested', 'head_sha': head, 'defects': [], 'notes': 'no details'}\n"
            "print(json.dumps({'type': 'final', 'text': json.dumps(review)}))",
        )
        reviewer = DshDiffReviewer(cli_path=str(cli), enabled=True, repo_root=self.repo)
        with self.assertRaises(DshRuntimeError):
            reviewer.review(
                task_record("T-review-empty", self.base_sha, head_sha=self.head_sha),
                self.head_sha,
                5.0,
            )


if __name__ == "__main__":
    unittest.main()
