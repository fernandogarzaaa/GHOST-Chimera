"""
Tests for IBM Bob Post-Hackathon Roadmap document.

Verifies that the roadmap document exists, contains all required sections,
and follows the "Do Not Fake Completion" policy.
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_roadmap_file_exists():
    """Test that the roadmap document exists."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    assert roadmap_path.exists(), "BOB_POST_HACKATHON_ROADMAP.md must exist"


def test_roadmap_contains_all_phases():
    """Test that the roadmap contains all five phases."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    required_phases = [
        "Phase 1: Developer Tools",
        "Phase 2: Testing Infrastructure",
        "Phase 3: Documentation",
        "Phase 4: CI/CD and Release",
        "Phase 5: Advanced Developer Intelligence",
    ]

    for phase in required_phases:
        assert phase in content, f"Roadmap must contain '{phase}'"


def test_roadmap_contains_do_not_fake_completion_policy():
    """Test that the roadmap contains the Do Not Fake Completion policy."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "Do Not Fake Completion Policy" in content, "Roadmap must contain 'Do Not Fake Completion Policy' section"

    # Check for key policy elements
    policy_elements = [
        "Acceptable Completion",
        "Unacceptable",
        "Working code",
        "Passing tests",
    ]

    for element in policy_elements:
        assert element in content, f"Policy must mention '{element}'"


def test_roadmap_contains_next_three_targets():
    """Test that the roadmap names the next three implementation targets."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "Next 3 Real Implementation Targets" in content, (
        "Roadmap must contain 'Next 3 Real Implementation Targets' section"
    )

    next_targets = [
        "Automated Changelog Generator",
        "Configuration Validator",
        "Dependency Audit Tool",
    ]

    for target in next_targets:
        assert target in content, f"Roadmap must name '{target}' as a next implementation target"


def test_roadmap_contains_priority_matrix():
    """Test that the roadmap contains a priority matrix."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "Priority Matrix" in content, "Roadmap must contain 'Priority Matrix' section"

    matrix_columns = [
        "Impact",
        "Effort",
        "Risk",
        "Phase",
        "Recommended Order",
    ]

    for column in matrix_columns:
        assert column in content, f"Priority matrix must include '{column}' column"


def test_roadmap_contains_completed_work_summary():
    """Test that the roadmap summarizes current completed Bob work."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "Current Completed Bob Work" in content, "Roadmap must contain 'Current Completed Bob Work' section"

    completed_tools = [
        "bob_accelerator.py",
        "coverage_report.py",
        "bob_delivery_package.py",
        "ADR System",
    ]

    for tool in completed_tools:
        assert tool in content, f"Roadmap must mention completed tool '{tool}'"


def test_roadmap_contains_success_metrics():
    """Test that the roadmap defines success metrics for each phase."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "Success Metrics" in content, "Roadmap must contain 'Success Metrics' section"

    phase_metrics = [
        "Phase 1 Success",
        "Phase 2 Success",
        "Phase 3 Success",
        "Phase 4 Success",
        "Phase 5 Success",
    ]

    for metric in phase_metrics:
        assert metric in content, f"Roadmap must define success metrics for '{metric}'"


def test_roadmap_contains_risk_management():
    """Test that the roadmap includes risk management section."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "Risk Management" in content, "Roadmap must contain 'Risk Management' section"

    risk_categories = [
        "Technical Risks",
        "Process Risks",
    ]

    for category in risk_categories:
        assert category in content, f"Risk management must include '{category}'"


def test_roadmap_contains_intentionally_unimplemented():
    """Test that the roadmap lists what remains intentionally unimplemented."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    assert "What Remains Intentionally Unimplemented" in content, (
        "Roadmap must contain 'What Remains Intentionally Unimplemented' section"
    )


def test_roadmap_is_honest_about_hackathon_status():
    """Test that the roadmap clearly states hackathon submission is complete."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    # Check for honest language about hackathon completion
    honest_statements = [
        "Hackathon submission complete",
        "not incomplete hackathon work",
        "post-hackathon",
    ]

    for statement in honest_statements:
        assert statement.lower() in content.lower(), f"Roadmap must honestly state: '{statement}'"


def test_roadmap_contains_implementation_plans():
    """Test that next 3 targets have detailed implementation plans."""
    roadmap_path = ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md"
    content = roadmap_path.read_text(encoding="utf-8")

    # Each of the next 3 targets should have implementation details
    implementation_sections = [
        "Implementation Plan",
        "Verification",
        "Definition of Done",
    ]

    for section in implementation_sections:
        # Should appear at least 3 times (once per target)
        count = content.count(section)
        assert count >= 3, f"'{section}' should appear at least 3 times (once per next target), found {count}"


if __name__ == "__main__":
    # Run tests manually
    import pytest

    pytest.main([__file__, "-v"])

# Made with Bob
