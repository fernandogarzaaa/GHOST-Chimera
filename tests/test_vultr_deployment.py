from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vultr_env_example_declares_required_guardrails():
    env_example = ROOT / ".env.vultr.example"
    content = env_example.read_text(encoding="utf-8")

    for required in [
        "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN=",
        "GHOSTCHIMERA_DEPLOYMENT_MODE=production",
        "GHOSTCHIMERA_EXTERNAL_ISOLATION=container",
        "GHOSTCHIMERA_SECURITY_REVIEWED=1",
        "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1",
        "GHOSTCHIMERA_MODEL_PROVIDER=vultr",
        "VULTR_INFERENCE_API_KEY=",
        "VULTR_INFERENCE_MODEL=",
        "VULTR_INFERENCE_BASE_URL=",
    ]:
        assert required in content

    assert "sk-" not in content


def test_vultr_compose_override_runs_token_protected_console():
    compose = ROOT / "docker-compose.vultr.yml"
    content = compose.read_text(encoding="utf-8")

    assert ".env.vultr" in content
    assert "--auth-token" in content
    assert "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN" in content
    assert "8766:8766" in content
    assert "8765:8765" in content
    assert "no-new-privileges:true" in content
    assert "cap_drop:" in content
    assert "healthcheck:" in content
    assert "ghost-chimera-state:" in content


def test_vultr_hackathon_docs_frame_track_and_demo_acceptance():
    deployment = (ROOT / "docs" / "VULTR_HACKATHON_DEPLOYMENT.md").read_text(encoding="utf-8")
    submission = (ROOT / "docs" / "HACKATHON_SUBMISSION_GUIDE.md").read_text(encoding="utf-8")

    assert "Agentic Workflows" in submission
    assert "Enterprise Utility" in submission
    assert "Vultr VM" in deployment
    assert "Streamlit" in submission
    assert "ghostchimera doctor --production" in deployment
    assert "No private local files" in deployment
    assert "Manager Operator" in deployment
    assert "Virtual Assistant" in deployment


def test_optional_streamlit_landing_page_is_repo_deployable():
    app = (ROOT / "streamlit-demo" / "streamlit_app.py").read_text(encoding="utf-8")
    requirements = (ROOT / "streamlit-demo" / "requirements.txt").read_text(encoding="utf-8")
    readme = (ROOT / "streamlit-demo" / "README.md").read_text(encoding="utf-8")

    assert "import streamlit as st" in app
    assert "Ghost Chimera" in app
    assert "Vultr Alignment" in app
    assert "does not access your machine" in app
    assert "private repositories" in app
    assert "streamlit" in requirements
    assert "streamlit-demo/streamlit_app.py" in readme


def test_streamlit_demo_shows_ibm_bob_workflow():
    app = (ROOT / "streamlit-demo" / "streamlit_app.py").read_text(encoding="utf-8")

    assert "IBM Bob" in app
    assert "Bob-to-Ghost Delivery Package" in app
    assert "Developer onboarding friction" in app
    assert "Interactive onboarding tool" in app
    assert "Automated test coverage reporter" in app


def test_ibm_bob_hackathon_workflow_doc_uses_bob_evidence():
    doc = (ROOT / "docs" / "IBM_BOB_HACKATHON_WORKFLOW.md").read_text(encoding="utf-8")

    assert "IBM Bob" in doc
    assert "Completed comprehensive analysis" in doc
    assert "Prioritized Backlog" in doc
    assert "Bob-to-Ghost" in doc
    assert "meaningful use of Bob" in doc
