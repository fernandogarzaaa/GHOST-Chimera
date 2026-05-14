from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.chimera_pilot.pr_review import PRReviewReport, _git, format_pr_review_report, run_pr_review


class PRReviewTests(unittest.TestCase):
    def test_review_no_diff_is_clean(self) -> None:
        report = run_pr_review(base="HEAD", head="HEAD")

        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.files_changed, [])
        self.assertEqual(report.findings, [])

    def test_review_flags_secret_and_missing_tests(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-pr-review-") as tmp:
            repo = Path(tmp)
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "tester@example.com")
            self._git(repo, "config", "user.name", "Tester")
            (repo / "ghostchimera").mkdir()
            (repo / "ghostchimera" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "base")
            secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
            (repo / "ghostchimera" / "feature.py").write_text(
                f'VALUE = "{secret}"\n',
                encoding="utf-8",
            )
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "head")

            report = run_pr_review(base="HEAD~1", head="HEAD", root=repo)

        titles = {finding.title for finding in report.findings}
        self.assertFalse(report.ok)
        self.assertIn("Potential secret added to diff", titles)
        self.assertIn("Source changes lack test updates", titles)

    def test_review_can_include_working_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-pr-review-worktree-") as tmp:
            repo = Path(tmp)
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "tester@example.com")
            self._git(repo, "config", "user.name", "Tester")
            (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "base")
            (repo / "README.md").write_text("# Demo\n\nUpdated\n", encoding="utf-8")

            report = run_pr_review(base="HEAD", head="WORKTREE", root=repo)

        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.files_changed, ["README.md"])

    def test_markdown_report_renders_findings(self) -> None:
        report = run_pr_review(base="HEAD", head="HEAD")
        rendered = format_pr_review_report(report)

        self.assertIn("# Ghost Chimera PR Review", rendered)
        self.assertIn("Files changed:", rendered)

    def test_git_diff_reader_forces_utf8_with_replacement(self) -> None:
        report = PRReviewReport(base="HEAD", head="WORKTREE", root=str(Path.cwd()))
        completed = subprocess.CompletedProcess(["git", "diff"], 0, stdout="ok\n", stderr="")

        with patch("ghostchimera.chimera_pilot.pr_review.subprocess.run", return_value=completed) as run:
            output = _git(Path.cwd(), ["diff"], report)

        self.assertEqual(output, "ok\n")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def _git(self, repo: Path, *args: str) -> None:
        completed = subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
