"""Mixture-of-agents — parallel reasoning with consensus voting.

Patterns adapted from Hermes-Agent's MixtureOfAgentsTool (Nous Research, MIT licensed).
Spawns N independent AIAgents with different prompt configurations,
scores outputs, and finds consensus via contradiction detection.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..agent_core.core import AgentCore
from ..cognition_layer.hallucination import HallucinationDetector
from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..model_layer.router import ModelRouter
from ..model_layer.providers import PROVIDERS
from .agent_loop import AIAgent, SessionState
from .error_classifier import ErrorClassifier, ErrorCategory
from .credential_pool import get_pool
from .context_compressor import get_context_engine
from .result_envelope import ResultEnvelope, merge_envelopes

logger = get_logger("mixture_of_agents")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_NUM_AGENTS = 3
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MIN_CONSENSUS_PCT = 60.0
DEFAULT_TIMEOUT = 120.0
REASONING_PROMPTS = [
    "You are an analytical expert. Break down the problem step by step with rigorous logic. Consider edge cases.",
    "You are a creative problem-solver. Think laterally and consider unconventional approaches. Challenge assumptions.",
    "You are a pragmatist. Focus on practical, actionable solutions. Prioritize simplicity and correctness.",
    "You are a skeptical reviewer. Critique the problem from multiple angles. Identify potential flaws and counterarguments.",
    "You are a domain specialist. Apply domain-specific heuristics and best practices to this problem.",
]

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MoAResult:
    """Result from a mixture-of-agents run."""
    query: str
    votes: list[dict[str, Any]]
    consensus_answer: str
    consensus_pct: float
    num_agents: int
    num_agreeing: int
    contradictions: list[dict]
    duration_seconds: float
    avg_tokens: int
    avg_duration: float
    confidence: float = 0.0
    consensus_method: str = "jaccard"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "num_agents": self.num_agents,
            "num_agreeing": self.num_agreeing,
            "consensus_pct": round(self.consensus_pct, 1),
            "confidence": round(self.confidence, 4),
            "consensus_method": self.consensus_method,
            "consensus_answer": self.consensus_answer[:2000],
            "consensus_answer_full": self.consensus_answer,
            "contradictions": self.contradictions,
            "duration_seconds": round(self.duration_seconds, 2),
            "avg_tokens": self.avg_tokens,
            "avg_duration": round(self.avg_duration, 2),
            "votes": self.votes,
        }


@dataclass(frozen=True)
class MoAConfig:
    """Configuration for mixture-of-agents."""
    num_agents: int = DEFAULT_NUM_AGENTS
    temperature: float = DEFAULT_TEMPERATURE
    min_consensus_pct: float = DEFAULT_MIN_CONSENSUS_PCT
    timeout: float = DEFAULT_TIMEOUT
    reasoning_prompt_prefixes: list[str] = field(default_factory=lambda: REASONING_PROMPTS)
    voting_strategy: str = "majority"  # majority | weighted | highest_quality


# ---------------------------------------------------------------------------
# Mixture of agents
# ---------------------------------------------------------------------------

class MixtureOfAgents:
    """Parallel reasoning with consensus via contradiction detection.

    Architecture:
    1. Spawn N independent AIAgents with different reasoning styles
    2. Each reasons independently on the same query
    3. Score outputs by quality (coherence, specificity, completeness)
    4. Detect contradictions between outputs
    5. Find consensus via voting/weighted scoring
    6. Return the best-consensus answer with confidence
    """

    def __init__(
        self,
        config: MoAConfig | None = None,
        model_router: ModelRouter | None = None,
        config_obj: GhostChimeraConfig | None = None,
    ):
        self.config = config or MoAConfig()
        self.router = model_router
        self.global_config = config_obj or GhostChimeraConfig.from_env()
        self._credentials = get_pool()
        self._error_classifier = ErrorClassifier()
        self._context_engine = get_context_engine()
        self._lock = threading.Lock()
        self._run_count = 0

    def vote(self, query: str, reasoning_prompts: list[str] | None = None) -> MoAResult:
        """Run the full MoA pipeline for a single query."""
        start = time.time()
        prompts = reasoning_prompts or self.config.reasoning_prompt_prefixes[:self.config.num_agents]

        # Ensure we don't request more prompts than available
        n_agents = min(self.config.num_agents, len(prompts))
        agents = self._spawn_agents(query, prompts[:n_agents])

        # Run in parallel (each agent now produces ResultEnvelope)
        results = self._run_agents_parallel(agents)

        # Score outputs
        scored = self._score_outputs(results, query)

        # Detect contradictions
        contradictions = self._detect_contradictions(results)

        # Find consensus
        consensus_answer, consensus_pct = self._find_consensus(scored)

        # Merge agent envelopes for combined confidence
        envelopes = [r.get("envelope") for r in results if r.get("envelope") is not None]
        if len(envelopes) >= 2:
            merged = merge_envelopes(envelopes)
            consensus_confidence = merged.confidence
        else:
            consensus_confidence = 0.0

        duration = time.time() - start
        tokens = [r.get("tokens", 0) for r in scored]
        durations = [r.get("duration", 0.0) for r in scored]

        with self._lock:
            self._run_count += 1

        return MoAResult(
            query=query,
            votes=scored,
            consensus_answer=consensus_answer,
            consensus_pct=consensus_pct,
            num_agents=len(results),
            num_agreeing=sum(1 for v in scored if v.get("agrees_with_consensus", False)),
            contradictions=contradictions,
            duration_seconds=duration,
            avg_tokens=int(sum(tokens) / len(tokens)) if tokens else 0,
            avg_duration=sum(durations) / len(durations) if durations else 0,
            confidence=consensus_confidence,
        )

    def vote_with_revote(
        self,
        query: str,
        max_rounds: int = 2,
        confidence_threshold: float = 0.65,
    ) -> MoAResult:
        """Multi-round voting: agents that disagree with the consensus get to revise."""
        current_result = self.vote(query)

        for round_num in range(1, max_rounds):
            if current_result.consensus_pct >= confidence_threshold:
                logger.info("Consensus reached at %.1f%% after %d rounds", current_result.consensus_pct, round_num)
                break

            # Find disagreeing agents and get them to reconsider
            disagreeing = [v for v in current_result.votes if not v.get("agrees_with_consensus", False)]
            if not disagreeing:
                break

            revised_results = []
            for v in disagreeing:
                new_prompt = (
                    f"Previous reasoning was not consensus. "
                    f"The consensus answer is: {current_result.consensus_answer[:500]}\n"
                    f"Reconsider your answer. What might you have missed?"
                )
                revised = self._revote_agent(v, new_prompt)
                revised_results.append(revised)

            # Merge revised results and re-score
            updated_votes = []
            for v in current_result.votes:
                if not v.get("agrees_with_consensus", False):
                    updated_votes.extend(revised_results)
                else:
                    updated_votes.append(v)

            current_result = MoAResult(
                query=query,
                votes=self._score_outputs(updated_votes, query),
                consensus_answer=current_result.consensus_answer,
                consensus_pct=current_result.consensus_pct,
                num_agents=len(updated_votes),
                num_agreeing=sum(1 for v in updated_votes if v.get("agrees_with_consensus", False)),
                contradictions=self._detect_contradictions(updated_votes),
                duration_seconds=time.time() - start,
                avg_tokens=current_result.avg_tokens,
                avg_duration=current_result.avg_duration,
            )

        return current_result

    def score_output(self, output: str, query: str) -> float:
        """Score an output by quality metrics."""
        score = 0.0

        # Specificity: outputs with numbers/dates/versions score higher
        import re
        numbers = re.findall(r'\b\d+[\.,]?\d*\b', output)
        score += min(20, len(numbers) * 2)

        # Coherence: outputs with logical connectors score higher
        connectors = len(re.findall(r'(therefore|however|consequently|thus|since|because|thus|accordingly)', output.lower()))
        score += min(20, connectors * 5)

        # Completeness: longer, structured outputs score higher (capped)
        words = len(output.split())
        score += min(20, words / 20)

        # Uncertainty markers: hedging language reduces score
        hedge_words = len(re.findall(r'(might|perhaps|possibly|unclear|unknown|speculate|guess)', output.lower()))
        score -= hedge_words * 3

        # Contradiction penalty: conflicting claims reduce score
        contradictions = self._detect_contradictions_for_text([output])
        score -= len(contradictions) * 15

        return max(0.0, min(100.0, score))

    def _spawn_agents(
        self,
        query: str,
        prompts: list[str],
    ) -> list[dict[str, Any]]:
        """Spawn independent AIAgents with different reasoning styles."""
        agents = []
        for i, prompt_prefix in enumerate(prompts):
            session = SessionState(
                session_id=f"moa-agent-{i}-{int(time.time() * 1000)}",
                system_prompt=(
                    f"{prompt_prefix}\n\n"
                    f"Query: {query}\n\n"
                    "Provide a clear, specific, and well-reasoned answer.\n"
                    "Do not hedge or equivocate. State your conclusion definitively.\n"
                    "Include specific details: numbers, names, dates where applicable.\n"
                ),
            )
            agent = AIAgent(system_prompt=session.system_prompt, session=session)
            agents.append({
                "index": i,
                "agent": agent,
                "prompt": prompt_prefix,
                "query": query,
            })
        return agents

    def _run_agents_parallel(self, agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run all agents in parallel and collect results."""
        results = []
        with ThreadPoolExecutor(max_workers=min(len(agents), self.config.num_agents)) as executor:
            futures = []
            for agent_info in agents:
                future = executor.submit(self._run_single_agent, agent_info)
                futures.append((agent_info, future))

            for agent_info, future in futures:
                try:
                    result = future.result(timeout=self.config.timeout)
                    result["agent_index"] = agent_info["index"]
                    result["prompt_style"] = agent_info["prompt"]
                    results.append(result)
                except FuturesTimeout:
                    results.append({
                        "agent_index": agent_info["index"],
                        "agent_output": "",
                        "success": False,
                        "error": "Timeout",
                        "prompt_style": agent_info["prompt"],
                        "tokens": 0,
                        "duration": self.config.timeout,
                    })
        return results

    def _run_single_agent(self, agent_info: dict) -> dict:
        """Run a single agent and return its result."""
        agent = agent_info["agent"]
        start = time.time()
        try:
            output = agent.run(agent_info["query"])
            duration = time.time() - start
            return {
                "agent_output": str(output)[:3000],
                "success": True,
                "tokens": agent.session.total_tokens,
                "duration": duration,
            }
        except Exception as exc:
            duration = time.time() - start
            return {
                "agent_output": "",
                "success": False,
                "error": str(exc),
                "tokens": agent.session.total_tokens,
                "duration": duration,
            }

    def _revote_agent(self, old_vote: dict, new_prompt: str) -> dict:
        """Run a revised reasoning for a disagreeing agent."""
        start = time.time()
        try:
            # Get the original agent
            agent = AIAgent(
                system_prompt=new_prompt,
            )
            # Use the agent's original session for continuity
            agent.session = old_vote.get("session") or SessionState(session_id="moa-revote")
            output = agent.run(new_prompt)
            duration = time.time() - start
            return {
                "agent_output": str(output)[:3000],
                "success": True,
                "tokens": agent.session.total_tokens,
                "duration": duration,
                "is_revote": True,
            }
        except Exception as exc:
            return {
                "agent_output": "",
                "success": False,
                "error": str(exc),
                "tokens": 0,
                "duration": time.time() - start,
                "is_revote": True,
            }

    def _score_outputs(
        self,
        results: list[dict[str, Any]],
        query: str,
    ) -> list[dict[str, Any]]:
        """Score all results by quality."""
        scored = []
        for r in results:
            if not r.get("success") or not r.get("agent_output"):
                scored.append({**r, "score": 0.0, "agrees_with_consensus": False})
                continue
            quality_score = self.score_output(r["agent_output"], query)
            scored.append({
                **r,
                "score": round(quality_score, 1),
                "agrees_with_consensus": False,  # set in _find_consensus
            })
        return scored

    def _find_consensus(
        self,
        scored: list[dict[str, Any]],
    ) -> tuple[str, float]:
        """Find the consensus answer via voting/weighted scoring."""
        if not scored:
            return ("", 0.0)

        # Group outputs by similarity
        outputs = [(i, s["agent_output"]) for i, s in enumerate(scored) if s.get("score", 0) > 0]
        if not outputs:
            return (scored[0].get("agent_output", ""), 0.0)

        # Calculate pairwise similarity (string overlap heuristic)
        n = len(outputs)
        similarity_matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                sim = self._jaccard_similarity(outputs[i][1], outputs[j][1])
                similarity_matrix[i][j] = sim
                similarity_matrix[j][i] = sim

        # Find the output with highest average similarity to others (consensus proxy)
        best_idx = max(range(n), key=lambda i: sum(similarity_matrix[i]) / (n - 1) if n > 1 else 0)
        consensus_output = outputs[best_idx][1]

        # Count "agreeing" outputs (similarity > threshold)
        agreement_threshold = 0.5
        agreeing = sum(1 for j in range(n) if similarity_matrix[best_idx][j] >= agreement_threshold)
        pct = (agreeing / n) * 100 if n > 0 else 0

        # Mark which votes agree with consensus
        for i, (idx, out) in enumerate(outputs):
            if similarity_matrix[best_idx][i] >= agreement_threshold:
                for s in scored:
                    if s.get("agent_index") == idx:
                        s["agrees_with_consensus"] = True

        return consensus_output, pct

    def _detect_contradictions(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict]:
        """Detect contradictions between outputs."""
        outputs = [(i, r.get("agent_output", "")) for i, r in enumerate(results) if r.get("success")]
        contradictions = []
        for i in range(len(outputs)):
            for j in range(i + 1, len(outputs)):
                c = self._detect_contradictions_for_text([outputs[i][1], outputs[j][1]])
                if c:
                    contradictions.extend([
                        {**contrad, "from_agent": outputs[i][0], "against_agent": outputs[j][0]}
                        for contrad in c
                    ])
        return contradictions

    def _detect_contradictions_for_text(self, texts: list[str]) -> list[dict]:
        """Find direct contradictions between two texts."""
        contradictions = []
        if len(texts) < 2:
            return contradictions

        # Look for direct negation patterns
        patterns = [
            (r'(\w+)\s+(is|are|was|were)\s+([^\s.]+)', r'\1\s+(is not|are not|was not|were not)\s+([^\s.]+)'),
            (r'(\w+)\s+can\s+(not|never)\s+(\w+)', r'(\w+)\s+(can|could)\s+(\w+)'),
            (r'(\d+)[\.,]?\d*\s+(percent|%)', r'(\d+)[\.,]?\d*\s+(percent|%)'),  # numeric contradictions
        ]

        for text_a, text_b in [(texts[0], texts[1])]:
            for pat_a, pat_b in patterns:
                matches_a = set(re.findall(pat_a, text_a.lower()))
                matches_b = set(re.findall(pat_b, text_b.lower()))
                if matches_a and matches_b:
                    # Simple string overlap check for contradictions
                    overlap = matches_a & matches_b
                    if overlap:
                        contradictions.append({
                            "type": "direct_negation",
                            "text_a": text_a[:200],
                            "text_b": text_b[:200],
                        })

        return contradictions

    def _jaccard_similarity(self, text_a: str, text_b: str) -> float:
        """Compute Jaccard similarity between two texts."""
        set_a = set(text_a.lower().split())
        set_b = set(text_b.lower().split())
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def status(self) -> dict[str, Any]:
        return {
            "num_agents": self.config.num_agents,
            "voting_strategy": self.config.voting_strategy,
            "min_consensus_pct": self.config.min_consensus_pct,
            "run_count": self._run_count,
        }


def get_moa(
    num_agents: int = DEFAULT_NUM_AGENTS,
    config_obj: GhostChimeraConfig | None = None,
) -> MixtureOfAgents:
    """Create a MixtureOfAgents instance."""
    config = MoAConfig(num_agents=num_agents)
    router = ModelRouter(provider_names=["openai", "llamacpp", "minimind"])
    return MixtureOfAgents(config=config, model_router=router, config_obj=config_obj)


__all__ = [
    "MixtureOfAgents",
    "MoAConfig",
    "MoAResult",
    "get_moa",
]
