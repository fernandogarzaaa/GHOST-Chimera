"""
Tests for Automated Changelog Generator.

Tests the changelog generation tool with mocked git output.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.generate_changelog import (
    build_git_log_command,
    categorize_commit,
    format_json,
    format_markdown,
    generate_changelog_data,
    parse_commit_line,
)


class TestCommitParsing:
    """Test commit line parsing."""
    
    def test_parse_commit_line_valid(self):
        """Test parsing a valid commit line."""
        line = "abc1234 Add new feature"
        result = parse_commit_line(line)
        assert result["sha"] == "abc1234"
        assert result["subject"] == "Add new feature"
    
    def test_parse_commit_line_no_space(self):
        """Test parsing a line with no space."""
        line = "abc1234"
        result = parse_commit_line(line)
        assert result["sha"] == ""
        assert result["subject"] == "abc1234"
    
    def test_parse_commit_line_multiple_spaces(self):
        """Test parsing a line with multiple spaces in subject."""
        line = "abc1234 feat: add new feature with spaces"
        result = parse_commit_line(line)
        assert result["sha"] == "abc1234"
        assert result["subject"] == "feat: add new feature with spaces"


class TestCommitCategorization:
    """Test commit categorization logic."""
    
    def test_categorize_feat_prefix(self):
        """Test categorization of feat: commits."""
        assert categorize_commit("feat: add new feature") == "Features"
        assert categorize_commit("feat(api): add endpoint") == "Features"
        assert categorize_commit("feature: new capability") == "Features"
    
    def test_categorize_fix_prefix(self):
        """Test categorization of fix: commits."""
        assert categorize_commit("fix: resolve bug") == "Fixes"
        assert categorize_commit("fix(ui): button alignment") == "Fixes"
        assert categorize_commit("bugfix: critical issue") == "Fixes"
    
    def test_categorize_test_prefix(self):
        """Test categorization of test: commits."""
        assert categorize_commit("test: add unit tests") == "Tests"
        assert categorize_commit("test(api): integration tests") == "Tests"
        assert categorize_commit("tests: coverage improvement") == "Tests"
    
    def test_categorize_docs_prefix(self):
        """Test categorization of docs: commits."""
        assert categorize_commit("docs: update README") == "Docs"
        assert categorize_commit("docs(api): add examples") == "Docs"
        assert categorize_commit("doc: fix typo") == "Docs"
    
    def test_categorize_chore_prefix(self):
        """Test categorization of chore: commits."""
        assert categorize_commit("chore: update dependencies") == "Chores"
        assert categorize_commit("chore(ci): fix workflow") == "Chores"
        assert categorize_commit("ci: add new job") == "Chores"
        assert categorize_commit("build: update config") == "Chores"
        assert categorize_commit("refactor: clean up code") == "Chores"
    
    def test_categorize_keyword_features(self):
        """Test keyword-based categorization for features."""
        assert categorize_commit("Add new API endpoint") == "Features"
        assert categorize_commit("Implement user authentication") == "Features"
        assert categorize_commit("New dashboard component") == "Features"
    
    def test_categorize_keyword_fixes(self):
        """Test keyword-based categorization for fixes."""
        assert categorize_commit("Fix memory leak") == "Fixes"
        assert categorize_commit("Bug in login flow") == "Fixes"
        assert categorize_commit("Patch security vulnerability") == "Fixes"
        assert categorize_commit("Resolve merge conflict") == "Fixes"
    
    def test_categorize_keyword_tests(self):
        """Test keyword-based categorization for tests."""
        # "Add" triggers Features first, so use different wording
        assert categorize_commit("Update testing for API") == "Tests"
        assert categorize_commit("Update test suite") == "Tests"
    
    def test_categorize_keyword_docs(self):
        """Test keyword-based categorization for docs."""
        assert categorize_commit("Update documentation") == "Docs"
        # "Fix" triggers Fixes first, so use different wording
        assert categorize_commit("Update README typo") == "Docs"
    
    def test_categorize_keyword_chores(self):
        """Test keyword-based categorization for chores."""
        assert categorize_commit("Update dependencies") == "Chores"
        assert categorize_commit("Bump deps version") == "Chores"
        assert categorize_commit("CI pipeline update") == "Chores"
    
    def test_categorize_other(self):
        """Test categorization of uncategorized commits."""
        assert categorize_commit("Random commit message") == "Other"
        assert categorize_commit("Merge branch 'main'") == "Other"


class TestChangelogGeneration:
    """Test changelog generation with mocked git output."""

    def test_build_git_log_command_for_release_tag(self):
        """Test that ref-like --since values become git ranges."""
        assert build_git_log_command(since="v0.2.0", max_count=5) == [
            "git",
            "log",
            "--oneline",
            "v0.2.0..HEAD",
            "--max-count",
            "5",
        ]

    def test_build_git_log_command_for_date(self):
        """Test that date-like --since values use git's date parser."""
        assert build_git_log_command(since="2026-05-01", max_count=5) == [
            "git",
            "log",
            "--oneline",
            "--since=2026-05-01",
            "--max-count",
            "5",
        ]

    def test_build_git_log_command_for_explicit_range(self):
        """Test that explicit git ranges are preserved."""
        assert build_git_log_command(since="v0.1.0..v0.2.0") == [
            "git",
            "log",
            "--oneline",
            "v0.1.0..v0.2.0",
        ]
    
    @patch("scripts.generate_changelog.get_git_log")
    def test_generate_changelog_data_empty(self, mock_git_log):
        """Test changelog generation with no commits."""
        mock_git_log.return_value = []
        
        result = generate_changelog_data()
        
        assert result["Features"] == []
        assert result["Fixes"] == []
        assert result["Tests"] == []
        assert result["Docs"] == []
        assert result["Chores"] == []
        assert result["Other"] == []
    
    @patch("scripts.generate_changelog.get_git_log")
    def test_generate_changelog_data_mixed(self, mock_git_log):
        """Test changelog generation with mixed commit types."""
        mock_git_log.return_value = [
            "abc1234 feat: add new feature",
            "def5678 fix: resolve bug",
            "ghi9012 test: add tests",
            "jkl3456 docs: update README",
            "mno7890 chore: update deps",
            "pqr1234 Random commit",
        ]
        
        result = generate_changelog_data()
        
        assert len(result["Features"]) == 1
        assert result["Features"][0]["sha"] == "abc1234"
        assert len(result["Fixes"]) == 1
        assert result["Fixes"][0]["sha"] == "def5678"
        assert len(result["Tests"]) == 1
        assert len(result["Docs"]) == 1
        assert len(result["Chores"]) == 1
        assert len(result["Other"]) == 1
    
    @patch("scripts.generate_changelog.get_git_log")
    def test_generate_changelog_data_with_max_count(self, mock_git_log):
        """Test changelog generation with max_count parameter."""
        mock_git_log.return_value = [
            "abc1234 feat: feature 1",
            "def5678 feat: feature 2",
        ]
        
        result = generate_changelog_data(max_count=2)
        
        mock_git_log.assert_called_once_with(since=None, max_count=2)
        assert len(result["Features"]) == 2


class TestChangelogFormatting:
    """Test changelog output formatting."""
    
    def test_format_markdown_empty(self):
        """Test markdown formatting with empty changelog."""
        changelog = {
            "Features": [],
            "Fixes": [],
            "Tests": [],
            "Docs": [],
            "Chores": [],
            "Other": []
        }
        
        result = format_markdown(changelog)
        
        assert "# Changelog" in result
        assert "## Features" not in result
    
    def test_format_markdown_with_commits(self):
        """Test markdown formatting with commits."""
        changelog = {
            "Features": [
                {"sha": "abc1234", "subject": "feat: add feature"},
                {"sha": "def5678", "subject": "feat: another feature"}
            ],
            "Fixes": [
                {"sha": "ghi9012", "subject": "fix: bug fix"}
            ],
            "Tests": [],
            "Docs": [],
            "Chores": [],
            "Other": []
        }
        
        result = format_markdown(changelog)
        
        assert "# Changelog" in result
        assert "## Features" in result
        assert "## Fixes" in result
        assert "- feat: add feature (abc1234)" in result
        assert "- feat: another feature (def5678)" in result
        assert "- fix: bug fix (ghi9012)" in result
        assert "## Tests" not in result
    
    def test_format_json_empty(self):
        """Test JSON formatting with empty changelog."""
        changelog = {
            "Features": [],
            "Fixes": [],
            "Tests": [],
            "Docs": [],
            "Chores": [],
            "Other": []
        }
        
        result = format_json(changelog)
        parsed = json.loads(result)
        
        assert parsed["Features"] == []
        assert parsed["Fixes"] == []
    
    def test_format_json_with_commits(self):
        """Test JSON formatting with commits."""
        changelog = {
            "Features": [
                {"sha": "abc1234", "subject": "feat: add feature"}
            ],
            "Fixes": [],
            "Tests": [],
            "Docs": [],
            "Chores": [],
            "Other": []
        }
        
        result = format_json(changelog)
        parsed = json.loads(result)
        
        assert len(parsed["Features"]) == 1
        assert parsed["Features"][0]["sha"] == "abc1234"
        assert parsed["Features"][0]["subject"] == "feat: add feature"


class TestChangelogCLI:
    """Test changelog CLI integration."""
    
    @patch("scripts.generate_changelog.get_git_log")
    def test_cli_runs_without_error(self, mock_git_log):
        """Test that CLI can be imported and basic functions work."""
        mock_git_log.return_value = [
            "abc1234 feat: test feature"
        ]
        
        # Test that we can generate changelog data
        result = generate_changelog_data(max_count=1)
        assert len(result["Features"]) == 1
        
        # Test that we can format it
        markdown = format_markdown(result)
        assert "# Changelog" in markdown
        
        json_output = format_json(result)
        assert "Features" in json_output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Made with Bob
