from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

from autopilot.adapters.github_runtime import GitHubIssueAdapter, GitHubRuntimeError
from autopilot.fakes import FakeExecutor, FakeReviewer, FakeTaskSource
from autopilot.models import (
    ExecutionResult,
    ReviewResult,
    ReviewVerdict,
    TaskRecord,
    TaskSpec,
    TaskStatus,
)
from autopilot.scheduler import RunResult, Scheduler, SchedulerConfig
from autopilot.store import SqliteStore
from autopilot.tests.support import approved, task

SHA = "a" * 40
HEAD = "b" * 40


def issue(number: int, labels: list[str], *, is_pr: bool = False) -> dict:
    item = {
        "number": number,
        "title": f"Task {number}",
        "body": f"Instructions for task {number}",
        "html_url": f"https://github.com/acme/repo/issues/{number}",
        "labels": [{"name": name} for name in labels],
    }
    if is_pr:
        item["pull_request"] = {"url": "https://api.github.com/pulls/9"}
    return item


def make_adapter(root: Path) -> GitHubIssueAdapter:
    return GitHubIssueAdapter(
        repository="acme/repo",
        base_branch="develop",
        repo_root=root,
        token="test-token",
        enabled=True,
        poll_interval_seconds=5,
    )


def pr_payload(url: str, *, head_sha: str = HEAD) -> dict:
    return {
        "html_url": url,
        "draft": True,
        "head": {
            "ref": "autopilot/gh-issue-7",
            "sha": head_sha,
            "repo": {"full_name": "acme/repo"},
        },
        "base": {"ref": "develop"},
    }


def record(root: Path, *, status: TaskStatus = TaskStatus.REVIEW) -> TaskRecord:
    return TaskRecord(
        task_id="gh-issue-7",
        title="Fix a bounded issue",
        status=status,
        base_sha=SHA,
        head_sha=HEAD,
        payload={
            "issue_number": 7,
            "repository": "acme/repo",
            "base_branch": "develop",
            "repo_root": str(root),
            "instructions": "Fix the reported defect",
        },
        rework_rounds=0,
        attempts=1,
        last_error=None,
        branch=None,
        created_at=0.0,
        updated_at=0.0,
    )


class GitHubIssueQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", str(self.root)], check=True, capture_output=True)

    def test_next_ready_uses_issue_label_and_ignores_pull_requests(self) -> None:
        adapter = make_adapter(self.root)
        adapter.poll_interval_seconds = 3600  # keep the test independent of wall-clock scheduling
        adapter._ensure_label = Mock()
        adapter._fetch_base_sha = Mock(return_value=SHA)
        adapter._ready_issues = Mock(return_value=[
            issue(1, ["agent:ready"]),
            issue(2, ["agent:ready"], is_pr=True),
            issue(3, ["needs-owner"]),
            issue(4, ["agent:ready"]),
        ])

        first = adapter.next_ready()
        second = adapter.next_ready()
        third = adapter.next_ready()
        fourth = adapter.next_ready()

        self.assertIsInstance(first, TaskSpec)
        self.assertIsInstance(second, TaskSpec)
        self.assertIsInstance(third, TaskSpec)
        self.assertIsNone(fourth)
        self.assertEqual(first.task_id, "gh-issue-1")
        self.assertEqual(first.base_sha, SHA)
        self.assertEqual(first.payload["issue_number"], 1)
        self.assertEqual(first.payload["repository"], "acme/repo")
        self.assertEqual(third.task_id, "gh-issue-4")
        adapter._fetch_base_sha.assert_called_once()
        adapter._ready_issues.assert_called_once()

    def test_disabled_adapter_fails_closed(self) -> None:
        with self.assertRaises(GitHubRuntimeError):
            GitHubIssueAdapter(
                repository="acme/repo",
                base_branch="develop",
                repo_root=self.root,
                token="test-token",
                enabled=False,
            )

    def test_from_env_requires_explicit_enable_and_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GitHubRuntimeError):
                GitHubIssueAdapter.from_env(self.root)
        with patch.dict(os.environ, {
            "AUTOPILOT_GITHUB_ENABLED": "1",
            "GITHUB_TOKEN": "test-token",
            "AUTOPILOT_GITHUB_REPOSITORY": "acme/repo",
            "AUTOPILOT_GITHUB_BASE_BRANCH": "develop",
        }, clear=True):
            adapter = GitHubIssueAdapter.from_env(self.root)
            self.assertEqual(adapter.repository, "acme/repo")
            self.assertEqual(adapter.base_branch, "develop")

    def test_approved_commit_is_pushed_to_dedicated_branch_and_draft_pr_created(self) -> None:
        adapter = make_adapter(self.root)
        task_record = record(self.root)
        review = ReviewResult(
            verdict=ReviewVerdict.APPROVED,
            head_sha=HEAD,
            reviewer="test-reviewer",
            notes="No blocking defect found.",
        )
        execution = ExecutionResult(head_sha=HEAD, artifact="autopilot/gh-issue-7")
        adapter._request = Mock(side_effect=[
            [],  # no existing open PR
            pr_payload("https://github.com/acme/repo/pull/19"),  # create draft PR
        ])
        with patch("autopilot.adapters.github_runtime._git", side_effect=[HEAD, "", ""]) as git_mock:
            url = adapter.publish_approved(task_record, review, execution)

        self.assertEqual(url, "https://github.com/acme/repo/pull/19")
        self.assertEqual(adapter._published_prs["gh-issue-7"], url)
        push_calls = [
            call for call in git_mock.call_args_list
            if len(call.args) > 1 and call.args[1] == "push"
        ]
        self.assertEqual(len(push_calls), 1)
        self.assertIn(
            "refs/heads/autopilot/gh-issue-7:refs/heads/autopilot/gh-issue-7",
            push_calls[0].args,
        )
        create_pr_call = adapter._request.call_args_list[1]
        self.assertEqual(create_pr_call.args[0], "POST")
        self.assertEqual(create_pr_call.args[1], "/pulls")
        self.assertTrue(create_pr_call.args[2]["draft"])
        self.assertEqual(create_pr_call.args[2]["base"], "develop")
        self.assertFalse(hasattr(adapter, "merge_pull_request"))

    def test_existing_draft_pr_is_reused_without_creating_another(self) -> None:
        adapter = make_adapter(self.root)
        task_record = record(self.root)
        review = ReviewResult(ReviewVerdict.APPROVED, HEAD, reviewer="test-reviewer")
        execution = ExecutionResult(head_sha=HEAD, artifact="autopilot/gh-issue-7")
        adapter._request = Mock(return_value=[
            pr_payload("https://github.com/acme/repo/pull/19")
        ])
        with patch("autopilot.adapters.github_runtime._git") as git_mock:
            url = adapter.publish_approved(task_record, review, execution)
        git_mock.assert_not_called()
        self.assertEqual(url, "https://github.com/acme/repo/pull/19")
        self.assertFalse(any(
            call.args[:2] == ("POST", "/pulls")
            for call in adapter._request.call_args_list
        ))

    def test_done_notification_reconciles_pr_and_adds_comment_after_publication(self) -> None:
        adapter = make_adapter(self.root)
        task_record = record(self.root)
        review = ReviewResult(
            ReviewVerdict.APPROVED,
            HEAD,
            reviewer="test-reviewer",
            notes="Reviewed the exact head.",
        )
        execution = ExecutionResult(head_sha=HEAD, artifact="autopilot/gh-issue-7")
        adapter.publish_approved = Mock(return_value="https://github.com/acme/repo/pull/19")
        adapter._set_labels = Mock()
        adapter._add_comment_once = Mock()

        adapter.on_task_result(task_record, RunResult(
            task_id=task_record.task_id,
            stage="execute-review",
            status=TaskStatus.DONE,
            review=review,
            execution=execution,
        ))

        adapter.publish_approved.assert_called_once_with(task_record, unittest.mock.ANY, execution)
        adapter._set_labels.assert_called_once()
        args = adapter._add_comment_once.call_args.args
        self.assertEqual(args[0], 7)
        self.assertIn("autopilot:published gh-issue-7", args[1])
        self.assertIn("https://github.com/acme/repo/pull/19", args[2])
        self.assertIn("Reviewed the exact head.", args[2])

    def test_branch_publisher_rejects_non_autopilot_refs_and_never_force_pushes(self) -> None:
        adapter = make_adapter(self.root)
        with patch("autopilot.adapters.github_runtime._git") as git_mock:
            with self.assertRaisesRegex(GitHubRuntimeError, "outside autopilot"):
                adapter._push_branch("main")
            git_mock.assert_not_called()

            adapter._push_branch("autopilot/gh-issue-7")

        calls = git_mock.call_args_list
        self.assertEqual(calls[0].args[1], "check-ref-format")
        push_call = calls[1]
        self.assertEqual(push_call.args[1], "push")
        self.assertNotIn("--force", push_call.args)
        self.assertIn(
            "refs/heads/autopilot/gh-issue-7:refs/heads/autopilot/gh-issue-7",
            push_call.args,
        )

    def test_publisher_refuses_to_reuse_pr_promoted_out_of_draft(self) -> None:
        adapter = make_adapter(self.root)
        promoted = pr_payload("https://github.com/acme/repo/pull/19")
        promoted["draft"] = False
        with self.assertRaisesRegex(GitHubRuntimeError, "no longer a Draft"):
            adapter._validate_pr_head(promoted, "autopilot/gh-issue-7", HEAD)

    def test_task_result_notifier_updates_labels_and_adds_owner_comment(self) -> None:
        adapter = make_adapter(self.root)
        task_record = record(self.root)
        adapter._set_labels = Mock()
        adapter._add_comment_once = Mock()
        adapter.on_task_result(task_record, RunResult(
            task_id=task_record.task_id,
            stage="execute",
            status=TaskStatus.NEEDS_OWNER,
            error="DSH timed out",
        ))
        adapter._set_labels.assert_called_once_with(
            7,
            add=["needs-owner"],
            remove=["agent:ready", "agent:working", "agent:changes-requested"],
        )
        self.assertIn("DSH timed out", adapter._add_comment_once.call_args.args[2])

    def test_api_errors_do_not_echo_token(self) -> None:
        adapter = make_adapter(self.root)
        with patch("autopilot.adapters.github_runtime.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(GitHubRuntimeError) as caught:
                adapter._request("GET", "/issues")
        self.assertNotIn("test-token", str(caught.exception))


class PublisherGateTest(unittest.TestCase):
    def test_failed_publication_cannot_mark_review_approved_task_done(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            store = SqliteStore(root / "state.sqlite3")
            try:
                source = FakeTaskSource([task("T-publish")])
                executor = FakeExecutor({"T-publish": [ExecutionResult(HEAD)]})
                reviewer = FakeReviewer({("T-publish", HEAD): approved("T-publish", HEAD)})

                class FailingPublisher:
                    def publish_approved(self, task, review, execution):
                        raise RuntimeError("simulated remote publication failure")

                scheduler = Scheduler(
                    store,
                    source,
                    executor,
                    reviewer,
                    workspace,
                    config=SchedulerConfig(),
                    publisher=FailingPublisher(),
                )
                result = scheduler.run_once()
                self.assertIsNotNone(result)
                self.assertEqual(result.status, TaskStatus.NEEDS_OWNER)
                self.assertEqual(store.counts()["done"], 0)
                self.assertEqual(store.counts()["needs-owner"], 1)
                self.assertEqual(store.review_count(), 0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
