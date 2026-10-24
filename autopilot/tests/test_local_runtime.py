from __future__ import annotations

import unittest
from unittest.mock import patch

from autopilot.adapters.local_runtime import (
    GitHubCli,
    GitHubIssueTaskSource,
    ExternalCommandError,
    parse_json_object,
    validate_changed_paths,
)


class RuntimeSafetyTests(unittest.TestCase):
    def test_changed_path_guard_blocks_secrets_and_runner_files(self) -> None:
        for path in (
            ".env",
            ".env.production",
            "outputs/autopilot.sqlite3",
            "backend/credentials.json",
            ".github/workflows/ci.yml",
            "autopilot/runner.py",
            "frontend/node_modules/package/index.js",
        ):
            with self.subTest(path=path), self.assertRaises(ExternalCommandError):
                validate_changed_paths([path])

    def test_changed_path_guard_allows_product_source_and_tests(self) -> None:
        validate_changed_paths([
            "frontend/src/App.tsx",
            "frontend/src/App.test.tsx",
            "backend/app/agents.py",
            "backend/tests/test_agents.py",
            "README.md",
        ])

    def test_review_parser_reads_object_and_rejects_non_object(self) -> None:
        self.assertEqual(
            parse_json_object('  {"verdict":"approved","head_sha":"abc"}  '),
            {"verdict": "approved", "head_sha": "abc"},
        )
        with self.assertRaises(ValueError):
            parse_json_object("not json")
        with self.assertRaises(ValueError):
            parse_json_object("[1, 2, 3]")

    def test_repository_scope_is_hard_coded(self) -> None:
        with self.assertRaises(ValueError):
            GitHubCli("yky666/ai_health_assistant")
        self.assertEqual(
            GitHubCli("Sunset-Sunrise-Sun/competition-part-work").repository,
            "Sunset-Sunrise-Sun/competition-part-work",
        )

    def test_task_source_returns_issue_identity_and_deduplicates(self) -> None:
        github = GitHubCli("Sunset-Sunrise-Sun/competition-part-work")
        issue = {
            "number": 27,
            "title": "Example task",
            "body": "Acceptance criteria",
            "url": "https://github.com/Sunset-Sunrise-Sun/competition-part-work/issues/27",
            "labels": [{"name": "agent:ready"}],
        }
        with patch.object(github, "list_ready_issues", return_value=[issue]), patch(
            "autopilot.adapters.local_runtime.run_checked",
            return_value="a" * 40,
        ):
            source = GitHubIssueTaskSource(
                github, __import__("pathlib").Path("."),
                "wjy/three-day-delivery",
            )
            task = source.next_ready()
            self.assertEqual(task.task_id, "issue-27")
            self.assertEqual(task.base_sha, "a" * 40)
            self.assertEqual(task.payload["issue_number"], 27)
            self.assertIsNone(source.next_ready())


if __name__ == "__main__":
    unittest.main()
