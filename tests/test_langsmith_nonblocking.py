"""LangSmith tracing must not block the traced call (audit2 poweruser F22)."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ghostchimera.observability import langsmith_tracing as lt
from ghostchimera.observability.langsmith_tracing import LangSmithConfig, LangSmithTracer


def test_slow_langsmith_endpoint_adds_no_latency() -> None:
    hits: list[str] = []

    class Slow(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            time.sleep(1.5)
            hits.append(self.command)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = _handle  # noqa: N815
        do_PATCH = _handle  # noqa: N815

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        tracer = LangSmithTracer(LangSmithConfig(api_key="lsv2-test", endpoint=endpoint))
        started = time.perf_counter()
        run = tracer.start_run("x", inputs={"a": 1})
        tracer.end_run(run, outputs={"b": 2})
        assert time.perf_counter() - started < 0.3
        assert lt.flush_traces(10.0)
        # Create is sent before close (single FIFO sender).
        assert hits == ["POST", "PATCH"]
    finally:
        server.shutdown()
        server.server_close()
