"""Tests for optional LangSmith tracing of the Nebius/Tavily integration paths.

All network traffic is mocked; no live LangSmith calls are made here.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from ghostchimera.observability import langsmith_tracing as lt
from ghostchimera.observability.langsmith_tracing import (
    LangSmithConfig,
    LangSmithTracer,
)


class FakeHttp:
    """Records Request objects and serves canned responses."""

    def __init__(self, fail=False):
        self.requests: list = []
        self.fail = fail

    def Request(self, url, data=None, headers=None, method=None):
        req = (url, data, headers, method)
        self.requests.append(req)
        return req

    def urlopen(self, req, timeout=None, context=None):
        if self.fail:
            raise URLError("tracing backend down")
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp


class TestConfig(unittest.TestCase):
    def test_no_key_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LANGSMITH_API_KEY", None)
            self.assertIsNone(LangSmithConfig.from_env())

    def test_key_enables_with_defaults(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "lsv2-test"}, clear=True):
            cfg = LangSmithConfig.from_env()
        self.assertIsNotNone(cfg)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.project, "ghost-chimera-hackathon")
        self.assertEqual(cfg.endpoint, "https://api.smith.langchain.com")

    def test_toggle_disables(self):
        for toggle in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_TRACING": toggle}, clear=True):
                cfg = LangSmithConfig.from_env()
            self.assertFalse(cfg.enabled, toggle)

    def test_project_and_endpoint_overrides(self):
        env = {
            "LANGSMITH_API_KEY": "k",
            "LANGSMITH_PROJECT": "my-project",
            "LANGSMITH_ENDPOINT": "https://smith.internal.example/",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = LangSmithConfig.from_env()
        self.assertEqual(cfg.project, "my-project")
        self.assertEqual(cfg.endpoint, "https://smith.internal.example")


class TestTracerTransport(unittest.TestCase):
    def _tracer(self, http):
        with patch.object(lt, "urllib_request", http):
            return http

    def test_disabled_is_total_noop(self):
        http = FakeHttp()
        tracer = LangSmithTracer(None)
        self.assertFalse(tracer.enabled)
        self.assertIsNone(tracer.start_run("x"))
        tracer.end_run({"id": "abc"}, outputs={"a": 1})
        with patch.object(lt, "urllib_request", http):
            pass
        self.assertEqual(http.requests, [])

    def test_start_run_posts_correct_payload(self):
        http = FakeHttp()
        tracer = LangSmithTracer(LangSmithConfig(api_key="lsv2-secret", project="demo-proj"))
        with patch.object(lt, "urllib_request", http):
            run = tracer.start_run(
                "nebius.chat_completion",
                run_type="llm",
                inputs={"model": "m"},
                metadata={"provider": "nebius"},
                tags=["t"],
            )
        self.assertIsNotNone(run)
        self.assertEqual(len(http.requests), 1)
        url, data, headers, method = http.requests[0]
        self.assertEqual(url, "https://api.smith.langchain.com/api/v1/runs")
        self.assertEqual(method, "POST")
        self.assertEqual(headers["x-api-key"], "lsv2-secret")
        body = json.loads(data.decode("utf-8"))
        self.assertEqual(body["name"], "nebius.chat_completion")
        self.assertEqual(body["run_type"], "llm")
        self.assertEqual(body["session_name"], "demo-proj")
        self.assertEqual(body["inputs"], {"model": "m"})
        self.assertEqual(body["id"], run["id"])
        # The API key must travel only in the header, never in the body.
        self.assertNotIn("lsv2-secret", data.decode("utf-8"))

    def test_end_run_patches_outputs(self):
        http = FakeHttp()
        tracer = LangSmithTracer(LangSmithConfig(api_key="k"))
        with patch.object(lt, "urllib_request", http):
            tracer.end_run({"id": "run-123", "name": "x"}, outputs={"response": "hi"})
        url, data, headers, method = http.requests[0]
        self.assertEqual(url, "https://api.smith.langchain.com/api/v1/runs/run-123")
        self.assertEqual(method, "PATCH")
        body = json.loads(data.decode("utf-8"))
        self.assertEqual(body["outputs"], {"response": "hi"})
        self.assertIn("end_time", body)

    def test_end_run_posts_error(self):
        http = FakeHttp()
        tracer = LangSmithTracer(LangSmithConfig(api_key="k"))
        with patch.object(lt, "urllib_request", http):
            tracer.end_run({"id": "run-9"}, error="ValueError: bad query")
        _, data, _, _ = http.requests[0]
        body = json.loads(data.decode("utf-8"))
        self.assertEqual(body["error"], "ValueError: bad query")

    def test_network_failure_is_swallowed(self):
        http = FakeHttp(fail=True)
        tracer = LangSmithTracer(LangSmithConfig(api_key="k"))
        with patch.object(lt, "urllib_request", http):
            run = tracer.start_run("x")  # must not raise
            tracer.end_run(run, outputs={})  # must not raise
        self.assertIsNotNone(run)

    def test_trace_context_manager_success(self):
        http = FakeHttp()
        tracer = LangSmithTracer(LangSmithConfig(api_key="k"))
        with patch.object(lt, "urllib_request", http), tracer.trace("op", run_type="tool") as run:
            self.assertIsNotNone(run)
        self.assertEqual(len(http.requests), 2)  # POST + PATCH
        self.assertEqual(http.requests[1][3], "PATCH")

    def test_trace_context_manager_error(self):
        http = FakeHttp()
        tracer = LangSmithTracer(LangSmithConfig(api_key="k"))
        with patch.object(lt, "urllib_request", http), self.assertRaises(RuntimeError), tracer.trace("op"):
            raise RuntimeError("caller blew up")
        _, data, _, _ = http.requests[1]
        body = json.loads(data.decode("utf-8"))
        self.assertIn("RuntimeError", body["error"])
        self.assertIn("caller blew up", body["error"])


def _fake_chat_response(text="traced reply"):
    resp = MagicMock()
    resp.status = 200
    resp.headers = {}
    resp.read.return_value = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestNebiusTracingHook(unittest.TestCase):
    def test_chat_traces_when_key_set(self):
        from ghostchimera.model_layer import openai_compatible_providers as ocp

        http = FakeHttp()
        env = {"NEBIUS_API_KEY": "nb-k", "LANGSMITH_API_KEY": "lsv2-trace"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(ocp, "urllib_request") as chat_http,
            patch("ssl.create_default_context"),
        ):
            chat_http.urlopen = MagicMock(return_value=_fake_chat_response())
            chat_http.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            p = ocp.NebiusProvider()
            result = p.chat("sys", "hello")
        self.assertEqual(result, "traced reply")
        # One run create + one run close for the chat completion.
        self.assertEqual(len(http.requests), 2)
        post_url, post_data, _, post_method = http.requests[0]
        self.assertTrue(post_url.endswith("/api/v1/runs"))
        body = json.loads(post_data.decode("utf-8"))
        self.assertEqual(body["name"], "nebius.chat_completion")
        self.assertEqual(body["inputs"]["model"], "nvidia/nemotron-3-nano-30b-a3b")
        self.assertEqual(body["inputs"]["user"], "hello")
        patch_url, patch_data, _, patch_method = http.requests[1]
        self.assertTrue(patch_url.endswith(f"/api/v1/runs/{body['id']}"))
        self.assertEqual(patch_method, "PATCH")
        self.assertEqual(json.loads(patch_data.decode("utf-8"))["outputs"]["response"], "traced reply")

    def test_chat_unchanged_without_langsmith_key(self):
        from ghostchimera.model_layer import openai_compatible_providers as ocp

        http = FakeHttp()
        with (
            patch.dict(os.environ, {"NEBIUS_API_KEY": "nb-k"}, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(ocp, "urllib_request") as chat_http,
            patch("ssl.create_default_context"),
        ):
            chat_http.urlopen = MagicMock(return_value=_fake_chat_response())
            chat_http.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            result = ocp.NebiusProvider().chat("sys", "hello")
        self.assertEqual(result, "traced reply")
        self.assertEqual(http.requests, [])

    def test_langsmith_toggle_off_skips_tracing(self):
        from ghostchimera.model_layer import openai_compatible_providers as ocp

        http = FakeHttp()
        env = {
            "NEBIUS_API_KEY": "nb-k",
            "LANGSMITH_API_KEY": "lsv2-trace",
            "LANGSMITH_TRACING": "0",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(ocp, "urllib_request") as chat_http,
            patch("ssl.create_default_context"),
        ):
            chat_http.urlopen = MagicMock(return_value=_fake_chat_response())
            chat_http.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            result = ocp.NebiusProvider().chat("sys", "hello")
        self.assertEqual(result, "traced reply")
        self.assertEqual(http.requests, [])

    def test_tracing_outage_does_not_break_chat(self):
        from ghostchimera.model_layer import openai_compatible_providers as ocp

        http = FakeHttp(fail=True)
        env = {"NEBIUS_API_KEY": "nb-k", "LANGSMITH_API_KEY": "lsv2-trace"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(ocp, "urllib_request") as chat_http,
            patch("ssl.create_default_context"),
        ):
            chat_http.urlopen = MagicMock(return_value=_fake_chat_response())
            chat_http.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            result = ocp.NebiusProvider().chat("sys", "hello")
        self.assertEqual(result, "traced reply")


class TestTavilyTracingHook(unittest.TestCase):
    def _rest_grounding(self):
        from ghostchimera.stealth import tavily_grounding as tg

        return tg

    def test_search_traces_when_key_set(self):
        tg = self._rest_grounding()
        http = FakeHttp()
        env = {"TAVILY_API_KEY": "tvly-k", "LANGSMITH_API_KEY": "lsv2-trace"}
        payload = {"results": [{"title": "R", "url": "u", "content": "c"}]}
        resp = MagicMock()
        resp.status = 200
        resp.headers = {}
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(tg, "urllib_request") as rest_http,
            patch("ssl.create_default_context"),
        ):
            rest_http.urlopen = MagicMock(return_value=resp)
            rest_http.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            g = tg.TavilyGrounding(mode="rest")
            results = g.search("nemotron 3")
        self.assertEqual(results[0]["title"], "R")
        self.assertEqual(len(http.requests), 2)
        body = json.loads(http.requests[0][1].decode("utf-8"))
        self.assertEqual(body["name"], "tavily.search")
        self.assertEqual(body["run_type"], "tool")
        self.assertEqual(body["inputs"]["query"], "nemotron 3")
        close = json.loads(http.requests[1][1].decode("utf-8"))
        self.assertEqual(close["outputs"]["result_count"], 1)
        self.assertEqual(close["outputs"]["transport"], "rest")

    def test_search_without_langsmith_key_makes_no_trace_calls(self):
        tg = self._rest_grounding()
        http = FakeHttp()
        payload = {"results": [{"title": "R", "url": "u", "content": "c"}]}
        resp = MagicMock()
        resp.status = 200
        resp.headers = {}
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with (
            patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-k"}, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(tg, "urllib_request") as rest_http,
            patch("ssl.create_default_context"),
        ):
            rest_http.urlopen = MagicMock(return_value=resp)
            rest_http.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            results = tg.TavilyGrounding(mode="rest").search("q")
        self.assertEqual(results[0]["title"], "R")
        self.assertEqual(http.requests, [])

    def test_extract_traces_when_key_set(self):
        tg = self._rest_grounding()
        http = FakeHttp()
        env = {"TAVILY_API_KEY": "tvly-k", "LANGSMITH_API_KEY": "lsv2-trace"}
        payload = {"results": [{"url": "https://e.com", "raw_content": "text"}]}
        resp = MagicMock()
        resp.status = 200
        resp.headers = {}
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(lt, "urllib_request", http),
            patch.object(tg, "urllib_request") as rest_http,
            patch("ssl.create_default_context"),
        ):
            rest_http.urlopen = MagicMock(return_value=resp)
            results = tg.TavilyGrounding(mode="rest").extract(["https://e.com"])
        self.assertEqual(results[0]["content"], "text")
        body = json.loads(http.requests[0][1].decode("utf-8"))
        self.assertEqual(body["name"], "tavily.extract")

    def test_search_error_is_traced(self):
        tg = self._rest_grounding()
        http = FakeHttp()
        env = {"TAVILY_API_KEY": "tvly-k", "LANGSMITH_API_KEY": "lsv2-trace"}
        with patch.dict(os.environ, env, clear=True), patch.object(lt, "urllib_request", http):
            g = tg.TavilyGrounding(mode="rest")
            with self.assertRaises(tg.TavilyError):
                g.search("   ")
        self.assertEqual(len(http.requests), 2)
        body = json.loads(http.requests[1][1].decode("utf-8"))
        self.assertIn("TavilyError", body["error"])


if __name__ == "__main__":
    unittest.main()
