# Competitive Capability Matrix

Last reviewed: 2026-05-13.

Ghost Chimera tracks release readiness against current agent-platform patterns,
not just internal feature names. The source of truth is executable:

```bash
ghostchimera capabilities --format json
ghostchimera capabilities --format markdown --save docs/capability-report.md
ghostchimera review-pr --base origin/main --head HEAD
ghostchimera review-pr --base origin/main --head WORKTREE
python -m ghostchimera.evals run --suite competitive
python -m ghostchimera.evals run --suite github-connected
python -m ghostchimera.evals run --suite path-synthesis
```

The matrix is also available in Ghost Console through
`GET /api/console/capabilities` and the **Capabilities** tab.

## Benchmarks

| Benchmark | Public context | Ghost Chimera release surface |
| --- | --- | --- |
| OpenAI Codex | Cloud/background coding tasks, GitHub/code-review workflows, browser/computer-use validation, and Codex CLI/IDE surfaces. See [Codex overview](https://platform.openai.com/docs/codex/overview). | Autonomy jobs, release gates, browser workspace, CLI/console, eval suites. |
| Claude Code | Scoped subagents, hooks, MCP, skills, and agent-team workflow surfaces. See [Claude Code overview](https://docs.anthropic.com/en/docs/claude-code/overview). | Subagent pool, hooks registry, MCP backend/server/client, skills registry, console controls. |
| LangGraph | Durable, stateful, controllable long-running agent workflows. See [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview). | Checkpoints, telemetry, operator workspace state, autonomy queue, release evals. |
| CrewAI | Role-based crews, flows, processes, and agent collaboration. See [CrewAI docs](https://docs.crewai.com/). | Agent pool, subagents, Mixture-of-Agents scoring, autonomy job profiles. |
| Hermes-style tool gateways | Tool-calling and MCP-style tool gateway patterns. See [Nous Hermes function calling](https://github.com/NousResearch/Hermes-Function-Calling). | MCP gateway/client/backend, credential-aware wrappers, policy hooks. |
| OpenClaw-style local autonomy | Local-first operator control, desktop/runtime actions, and policy-gated execution. | Desktop control policy, kill switch, browser workspace, local model/MiniMind runtime. |

## Required Capabilities

The competitive eval currently checks these capability families:

- Background task orchestration
- Repository release gates
- Browser and visual validation
- Hooks and policy gateway
- MCP tool gateway
- Isolated subagents and agent teams
- Durable stateful flows
- Personal local context
- Model routing and local runtime
- Red-team safety evals
- GitHub-connected autonomous engineer
- Multi-purpose Ghost path synthesis
- Automated code review

Each capability must map to real files and symbols. Missing surfaces lower the
score and appear as `top_gaps` in `ghostchimera capabilities --format json`.

Automated review is exposed through `ghostchimera review-pr` and
`POST /api/console/review-pr`. It performs deterministic checks for likely
secrets, destructive commands, `shell=True`, unfinished placeholder code,
missing tests for source changes, missing README/checklist updates for
operator-facing release surfaces, and generated artifacts.

## Beta Positioning

Ghost Chimera can be positioned as a local-first agent orchestration runtime
that combines policy-gated autonomy, personal local context, MCP tool gateways,
browser/desktop actions, release evals, and optional local inference.

Do not claim complete superiority over cloud coding agents. The honest beta
claim is stronger: Ghost Chimera exposes a broader local orchestration surface,
and the competitive matrix shows exactly which surfaces exist and what optional
integrations can be built next.
