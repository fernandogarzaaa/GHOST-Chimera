"""Every outbound HTTP request carries ``User-Agent: GHOST-Chimera/<version>``.

Groq (and some CDNs) answer HTTP 403 when the header is missing, so this is
a correctness requirement, not cosmetics.
"""

from __future__ import annotations

import ast
import io
import json
import pathlib
import tempfile
import urllib.request
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import ghostchimera
from ghostchimera.http_identity import USER_AGENT, ensure_user_agent, with_user_agent

PACKAGE_ROOT = pathlib.Path(ghostchimera.__file__).parent


def test_user_agent_names_package_and_version() -> None:
    expected = f"GHOST-Chimera/{ghostchimera.__version__}"
    assert expected == USER_AGENT


def test_ensure_user_agent_wraps_url_strings() -> None:
    req = ensure_user_agent("https://example.com/x")
    assert isinstance(req, urllib.request.Request)
    assert req.get_header("User-agent") == USER_AGENT


def test_ensure_user_agent_keeps_an_explicit_agent() -> None:
    req = urllib.request.Request("https://example.com", headers={"User-Agent": "Mozilla/5.0 custom"})
    assert ensure_user_agent(req).get_header("User-agent") == "Mozilla/5.0 custom"


def test_with_user_agent_is_case_insensitive_and_copies() -> None:
    original = {"user-agent": "x"}
    assert with_user_agent(original) == {"user-agent": "x"}
    added = with_user_agent({"Accept": "a"})
    assert added["User-Agent"] == USER_AGENT
    assert with_user_agent(None) == {"User-Agent": USER_AGENT}


class _FakeResponse(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_openai_compatible_provider_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Groq 403 regression: the chat request must carry the header."""
    from ghostchimera.model_layer.openai_compatible_providers import GroqProvider

    seen: list[urllib.request.Request] = []

    def fake_urlopen(req, *args, **kwargs):
        seen.append(req)
        body = {"choices": [{"message": {"content": "pong"}}]}
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert GroqProvider().chat("sys", "ping") == "pong"
    assert seen and seen[0].get_header("User-agent") == USER_AGENT


def test_ssrf_dispatcher_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.safety_layer import ssrf

    seen: list[urllib.request.Request] = []

    class _Opener:
        def open(self, req, timeout=None):
            seen.append(req)
            return _FakeResponse(b"ok")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _Opener())
    dispatcher = ssrf.NetworkDispatcher(ssrf.SSRFPolicy())
    monkeypatch.setattr(dispatcher.policy, "is_permitted", lambda url: (True, ""))
    result = dispatcher.fetch("https://example.com/")
    assert result.status_code == 200
    assert seen[0].get_header("User-agent") == USER_AGENT


def _urlopen_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "urlopen":
            yield node


def test_every_urlopen_in_the_package_goes_through_ensure_user_agent() -> None:
    """Static guard so a new HTTP call site cannot silently drop the header."""
    offenders: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _urlopen_calls(tree):
            first = call.args[0] if call.args else None
            ok = (
                isinstance(first, ast.Call)
                and isinstance(first.func, ast.Name)
                and first.func.id == "ensure_user_agent"
            )
            if not ok:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{call.lineno}")
    assert offenders == [], f"urlopen() without ensure_user_agent(): {offenders}"


def test_shared_ssl_context_is_a_singleton() -> None:
    """The process-wide TLS context is created once and reused."""
    from ghostchimera.http_identity import shared_ssl_context

    assert shared_ssl_context() is shared_ssl_context()


def test_background_thread_modules_never_create_ssl_contexts_directly() -> None:
    """Static guard against the SIGSEGV race.

    ssl.create_default_context() loads the CA bundle through OpenSSL, which
    segfaults when called concurrently from background threads (seen on
    Python 3.13 in CI). Modules that do HTTPS from worker threads must use
    shared_ssl_context() instead.
    """
    offenders: list[str] = []
    for rel in ("observability/langsmith_tracing.py", "model_layer/free_tier_monitor.py"):
        path = PACKAGE_ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_default_context"
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], f"direct ssl.create_default_context() in worker-thread module: {offenders}"


def test_shared_ssl_context_survives_concurrent_use() -> None:
    """Many threads sharing one context for real TLS handshakes: no crash, no re-creation."""
    import socket
    import ssl
    import threading

    # Self-signed cert for a localhost TLS server, generated in-process
    # (no openssl CLI dependency; Windows runners lack it).
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from ghostchimera.http_identity import shared_ssl_context

    def _self_signed_cert() -> tuple[bytes, bytes]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(days=1))
            .not_valid_after(datetime.now(UTC) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        return key_pem, cert_pem

    key_pem, cert_pem = _self_signed_cert()
    key_file = pathlib.Path(tempfile.gettempdir()) / "test-shared-ctx-key.pem"
    cert_file = pathlib.Path(tempfile.gettempdir()) / "test-shared-ctx-cert.pem"
    key_file.write_bytes(key_pem)
    cert_file.write_bytes(cert_pem)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(cert_file), str(key_file))
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(32)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        srv.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            try:
                tls = server_ctx.wrap_socket(conn, server_side=True)
                tls.sendall(b"ok")
                tls.close()
            except Exception:
                pass

    threading.Thread(target=serve, daemon=True).start()
    try:
        ctx = shared_ssl_context()
        ctx.load_verify_locations(cafile=str(cert_file))
        creations: list[int] = []
        orig = ssl.create_default_context

        def counting(*a: object, **k: object) -> ssl.SSLContext:
            creations.append(1)
            return orig(*a, **k)

        errors: list[str] = []

        def worker(n: int) -> None:
            try:
                for _ in range(10):
                    c = shared_ssl_context()
                    assert c is ctx
                    s = socket.create_connection(("127.0.0.1", port), timeout=10)
                    tls = c.wrap_socket(s, server_hostname="localhost")
                    assert tls.recv(2) == b"ok"
                    tls.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"thread {n}: {exc!r}")

        with patch("ssl.create_default_context", side_effect=counting):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert not errors, errors[:3]
        assert creations == [], "worker threads created SSL contexts"
    finally:
        stop.set()
        srv.close()
