from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from autopilot.adapters.dsh_runtime import (
    DshDiffReviewer,
    DshRuntimeError,
    DshWorktreeExecutor,
    UnsafeTaskChange,
)
from autopilot.models import (
    ExecutionTimeout,
    LeaseLost,
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
