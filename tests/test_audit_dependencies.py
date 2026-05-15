"""
Tests for Dependency Audit Tool.

Tests the dependency audit tool with fixture pyproject.toml files.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.audit_dependencies import (
    analyze_dependency_spec,
    audit_dependencies,
    format_json_output,
    format_markdown,
    format_text,
    parse_pyproject,
)


class TestDependencySpecAnalysis:
    """Test dependency specification analysis."""
    
    def test_analyze_pinned_dependency(self):
        """Test analysis of a pinned dependency."""
        result = analyze_dependency_spec("package==1.0.0")
        assert result["spec"] == "package==1.0.0"
        assert len(result["risks"]) == 0
    
    def test_analyze_unpinned_upper_bound(self):
        """Test analysis of dependency with unpinned upper bound."""
        result = analyze_dependency_spec("package>=1.0.0")
        assert "Unpinned upper bound (>=)" in result["risks"]
        assert any("upper bound" in note.lower() for note in result["notes"])
    
    def test_analyze_bounded_range(self):
        """Test analysis of dependency with bounded range."""
        result = analyze_dependency_spec("package>=1.0.0,<2.0.0")
        # Should not have unpinned upper bound risk
        assert not any("Unpinned" in risk for risk in result["risks"])
    
    def test_analyze_no_version_constraint(self):
        """Test analysis of dependency with no version constraint."""
        result = analyze_dependency_spec("*")
        assert "No version constraint" in result["risks"]

        result = analyze_dependency_spec("package")
        assert "No version constraint" in result["risks"]
    
    def test_analyze_prerelease_version(self):
        """Test analysis of pre-release version."""
        result = analyze_dependency_spec("package==1.0.0-alpha")
        assert "Pre-release version" in result["risks"]
        
        result = analyze_dependency_spec("package==1.0.0-beta.1")
        assert "Pre-release version" in result["risks"]
        
        result = analyze_dependency_spec("package==1.0.0rc1")
        assert "Pre-release version" in result["risks"]

    def test_analyze_environment_marker_is_not_prerelease(self):
        """Test that package names and markers do not trigger prerelease checks."""
        result = analyze_dependency_spec("torch>=2.6; python_version < '3.14'")
        assert "Pre-release version" not in result["risks"]
        assert "Unpinned upper bound (>=)" in result["risks"]
    
    def test_analyze_git_dependency(self):
        """Test analysis of git dependency."""
        result = analyze_dependency_spec("package @ git+https://github.com/user/repo.git")
        assert "Git dependency" in result["risks"]

    def test_analyze_direct_reference_dependency(self):
        """Test analysis of a non-git direct reference dependency."""
        result = analyze_dependency_spec("package @ https://example.com/package.whl")
        assert "Direct reference dependency" in result["risks"]
        assert "Git dependency" not in result["risks"]


class TestPyprojectParsing:
    """Test pyproject.toml parsing."""
    
    def test_parse_pyproject_simple(self):
        """Test parsing a simple pyproject.toml."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[project]\n')
            f.write('name = "test-project"\n')
            f.write('dependencies = ["package1>=1.0.0", "package2==2.0.0"]\n')
            temp_path = Path(f.name)
        
        try:
            result = parse_pyproject(temp_path)
            assert result["project"]["name"] == "test-project"
            assert len(result["project"]["dependencies"]) == 2
        finally:
            temp_path.unlink()
    
    def test_parse_pyproject_with_optional_deps(self):
        """Test parsing pyproject.toml with optional dependencies."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[project]\n')
            f.write('name = "test-project"\n')
            f.write('dependencies = ["package1>=1.0.0"]\n')
            f.write('[project.optional-dependencies]\n')
            f.write('dev = ["pytest>=7.0.0"]\n')
            f.write('docs = ["sphinx>=4.0.0"]\n')
            temp_path = Path(f.name)
        
        try:
            result = parse_pyproject(temp_path)
            assert "dev" in result["project"]["optional-dependencies"]
            assert "docs" in result["project"]["optional-dependencies"]
        finally:
            temp_path.unlink()
    
    def test_parse_pyproject_nonexistent(self):
        """Test parsing a nonexistent pyproject.toml."""
        with pytest.raises(FileNotFoundError):
            parse_pyproject(Path("/nonexistent/pyproject.toml"))
    
    def test_parse_pyproject_invalid(self):
        """Test parsing an invalid pyproject.toml."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("invalid toml content {{{")
            temp_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError):
                parse_pyproject(temp_path)
        finally:
            temp_path.unlink()


class TestDependencyAudit:
    """Test dependency audit logic."""
    
    def test_audit_empty_dependencies(self):
        """Test auditing with no dependencies."""
        pyproject_data = {
            "project": {
                "name": "test-project",
                "dependencies": []
            }
        }
        
        result = audit_dependencies(pyproject_data)
        
        assert result["risk_summary"]["total_dependencies"] == 0
        assert result["risk_summary"]["dependencies_with_risks"] == 0
        assert len(result["base_dependencies"]) == 0
    
    def test_audit_base_dependencies(self):
        """Test auditing base dependencies."""
        pyproject_data = {
            "project": {
                "name": "test-project",
                "dependencies": [
                    "package1==1.0.0",
                    "package2>=2.0.0",
                    "package3>=3.0.0,<4.0.0"
                ]
            }
        }
        
        result = audit_dependencies(pyproject_data)
        
        assert result["risk_summary"]["total_dependencies"] == 3
        assert len(result["base_dependencies"]) == 3
        # package2 should have unpinned upper bound risk
        assert result["risk_summary"]["dependencies_with_risks"] >= 1
    
    def test_audit_optional_dependencies(self):
        """Test auditing optional dependencies."""
        pyproject_data = {
            "project": {
                "name": "test-project",
                "dependencies": [],
                "optional-dependencies": {
                    "dev": ["pytest>=7.0.0"],
                    "docs": ["sphinx==4.0.0"]
                }
            }
        }
        
        result = audit_dependencies(pyproject_data)
        
        assert "dev" in result["optional_extras"]
        assert "docs" in result["optional_extras"]
        assert result["risk_summary"]["total_dependencies"] == 2
    
    def test_audit_missing_expected_extras(self):
        """Test detection of missing expected extras."""
        pyproject_data = {
            "project": {
                "name": "test-project",
                "dependencies": [],
                "optional-dependencies": {
                    "dev": ["pytest>=7.0.0"]
                    # Missing "gateway" and "mcp"
                }
            }
        }
        
        result = audit_dependencies(pyproject_data)
        
        assert "missing_expected_extras" in result["risk_summary"]
        missing = result["risk_summary"]["missing_expected_extras"]
        assert "gateway" in missing
        assert "mcp" in missing
    
    def test_audit_common_risks(self):
        """Test identification of common risks."""
        pyproject_data = {
            "project": {
                "name": "test-project",
                "dependencies": [
                    "package1>=1.0.0",
                    "package2>=2.0.0",
                    "package3>=3.0.0"
                ]
            }
        }
        
        result = audit_dependencies(pyproject_data)
        
        assert len(result["risk_summary"]["common_risks"]) > 0
        # Should have "Unpinned upper bound" as a common risk
        risk_types = [r["risk"] for r in result["risk_summary"]["common_risks"]]
        assert "Unpinned upper bound (>=)" in risk_types


class TestAuditFormatting:
    """Test audit output formatting."""
    
    def test_format_text_empty(self):
        """Test text formatting with no dependencies."""
        results = {
            "base_dependencies": [],
            "optional_extras": {},
            "dev_dependencies": [],
            "risk_summary": {
                "total_dependencies": 0,
                "dependencies_with_risks": 0,
                "common_risks": []
            }
        }
        
        output = format_text(results)
        
        assert "Dependency Specification Audit" in output
        assert "Total dependencies: 0" in output
    
    def test_format_text_with_risks(self):
        """Test text formatting with risks."""
        results = {
            "base_dependencies": [
                {
                    "spec": "package>=1.0.0",
                    "risks": ["Unpinned upper bound"],
                    "notes": ["Consider adding upper bound"]
                }
            ],
            "optional_extras": {},
            "dev_dependencies": [],
            "risk_summary": {
                "total_dependencies": 1,
                "dependencies_with_risks": 1,
                "common_risks": [
                    {"risk": "Unpinned upper bound", "count": 1}
                ]
            }
        }
        
        output = format_text(results)
        
        assert "package>=1.0.0" in output
        assert "[RISK]" in output
        assert "Unpinned upper bound" in output
    
    def test_format_markdown(self):
        """Test markdown formatting."""
        results = {
            "base_dependencies": [
                {
                    "spec": "package==1.0.0",
                    "risks": [],
                    "notes": []
                }
            ],
            "optional_extras": {},
            "dev_dependencies": [],
            "risk_summary": {
                "total_dependencies": 1,
                "dependencies_with_risks": 0,
                "common_risks": []
            }
        }
        
        output = format_markdown(results)
        
        assert "# Ghost Chimera Dependency Specification Audit" in output
        assert "## Summary" in output
        assert "package==1.0.0" in output
    
    def test_format_json_output(self):
        """Test JSON formatting."""
        results = {
            "base_dependencies": [
                {
                    "spec": "package==1.0.0",
                    "risks": [],
                    "notes": []
                }
            ],
            "optional_extras": {},
            "dev_dependencies": [],
            "risk_summary": {
                "total_dependencies": 1,
                "dependencies_with_risks": 0,
                "common_risks": []
            }
        }
        
        output = format_json_output(results)
        parsed = json.loads(output)
        
        assert parsed["risk_summary"]["total_dependencies"] == 1
        assert len(parsed["base_dependencies"]) == 1


class TestAuditIntegration:
    """Test dependency audit integration."""
    
    def test_audit_complete_pyproject(self):
        """Test auditing a complete pyproject.toml."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[project]\n')
            f.write('name = "ghost-chimera"\n')
            f.write('dependencies = [\n')
            f.write('  "anthropic>=0.18.0",\n')
            f.write('  "pydantic==2.6.0",\n')
            f.write(']\n')
            f.write('[project.optional-dependencies]\n')
            f.write('dev = ["pytest>=7.0.0", "black==23.0.0"]\n')
            f.write('gateway = ["fastapi>=0.100.0"]\n')
            f.write('mcp = ["mcp>=0.1.0"]\n')
            temp_path = Path(f.name)
        
        try:
            pyproject_data = parse_pyproject(temp_path)
            result = audit_dependencies(pyproject_data)
            
            assert result["risk_summary"]["total_dependencies"] > 0
            assert "dev" in result["optional_extras"]
            assert "gateway" in result["optional_extras"]
            assert "mcp" in result["optional_extras"]
            
            # Should not have missing expected extras
            assert "missing_expected_extras" not in result["risk_summary"] or \
                   len(result["risk_summary"]["missing_expected_extras"]) == 0
        finally:
            temp_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Made with Bob
