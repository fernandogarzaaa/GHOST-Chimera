"""Agent loop — persistent multi-turn session with tool-calling.

Patterns adapted from Hermes-Agent's AIAgent (Apache/MIT licensed Nous Research).
Ghost Chimera adds structured TaskSpec routing on top of the tool-calling loop
so tool decisions are always scheduled through the Chimera Pilot pipeline.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..cognition_layer.confidence import (
    ChimeraValue,
    Confidence,
    ConfidentValue,
    ConvergeValue,
    ExploreValue,
    ProvisionalValue,
)
from ..cognition_layer.workspace import ReflectionEngine, SelfModel, WorkingMemory
from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..model_layer.router import ModelRouter
from ..safety_layer.approval import approve
from .autonomy import AutonomyProfile, get_autonomy_profile_from_env
from .hooks import HookName
from .kernel import ChimeraPilotKernel
from .result_envelope import ResultEnvelope
from .task_ir import TaskKind, TaskSpec
from .telemetry import InMemoryTelemetryStore, now
from .tool_middleware import get_default_chain

logger = get_logger("agent_loop")

# ---------------------------------------------------------------------------
# Message / session primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str | list[dict]
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    finish_reason: str | None = None
    tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.finish_reason:
            result["finish_reason"] = self.finish_reason
        if self.tokens is not None:
            result["tokens"] = self.tokens
        return result


@dataclass
class SessionState:
    """Persistent session carrying message history and token state."""

    session_id: str
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    model_name: str = ""
    max_tokens: int = 16384
    # Token tracking from API usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    compression_count: int = 0
    started_at: float = field(default_factory=now)
    ended_at: float | None = None
    end_reason: str | None = None
    api_call_count: int = 0
    estimated_cost_usd: float = 0.0
    # Confidence tracking (Phase 2-4)
    confidence_history: list[float] = field(default_factory=list)

    def turn_count(self) -> int:
        return len([m for m in self.messages if m.role in {"user", "assistant"}])

    def message_dicts(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.messages]

    def recent_confidence(self, n: int = 5) -> float:
        """Return average confidence of the last N turns."""
        if not self.confidence_history:
            return 0.0
        return sum(self.confidence_history[-n:]) / min(n, len(self.confidence_history))


@dataclass
class ToolCall:
    """Represents a tool invocation requested by the agent."""

    id: str
    name: str
    arguments: dict[str, Any]
    result: str | None = None
    status: str = "pending"  # pending | success | error


@dataclass(frozen=True)
class Classification:
    recoverable: bool = False
    retry: bool = False
    backoff_seconds: float = 0.0
    switch_model: bool = False
    compress: bool = False
    requires_action: str | None = None
    message: str = ""


class ErrorClassifier:
    """Classify LLM/provider errors and recommend recovery strategies."""

    CLASSIFICATIONS: list[tuple[str, Classification]] = [
        (
            "rate_limit",
            Classification(
                recoverable=True,
                retry=True,
                backoff_seconds=5.0,
                message="Rate limit exceeded — will retry with backoff",
            ),
        ),
        (
            "insufficient_quota",
            Classification(recoverable=False, message="Insufficient API quota — cannot recover"),
        ),
        (
            "context_length",
            Classification(
                recoverable=True, compress=True, message="Context length exceeded — compression recommended"
            ),
        ),
        (
            "model_not_found",
            Classification(recoverable=True, switch_model=True, message="Model unavailable — switch to fallback"),
        ),
        (
            "authentication",
            Classification(recoverable=False, message="Authentication failed — check API keys"),
        ),
        (
            "overloaded",
            Classification(
                recoverable=True, retry=True, backoff_seconds=10.0, message="Provider overloaded — retry with backoff"
            ),
        ),
        (
            "default",
            Classification(recoverable=False, message="Unrecoverable error"),
        ),
    ]

    @classmethod
    def classify(cls, error_msg: str, error_type: str | None = None) -> Classification:
        full_text = f"{error_type or ''} {error_msg}".lower()
        for keyword, classification in cls.CLASSIFICATIONS:
            if keyword == "default":
                continue
            if keyword in full_text:
                return classification
        return cls.CLASSIFICATIONS[-1][1]  # default


# ---------------------------------------------------------------------------
# AIAgent — the persistent session runtime
# ---------------------------------------------------------------------------


class AIAgent:
    """Multi-turn agent with tool-calling loop, error recovery, and model fallback.

    Architecture:
        1. User sends a message -> AIAgent.run()
        2. AIAgent checks context budget -> compresses if needed
        3. AIAgent calls model via ModelRouter (with fallback chain)
        4. If model returns tool_calls -> execute tools -> go to step 2
        5. If model returns text -> return to caller
        6. Errors classified -> retry / switch model / compress as needed
    """

    def __init__(
        self,
        kernel: ChimeraPilotKernel | None = None,
        model_name: str = "claude-sonnet-4-20250514",
        max_tool_rounds: int | None = None,
        fallback_chain: list[str] | None = None,
        system_prompt: str = "",
        max_tokens: int = 16384,
        router: ModelRouter | None = None,
        config: GhostChimeraConfig | None = None,
        session: SessionState | None = None,
        autonomy_profile: AutonomyProfile | None = None,
    ):
        self.autonomy_profile = autonomy_profile or get_autonomy_profile_from_env()
        self.kernel = kernel or ChimeraPilotKernel.default()
        self.model_name = model_name
        self.max_tool_rounds = max_tool_rounds if max_tool_rounds is not None else self.autonomy_profile.max_tool_rounds
        self.fallback_chain = fallback_chain or ["claude-sonnet-4-20250514", "claude-haiku-4-20250514"]
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.router = router
        self.config = config
        self.error_classifier = ErrorClassifier()
        self.telemetry = InMemoryTelemetryStore()
        self._lock = threading.Lock()

        # Cognition primitives
        self.self_model = SelfModel(identity="ghost-chimera-agent")
        self.working_memory = WorkingMemory(task="default")
        self.reflection_engine = ReflectionEngine()

        # Confidence tracking (Phase 2-4)
        self.current_confidence: float = 0.0
        self.confidence_threshold: float = 0.85
        self._last_envelope: ResultEnvelope | None = None
        self._running_confidence: float = 0.5  # neutral starting point
        self._iteration_confidences: list[float] = []

        # Session management
        self._sessions: dict[str, SessionState] = {}
        self._active_session_id: str = session.session_id if session else "default"
        self._session = session or SessionState(session_id=self._active_session_id, system_prompt=system_prompt)

    @property
    def session(self) -> SessionState:
        return self._session

    @property
    def active_session_id(self) -> str:
        return self._active_session_id

    def start_session(self, session_id: str, system_prompt: str = "") -> SessionState:
        """Create a new session and make it active."""
        session = SessionState(session_id=session_id, system_prompt=system_prompt)
        with self._lock:
            self._sessions[session_id] = session
            self._active_session_id = session_id
            self._session = session
        logger.info("Started session %s", session_id)
        return session

    def switch_session(self, session_id: str) -> SessionState:
        """Switch to an existing session."""
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")
        with self._lock:
            self._active_session_id = session_id
            self._session = self._sessions[session_id]
        logger.info("Switched to session %s", session_id)
        return self._session

    def end_session(self, reason: str = "completed") -> SessionState:
        """Mark the current session as ended."""
        self._session.ended_at = now()
        self._session.end_reason = reason
        with self._lock:
            self._sessions[self._active_session_id] = self._session
        return self._session

    # ------------------------------------------------------------------
    # Core run loop
    # ------------------------------------------------------------------

    def run(self, user_message: str, tools: list[dict[str, Any]] | None = None) -> str:
        """Execute one user turn: tool-calling loop until model returns text.

        Returns the final text response from the model.
        """
        self._add_message(Message(role="user", content=user_message))

        for turn in range(self.max_tool_rounds):
            # Check context budget
            self._maybe_compress()

            # Attempt model call with fallback
            try:
                response = self._call_model(tools=tools)
            except Exception as exc:
                classification = self.error_classifier.classify(str(exc))
                recovery = self._recover(exc, classification)
                if not recovery:
                    raise
                continue

            # Track usage
            self._track_usage(response)

            # Check if model wants to call tools
            tool_calls = response.get("tool_calls")
            if tool_calls:
                results = self._execute_tool_calls(tool_calls, tools=tools)
                self._add_tool_results(results)
                raw_confidence = self._evaluate_iteration_confidence(results)
                self._update_confidence(raw_confidence)
                continue  # loop back to model

            # Model returned text — this is our answer
            content = response.get("content", "")
            if content:
                self._add_message(
                    Message(
                        role="assistant",
                        content=content,
                        finish_reason=response.get("finish_reason"),
                        tokens=response.get("usage", {}).get("total_tokens"),
                    )
                )
                confidence_value = self._build_confidence_value(str(content))
                self._last_envelope = ResultEnvelope(
                    kind="agent_response",
                    value=content,
                    confidence=self._running_confidence,
                    confidence_source="agent_loop",
                )
                self._last_envelope.claims = [
                    {"claim": "agent_completed", "passed": True},
                    {"claim": "confidence_level", "value": str(confidence_value)},
                ]
                self._session.confidence_history.append(self._running_confidence)
                self.current_confidence = self._running_confidence
                self.working_memory.task = user_message
                self.reflection_engine.record(
                    self.working_memory,
                    action="agent_response",
                    outcome="completed" if self._running_confidence >= self.confidence_threshold else "below_threshold",
                    confidence=self._running_confidence,
                )
                self.self_model.set_goal("current", user_message)
                logger.info("Turn %d: agent returned text", turn + 1)
                return self.format_with_confidence(str(content))

            self._add_message(
                Message(
                    role="assistant",
                    content="",
                    finish_reason=response.get("finish_reason"),
                )
            )

        # Exhausted tool rounds
        raise RuntimeError(f"Reached max tool rounds ({self.max_tool_rounds}) without returning text")

    def run_async(self, user_message: str, tools: list[dict[str, Any]] | None = None) -> str:
        """Async-compatible entry point — delegates to sync run via threading."""
        import asyncio

        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're inside an event loop — use run_in_executor
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(self.run, user_message, tools)
                return asyncio.get_event_loop().run_in_executor(None, lambda: future.result())
        else:
            return self.run(user_message, tools)

    def create_task(
        self,
        kind: TaskKind,
        objective: str,
        inputs: dict[str, Any] | None = None,
    ) -> TaskSpec:
        """Convert a user message into a TaskSpec routed through Chimera Pilot."""
        return TaskSpec.create(
            kind=kind,
            objective=objective,
            inputs=inputs or {},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_model(self, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Call the LLM via ModelRouter with fallback chain."""
        last_exception: Exception | None = None
        for model in self.fallback_chain:
            try:
                messages = self._session.message_dicts()
                if self._session.system_prompt:
                    messages = [Message(role="system", content=self._session.system_prompt).to_dict()] + messages
                self.kernel.hooks.fire(
                    HookName.LLM_INPUT,
                    messages=messages,
                    model=model,
                    session_id=self._session.session_id,
                )

                # Use kernel if available for structured routing
                if self.router:
                    response = self.router.complete(
                        model=model,
                        messages=messages,
                        tools=tools or [],
                        max_tokens=self.max_tokens,
                    )
                    if response:
                        self.kernel.hooks.fire(
                            HookName.LLM_OUTPUT,
                            response=response,
                            model=model,
                            session_id=self._session.session_id,
                        )
                        self.model_name = model
                        return response

                # Fallback: delegate to kernel's execution path
                task = TaskSpec.create(
                    kind=TaskKind.REASONING,
                    objective=f"Respond to user: {messages[-1].get('content', '') if messages else ''}",
                    inputs={"messages": messages, "model": model},
                )
                result = self.kernel.execute_task(task)
                if result.ok:
                    self.model_name = model
                    response = {"content": result.result.output, "finish_reason": "stop"}
                    self.kernel.hooks.fire(
                        HookName.LLM_OUTPUT,
                        response=response,
                        model=model,
                        session_id=self._session.session_id,
                    )
                    return response

            except Exception as exc:
                last_exception = exc
                logger.warning("Model %s failed: %s", model, exc)
                continue

        raise RuntimeError(f"All models in fallback chain failed: {last_exception}")

    def _execute_tool_calls(
        self,
        tool_calls: list[dict],
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict]:
        """Execute tool calls returned by the model."""
        results = []
        tool_map = {t["name"]: t for t in (tools or [])}
        middleware_chain = get_default_chain()
        context = {"session_id": self._session.session_id, "active_session_id": self._active_session_id}

        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("arguments", {})
            call_id = tc.get("id", f"call_{len(results)}")
            self.kernel.hooks.fire(
                HookName.BEFORE_TOOL_CALL,
                tool_name=name,
                arguments=args,
                session_id=self._session.session_id,
                requester=self._active_session_id,
            )

            tool_def = tool_map.get(name)
            if not tool_def:
                missing_tool_message = f"Tool {name} not found in available tools"
                results.append(
                    {
                        "tool_call_id": call_id,
                        "tool_name": name,
                        "status": "error",
                        "content": missing_tool_message,
                    }
                )
                self.kernel.hooks.fire(
                    HookName.AFTER_TOOL_CALL,
                    tool_name=name,
                    arguments=args,
                    result=missing_tool_message,
                    ok=False,
                    session_id=self._session.session_id,
                )
                continue

            status = "success"
            output: Any = ""
            try:
                if self.autonomy_profile.require_approval_for_high_impact and bool(
                    tool_def.get("requires_approval", False)
                ):
                    approval_result = approve(name, args, requester=self._active_session_id)
                    if not approval_result.approved:
                        raise PermissionError(approval_result.reason)
                handler = tool_def.get("handler")
                if handler:
                    output = handler(**args) if args else handler()
                else:
                    # Route through Chimera Pilot for structured backends
                    task = TaskSpec.create(
                        kind=TaskKind.TOOL_CALL,
                        objective=f"Call tool {name}",
                        inputs={"tool_name": name, "arguments": args},
                    )
                    result = self.kernel.execute_task(task)
                    status = "success" if result.ok else "error"
                    output = result.result.output if result.ok else result.result.error
            except Exception as exc:
                status = "error"
                output = str(exc)

            transformed = middleware_chain.run(name, output, context=context)
            if isinstance(transformed, str):
                content = transformed
            else:
                try:
                    content = json.dumps(transformed, ensure_ascii=False, default=str)
                except Exception:
                    content = str(transformed)
            results.append(
                {
                    "tool_call_id": call_id,
                    "tool_name": name,
                    "status": status,
                    "content": content,
                }
            )
            self.kernel.hooks.fire(
                HookName.AFTER_TOOL_CALL,
                tool_name=name,
                arguments=args,
                result=content,
                ok=status == "success",
                session_id=self._session.session_id,
            )

        return results

    def _maybe_compress(self) -> None:
        """Compress if conversation exceeds threshold."""
        messages = self._session.messages
        n = len(messages)
        # Compress when session gets large (heuristic: > 30 messages)
        if n > 30 and self._session.total_tokens > self._session.max_tokens * 0.75:
            logger.info("Context compression triggered (%d messages, %d tokens)", n, self._session.total_tokens)
            self._compress_session()

    def _compress_session(self) -> None:
        """Compress early messages into a summary."""
        messages = self._session.messages
        if len(messages) < 10:
            return

        # Preserve head (first 3) and tail (last 6), summarize the middle
        head = messages[:3]
        tail = messages[-6:]
        middle = messages[3:-6]

        # Build summary of middle section
        summary_parts = []
        for msg in middle:
            content = msg.content
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("text"))
            summary_parts.append(f"[{msg.role}]: {content}")

        summary = "\n".join(summary_parts[:50])  # limit summary depth
        summary_msg = Message(
            role="system",
            content=f"[CONTEXT COMPACTION] Earlier conversation summarized:\n{summary[:4000]}",
        )

        self._session.messages = [summary_msg] + tail
        self._session.compression_count += 1
        logger.info(
            "Compressed session: %d -> %d messages", len(middle) + len(head) + len(tail), len(self._session.messages)
        )

    def _track_usage(self, response: dict[str, Any]) -> None:
        """Track token usage from API response."""
        usage = response.get("usage", {})
        if usage:
            self._session.prompt_tokens = usage.get("prompt_tokens", 0)
            self._session.completion_tokens = usage.get("completion_tokens", 0)
            self._session.total_tokens = usage.get("total_tokens", 0)
            self._session.api_call_count += 1

    def _add_message(self, message: Message) -> None:
        """Add a message to the current session."""
        self._session.messages.append(message)

    def _add_tool_results(self, results: list[dict]) -> None:
        """Add tool call and tool result messages to session."""
        for r in results:
            tool_call_msg = Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": r["tool_call_id"],
                        "name": r["tool_name"],
                        "arguments": {},
                    }
                ],
            )
            self._add_message(tool_call_msg)

            result_msg = Message(
                role="tool",
                content=r.get("content", ""),
                tool_call_id=r["tool_call_id"],
            )
            self._add_message(result_msg)

    def _recover(self, exc: Exception, classification: Classification) -> bool:
        """Attempt error recovery. Returns True if recovered."""
        logger.info("Error recovery: %s", classification.message)
        if not classification.is_recoverable:
            return False
        if classification.retry and classification.backoff_seconds > 0:
            time.sleep(classification.backoff_seconds)
            return True
        if classification.switch_model:
            # Already handled by fallback chain in _call_model
            return True
        if classification.compress:
            self._compress_session()
            return True
        return False

    # -------------- confidence helpers
    # --------------

    def _evaluate_iteration_confidence(self, results: list[dict]) -> float:
        """Evaluate confidence for a single iteration based on tool results."""
        if not results:
            return 0.3

        success_count = sum(1 for r in results if r.get("status") == "success")
        success_rate = success_count / len(results)

        structured_count = 0
        for r in results:
            content = r.get("content", "")
            if isinstance(content, str):
                try:
                    json.loads(content)
                    structured_count += 1
                except (json.JSONDecodeError, ValueError):
                    continue
        structure_score = structured_count / len(results) if results else 0.0

        convergence_bonus = 0.0
        if self._iteration_confidences:
            diff = abs(self._running_confidence - self._iteration_confidences[-1])
            if diff < 0.1:
                convergence_bonus = 0.1
            elif diff < 0.2:
                convergence_bonus = 0.05

        raw = (0.5 * success_rate) + (0.3 * structure_score) + (0.2 * convergence_bonus)
        return max(0.05, min(0.99, raw))

    def _update_confidence(self, raw_confidence: float) -> None:
        """Update running confidence using product rule."""
        if not self._iteration_confidences:
            self._running_confidence = raw_confidence
        else:
            combined = Confidence(raw_confidence, source="agent_loop").combine(
                Confidence(self._running_confidence, source="running")
            )
            self._running_confidence = combined.value

        self._iteration_confidences.append(self._running_confidence)
        self._session.confidence_history.append(self._running_confidence)
        logger.debug("Confidence: %.3f (raw: %.3f)", self._running_confidence, raw_confidence)

    def format_with_confidence(self, result: str) -> str:
        """Format result with confidence-aware annotations."""
        if self._running_confidence < 0.3:
            return f"[Explore] {result}\n(Confidence: low -- treat as preliminary)"
        if self._running_confidence < 0.6:
            return f"[Provisional] {result}\n(Confidence: moderate -- verify before using)"
        if self._running_confidence < 0.95:
            return f"[Converging] {result}\n(Confidence: building -- check key claims)"
        return result

    def _build_confidence_value(self, result: str) -> ChimeraValue:
        """Build the appropriate ChimeraValue based on confidence level."""
        raw_confidence = Confidence(self._running_confidence, source="agent_loop")
        if self._running_confidence >= 0.95:
            return ConfidentValue(raw=result, confidence=raw_confidence)
        if self._running_confidence >= 0.6:
            return ConvergeValue(raw=result, confidence=raw_confidence)
        if self._running_confidence >= 0.3:
            return ProvisionalValue(raw=result, confidence=raw_confidence)
        return ExploreValue(raw=result, confidence=raw_confidence)

    def status(self) -> dict[str, Any]:
        """Return current session status."""
        return {
            "session_id": self._active_session_id,
            "model": self.model_name,
            "message_count": len(self._session.messages),
            "prompt_tokens": self._session.prompt_tokens,
            "completion_tokens": self._session.completion_tokens,
            "total_tokens": self._session.total_tokens,
            "compression_count": self._session.compression_count,
            "api_call_count": self._session.api_call_count,
            "estimated_cost_usd": self._session.estimated_cost_usd,
            "turn_count": self._session.turn_count(),
            "running_confidence": self._running_confidence,
            "confidence_history_count": len(self._session.confidence_history),
        }


__all__ = ["AIAgent", "SessionState", "Message", "ToolCall", "ErrorClassifier", "Classification"]
