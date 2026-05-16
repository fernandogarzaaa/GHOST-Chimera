from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bob_quality_workflow_contains_required_checks():
    workflow = ROOT / ".github" / "workflows" / "bob-quality.yml"
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")

    for command in [
        "python scripts/bob_accelerator.py",
        "python scripts/audit_dependencies.py --format markdown",
        "python scripts/bob_delivery_package.py --output docs/bob_delivery_package.md",
        "python -m pytest",
    ]:
        assert command in content


def test_test_matrix_covers_supported_platforms_and_versions():
    workflow = ROOT / ".github" / "workflows" / "test-matrix.yml"
    content = workflow.read_text(encoding="utf-8")

    for item in ["ubuntu-latest", "macos-latest", "windows-latest", '"3.11"', '"3.12"', '"3.13"']:
        assert item in content


def test_pull_request_template_has_bob_and_safety_sections():
    template = ROOT / ".github" / "pull_request_template.md"
    content = template.read_text(encoding="utf-8")

    assert "Bob Checks" in content
    assert "Safety and Production Impact" in content
    assert "python -m pytest -q" in content
