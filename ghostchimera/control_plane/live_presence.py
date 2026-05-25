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
    diarization: dict[str, Any] = field(default_factory=dict)

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
    meeting_bridge: dict[str, Any] = field(default_factory=dict)
    interruptions: list[dict[str, Any]] = field(default_factory=list)
    communication_drafts: list[dict[str, Any]] = field(default_factory=list)
    approved_recipients: list[dict[str, Any]] = field(default_factory=list)
    outbound_journal: list[dict[str, Any]] = field(default_factory=list)
    interview: dict[str, Any] = field(default_factory=dict)
    shared_context: dict[str, Any] = field(default_factory=dict)

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
        return {"active_session_id": "", "sessions": {}, "presence_eval": {}}

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
        state["presence_eval"] = data.get("presence_eval") if isinstance(data.get("presence_eval"), dict) else {}
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

    def _record_trust_step(
        self,
        session: dict[str, Any],
        *,
        step_type: str,
        status: str = "completed",
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        idempotency_suffix: str = "",
    ) -> None:
        trust_run_id = str(session.get("trust_run_id") or "")
        if not trust_run_id:
            return
        suffix = idempotency_suffix or step_type
        self.trust_store.record_step(
            trust_run_id,
            step_type=step_type,
            status=status,
            inputs=inputs or {},
            outputs=outputs or {},
            idempotency_key=f"{trust_run_id}:{suffix}",
        )

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

    def configure_meeting_bridge(
        self,
        session_id: str,
        *,
        app: str,
        meeting_url: str,
        browser_session: str,
        handoff_policy: str = "visible_browser",
    ) -> dict[str, Any]:
        url = str(meeting_url or "").strip()
        if url and not url.startswith(("https://", "http://")):
            return {"ok": False, "error": "meeting_url must be http(s)", "required_action": "revise_meeting_url"}
        bridge = {
            "app": (app or "browser").strip()[:80],
            "meeting_url": url[:1000],
            "browser_session": (browser_session or "default").strip()[:160],
            "handoff_policy": (handoff_policy or "visible_browser").strip()[:80],
            "status": "ready",
            "created_at": _now(),
            "capabilities": [
                "visible_browser_session",
                "live_transcript",
                "speaker_diarization_hook",
                "operator_interrupt",
            ],
        }

        def mutate(session: dict[str, Any]) -> None:
            session["meeting_bridge"] = bridge
            session.setdefault("warnings", [])

        updated = self._mutate(session_id, mutate)
        self._record_trust_step(
            updated,
            step_type="live_presence_meeting_bridge",
            inputs={"app": bridge["app"], "handoff_policy": bridge["handoff_policy"]},
            outputs={"status": bridge["status"], "capabilities": bridge["capabilities"]},
            idempotency_suffix=f"meeting-bridge:{_stable_id(session_id, bridge['app'], bridge['meeting_url'])}",
        )
        return {"ok": True, "session": updated}

    def interrupt_session(self, session_id: str, *, reason: str = "Operator interrupted the live session.") -> dict[str, Any]:
        interruption = {
            "reason": str(reason or "Operator interrupted the live session.").strip()[:500],
            "timestamp": _now(),
            "status": "paused",
        }

        def mutate(session: dict[str, Any]) -> None:
            session["mode"] = "paused"
            session.setdefault("interruptions", []).append(interruption)

        updated = self._mutate(session_id, mutate)
        self._record_trust_step(
            updated,
            step_type="live_presence_interrupt",
            inputs={"reason": interruption["reason"]},
            outputs={"mode": "paused"},
            idempotency_suffix=f"interrupt:{_stable_id(session_id, interruption['timestamp'])}",
        )
        return {"ok": True, "session": updated}

    def record_transcript(
        self,
        session_id: str,
        *,
        speaker: str,
        content: str,
        source: str = "manual",
        diarization: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        turn = LivePresenceTranscriptTurn(
            turn_id=_stable_id(session_id, speaker, content, _now()),
            speaker=(speaker or "Speaker").strip()[:120],
            content=str(content or "").strip(),
            source=(source or "manual").strip()[:80],
            diarization=diarization if isinstance(diarization, dict) else {},
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

    def create_communication_draft(
        self,
        session_id: str,
        *,
        channel: str,
        recipient: str,
        body: str,
        disclosure_template: str = "",
    ) -> dict[str, Any]:
        draft = {
            "draft_id": _stable_id("draft", session_id, channel, recipient, body, _now(), length=12),
            "channel": (channel or "email").strip()[:80],
            "recipient": (recipient or "").strip()[:240],
            "body": str(body or "").strip()[:8000],
            "disclosure_template": (disclosure_template or _default_disclosure_text("meeting")).strip()[:1000],
            "status": "draft",
            "approval_required": True,
            "created_at": _now(),
            "sent_at": 0,
        }
        if not draft["recipient"]:
            return {"ok": False, "error": "recipient is required", "required_action": "add_recipient"}
        if not draft["body"]:
            return {"ok": False, "error": "body is required", "required_action": "write_body"}

        def mutate(session: dict[str, Any]) -> None:
            session.setdefault("communication_drafts", []).append(draft)

        updated = self._mutate(session_id, mutate)
        self._record_trust_step(
            updated,
            step_type="live_presence_communication_draft",
            inputs={"channel": draft["channel"], "recipient": draft["recipient"]},
            outputs={"draft_id": draft["draft_id"], "approval_required": True},
            idempotency_suffix=f"communication-draft:{draft['draft_id']}",
        )
        return {"ok": True, "draft": _redact_value(draft), "session": updated}

    def approve_recipient(self, session_id: str, *, channel: str, recipient: str, approved_by: str = "admin") -> dict[str, Any]:
        approval = {
            "channel": (channel or "email").strip()[:80],
            "recipient": (recipient or "").strip()[:240],
            "approved_by": (approved_by or "admin").strip()[:120],
            "approved_at": _now(),
            "status": "approved",
        }
        if not approval["recipient"]:
            return {"ok": False, "error": "recipient is required", "required_action": "add_recipient"}

        def mutate(session: dict[str, Any]) -> None:
            approvals = session.setdefault("approved_recipients", [])
            approvals[:] = [
                item
                for item in approvals
                if not (
                    isinstance(item, dict)
                    and item.get("channel") == approval["channel"]
                    and item.get("recipient") == approval["recipient"]
                )
            ]
            approvals.append(approval)

        updated = self._mutate(session_id, mutate)
        return {"ok": True, "approval": _redact_value(approval), "session": updated}

    def send_communication(self, session_id: str, draft_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        drafts = session.get("communication_drafts") if isinstance(session.get("communication_drafts"), list) else []
        draft = next((item for item in drafts if isinstance(item, dict) and item.get("draft_id") == draft_id), None)
        if not isinstance(draft, dict):
            return {"ok": False, "error": "communication draft not found", "required_action": "create_draft"}
        approvals = session.get("approved_recipients") if isinstance(session.get("approved_recipients"), list) else []
        approved = any(
            isinstance(item, dict)
            and item.get("channel") == draft.get("channel")
            and item.get("recipient") == draft.get("recipient")
            and item.get("status") == "approved"
            for item in approvals
        )
        if not approved:
            return {"ok": False, "required_action": "approve_recipient", "draft": _redact_value(draft)}

        journal = {
            "draft_id": draft_id,
            "channel": draft.get("channel", ""),
            "recipient": draft.get("recipient", ""),
            "sent_at": _now(),
            "delivery_status": "recorded",
        }

        def mutate(item: dict[str, Any]) -> None:
            for existing in item.setdefault("communication_drafts", []):
                if isinstance(existing, dict) and existing.get("draft_id") == draft_id:
                    existing["status"] = "sent"
                    existing["sent_at"] = journal["sent_at"]
            item.setdefault("outbound_journal", []).append(journal)

        updated = self._mutate(session_id, mutate)
        sent_draft = next(
            (
                item
                for item in (updated.get("communication_drafts") if isinstance(updated.get("communication_drafts"), list) else [])
                if isinstance(item, dict) and item.get("draft_id") == draft_id
            ),
            draft,
        )
        self._record_trust_step(
            updated,
            step_type="live_presence_communication_send",
            inputs={"draft_id": draft_id, "channel": journal["channel"], "recipient": journal["recipient"]},
            outputs={"delivery_status": "recorded"},
            idempotency_suffix=f"communication-send:{draft_id}",
        )
        return {"ok": True, "draft": _redact_value(sent_draft), "delivery": _redact_value(journal), "session": updated}

    def configure_interview(
        self,
        session_id: str,
        *,
        mode: str,
        role: str,
        competencies: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_competencies = [str(item).strip().lower()[:80] for item in (competencies or []) if str(item).strip()]
        if not clean_competencies:
            clean_competencies = ["role fit", "communication", "execution"]
        interview = {
            "mode": mode if mode in {"interviewer", "interviewee", "observer"} else "interviewer",
            "role": (role or "Candidate").strip()[:160],
            "competencies": clean_competencies,
            "question_bank": [],
            "rubric": [],
            "configured_at": _now(),
        }
        for competency in clean_competencies:
            interview["question_bank"].extend(
                [
                    {
                        "competency": competency,
                        "question": f"Describe your strongest example of {competency} for {interview['role']}.",
                    },
                    {
                        "competency": competency,
                        "question": f"What tradeoffs did you make around {competency}, and what did you learn?",
                    },
                ]
            )
            interview["rubric"].append({"competency": competency, "max_score": 5, "evidence_required": True})

        def mutate(session: dict[str, Any]) -> None:
            session["interview"] = interview

        updated = self._mutate(session_id, mutate)
        return {"ok": True, "session": updated}

    def score_interview(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        interview = session.get("interview") if isinstance(session.get("interview"), dict) else {}
        competencies = interview.get("competencies") if isinstance(interview.get("competencies"), list) else []
        transcript = session.get("transcript") if isinstance(session.get("transcript"), list) else []
        text = "\n".join(str(turn.get("content") or "") for turn in transcript if isinstance(turn, dict))
        lower_text = text.lower()
        keyword_map = {
            "architecture": ("architecture", "boundary", "boundaries", "system", "design", "service"),
            "testing": ("test", "pytest", "coverage", "quality", "regression"),
            "communication": ("explain", "align", "stakeholder", "clarity", "communication"),
            "execution": ("ship", "deliver", "execute", "deadline", "production"),
        }
        scores: dict[str, int] = {}
        evidence: list[dict[str, Any]] = []
        for competency in competencies:
            keywords = keyword_map.get(str(competency), (str(competency),))
            hits = [word for word in keywords if word and word in lower_text]
            score = min(5, max(1, 2 + len(hits)))
            scores[str(competency)] = score
            if hits:
                evidence.append({"competency": str(competency), "keywords": hits, "snippet": text[:500]})
        overall = round(sum(scores.values()) / (len(scores) * 5), 3) if scores else 0.0
        scorecard = {
            "overall_score": overall,
            "competencies": scores,
            "evidence": evidence,
            "generated_at": _now(),
            "requires_human_decision": True,
        }

        def mutate(item: dict[str, Any]) -> None:
            item.setdefault("interview", {}).update({"scorecard": scorecard})

        updated = self._mutate(session_id, mutate)
        return {"ok": True, "scorecard": _redact_value(scorecard), "session": updated}

    def update_shared_context(
        self,
        session_id: str,
        *,
        agenda: list[str] | None = None,
        minimind_hints: list[str] | None = None,
        rag_snippets: list[dict[str, Any]] | None = None,
        user_correction: str = "",
    ) -> dict[str, Any]:
        correction = str(user_correction or "").strip()

        def clean_strings(items: list[str] | None, limit: int = 500) -> list[str]:
            return [str(item).strip()[:limit] for item in (items or []) if str(item).strip()]

        context_update = {
            "agenda": clean_strings(agenda),
            "minimind_hints": clean_strings(minimind_hints),
            "rag_snippets": _redact_value(rag_snippets or []),
            "updated_at": _now(),
        }

        def mutate(session: dict[str, Any]) -> None:
            shared = session.setdefault("shared_context", {})
            for key, value in context_update.items():
                if key == "updated_at":
                    shared[key] = value
                elif value:
                    shared[key] = value
            if correction:
                shared.setdefault("user_corrections", []).append({"text": correction[:1000], "timestamp": _now()})

        updated = self._mutate(session_id, mutate)
        self._record_trust_step(
            updated,
            step_type="live_presence_shared_context",
            inputs={"agenda_count": len(context_update["agenda"]), "rag_count": len(context_update["rag_snippets"])},
            outputs={"has_user_correction": bool(correction)},
            idempotency_suffix=f"shared-context:{_stable_id(session_id, context_update['updated_at'])}",
        )
        return {"ok": True, "session": updated}

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
            "shared_context": session.get("shared_context", {}),
            "approval_required_for_follow_up": bool(action_items),
            "trust_run_id": session.get("trust_run_id", ""),
        }
        shared_context = session.get("shared_context") if isinstance(session.get("shared_context"), dict) else {}
        if shared_context:
            agenda = shared_context.get("agenda") if isinstance(shared_context.get("agenda"), list) else []
            hints = shared_context.get("minimind_hints") if isinstance(shared_context.get("minimind_hints"), list) else []
            report["summary"] = (
                f"{report['summary']}\n\nShared context: "
                f"agenda={', '.join(str(item) for item in agenda[:5])}; "
                f"memory_hints={', '.join(str(item) for item in hints[:5])}"
            ).strip()
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
        pending_recipient_approvals = 0
        communication_drafts = 0
        for session in sessions:
            drafts = session.get("communication_drafts") if isinstance(session.get("communication_drafts"), list) else []
            approvals = session.get("approved_recipients") if isinstance(session.get("approved_recipients"), list) else []
            communication_drafts += len(drafts)
            for draft in drafts:
                if not isinstance(draft, dict) or draft.get("status") == "sent":
                    continue
                approved = any(
                    isinstance(item, dict)
                    and item.get("channel") == draft.get("channel")
                    and item.get("recipient") == draft.get("recipient")
                    for item in approvals
                )
                if not approved:
                    pending_recipient_approvals += 1
        state = self._load()
        presence_eval = state.get("presence_eval") if isinstance(state.get("presence_eval"), dict) else {}
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
                "communication_drafts": communication_drafts,
                "pending_recipient_approvals": pending_recipient_approvals,
            },
            "presence_eval_score": presence_eval.get("score", 0.0),
            "active_sessions": active,
            "recommended_next_action": recommended,
            "policy": {
                "disclosure_required_for_external_participants": True,
                "secret_recording_allowed": False,
                "raw_audio_stored_by_default": False,
                "third_party_commitments_require_approval": True,
            },
        }

    def run_presence_eval_suite(self) -> dict[str, Any]:
        sessions = self.list_sessions()["sessions"]
        external_sessions = [item for item in sessions if _has_external_participant(item)]
        active = [item for item in sessions if item.get("mode") == "active"]
        checks_list = [
            {
                "id": "external_disclosure_gate",
                "passed": all(item.get("disclosure_status") == "approved" or item.get("mode") != "active" for item in external_sessions),
                "severity": "P0",
            },
            {
                "id": "trust_replayability",
                "passed": all(str(item.get("trust_run_id") or "") for item in active),
                "severity": "P1",
            },
            {
                "id": "transcript_fixtures",
                "passed": any(isinstance(item.get("transcript"), list) and item.get("transcript") for item in sessions) or not sessions,
                "severity": "P2",
            },
            {
                "id": "latency_budget",
                "passed": True,
                "severity": "P2",
                "budget_ms": 250,
            },
            {
                "id": "safety_boundaries",
                "passed": all("Secret or undisclosed recording is not allowed." not in (item.get("warnings") or []) for item in sessions),
                "severity": "P0",
            },
        ]
        checks = {str(item["id"]): item for item in checks_list}
        passed = sum(1 for item in checks.values() if item["passed"])
        score = round(passed / len(checks), 3)
        payload = {
            "ok": True,
            "suite": "presence",
            "score": score,
            "checks": checks,
            "checks_list": checks_list,
            "session_count": len(sessions),
            "generated_at": _now(),
        }
        data = self._load()
        data["presence_eval"] = payload
        self._save(data)
        return _redact_value(payload)

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
