import json

from scripts.generate_sbom import build_sbom, format_markdown


def test_sbom_generator_reports_runtime_and_optional_dependencies():
    pyproject = {
        "project": {
            "name": "demo",
            "version": "1.0.0",
            "dependencies": ["requests>=2"],
            "optional-dependencies": {"dev": ["pytest>=8"]},
        }
    }

    sbom = build_sbom(pyproject)
    markdown = format_markdown(sbom)

    assert sbom["type"] == "sbom-lite"
    assert sbom["component_count"] == 2
    assert {"name": "requests", "spec": "requests>=2", "scope": "runtime"} in sbom["components"]
    assert "Does not perform vulnerability scanning" in markdown
    json.dumps(sbom)
