# AIAgent, ContextCompressor, MCPWrapper

## Architecture

Ghost Chimera's core reasoning loop is built on three cooperating modules in `ghostchimera/chimera_pilot/`.

### AIAgent (`agent_loop.py`)

The `AIAgent` class is the fundamental reasoning unit. Each agent owns:

- A `system_prompt` defining the agent's role
- A `SessionState` tracking turn count, total tokens, messages
- The `run()` method that:
  1. Appends user input to the session's `messages` list
  2. Calls the configured `ModelRouter` for completion
  3. Records the result back into the session
  4. Tracks token usage and turn history

The session state uses `ChimeraValue` and `Confidence` objects from `cognition_layer/confidence.py` for typed confidence tracking on the final result.

### ContextCompressor (`context_compressor.py`)

The `ContextCompressor` manages context window budget by:

1. Tracking current token count from session state
2. Checking `should_compress()` against a configured context budget (default 1000 tokens)
3. If over budget:
   - Truncating oldest messages first (`truncate_messages()`)
   - Optionally summarizing via local model (`compress_via_model()`) when `use_llm_summarization=True`
4. Using a `focus_topic` parameter to prioritize relevant content during truncation

The context engine is a singleton accessible via `get_context_engine()`.

### MCPWrapper (`mcp_wrapper.py`)

The `MCPWrapper` bridges Ghost Chimera's internal task representation with MCP (Model Context Protocol) tool definitions. It:

- Converts `TaskIR` nodes to MCP tool schemas
- Wraps MCP tool execution with safety policy checks (SSRF, production mode)
- Returns results as `ResultEnvelope` objects
- Handles MCP stdio transport (launching MCP servers, reading responses)

The wrapper is used by the `GatewayServer` to expose MCP tools as REST endpoints and WebSocket streams.

## Data Flow

```
User Input → AIAgent.run() → ModelRouter.select() → Model Provider
                                              ↓
                                        ResultEnvelope
                                              ↓
                                   ContextCompressor.compress()
                                              ↓
                                   MCPWrapper.wrap() → Gateway response
```

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/agent_loop.py` | AIAgent, SessionState |
| `ghostchimera/chimera_pilot/context_compressor.py` | ContextCompressor, get_context_engine |
| `ghostchimera/chimera_pilot/mcp_wrapper.py` | MCPWrapper, tool conversion |
| `ghostchimera/cognition_layer/confidence.py` | Confidence, ConfidentValue |
