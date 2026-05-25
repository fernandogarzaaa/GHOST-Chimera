"""Live user, meeting, and interview presence runtime.

The runtime is local-first and disclosure-gated. It lets Ghost Chimera manage
live sessions with the user or other people, but it does not claim API access,
steal browser credentials, or secretly record participants.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..trust_runtime import TrustRuntimeStore
from .conversation import _redact_value

SESSION_TYPES = {"companion", "meeting", "interview"}
SESSION_MODES = {"draft", "waiting_for_disclosure", "active", "paused", "ended"}
SECRET_RECORDING_TERMS = ("secretly record", "record secretly", "hidden recording", "without consent")
ACTION_PATTERNS = (
    re.compile(r"\baction item\s*:\s*(?P<item>.+)", re.IGNORECASE),
    re.compile(r"\bfollow[- ]?up\s*:\s*(?P<item>.+)", re.IGNORECASE),
    re.compile(r"\btodo\s*:\s*(?P<item>.+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class LivePresenceParticipant:
    name: str
    role: str = "participant"
    external: bool = False
    consent_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass(frozen=True)
class LivePresenceTranscriptTurn:
    turn_id: str
    speaker: str
    content: str
    timestamp: float = field(default_factory=time.time)
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass
class LivePresenceSession:
    session_id: str
    title: str
    session_type: str = "meeting"
    mode: str = "draft"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    participants: list[dict[str, Any]] = field(default_factory=list)
    disclosure_status: str = "not_required"
    disclosure_text: str = ""
    visible_meeting_mode: bool = False
    recording_enabled: bool = False
    trust_run_id: str = ""
    transcript: list[dict[str, Any]] = field(default_factory=list)
    action_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


def _now() -> float:
    return time.time()


def _stable_id(*parts: object, length: int = 16) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _default_disclosure_text(session_type: str) -> str:
    if session_type == "interview":
        return "Ghost Chimera is assisting as a delegated AI operator. The user remains responsible for final decisions."
    return "Ghost Chimera is present as a delegated AI operator for note-taking, summaries, and approved follow-up."


def _normalize_participants(participants: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in participants or []:
        if not isinstance(item, dict):
            continue
        participant = LivePresenceParticipant(
            name=str(item.get("name") or "Participant").strip()[:120],
            role=str(item.get("role") or "participant").strip()[:80],
            external=bool(item.get("external")),
            consent_status=str(item.get("consent_status") or ("pending" if item.get("external") else "approved")),
        )
        normalized.append(participant.to_dict())
    return normalized


def _has_external_participant(session: dict[str, Any]) -> bool:
    participants = session.get("participants") if isinstance(session.get("participants"), list) else []
    return any(isinstance(item, dict) and bool(item.get("external")) for item in participants)


def _extract_action_items(content: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pattern in ACTION_PATTERNS:
        match = pattern.search(content)
        if match:
            text = str(match.group("item") or "").strip()
            if text:
                items.append({"text": text[:500], "status": "proposed", "requires_approval": True})
    return items


class LivePresenceStore:
    """Durable local store for live user/meeting/interview sessions."""

    def __init__(self, state_dir: str | Path, *, trust_store: TrustRuntimeStore | None = None) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.path = self.state_dir / "live_presence_sessions.json"
        self.trust_store = trust_store or TrustRuntimeStore(self.state_dir)

    def _default_state(self) -> dict[str, Any]:
        return {"active_session_id": "", "sessions": {}}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_state()
        if not isinstance(data, dict):
            return self._default_state()
        state = self._default_state()
        state["active_session_id"] = str(data.get("active_session_id") or "")
        state["sessions"] = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        return _redact_value(state)

    def _save(self, data: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(_redact_value(data), indent=2, sort_keys=True), encoding="utf-8")

    def create_session(
        self,
        *,
        title: str,
        session_type: str = "meeting",
        session_id: str = "",
        participants: list[dict[str, Any]] | None = None,
        disclosure_text: str = "",
        recording_enabled: bool = False,
    ) -> dict[str, Any]:
        stype = session_type if session_type in SESSION_TYPES else "meeting"
        normalized_participants = _normalize_participants(participants)
        requires_disclosure = any(item.get("external") for item in normalized_participants)
        sid = session_id.strip() if session_id else _stable_id("live-presence", title, stype, _now())
        session = LivePresenceSession(
            session_id=sid,
            title=(title or "Live Presence Session").strip()[:160],
            session_type=stype,
            participants=normalized_participants,
            disclosure_status="pending" if requires_disclosure else "not_required",
            disclosure_text=(disclosure_text or _default_disclosure_text(stype)).strip(),
            visible_meeting_mode=requires_disclosure,
            recording_enabled=bool(recording_enabled),
            warnings=[],
        )
        if any(term in f"{title} {disclosure_text}".lower() for term in SECRET_RECORDING_TERMS):
            session.warnings.append("Secret or undisclosed recording is not allowed.")
            session.recording_enabled = False
        data = self._load()
        data["sessions"][sid] = session.to_dict()
        data["active_session_id"] = sid
        self._save(data)
        return {"ok": True, "session_id": sid, "session": session.to_dict()}

    def list_sessions(self) -> dict[str, Any]:
        data = self._load()
        sessions = list((data.get("sessions") or {}).values())
        sessions.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
        return {"ok": True, "sessions": sessions, "active_session_id": data.get("active_session_id", "")}

    def get_session(self, session_id: str = "") -> dict[str, Any]:
        data = self._load()
        sid = session_id or str(data.get("active_session_id") or "")
        session = (data.get("sessions") or {}).get(sid)
        if not isinstance(session, dict):
            raise KeyError(sid)
        return _redact_value(session)

    def _mutate(self, session_id: str, mutate: Any) -> dict[str, Any]:
        data = self._load()
        session = (data.get("sessions") or {}).get(session_id)
        if not isinstance(session, dict):
            raise KeyError(session_id)
        mutate(session)
        session["updated_at"] = _now()
        data["sessions"][session_id] = _redact_value(session)
        data["active_session_id"] = session_id
        self._save(data)
        return _redact_value(session)

    def approve_disclosure(self, session_id: str, *, approved_by: str = "admin") -> dict[str, Any]:
        def mutate(session: dict[str, Any]) -> None:
            session["disclosure_status"] = "approved"
            session["visible_meeting_mode"] = True
            participants = session.get("participants") if isinstance(session.get("participants"), list) else []
            for participant in participants:
                if isinstance(participant, dict) and participant.get("external"):
                    participant["consent_status"] = "approved"
            session.setdefault("transcript", []).append(
                LivePresenceTranscriptTurn(
                    turn_id=_stable_id(session_id, "disclosure", approved_by, _now()),
                    speaker="Ghost",
                    content=f"Disclosure approved by {approved_by}.",
                    source="system",
                ).to_dict()
            )

        session = self._mutate(session_id, mutate)
        return {"ok": True, "session": session}

    def start_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if _has_external_participant(session) and session.get("disclosure_status") != "approved":
            updated = self._mutate(session_id, lambda item: item.update({"mode": "waiting_for_disclosure"}))
            return {
                "ok": False,
                "required_action": "approve_disclosure",
                "reply": "External participants require visible disclosure and consent before Ghost can join live.",
                "session": updated,
            }
        if any(term in json.dumps(session, default=str).lower() for term in SECRET_RECORDING_TERMS):
            return {"ok": False, "required_action": "revise_session", "error": "Secret recording requests are not allowed.", "session": session}
        trust = self.trust_store.create_run(
            agent_name="ghost_live_presence",
            objective=f"{session.get('session_type')}: {session.get('title')}",
            source="live_presence",
            metadata={"session_id": session_id, "visible_meeting_mode": bool(session.get("visible_meeting_mode"))},
        )
        self.trust_store.record_step(
            trust["run_id"],
            step_type="live_presence_start",
            status="completed",
            inputs={"session_id": session_id, "session_type": session.get("session_type")},
            outputs={"disclosure_status": session.get("disclosure_status")},
            idempotency_key=f"{trust['run_id']}:live-presence-start",
        )

        def mutate(item: dict[str, Any]) -> None:
            item["mode"] = "active"
            item["trust_run_id"] = trust["run_id"]

        updated = self._mutate(session_id, mutate)
        return {"ok": True, "session": updated, "trust_run": self.trust_store.get_run(trust["run_id"])}

    def record_transcript(self, session_id: str, *, speaker: str, content: str, source: str = "manual") -> dict[str, Any]:
        turn = LivePresenceTranscriptTurn(
            turn_id=_stable_id(session_id, speaker, content, _now()),
            speaker=(speaker or "Speaker").strip()[:120],
            content=str(content or "").strip(),
            source=(source or "manual").strip()[:80],
        ).to_dict()
        extracted = _extract_action_items(str(content or ""))

        def mutate(session: dict[str, Any]) -> None:
            session.setdefault("transcript", []).append(turn)
            if extracted:
                session.setdefault("action_items", []).extend(extracted)

        updated = self._mutate(session_id, mutate)
        trust_run_id = str(updated.get("trust_run_id") or "")
        if trust_run_id:
            self.trust_store.record_step(
                trust_run_id,
                step_type="live_presence_transcript",
                status="completed",
                inputs={"speaker": turn["speaker"], "source": turn["source"]},
                outputs={"content": turn["content"], "action_items": extracted},
                idempotency_key=f"{trust_run_id}:transcript:{turn['turn_id']}",
            )
        return {"ok": True, "turn": turn, "action_items": extracted, "session": updated}

    def generate_report(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        transcript = session.get("transcript") if isinstance(session.get("transcript"), list) else []
        action_items = session.get("action_items") if isinstance(session.get("action_items"), list) else []
        report = {
            "session_id": session_id,
            "title": session.get("title", ""),
            "session_type": session.get("session_type", ""),
            "mode": session.get("mode", ""),
            "participants": session.get("participants", []),
            "turn_count": len(transcript),
            "action_items": action_items,
            "summary": self._summary_from_transcript(transcript),
            "approval_required_for_follow_up": bool(action_items),
            "trust_run_id": session.get("trust_run_id", ""),
        }
        trust_run_id = str(session.get("trust_run_id") or "")
        if trust_run_id:
            self.trust_store.record_step(
                trust_run_id,
                step_type="live_presence_report",
                status="completed",
                outputs=report,
                idempotency_key=f"{trust_run_id}:report",
            )
        return {"ok": True, "report": _redact_value(report), "session": session}

    def status(self) -> dict[str, Any]:
        sessions = self.list_sessions()["sessions"]
        active = [item for item in sessions if item.get("mode") == "active"]
        pending = [item for item in sessions if item.get("disclosure_status") == "pending"]
        recommended: dict[str, Any]
        if pending:
            recommended = {
                "action": "approve_disclosure",
                "label": "Approve participant disclosure",
                "session_id": pending[0].get("session_id", ""),
            }
        elif not sessions:
            recommended = {"action": "create_session", "label": "Create a meeting or interview session"}
        else:
            recommended = {"action": "review_report", "label": "Review the latest live presence report", "session_id": sessions[0].get("session_id", "")}
        return {
            "ok": True,
            "counts": {
                "sessions": len(sessions),
                "active_sessions": len(active),
                "pending_disclosures": len(pending),
                "action_items": sum(len(item.get("action_items") or []) for item in sessions if isinstance(item, dict)),
            },
            "active_sessions": active,
            "recommended_next_action": recommended,
            "policy": {
                "disclosure_required_for_external_participants": True,
                "secret_recording_allowed": False,
                "raw_audio_stored_by_default": False,
                "third_party_commitments_require_approval": True,
            },
        }

    def _summary_from_transcript(self, transcript: list[Any]) -> str:
        if not transcript:
            return "No transcript has been captured yet."
        snippets = [
            str(turn.get("content") or "").strip()
            for turn in transcript
            if isinstance(turn, dict) and str(turn.get("content") or "").strip()
        ]
        if not snippets:
            return "No transcript has been captured yet."
        return " ".join(snippets[-4:])[:1200]

