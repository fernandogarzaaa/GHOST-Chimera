"""Tests for the Ghost Console knowledge-graph + consolidation endpoints."""

from __future__ import annotations

import json

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes


def _ctx(method, path, body=None, query=None):
    encoded = json.dumps(body) if body is not None else ""
    return {"method": method, "path": path, "headers": {}, "body": encoded, "query": query or {}}


def _server(tmp_path, monkeypatch) -> GatewayServer:
    monkeypatch.setenv("GHOSTCHIMERA_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("GHOSTCHIMERA_TEMPORAL_GRAPH_DB", str(tmp_path / "graph.sqlite3"))
    server = GatewayServer()
    register_console_routes(server)
    return server


def test_graph_and_consolidate_routes_registered(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    assert server.routes.find("GET", "/api/console/memory/graph") is not None
    assert server.routes.find("POST", "/api/console/memory/consolidate") is not None


def test_empty_graph_reports_zero_facts(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    route = server.routes.find("GET", "/api/console/memory/graph")
    payload = route.handler(_ctx("GET", "/api/console/memory/graph"))
    assert payload["ok"] is True
    assert payload["active_fact_count"] == 0
    assert payload["facts"] == []


def test_consolidation_promotes_and_graph_surfaces_fact(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)

    # Ingest an episodic memory carrying a structured triple.
    ingest = server.routes.find("POST", "/api/console/memory/ingest")
    ingest.handler(
        _ctx(
            "POST",
            "/api/console/memory/ingest",
            body={
                "source": "chat",
                "content": "user employer onboarding",
                "metadata": {
                    "subject": "user",
                    "predicate": "works_at",
                    "object": "Globex",
                    "access_count": 9,
                },
            },
        )
    )

    consolidate = server.routes.find("POST", "/api/console/memory/consolidate")
    result = consolidate.handler(
        _ctx("POST", "/api/console/memory/consolidate", body={"promotion_threshold": 0.3})
    )
    assert result["ok"] is True
    assert result["report"]["promoted"] == 1

    graph = server.routes.find("GET", "/api/console/memory/graph")
    payload = graph.handler(_ctx("GET", "/api/console/memory/graph"))
    assert payload["active_fact_count"] == 1
    assert payload["facts"][0]["subject"] == "user"
    assert payload["facts"][0]["object"] == "Globex"
