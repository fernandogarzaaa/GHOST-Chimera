from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mkdocs_config_and_nav_targets_exist():
    config = ROOT / "mkdocs.yml"
    assert config.exists()
    content = config.read_text(encoding="utf-8")

    for target in ["index.md", "quick-start.md", "bob-tools.md", "api-reference.md", "safety-production.md"]:
        assert target in content
        assert (ROOT / "docs" / target).exists(), f"Missing docs page {target}"


def test_docs_pages_reference_bob_tools():
    content = (ROOT / "docs" / "bob-tools.md").read_text(encoding="utf-8")
    for tool in ["bob_accelerator.py", "generate_api_reference.py", "generate_sbom.py", "dependency_graph.py"]:
        assert tool in content
