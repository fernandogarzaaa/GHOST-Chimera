/* Ghost Console API transport: request orchestration for api().
 *
 * Plain script (no modules): loaded before app.js, exposes
 * `GhostApiTransport.createApiTransport`. Under node, load via `vm` and
 * call the factory directly — see scripts/api_transport.test.mjs.
 *
 * Contract:
 * - In-flight dedupe applies ONLY to idempotent GET/HEAD requests.
 *   Mutations always reach the server; collapsing identical POSTs would
 *   silently discard legitimate user intent.
 * - Stale rendering is impossible by construction for identical requests:
 *   concurrent callers share one promise, so there is no older response
 *   left to overwrite newer state. Sequential requests always refetch.
 *   Always a valid payload or a thrown error — never a fake ok.
 */
(function (root) {
  "use strict";

  function createApiTransport(deps) {
    var fetchFn = deps.fetchFn;
    var getToken = deps.getToken || function () { return ""; };
    var onUnauthorized = deps.onUnauthorized || function () {};
    var apiInflight = {};

    function apiCacheKey(method, path, bodyText) {
      return method + " " + path + " " + (bodyText || "");
    }

    function apiIsIdempotent(method) {
      return method === "GET" || method === "HEAD";
    }

    function apiFetchOnce(path, opts) {
      return fetchFn(path, opts).then(function (r) {
        if (r.status === 401) {
          onUnauthorized();
          throw new Error("Unauthorized — enter the console token");
        }
        if (!r.ok) {
          return r.text().catch(function () { return ""; }).then(function (errText) {
            throw new Error("HTTP " + r.status + ": " + errText);
          });
        }
        var ct = r.headers.get("content-type") || "";
        if (ct.indexOf("application/json") !== -1) {
          return r.json().catch(function () { return null; });
        }
        return r.text().catch(function () { return null; });
      });
    }

    function apiFetch(path, opts) {
      var method = (opts.method || "GET").toUpperCase();
      if (!apiIsIdempotent(method)) return apiFetchOnce(path, opts);
      // The auth generation is part of the key: a request issued under
      // token A must never satisfy (or 401-poison) a caller on token B.
      var key = apiCacheKey(method, path, typeof opts.body === "string" ? opts.body : "")
        + "\x00" + getToken();
      var pending = apiInflight[key];
      if (pending) return pending;
      pending = apiFetchOnce(path, opts);
      apiInflight[key] = pending;
      var cleanup = function () { if (apiInflight[key] === pending) delete apiInflight[key]; };
      pending.then(cleanup, cleanup);
      return pending;
    }

    function request(path, opts) {
      opts = opts || {};
      if (!opts.headers) opts.headers = {};
      opts.headers["Content-Type"] = "application/json";
      var token = getToken();
      if (token) opts.headers["X-Gateway-Token"] = token;
      if (opts.body && typeof opts.body === "object") opts.body = JSON.stringify(opts.body);
      return apiFetch(path, opts);
    }

    return {
      request: request,
      apiFetch: apiFetch,
      apiIsIdempotent: apiIsIdempotent,
      apiCacheKey: apiCacheKey,
    };
  }

  root.GhostApiTransport = { createApiTransport: createApiTransport };
})(typeof window !== "undefined" ? window : globalThis);
