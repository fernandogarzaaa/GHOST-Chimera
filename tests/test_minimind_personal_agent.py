from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from ghostchimera.model_layer.minimind_personal_agent import MiniMindPersonalAgent

RAW_EMAIL = textwrap.dedent(
    """\
    From: lead@example.com
    To: user@example.com
    Subject: Follow-up needed
    Date: Mon, 01 Jan 2024 10:00:00 +0000
    Content-Type: text/plain; charset=utf-8

    Follow-up: prepare the beta release notes before Friday.
    """
)


def test_personal_minimind_requires_admin_consent_before_bootstrap() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-minimind-") as tmp:
        base = Path(tmp)
        note = base / "notes.txt"
        note.write_text("TODO: ship v0.4.0 beta.", encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")

        result = agent.bootstrap(file_paths=[str(note)], include_system_specs=True)

        assert result["ok"] is False
        assert result["type"] == "consent_required"
        assert agent.status()["enabled"] is False


def test_personal_minimind_persists_admin_consent_and_bootstraps_sources() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-minimind-") as tmp:
        base = Path(tmp)
        note = base / "notes.txt"
        note.write_text("TODO: ship v0.4.0 beta and update the gateway dashboard.", encoding="utf-8")
        eml = base / "message.eml"
        eml.write_text(RAW_EMAIL, encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")

        consent = agent.grant_consent(
            admin_controls=True,
            allow_system_specs=True,
            allow_files=True,
            allow_email=True,
            allow_autonomy=True,
            allow_training=True,
            file_paths=[str(note)],
            email_paths=[str(eml)],
            operator="tester",
        )
        result = agent.bootstrap(include_system_specs=True)
        status = agent.status()

        assert consent["ok"] is True
        assert result["ok"] is True
        assert result["bootstrap"]["allow_files"] is True
        assert result["bootstrap"]["allow_email"] is True
        assert result["bootstrap"]["dataset_records"] >= 2
        assert result["system_profile"]["ok"] is True
        assert "task_hints" in result
        assert status["enabled"] is True
        assert status["dataset_count"] >= 2
        assert Path(status["dataset_path"]).exists()


def test_personal_minimind_whole_machine_crawl_discovers_docs_and_email_with_exclusions() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-crawl-") as tmp:
        base = Path(tmp)
        crawl_root = base / "machine"
        docs = crawl_root / "Documents"
        mail = crawl_root / "Mail"
        excluded = crawl_root / ".git"
        docs.mkdir(parents=True)
        mail.mkdir()
        excluded.mkdir()
        (docs / "roadmap.txt").write_text("TODO: prepare the launch checklist.", encoding="utf-8")
        (mail / "launch.eml").write_text(RAW_EMAIL, encoding="utf-8")
        (excluded / "secret.txt").write_text("TODO: this excluded file should not be ingested.", encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")

        agent.grant_consent(
            admin_controls=True,
            allow_machine_crawl=True,
            allow_email_crawl=True,
            allow_training=True,
            crawl_roots=[crawl_root],
        )
        result = agent.bootstrap(max_files=10, max_emails=10)
        handoff = agent.build_handoff("What launch work is pending?")

        assert result["ok"] is True
        assert result["crawl"]["enabled"] is True
        assert result["crawl"]["documents_discovered"] == 1
        assert result["crawl"]["emails_discovered"] == 1
        assert result["bootstrap"]["dataset_records"] >= 2
        assert "launch checklist" in handoff["personal_context"]
        assert "excluded file" not in handoff["personal_context"]


def test_personal_minimind_machine_crawl_requires_explicit_toggle() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-crawl-off-") as tmp:
        base = Path(tmp)
        crawl_root = base / "machine"
        crawl_root.mkdir()
        (crawl_root / "roadmap.txt").write_text("TODO: this should not be crawled.", encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")

        agent.grant_consent(admin_controls=True, allow_training=True, crawl_roots=[crawl_root])
        result = agent.bootstrap(max_files=10)

        assert result["ok"] is True
        assert result["crawl"]["enabled"] is False
        assert result["bootstrap"]["memory_documents"] == 0


def test_personal_minimind_honors_explicit_crawl_root_inside_state_dir() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-crawl-state-") as tmp:
        base = Path(tmp)
        state_dir = base / "state"
        crawl_root = state_dir / "selected-source"
        crawl_root.mkdir(parents=True)
        (crawl_root / "roadmap.txt").write_text("TODO: verify installed wheel personal crawl.", encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=state_dir, memory_db=base / "memory.sqlite3")

        agent.grant_consent(
            admin_controls=True,
            allow_machine_crawl=True,
            allow_training=True,
            crawl_roots=[crawl_root],
        )
        result = agent.bootstrap(max_files=10)

        assert result["ok"] is True
        assert result["crawl"]["documents_discovered"] == 1
        assert result["bootstrap"]["memory_documents"] == 1


def test_personal_minimind_builds_handoff_context_for_primary_model() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-minimind-") as tmp:
        base = Path(tmp)
        note = base / "work.txt"
        note.write_text("The user wants beta release notes drafted for Ghost Chimera v0.4.0.", encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")
        agent.grant_consent(admin_controls=True, allow_files=True, allow_training=True, file_paths=[str(note)])
        agent.bootstrap()

        handoff = agent.build_handoff("What should Ghost do next for the beta release?")

        assert handoff["ok"] is True
        assert "primary_model_prompt" in handoff
        assert "beta release notes" in handoff["personal_context"]
        assert "Personal MiniMind context" in handoff["primary_model_prompt"]


def test_personal_minimind_handoff_includes_active_ghost_path() -> None:
    from ghostchimera.personalization.path_synthesizer import synthesize_path

    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-minimind-path-") as tmp:
        base = Path(tmp)
        note = base / "work.txt"
        note.write_text("The user prefers pytest-first AI engineering work.", encoding="utf-8")
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")
        agent.grant_consent(admin_controls=True, allow_files=True, allow_training=True, file_paths=[str(note)])
        agent.bootstrap()

        handoff = agent.build_handoff(
            "Implement a model eval harness.",
            role_path=synthesize_path("ai-engineer-proxy", {"training_mode": "rag-first"}),
        )

        assert handoff["ok"] is True
        assert handoff["ghost_path"]["role"]["id"] == "ai-engineer-proxy"
        assert "AI Engineer Proxy" in handoff["primary_model_prompt"]
        assert "authorized Ghost Chimera operator proxy" in handoff["primary_model_prompt"]


def test_personal_minimind_can_revoke_consent() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-minimind-") as tmp:
        base = Path(tmp)
        agent = MiniMindPersonalAgent(state_dir=base / "state", memory_db=base / "memory.sqlite3")
        agent.grant_consent(admin_controls=True, allow_system_specs=True)

        revoked = agent.revoke_consent()

        assert revoked["ok"] is True
        assert agent.status()["enabled"] is False
