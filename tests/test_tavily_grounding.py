"""Tests for Tavily web grounding (MCP-first, REST fallback)."""

from __future__ import annotations

import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ghostchimera.stealth import tavily_grounding as tg
from ghostchimera.stealth.tavily_grounding import TavilyError, TavilyGrounding


def _rest_response(payload: dict):
    resp = MagicMock()
    resp.status = 200
    resp.headers = {"Content-Type": "application/json"}
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _mcp_search_result(hits):
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"results": hits}),
            }
        ]
    }


class FakeMcpClient:
    """Stands in for McpClient; records tool calls."""

    def __init__(self, search_hits=(), extract_items=()):
        self.search_hits = list(search_hits)
        self.extract_items = list(extract_items)
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def initialize(self):
        return {"serverInfo": {"name": "tavily"}}

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "tavily-search":
            return _mcp_search_result(self.search_hits)
        if name == "tavily-extract":
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"results": self.extract_items})}
                ]
            }
        raise AssertionError(f"unexpected tool {name}")

    def close(self):
        self.closed = True


def _event(payload=None, event_type="user.message"):
    return SimpleNamespace(
        event_type=event_type, source="test", payload=dict(payload or {}),
        privacy_classification="internal",
    )


class TestAvailability(unittest.TestCase):
    def test_no_key_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TAVILY_API_KEY", None)
            g = TavilyGrounding()
        self.assertFalse(g.available)
        with self.assertRaises(TavilyError):
            g.search("anything")
        self.assertIsNone(g.ground_event(_event({"ground_with_web": True})))

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            TavilyGrounding(api_key="tvly-x", mode="smoke-signals")


class TestRestFallback(unittest.TestCase):
    def test_rest_search_posts_correctly(self):
        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        payload = {
            "results": [
                {"title": "T", "url": "https://example.com", "content": "snippet here", "score": 0.9}
            ]
        }
        with patch.object(tg, "urllib_request") as fake_urllib, patch("ssl.create_default_context"):
            fake_urllib.urlopen = MagicMock(return_value=_rest_response(payload))
            fake_urllib.Request.side_effect = (
                lambda url, data=None, headers=None, method=None: (url, data, headers, method)
            )
            out = g.search("nemotron 3 release", max_results=3)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "T")
        self.assertEqual(out[0]["url"], "https://example.com")
        self.assertEqual(out[0]["snippet"], "snippet here")
        self.assertEqual(out[0]["score"], 0.9)
        self.assertEqual(g._last_transport, "rest")
        (url,), kwargs = fake_urllib.Request.call_args
        self.assertEqual(url, "https://api.tavily.com/search")
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tvly-test")
        body = json.loads(kwargs["data"].decode("utf-8"))
        self.assertEqual(body["api_key"], "tvly-test")
        self.assertEqual(body["query"], "nemotron 3 release")
        self.assertEqual(body["max_results"], 3)

    def test_rest_extract(self):
        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        payload = {"results": [{"url": "https://example.com", "raw_content": "page text"}]}
        with patch.object(tg, "urllib_request") as fake_urllib, patch("ssl.create_default_context"):
            fake_urllib.urlopen = MagicMock(return_value=_rest_response(payload))
            out = g.extract(["https://example.com"], query="q")
        self.assertEqual(out[0]["url"], "https://example.com")
        self.assertEqual(out[0]["content"], "page text")

    def test_rest_http_error_raises(self):
        from urllib.error import HTTPError

        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        err = HTTPError("https://api.tavily.com/search", 401, "Unauthorized", {}, io.BytesIO(b""))
        with patch.object(tg, "urllib_request") as fake_urllib, patch("ssl.create_default_context"):
            fake_urllib.urlopen = MagicMock(side_effect=err)
            with self.assertRaises(TavilyError):
                g.search("x")


class TestMcpPath(unittest.TestCase):
    def test_remote_mcp_search(self):
        g = TavilyGrounding(api_key="tvly-test", mode="remote")
        fake = FakeMcpClient(
            search_hits=[{"title": "Hit", "url": "https://t.co", "content": "body", "score": 0.8}]
        )
        g._remote = fake
        out = g.search("query here")
        self.assertEqual(out[0]["title"], "Hit")
        self.assertEqual(out[0]["snippet"], "body")
        self.assertEqual(g._last_transport, "mcp-remote")
        name, args = fake.calls[0]
        self.assertEqual(name, "tavily-search")
        self.assertEqual(args["query"], "query here")
        self.assertEqual(args["max_results"], 5)

    def test_mcp_extract(self):
        g = TavilyGrounding(api_key="tvly-test", mode="remote")
        fake = FakeMcpClient(
            extract_items=[{"url": "https://t.co", "raw_content": "full page"}]
        )
        g._remote = fake
        out = g.extract(["https://t.co"])
        self.assertEqual(out[0]["content"], "full page")
        name, _ = fake.calls[0]
        self.assertEqual(name, "tavily-extract")

    def test_auto_falls_back_to_rest(self):
        from ghostchimera.mcp.mcp_protocol import McpError

        g = TavilyGrounding(api_key="tvly-test", mode="auto")
        with patch.object(
            TavilyGrounding, "_remote_client", side_effect=McpError("remote down")
        ), patch.object(
            TavilyGrounding, "_local_client", side_effect=McpError("no npx")
        ), patch.object(tg, "urllib_request") as fake_urllib, patch(
            "ssl.create_default_context"
        ):
            fake_urllib.urlopen = MagicMock(
                return_value=_rest_response({"results": [{"title": "R", "url": "u", "content": "c"}]})
            )
            out = g.search("fallback query")
        self.assertEqual(out[0]["title"], "R")
        self.assertEqual(g._last_transport, "rest")

    def test_empty_query_rejected(self):
        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        with self.assertRaises(TavilyError):
            g.search("   ")


class TestGroundEvent(unittest.TestCase):
    def test_opt_in_event_grounds(self):
        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        with patch.object(tg, "urllib_request") as fake_urllib, patch("ssl.create_default_context"):
            fake_urllib.urlopen = MagicMock(
                return_value=_rest_response({"results": [{"title": "R", "url": "u", "content": "c"}]})
            )
            out = g.ground_event(
                _event({"ground_with_web": True, "web_query": "nemotron 3 benchmarks"})
            )
        self.assertIsNotNone(out)
        self.assertEqual(out["query"], "nemotron 3 benchmarks")
        self.assertEqual(out["tool"], "tavily-search")
        self.assertEqual(out["transport"], "rest")

    def test_research_event_type_grounds_without_flag(self):
        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        with patch.object(tg, "urllib_request") as fake_urllib, patch("ssl.create_default_context"):
            fake_urllib.urlopen = MagicMock(return_value=_rest_response({"results": []}))
            out = g.ground_event(_event({"summary": "latest llm news"}, event_type="news_digest"))
        self.assertIsNotNone(out)
        self.assertIn("news_digest", out["query"])

    def test_ordinary_event_does_not_ground(self):
        g = TavilyGrounding(api_key="tvly-test", mode="rest")
        with patch.object(tg, "urllib_request") as fake_urllib:
            out = g.ground_event(_event({"summary": "file saved"}))
        self.assertIsNone(out)
        fake_urllib.urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
