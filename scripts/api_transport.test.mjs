// Behavioral tests for static/api_transport.js (node:test, no dependencies).
// Covers: overlapping GET dedupe, distinct POST intents never collapsing,
// sequential refetch, failure propagation + retry, per-request tokens,
// 401 handling, and HEAD dedupe.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = readFileSync(
  join(root, "ghostchimera/control_plane/static/api_transport.js"), "utf-8"
);

function loadTransport(stubs = {}) {
  const sandbox = { console };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return sandbox.GhostApiTransport.createApiTransport({
    fetchFn: stubs.fetchFn || (() => Promise.reject(new Error("no fetch stub"))),
    getToken: stubs.getToken || (() => ""),
    onUnauthorized: stubs.onUnauthorized || (() => {}),
  });
}

function jsonResponse(payload, { status = 200 } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => (name === "content-type" ? "application/json" : "") },
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  };
}

describe("api_transport", () => {
  it("exposes the factory on the global", () => {
    const sandbox = {};
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);
    assert.equal(typeof sandbox.GhostApiTransport.createApiTransport, "function");
  });

  it("dedupes overlapping identical GETs into one fetch", async () => {
    let calls = 0;
    const t = loadTransport({
      fetchFn: () => {
        calls += 1;
        return new Promise((resolve) => setTimeout(() => resolve(jsonResponse({ n: calls })), 20));
      },
    });
    const [a, b, c] = await Promise.all([t.request("/x"), t.request("/x"), t.request("/x")]);
    assert.equal(calls, 1);
    assert.deepEqual([a, b, c], [{ n: 1 }, { n: 1 }, { n: 1 }]);
  });

  it("dedupes HEAD requests too", async () => {
    let calls = 0;
    const t = loadTransport({
      fetchFn: () => {
        calls += 1;
        return Promise.resolve(jsonResponse({}));
      },
    });
    await Promise.all([
      t.request("/h", { method: "HEAD" }),
      t.request("/h", { method: "HEAD" }),
    ]);
    assert.equal(calls, 1);
  });

  it("never dedupes POST mutations, even identical ones", async () => {
    let calls = 0;
    const t = loadTransport({
      fetchFn: () => {
        calls += 1;
        return Promise.resolve(jsonResponse({ n: calls }));
      },
    });
    const [a, b] = await Promise.all([
      t.request("/chat", { method: "POST", body: { text: "hi" } }),
      t.request("/chat", { method: "POST", body: { text: "hi" } }),
    ]);
    assert.equal(calls, 2);
    assert.deepEqual([a.n, b.n].sort(), [1, 2]);
  });

  it("never dedupes PUT/DELETE either", async () => {
    let calls = 0;
    const t = loadTransport({
      fetchFn: () => {
        calls += 1;
        return Promise.resolve(jsonResponse({}));
      },
    });
    await Promise.all([
      t.request("/r", { method: "PUT", body: {} }),
      t.request("/r", { method: "PUT", body: {} }),
      t.request("/r", { method: "DELETE" }),
    ]);
    assert.equal(calls, 3);
  });

  it("refetches sequential GETs (no stale cache)", async () => {
    let calls = 0;
    const t = loadTransport({
      fetchFn: () => {
        calls += 1;
        return Promise.resolve(jsonResponse({ n: calls }));
      },
    });
    assert.deepEqual(await t.request("/v"), { n: 1 });
    assert.deepEqual(await t.request("/v"), { n: 2 });
    assert.equal(calls, 2);
  });

  it("does not mix different paths or bodies", async () => {
    const seen = [];
    const t = loadTransport({
      fetchFn: (path, opts) => {
        seen.push(`${path}|${opts.body || ""}`);
        return Promise.resolve(jsonResponse({}));
      },
    });
    await Promise.all([
      t.request("/a"),
      t.request("/b"),
      t.request("/a", { method: "POST", body: { x: 1 } }),
    ]);
    assert.equal(seen.length, 3);
  });

  it("propagates failures to all sharers and retries after", async () => {
    let calls = 0;
    const t = loadTransport({
      fetchFn: () => {
        calls += 1;
        if (calls === 1) return Promise.resolve(jsonResponse({ e: 1 }, { status: 500 }));
        return Promise.resolve(jsonResponse({ ok: true }));
      },
    });
    const results = await Promise.allSettled([t.request("/f"), t.request("/f")]);
    assert.equal(calls, 1);
    assert.ok(results.every((r) => r.status === "rejected"));
    assert.match(results[0].reason.message, /HTTP 500/);
    assert.deepEqual(await t.request("/f"), { ok: true });
    assert.equal(calls, 2);
  });

  it("isolates concurrent GETs across token changes", async () => {
    let calls = 0;
    let token = "A";
    const t = loadTransport({
      getToken: () => token,
      fetchFn: (_path, opts) => {
        calls += 1;
        const seen = opts.headers["X-Gateway-Token"];
        return new Promise((resolve) =>
          setTimeout(() => resolve(jsonResponse({ seen })), 20)
        );
      },
    });
    const pendingA = t.request("/t");
    token = "B";
    const pendingB = t.request("/t");
    const [a, b] = await Promise.all([pendingA, pendingB]);
    assert.equal(calls, 2);
    assert.deepEqual(a, { seen: "A" });
    assert.deepEqual(b, { seen: "B" });
  });

  it("sends the current token per request, not a cached one", async () => {
    let token = "first";
    const seen = [];
    const t = loadTransport({
      getToken: () => token,
      fetchFn: (_path, opts) => {
        seen.push(opts.headers["X-Gateway-Token"]);
        return Promise.resolve(jsonResponse({}));
      },
    });
    await t.request("/a");
    token = "second";
    await t.request("/b");
    assert.deepEqual(seen, ["first", "second"]);
  });

  it("stringifies object bodies and sets content type", async () => {
    let captured;
    const t = loadTransport({
      fetchFn: (_path, opts) => {
        captured = opts;
        return Promise.resolve(jsonResponse({}));
      },
    });
    await t.request("/p", { method: "POST", body: { a: 1 } });
    assert.equal(captured.body, '{"a":1}');
    assert.equal(captured.headers["Content-Type"], "application/json");
  });

  it("calls onUnauthorized on 401 without leaking the token", async () => {
    let unauthorized = 0;
    const t = loadTransport({
      getToken: () => "tok",
      onUnauthorized: () => {
        unauthorized += 1;
      },
      fetchFn: () =>
        Promise.resolve({
          status: 401,
          ok: false,
          headers: { get: () => "" },
          text: () => Promise.resolve("nope"),
        }),
    });
    await assert.rejects(t.request("/x"), /Unauthorized/);
    assert.equal(unauthorized, 1);
  });
});
