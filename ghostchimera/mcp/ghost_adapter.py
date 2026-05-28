"""Compressed Ghost MCP adapter.

Maps a single external ``ghost`` MCP tool to the broader Ghost Chimera runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..sdk import GhostClient
from ..trust_runtime import TrustRuntimeStore


class GhostMCPAdapter:
    """Bridge one high-level MCP tool to Ghost Chimera capabilities."""

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        config_path: str | Path | None = None,
        client: GhostClient | None = None,
    ) -> None:
        resolved_state_dir = Path(state_dir).expanduser() if state_dir is not None else None
        self._client = client or GhostClient(state_dir=resolved_state_dir, config_path=config_path)
        self._state_dir = Path(resolved_state_dir or self._client.memory.db_path.parent).expanduser()

    def invoke(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a compressed Ghost action request."""

        payload = dict(arguments or {})
        action = str(payload.pop("action", "run") or "run").strip().lower()
        try:
            handler = getattr(self, f"_action_{action.replace('.', '_')}", None)
            if handler is None:
                return self._envelope(
                    ok=False,
                    action=action,
                    status="error",
                    summary=f"Unsupported ghost action: {action}",
                    warnings=[f"Unknown action: {action}"],
                    next_actions=self.available_actions(),
                )
            result = handler(payload)
            return self._normalize_result(action, result)
        except ValueError as exc:
            return self._envelope(
                ok=False,
                action=action,
                status="error",
                summary=str(exc),
                warnings=[str(exc)],
                next_actions=self.available_actions(),
            )
        except Exception as exc:  # noqa: BLE001
            return self._envelope(
                ok=False,
                action=action,
                status="error",
                summary=f"Ghost action failed: {exc}",
                warnings=[str(exc)],
                next_actions=self.available_actions(),
            )

    @staticmethod
    def available_actions() -> list[str]:
        return [
            "run",
            "status",
            "memory",
            "context",
            "consent",
            "bootstrap",
            "teach",
            "train",
            "trust",
            "workspace",
            "providers",
        ]

    def _action_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        objective = str(payload.get("objective") or payload.get("query") or "").strip()
        if not objective:
            raise ValueError("Missing objective for action 'run'.")
        result = self._client.run(objective)
        context = self._client.preview_context(objective, limit=int(payload.get("limit") or 5))
        handoff = self._client.minimind_handoff(objective, limit=int(payload.get("handoff_limit") or 8))
        providers = self._client.providers()
        warnings: list[str] = []
        if not handoff.get("ok", False) and handoff.get("error"):
            warnings.append(str(handoff["error"]))
        return {
            "ok": result.ok,
            "summary": f"Ghost completed objective via {result.backend_id or 'unknown backend'}.",
            "output": result.output,
            "details": {
                "run": result.to_dict(),
                "context": context,
                "handoff": handoff,
            },
            "sources": list(context.get("sources") or []),
            "backend": result.backend_id,
            "provider": providers.get("status", {}).get("provider", ""),
            "warnings": warnings,
            "artifacts": {
                "executions": result.executions,
            },
        }

    def _action_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        status = self._client.runtime_status()
        return {
            "ok": True,
            "summary": "Ghost runtime status retrieved.",
            "output": status,
            "details": status,
            "sources": [],
            "backend": "",
            "provider": status.get("providers", {}).get("status", {}).get("provider", ""),
            "warnings": list(status.get("trust", {}).get("warnings") or []),
            "artifacts": {
                "state_dir": status.get("config", {}).get("state_dir"),
                "memory_db": status.get("config", {}).get("memory_db"),
            },
        }

    def _action_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("mode") or "").strip().lower()
        if not mode:
            mode = "search" if str(payload.get("query") or "").strip() else "recent"
        if mode == "search":
            query = str(payload.get("query") or "").strip()
            if not query:
                raise ValueError("Missing query for memory search.")
            limit = int(payload.get("limit") or 5)
            stale_after_days = payload.get("stale_after_days")
            results = self._client.memory.search(query, limit=limit, stale_after_days=stale_after_days)
            return {
                "ok": True,
                "summary": f"Ghost found {len(results)} memory result(s).",
                "output": results,
                "details": {"mode": mode, "results": results},
                "sources": [item.get("source", "") for item in results if item.get("source")],
                "artifacts": {"count": len(results)},
            }
        if mode == "recent":
            limit = int(payload.get("limit") or 20)
            results = self._client.recent_memory_documents(limit=limit)
            return {
                "ok": True,
                "summary": f"Ghost returned {len(results)} recent memory document(s).",
                "output": results,
                "details": {"mode": mode, "results": results},
                "sources": [item.get("source", "") for item in results if item.get("source")],
                "artifacts": {"count": len(results)},
            }
        if mode == "ingest_document":
            source = str(payload.get("source") or "").strip()
            text = str(payload.get("text") or payload.get("content") or "").strip()
            if not source or not text:
                raise ValueError("ingest_document requires source and text.")
            result = self._client.ingest_document(source, text, metadata=payload.get("metadata"))
            return {
                "ok": True,
                "summary": f"Ghost ingested {result.ingested} document chunk(s).",
                "output": result.to_dict(),
                "details": {"mode": mode, "result": result.to_dict()},
                "sources": [source],
            }
        if mode == "ingest_file":
            path = Path(str(payload.get("path") or "")).expanduser()
            result = self._client.ingest_file(path)
            return {
                "ok": True,
                "summary": f"Ghost ingested file {path}.",
                "output": result.to_dict(),
                "details": {"mode": mode, "result": result.to_dict()},
                "sources": [str(path)],
            }
        if mode == "ingest_directory":
            path = Path(str(payload.get("path") or "")).expanduser()
            result = self._client.ingest_directory(path, max_files=int(payload.get("max_files") or 500))
            return {
                "ok": True,
                "summary": f"Ghost ingested directory {path}.",
                "output": result.to_dict(),
                "details": {"mode": mode, "result": result.to_dict()},
                "sources": [str(path)],
            }
        if mode == "ingest_email_file":
            path = Path(str(payload.get("path") or "")).expanduser()
            result = self._client.ingest_email_file(path)
            return {
                "ok": True,
                "summary": f"Ghost ingested email file {path}.",
                "output": result.to_dict(),
                "details": {"mode": mode, "result": result.to_dict()},
                "sources": [str(path)],
            }
        if mode == "ingest_raw_email":
            raw_text = str(payload.get("raw_text") or payload.get("text") or "").strip()
            if not raw_text:
                raise ValueError("ingest_raw_email requires raw_text.")
            result = self._client.ingest_raw_email(raw_text)
            return {
                "ok": True,
                "summary": f"Ghost ingested {result.ingested} raw email(s).",
                "output": result.to_dict(),
                "details": {"mode": mode, "result": result.to_dict()},
                "sources": ["raw_email"],
            }
        raise ValueError(f"Unsupported memory mode: {mode}")

    def _action_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        objective = str(payload.get("objective") or payload.get("query") or "").strip()
        if not objective:
            raise ValueError("Missing objective for action 'context'.")
        result = self._client.preview_context(objective, limit=int(payload.get("limit") or 5))
        return {
            "ok": bool(result.get("ok", True)),
            "summary": "Ghost prepared personal context preview.",
            "output": result,
            "details": result,
            "sources": list(result.get("sources") or []),
        }

    def _action_consent(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or payload.get("mode") or "status").strip().lower()
        if operation == "status":
            result = self._client.personal_minimind_status()
            return {"ok": True, "summary": "Ghost consent status retrieved.", "output": result, "details": result}
        if operation == "grant":
            result = self._client.enable_personal_minimind(
                admin_controls=bool(payload.get("admin_controls", True)),
                allow_system_specs=bool(payload.get("allow_system_specs", False)),
                allow_files=bool(payload.get("allow_files", False)),
                allow_email=bool(payload.get("allow_email", False)),
                allow_machine_crawl=bool(payload.get("allow_machine_crawl", False)),
                allow_email_crawl=bool(payload.get("allow_email_crawl", False)),
                allow_autonomy=bool(payload.get("allow_autonomy", False)),
                allow_training=bool(payload.get("allow_training", False)),
                file_paths=list(payload.get("file_paths") or []),
                email_paths=list(payload.get("email_paths") or []),
                crawl_roots=list(payload.get("crawl_roots") or []),
                exclude_paths=list(payload.get("exclude_paths") or []),
                operator=str(payload.get("operator") or "ghost-mcp"),
            )
            return {"ok": bool(result.get("ok")), "summary": "Ghost updated consent grants.", "output": result, "details": result}
        if operation == "revoke":
            result = self._client.revoke_personal_minimind()
            return {"ok": bool(result.get("ok")), "summary": "Ghost revoked personal consent.", "output": result, "details": result}
        raise ValueError(f"Unsupported consent operation: {operation}")

    def _action_bootstrap(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._client.bootstrap_personal_minimind(
            file_paths=list(payload.get("file_paths") or []),
            email_paths=list(payload.get("email_paths") or []),
            include_system_specs=bool(payload.get("include_system_specs", False)),
            max_files=int(payload.get("max_files") or 500),
            max_emails=int(payload.get("max_emails") or 1000),
        )
        return {
            "ok": bool(result.get("ok")),
            "summary": "Ghost completed Personal MiniMind bootstrap.",
            "output": result,
            "details": result,
            "sources": list(result.get("bootstrap", {}).get("sources") or []),
            "artifacts": {
                "dataset_path": result.get("bootstrap", {}).get("dataset_path") or result.get("dataset_path"),
            },
        }

    def _action_teach(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records")
        output_path = payload.get("output_path")
        if isinstance(records, list) and records:
            path = self._client.teach_many(records, output_path=output_path)
        else:
            prompt = str(payload.get("prompt") or "").strip()
            response = str(payload.get("response") or "").strip()
            if not prompt or not response:
                raise ValueError("teach requires either records or prompt/response.")
            path = self._client.teach(prompt, response, output_path=output_path)
        status = self._client.training_status()
        return {
            "ok": True,
            "summary": "Ghost appended training data.",
            "output": {"dataset_path": str(path), "dataset_count": status.get("dataset_count")},
            "details": status,
            "artifacts": {"dataset_path": str(path)},
        }

    def _action_train(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._client.train_personal_minimind(
            mode=str(payload.get("mode") or "local"),
            epochs=int(payload.get("epochs") or 12),
            learning_rate=float(payload.get("learning_rate") or 0.25),
            max_vocab=int(payload.get("max_vocab") or 512),
        )
        return {
            "ok": bool(result.get("ok")),
            "summary": f"Ghost completed {result.get('mode', 'local')} training flow.",
            "output": result,
            "details": result,
            "warnings": list(result.get("training", {}).get("status", {}).get("warnings") or []),
            "artifacts": {"status": result.get("status"), "training": result.get("training")},
        }

    def _action_trust(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or payload.get("mode") or "status").strip().lower()
        store = TrustRuntimeStore(self._state_dir)
        if operation == "status":
            result = store.trust_status()
        elif operation in {"approve", "revoke"}:
            server_id = str(payload.get("server_id") or "").strip()
            if not server_id:
                raise ValueError("trust approve/revoke requires server_id.")
            result = store.mcp_trust_set(
                server_id,
                "approved" if operation == "approve" else "revoked",
                risk_ceiling=str(payload.get("risk_ceiling") or "medium"),
                tools=list(payload.get("tools") or payload.get("tool") or []),
            )
        else:
            raise ValueError(f"Unsupported trust operation: {operation}")
        return {
            "ok": bool(result.get("ok", True)),
            "summary": "Ghost trust state retrieved." if operation == "status" else f"Ghost trust {operation} applied.",
            "output": result,
            "details": result,
            "warnings": list(result.get("warnings") or []),
        }

    def _action_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        objective = str(payload.get("objective") or "").strip()
        result = self._client.workspace(objective, limit=int(payload.get("limit") or 5))
        return {
            "ok": bool(result.get("ok", True)),
            "summary": "Ghost workspace state retrieved.",
            "output": result,
            "details": result,
            "sources": [item.get("source", "") for item in result.get("objective_context", []) if item.get("source")],
        }

    def _action_providers(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        result = self._client.providers()
        return {
            "ok": True,
            "summary": "Ghost provider configuration retrieved.",
            "output": result,
            "details": result,
            "provider": result.get("status", {}).get("provider", ""),
            "warnings": list(result.get("status", {}).get("errors") or []),
        }

    def _normalize_result(self, action: str, result: dict[str, Any]) -> dict[str, Any]:
        providers = self._client.providers()
        trust = self._client.trust_status()
        return self._envelope(
            ok=bool(result.get("ok")),
            action=action,
            status="ok" if result.get("ok") else "error",
            summary=str(result.get("summary") or ""),
            output=result.get("output"),
            details=result.get("details"),
            sources=list(result.get("sources") or []),
            backend=str(result.get("backend") or ""),
            provider=str(result.get("provider") or providers.get("status", {}).get("provider") or ""),
            trust_state={"ready": trust.get("ready"), "warnings": trust.get("warnings", [])},
            warnings=list(result.get("warnings") or []),
            next_actions=result.get("next_actions"),
            artifacts=result.get("artifacts"),
        )

    @staticmethod
    def _envelope(
        *,
        ok: bool,
        action: str,
        status: str,
        summary: str,
        output: Any = None,
        details: Any = None,
        sources: list[str] | None = None,
        backend: str = "",
        provider: str = "",
        trust_state: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        next_actions: list[str] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": ok,
            "action": action,
            "status": status,
            "summary": summary,
            "output": output,
            "details": details,
            "sources": sources or [],
            "backend": backend,
            "provider": provider,
            "trust_state": trust_state or {},
            "warnings": warnings or [],
            "next_actions": next_actions or [],
            "artifacts": artifacts or {},
        }


__all__ = ["GhostMCPAdapter"]
