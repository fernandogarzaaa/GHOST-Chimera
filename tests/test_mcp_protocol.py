"""Tests for the real MCP JSON-RPC client (streamable HTTP + stdio transports)."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from ghostchimera.mcp import mcp_protocol
from ghostchimera.mcp.mcp_protocol import (
    McpClient,
    McpError,
    StdioTransport,
    StreamableHttpTransport,
)


def _http_response(body: bytes, content_type: str = "application/json", status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.headers = {"Content-Type": content_type}
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestStreamableHttpTransport(unittest.TestCase):
    def _transport(self):
        return StreamableHttpTransport(
            "https://mcp.tavily.com/mcp",
            headers={"Authorization": "Bearer tvly-test"},
            timeout=5.0,
        )

    def test_json_response(self):
        t = self._transport()
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        with patch.object(mcp_protocol, "urllib_request") as fake_urllib, patch(
            "ssl.create_default_context"
        ):
            fake_urllib.urlopen = MagicMock(
                return_value=_http_response(json.dumps(payload).encode())
            )
            fake_urllib.Request.side_effect = (
                lambda url, data=None, headers=None, method=None: (url, data, headers, method)
            )
            out = t.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(out, payload)
        (url,), kwargs = fake_urllib.Request.call_args
        self.assertEqual(url, "https://mcp.tavily.com/mcp")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tvly-test")
        self.assertIn("text/event-stream", kwargs["headers"]["Accept"])

    def test_sse_response_parsed(self):
        t = self._transport()
        sse = (
            b"event: message\n"
            b'data: {"jsonrpc":"2.0","id":3,"result":{"tools":[{"name":"tavily-search"}]}}\n\n'
        )
        with patch.object(mcp_protocol, "urllib_request") as fake_urllib, patch(
            "ssl.create_default_context"
        ):
            fake_urllib.urlopen = MagicMock(
                return_value=_http_response(sse, content_type="text/event-stream")
            )
            fake_urllib.Request.side_effect = (
                lambda url, data=None, headers=None, method=None: (url, data, headers, method)
            )
            out = t.request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        self.assertEqual(out["result"]["tools"][0]["name"], "tavily-search")

    def test_session_id_tracked(self):
        t = self._transport()
        resp = _http_response(b'{"jsonrpc":"2.0","id":1,"result":{}}')
        resp.headers = {"Content-Type": "application/json", "mcp-session-id": "sess-123"}
        with patch.object(mcp_protocol, "urllib_request") as fake_urllib, patch(
            "ssl.create_default_context"
        ):
            fake_urllib.urlopen = MagicMock(return_value=resp)
            fake_urllib.Request.side_effect = (
                lambda url, data=None, headers=None, method=None: (url, data, headers, method)
            )
            t.request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            t.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(t.session_id, "sess-123")
        (_,), kwargs = fake_urllib.Request.call_args
        self.assertEqual(kwargs["headers"]["mcp-session-id"], "sess-123")

    def test_http_error_raises_mcp_error(self):
        from urllib.error import HTTPError

        t = self._transport()
        err = HTTPError("https://mcp.tavily.com/mcp", 401, "Unauthorized", {}, io.BytesIO(b"bad key"))
        with patch.object(mcp_protocol, "urllib_request") as fake_urllib, patch(
            "ssl.create_default_context"
        ):
            fake_urllib.urlopen = MagicMock(side_effect=err)
            with self.assertRaises(McpError) as ctx:
                t.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn("401", str(ctx.exception))


class _FakeStdin:
    def __init__(self):
        self.written: list[str] = []
        self.closed = False

    def write(self, s: str) -> None:
        self.written.append(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _FakePopen:
    def __init__(self, stdout_lines):
        self.stdin = _FakeStdin()
        self.stdout = iter(stdout_lines)
        self.stderr = iter([])
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class TestStdioTransport(unittest.TestCase):
    def _popen_factory(self, lines):
        created = {}

        def factory(*args, **kwargs):
            proc = _FakePopen(lines)
            created["proc"] = proc
            return proc

        factory.created = created
        return factory

    def test_request_response_roundtrip(self):
        lines = ['{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}\n']
        factory = self._popen_factory(lines)
        t = StdioTransport(["npx", "-y", "tavily-mcp"], env={"TAVILY_API_KEY": "tvly-x"})
        with patch.object(mcp_protocol.subprocess, "Popen", factory):
            t.start()
            out = t.request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            t.close()
        self.assertEqual(out["result"]["protocolVersion"], "2024-11-05")
        proc = factory.created["proc"]
        sent = json.loads(proc.stdin.written[0])
        self.assertEqual(sent["method"], "initialize")
        self.assertTrue(proc.terminated)

    def test_skips_unmatched_lines(self):
        lines = [
            '{"jsonrpc":"2.0","method":"notifications/message","params":{}}\n',
            "some log chatter\n",
            '{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n',
        ]
        factory = self._popen_factory(lines)
        t = StdioTransport(["npx", "-y", "tavily-mcp"], timeout=5.0)
        with patch.object(mcp_protocol.subprocess, "Popen", factory):
            t.start()
            out = t.request({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
            t.close()
        self.assertEqual(out["result"], {"tools": []})

    def test_start_failure_raises(self):
        def boom(*args, **kwargs):
            raise FileNotFoundError("npx")

        t = StdioTransport(["npx", "-y", "tavily-mcp"])
        with patch.object(mcp_protocol.subprocess, "Popen", boom):
            with self.assertRaises(McpError):
                t.start()


class _FakeTransport:
    """Scripted transport: method name -> result dict."""

    def __init__(self, script):
        self.script = script
        self.sent: list[dict] = []

    def request(self, message):
        self.sent.append(message)
        method = message.get("method")
        if message.get("id") is None:
            return None
        result = self.script[method]
        if isinstance(result, Exception):
            raise result
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def close(self):
        pass


class TestMcpClient(unittest.TestCase):
    def _client(self, script):
        return McpClient(_FakeTransport(script))

    def test_initialize_handshake(self):
        c = self._client(
            {
                "initialize": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "tavily"}},
                "tools/list": {"tools": [{"name": "tavily-search"}]},
                "tools/call": {"content": [{"type": "text", "text": "{}"}]},
            }
        )
        info = c.initialize()
        self.assertEqual(info["serverInfo"]["name"], "tavily")
        methods = [m["method"] for m in c.transport.sent]
        self.assertEqual(methods[0], "initialize")
        self.assertEqual(methods[1], "notifications/initialized")
        tools = c.list_tools()
        self.assertEqual(tools[0]["name"], "tavily-search")
        out = c.call_tool("tavily-search", {"query": "x"})
        self.assertIn("content", out)
        call_msg = c.transport.sent[-1]
        self.assertEqual(call_msg["params"]["name"], "tavily-search")
        self.assertEqual(call_msg["params"]["arguments"], {"query": "x"})

    def test_protocol_error_raises(self):
        transport = _FakeTransport({})
        c = McpClient(transport)
        transport.script["initialize"] = McpError("boom")
        with self.assertRaises(McpError):
            c.initialize()

    def test_tool_is_error_raises(self):
        c = self._client(
            {"tools/call": {"content": [{"type": "text", "text": "nope"}], "isError": True}}
        )
        with self.assertRaises(McpError):
            c.call_tool("tavily-search", {"query": "x"})

    def test_jsonrpc_error_raises(self):
        class ErrTransport(_FakeTransport):
            def request(self, message):
                self.sent.append(message)
                return {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": "Method not found"},
                }

        c = McpClient(ErrTransport({}))
        with self.assertRaises(McpError) as ctx:
            c.list_tools()
        self.assertIn("Method not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
