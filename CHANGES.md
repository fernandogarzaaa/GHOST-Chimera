# v0.2.0 Beta Changelog

## Safety & Security
- **Rate limiting**: Token bucket rate limiter with per-name bucket isolation
- **Schema validation**: Per-TaskKind input validation (Python, test, quantum, web research, file analysis, RAG, reasoning)
- **TLS enforcement**: HTTP tool requires HTTPS with explicit SSL context; rejects file://, data:, javascript: schemes
- **API key sanitization**: Provider `to_dict()` no longer exposes keys; `_sanitize_key()` helper masks leaked keys
- **Fragment bypass prevention**: 4-layer policy check (normalization, base64, whitespace-tolerant regex, AST analysis)
- **Audit log integrity**: HMAC-SHA256 chain verification for audit entries
- **Path containment fix**: String prefix matching replaces broken Path containment check

## New Features
- **MCP integration**: MCPServer (HTTP), MCPClient (HTTP JSON-RPC), MCPBackend for task execution through MCP servers
- **Model routing**: ModelRouter with fallback chain; `GHOSTCHIMERA_MODEL_PROVIDER=provider1,provider2` uses router
- **Telemetry exports**: `export_json()`, `export_csv()`, percentile computation, rich diagnostics (p50/p95/p99, error_rate, per-backend stats)
- **Structured logging**: `logging_config.py` with console + file handlers, JSON/text format support

## Infrastructure
- **Config migration**: `GhostChimeraConfig.migrate_from_v01()` and `validate_consistency()`
- **Health cache**: Scheduler caches backend estimates for 60 seconds
- **Connection pooling**: Memory store connection pooling

## Tests
- **Integration test suite**: Full pipeline, safety, and logging integration tests
- **Expanded unit tests**: Rate limiter, schema, scheduler, verifier, executor, telemetry, compiler, MCP, router
- **Integration test infrastructure**: Shared pytest fixtures for deterministic kernel and executor

## v0.2.0 Beta

Ghost Chimera v0.2.0 Beta introduces foundational safety, MCP integration, model routing, structured logging, and comprehensive test coverage.

### Safety & Security
- Rate limiting infrastructure (token bucket with per-name isolation)
- Input schema validation per TaskKind
- TLS enforcement in HTTP browser tool (HTTPS-only with explicit SSL context)
- API key sanitization across all providers and telemetry
- 4-layer dangerous fragment detection (normalization, base64, regex, AST)
- HMAC-SHA256 audit log chain verification

### New Features
- MCP (Model Context Protocol) server/client/backend integration
- Model provider routing with fallback chain
- Telemetry export (JSON/CSV) and diagnostic percentiles (p50/p95/p99)
- Structured logging with JSON format support

### Infrastructure
- Config migration layer for v0.1 -> v0.2
- Scheduler health cache (60s TTL)
- Memory store connection pooling

### Tests
- Integration test suite (pipeline, safety, logging)
- Expanded unit test coverage approaching 90%
- Shared pytest fixtures for deterministic testing

### Breaking Changes
- None (all changes are additive)
