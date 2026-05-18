# Native Absorption

Ghost Chimera absorbs selected ideas from the author's adjacent projects as
Ghost-native capabilities. These features are built into the repository and do
not require external runtime dependencies, external MCP servers, automatic model
downloads, or background training.

## Absorbed Capabilities

- `ChimeraLang` and `chimeralang-mcp`: confidence and variance guardrails,
  tamper-evident handoffs, operational trace stages, and query-aware context
  compression.
- `OpenDrop`: local model source resolution, GGUF/SafeTensors inventory,
  hardware posture, license posture, and quantization recommendations.
- `OpenChimera_v1`: MCP capability normalization, local model inventory
  patterns, and a real operator sandbox journey harness.

## Operator Surfaces

```bash
ghostchimera cognition guard --confidence 0.9 --variance 0.01
ghostchimera context compress --text "latency latency matters" --focus latency
ghostchimera local-model inventory
ghostchimera local-model resolve --source Qwen/Qwen2.5-7B-Instruct
ghostchimera capability-pack list
ghostchimera sandbox journey
```

The Ghost Console exposes the same capabilities through Local Models, Cognitive
Guardrails, Capability Pack, and Sandbox tabs.

## Safety Boundary

Native absorption is advisory and preview-first:

- No external MCP server is required.
- No model is downloaded, converted, activated, trained, or served unless a user
  explicitly approves that future action.
- No hidden chain-of-thought is exposed; the thinking surface shows operational
  stages only.
- Secrets are redacted from capability-pack, MCP, model, and Console responses.

## Attribution

The implementation is Ghost-native and selectively reimplements small,
dependency-light ideas from:

- https://github.com/fernandogarzaaa/chimeralang-mcp
- https://github.com/fernandogarzaaa/ChimeraLang
- https://github.com/fernandogarzaaa/OpenDrop
- https://github.com/fernandogarzaaa/OpenChimera_v1
