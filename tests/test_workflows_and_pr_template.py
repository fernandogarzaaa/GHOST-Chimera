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


def test_daily_maintenance_workflow_refreshes_catalog_and_dependency_audit():
    workflow = ROOT / ".github" / "workflows" / "daily-maintenance.yml"
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")

    for item in [
        "schedule:",
        "workflow_dispatch:",
        "python scripts/update_model_provider_catalog.py",
        "--sources openrouter,huggingface,vultr",
        "docs/model_provider_catalog.json",
        "docs/model_provider_catalog.md",
        "python scripts/audit_dependencies.py --format markdown --output docs/dependency_audit.md",
        "python -m pytest tests/test_update_model_provider_catalog.py tests/test_model_discovery.py -q",
        "peter-evans/create-pull-request@v6",
        "No secrets are committed.",
    ]:
        assert item in content


def test_dependabot_runs_daily_for_python_and_github_actions():
    config = ROOT / ".github" / "dependabot.yml"
    assert config.exists()
    content = config.read_text(encoding="utf-8")

    assert "package-ecosystem: pip" in content
    assert "package-ecosystem: github-actions" in content
    assert content.count("interval: daily") >= 2
