(function () {
  "use strict";
  var state = { profiles: [], workspace: null, token: "" };

  /**
 * Selects the first DOM element that matches a CSS selector.
 * @param {string} sel - A CSS selector string.
 * @returns {Element|null} The first matching Element, or `null` if no match is found.
 */
  function $(sel) { return document.querySelector(sel); }
  /**
 * Selects all DOM elements matching a CSS selector.
 * @param {string} sel - CSS selector string.
 * @returns {NodeListOf<Element>} A static NodeList of matching elements (empty if none).
 */
function $$$(sel) { return document.querySelectorAll(sel); }
  /**
   * Create an element, apply attributes, and optionally set its text content.
   * @param {string} tag - The tag name for the element (e.g., "div", "span").
   * @param {Object<string,string>} [attrs] - Map of attribute names to values to set on the element.
   * @param {string} [text] - Text to assign to the element's `textContent`.
   * @returns {HTMLElement} The created DOM element with the specified attributes and text.
   */
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function(k) { e.setAttribute(k, attrs[k]); });
    if (text !== undefined) e.textContent = text;
    return e;
  }
  /**
 * Escape HTML special characters in a value by replacing them with their corresponding HTML entities.
 * @param {*} s - The value to escape; it will be converted to a string.
 * @returns {string} The input converted to a string with `&`, `<`, `>`, `"` and `'` replaced by their HTML entities.
 */
function esc(s) { return String(s).replace(/[&<>"']/g, function(c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  /**
 * Replace the contents of the element matching the selector with a single <div class="empty"> showing a message.
 * @param {string} id - A DOM selector for the target element (e.g., "#container").
 * @param {string} msg - The message text to display inside the inserted empty placeholder.
 */
function empty(id, msg) { var d = $(id); d.innerHTML = ""; d.appendChild(el("div", { class: "empty" }, msg)); }

  // --- Token auth ---

  /**
   * Show the token overlay for authentication.
   */
  function showTokenOverlay() {
    var ov = $("#tokenOverlay");
    ov.style.display = "flex";
  }

  /**
   * Hide the token overlay.
   */
  function hideTokenOverlay() {
    var ov = $("#tokenOverlay");
    ov.style.display = "none";
  }

  $("#tokenSubmit").addEventListener("click", function() {
    var t = ($("#tokenInput").value || "").trim();
    if (!t) return;
    state.token = t;
    try { localStorage.setItem("ghostchimera_console_token", t); } catch (_) {}
    hideTokenOverlay();
    refreshStatus();
  });

  // Allow Enter key in token input
  $("#tokenInput").addEventListener("keydown", function(e) {
    if (e.key === "Enter") $("#tokenSubmit").click();
  });

  /**
   * Initialise auth: check if the server requires a token, and load any stored token.
   */
  async function initAuth() {
    try {
      var meta = await fetch("/api/console/token").then(function(r) { return r.json(); });
      if (meta && meta.auth_enabled) {
        var stored = "";
        try { stored = localStorage.getItem("ghostchimera_console_token") || ""; } catch (_) {}
        if (stored) {
          state.token = stored;
        } else {
          showTokenOverlay();
        }
      }
    } catch (_) {}
  }

  // --- Tabs ---
  $$$("#tabBar .tab").forEach(function(tab) {
    tab.addEventListener("click", function() {
      $$$(".tab").forEach(function(t) { t.classList.remove("active"); });
      $$$(".tab-content").forEach(function(c) { c.classList.remove("active"); });
      tab.classList.add("active");
      $("#tab-" + tab.dataset.tab).classList.add("active");
    });
  });

  /**
   * Send an HTTP request and return the parsed JSON response.
   * Includes the X-Gateway-Token header when a console auth token is configured.
   * @param {string} path - Request URL or path.
   * @param {RequestInit} [opts] - Fetch options.
   * @returns {any} The parsed JSON response body.
   */
  async function api(path, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    opts.headers["Content-Type"] = "application/json";
    if (state.token) opts.headers["X-Gateway-Token"] = state.token;
    if (opts.body && typeof opts.body === "object") opts.body = JSON.stringify(opts.body);
    var r = await fetch(path, opts);
    if (r.status === 401) {
      // Auth required — prompt for token
      state.token = "";
      try { localStorage.removeItem("ghostchimera_console_token"); } catch (_) {}
      showTokenOverlay();
      throw new Error("Unauthorized — enter the console token");
    }
    if (!r.ok) {
      var errText = await r.text().catch(function() { return ""; });
      throw new Error("HTTP " + r.status + ": " + errText);
    }
    var ct = r.headers.get("content-type") || "";
    if (ct.indexOf("application/json") !== -1) {
      try { return await r.json(); } catch (e) { return null; }
    }
    return await r.text().catch(function() { return null; });
  }
  /**
   * Update an element to display a badge with the given text and optional CSS classes.
   * @param {Element} el - The DOM element to convert into a badge.
   * @param {string} text - The text content to display inside the badge.
   * @param {string} [cls] - Optional additional class name(s) appended after `"badge"`.
   */
  function badge(el, text, cls) {
    el.textContent = text;
    el.className = "badge " + (cls || "");
  }

  /**
   * Refreshes console status and updates related UI panels.
   */
  async function refreshStatus() {
    try {
      var data = await api("/api/console/status");
      badge($("#health"), "online", "ok");
      state.profiles = data.profiles || [];

      var metrics = [
        ["Gateway", data.gateway.running ? "running" : "available"],
        ["Sessions", data.gateway.session_count],
        ["Backends", data.gateway.backends ? data.gateway.backends.length : "—"],
        ["Profile", data.autonomy.resolved_profile.name],
        ["Model", data.runtime.local_model.profile || "—"],
      ];
      var cards = $("#statusCards");
      cards.innerHTML = "";
      metrics.forEach(function(m) {
        var card = el("div", { class: "card" });
        var h3 = el("h3", null, m[0]);
        var v = el("div", { class: "value" }, String(m[1]));
        card.appendChild(h3);
        card.appendChild(v);
        cards.appendChild(card);
      });

      var sel = $("#autonomyLevel");
      sel.innerHTML = "";
      state.profiles.forEach(function(p) {
        var opt = el("option", { value: p.name });
        opt.textContent = p.name;
        if (p.name === data.autonomy.resolved_profile.name) opt.selected = true;
        sel.appendChild(opt);
      });
      $("#autonomyDesc").textContent = data.autonomy.resolved_profile.description || "";
      $("#trueAutonomyDesktop").checked = !!(data.autonomy.config && data.autonomy.config.true_autonomy_desktop);
      $("#personalContext").checked = !!(data.autonomy.config && data.autonomy.config.personal_context);

      var jSel = $("#jobProfile");
      jSel.innerHTML = "";
      state.profiles.forEach(function(p) {
        var opt = el("option", { value: p.name });
        opt.textContent = p.name;
        jSel.appendChild(opt);
      });
      if (jSel.children.length) jSel.value = data.autonomy.resolved_profile.name;

      await refreshJobs();
      await refreshSchedules();
      await refreshWorkspace();
      await refreshMemory();
      await refreshReadiness();
    } catch (e) {
      badge($("#health"), "offline", "error");
    }
  }

  // --- Autonomy ---
  $("#autonomyLevel").addEventListener("change", function() {
    var p = state.profiles.find(function(p) { return p.name === $("#autonomyLevel").value; });
    $("#autonomyDesc").textContent = p ? p.description : "";
  });
  $("#saveAutonomy").addEventListener("click", async function() {
    var r = await api("/api/console/autonomy", {
      method: "POST",
      body: {
        level: $("#autonomyLevel").value,
        true_autonomy_desktop: $("#trueAutonomyDesktop").checked,
        personal_context: $("#personalContext").checked,
      },
    });
    writeOutput(JSON.stringify(r, null, 2));
    await refreshStatus();
  });

  // --- Run ---

  /**
   * Render a human-readable summary banner for a run result.
   * Shows success/failure status and a brief per-execution breakdown above the raw JSON.
   * @param {Object} r - The run result object.
   */
  function renderRunSummary(r) {
    var summaryEl = $("#runSummary");
    summaryEl.innerHTML = "";
    summaryEl.style.display = "block";
    var overall = el("div", { class: "list-item" });
    var statusBadge = el("span", { class: "badge " + (r.ok ? "ok" : "error") }, r.ok ? "✓ Completed" : "✗ Failed");
    overall.appendChild(statusBadge);
    if (r.error) {
      overall.appendChild(el("span", { class: "meta" }, r.error));
    }
    summaryEl.appendChild(overall);
    if (Array.isArray(r.executions)) {
      r.executions.forEach(function(e) {
        var item = el("div", { class: "list-item" });
        var cls = e.ok ? "ok" : "error";
        item.appendChild(el("span", { class: "badge " + cls }, cls));
        item.appendChild(el("span", { class: "name" }, e.objective || e.kind || "task"));
        if (e.result !== undefined && e.result !== null) {
          item.appendChild(el("span", { class: "meta" }, String(e.result).slice(0, 120)));
        }
        if (e.error) item.appendChild(el("span", { class: "meta" }, "Error: " + e.error));
        summaryEl.appendChild(item);
      });
    }
  }

  $("#runObjective").addEventListener("click", async function() {
    var obj = $("#objective").value.trim();
    if (!obj) return writeOutput("Enter an objective first.");
    $("#runSummary").style.display = "none";
    writeOutput("Running…");
    try {
      var r = await api("/api/console/run", { method: "POST", body: { objective: obj } });
      renderRunSummary(r);
      writeOutput(JSON.stringify(r, null, 2));
    } catch (e) {
      writeOutput("Error: " + e.message);
    }
  });
  $("#clearOutput").addEventListener("click", function() {
    $("#runSummary").style.display = "none";
    writeOutput("Ready.");
  });

  /**
   * Load available autonomy jobs and render the job selector and recent job history in the UI.
   */
  async function refreshJobs() {
    var data = await api("/api/console/autonomy/jobs");
    var jSel = $("#jobName");
    jSel.innerHTML = "";
    (data.available_jobs || []).forEach(function(j) {
      var opt = el("option", { value: j.name });
      opt.textContent = j.name;
      jSel.appendChild(opt);
    });

    var history = $("#jobHistory");
    if (!Array.isArray(data.history) || !data.history.length) return empty("#jobHistory", "No autonomy jobs yet.");
    history.innerHTML = "";
    var items = data.history.slice().reverse().slice(0, 20);
    items.forEach(function(j) {
      var cls = j.status === "error" ? "error" : j.status === "preview" ? "warn" : "ok";
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, j.name));
      item.appendChild(el("span", { class: "badge " + cls }, j.status));
      item.appendChild(el("span", { class: "meta" }, j.profile + (j.execute ? " execute" : " preview")));
      item.appendChild(el("span", { class: "meta" }, new Date((j.requested_at || 0) * 1000).toLocaleString()));
      history.appendChild(item);
    });
  }
  $("#runJob").addEventListener("click", async function() {
    var r = await api("/api/console/autonomy/jobs", {
      method: "POST",
      body: {
        job: $("#jobName").value,
        profile: $("#jobProfile").value,
        execute: $("#jobExecute").checked,
        run_now: true,
      },
    });
    writeOutput(JSON.stringify(r, null, 2));
    await refreshJobs();
  });

  /**
   * Load the current workspace, update in-memory state, and render its summary in the UI.
   * Also renders the goals list from the self_model.
   */
  async function refreshWorkspace() {
    var data = await api("/api/console/workspace");
    state.workspace = data;
    var lines = [
      ["Identity", data.self_model && data.self_model.identity],
      ["Evidence", (data.working_memory && data.working_memory.evidence ? data.working_memory.evidence.length : 0)],
      ["Reflections", (data.working_memory && data.working_memory.reflections ? data.working_memory.reflections.length : 0)],
      ["Uncertainty", (data.uncertainty && data.uncertainty.score != null ? Number(data.uncertainty.score).toFixed(2) : "—")],
      ["Quality", (data.quality ? (data.quality.needs_review || 0) + " needs review" : "—")],
      ["Updated", data.updated_at || "—"],
    ];
    var wd = $("#workspaceDetail");
    wd.innerHTML = "";

    // Goals section
    var goals = (data.self_model && data.self_model.goals) ? data.self_model.goals : {};
    var goalKeys = Object.keys(goals);
    if (goalKeys.length) {
      var goalHdr = el("div", { class: "list-item" });
      goalHdr.appendChild(el("span", { class: "name" }, "Goals"));
      goalHdr.appendChild(el("span", { class: "badge ok" }, String(goalKeys.length)));
      wd.appendChild(goalHdr);
      goalKeys.forEach(function(k) {
        var item = el("div", { class: "list-item" }, null);
        item.style.paddingLeft = "24px";
        item.appendChild(el("span", { class: "name" }, k));
        item.appendChild(el("span", { class: "meta" }, goals[k]));
        wd.appendChild(item);
      });
    }

    lines.forEach(function(l) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, l[0]));
      item.appendChild(el("span", { class: "meta" }, String(l[1] || "—")));
      wd.appendChild(item);
    });
  }
  $("#setGoal").addEventListener("click", async function() {
    var name = $("#goalName").value.trim();
    var desc = $("#goalDescription").value.trim();
    if (!name || !desc) return;
    await api("/api/console/workspace/goals", {
      method: "POST",
      body: { name: name, description: desc },
    });
    $("#goalName").value = "";
    $("#goalDescription").value = "";
    await refreshWorkspace();
  });
  $("#addEvidence").addEventListener("click", async function() {
    await api("/api/console/workspace/evidence", {
      method: "POST",
      body: {
        source: $("#evidenceSource").value,
        content: $("#evidenceContent").value,
        confidence: parseFloat($("#evidenceConfidence").value) || 0.5,
      },
    });
    await refreshWorkspace();
    await refreshJobs();
  });
  $("#addReflection").addEventListener("click", async function() {
    await api("/api/console/workspace/reflections", {
      method: "POST",
      body: {
        action: $("#reflectionAction").value,
        outcome: $("#reflectionOutcome").value,
        confidence: parseFloat($("#reflectionConfidence").value) || 0.5,
      },
    });
    await refreshWorkspace();
    await refreshJobs();
  });
  $("#syncMemory").addEventListener("click", async function() {
    var r = await api("/api/console/workspace/sync-memory", {
      method: "POST",
      body: { min_confidence: 0.0, stale_after_days: 30 },
    });
    writeOutput(JSON.stringify(r, null, 2));
  });

  // --- Memory tab ---

  async function refreshMemory() {
    try {
      var st = await api("/api/console/memory/status");
      var ms = $("#memoryStatus");
      ms.innerHTML = "";
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, "Documents"));
      item.appendChild(el("span", { class: "badge ok" }, String(st.count || 0)));
      item.appendChild(el("span", { class: "meta" }, st.memory_db || ""));
      ms.appendChild(item);
    } catch (_) {
      empty("#memoryStatus", "Memory unavailable.");
    }
  }

  $("#memoryIngest").addEventListener("click", async function() {
    var source = ($("#memorySource").value || "").trim();
    var content = ($("#memoryContent").value || "").trim();
    if (!source || !content) return;
    var r = await api("/api/console/memory/ingest", { method: "POST", body: { source: source, content: content } });
    $("#memoryContent").value = "";
    $("#memoryOutput").textContent = JSON.stringify(r, null, 2);
    await refreshMemory();
  });

  $("#memorySearch").addEventListener("click", async function() {
    var q = ($("#memoryQuery").value || "").trim();
    if (!q) return;
    var r = await api("/api/console/memory/search", { method: "POST", body: { query: q, limit: 5 } });
    $("#memoryOutput").textContent = JSON.stringify(r, null, 2);
  });

  $("#minimindStatus").addEventListener("click", async function() {
    var r = await api("/api/console/minimind/status");
    $("#memoryOutput").textContent = JSON.stringify(r, null, 2);
  });

  $("#exportDataset").addEventListener("click", async function() {
    var raw = ($("#datasetRecords").value || "").trim();
    if (!raw) return;
    var records = null;
    try { records = JSON.parse(raw); } catch (e) { return $("#memoryOutput").textContent = "Invalid JSON: " + e.message; }
    var r = await api("/api/console/minimind/dataset", { method: "POST", body: { records: records } });
    $("#memoryOutput").textContent = JSON.stringify(r, null, 2);
  });

  // --- Browser tab ---

  /**
   * Refresh the browser workspace status badge and update the agent-browser detail.
   */
  async function refreshBrowserStatus() {
    try {
      var data = await api("/api/console/browser/status");
      var avail = data && data.available;
      badge($("#browserStatusBadge"), avail ? "available" : "unavailable", avail ? "ok" : "warn");
      $("#browserStatusDetail").textContent = (data && data.detail) ? data.detail : "";
    } catch (e) {
      badge($("#browserStatusBadge"), "error", "error");
    }
  }
  $("#browserFetch").addEventListener("click", async function() {
    var url = $("#browserFetchUrl").value.trim();
    if (!url) return;
    $("#browserOutput").textContent = "Fetching…";
    try {
      var r = await api("/api/console/browser/fetch", { method: "POST", body: { url: url } });
      if (r.ok) {
        var preview = (r.content || "").slice(0, 2000);
        $("#browserOutput").textContent = preview + (r.truncated ? "\n\n[truncated]" : "");
      } else {
        $("#browserOutput").textContent = "Error: " + (r.error || "unknown");
      }
    } catch (e) {
      $("#browserOutput").textContent = "Error: " + e.message;
    }
  });
  $("#browserOpen").addEventListener("click", async function() {
    var url = $("#browserOpenUrl").value.trim();
    if (!url) return;
    try {
      var r = await api("/api/console/browser/open", { method: "POST", body: { url: url } });
      $("#browserOutput").textContent = JSON.stringify(r, null, 2);
    } catch (e) {
      $("#browserOutput").textContent = "Error: " + e.message;
    }
  });
  $("#browserSnapshot").addEventListener("click", async function() {
    var url = $("#browserOpenUrl").value.trim();
    try {
      var r = await api("/api/console/browser/snapshot", { method: "POST", body: { url: url } });
      if (r.ok && r.output) {
        $("#browserOutput").textContent = r.output;
      } else {
        $("#browserOutput").textContent = JSON.stringify(r, null, 2);
      }
    } catch (e) {
      $("#browserOutput").textContent = "Error: " + e.message;
    }
  });

  // --- Security tab ---

  /**
   * Load security events, summary, and audit chain status from the backend and render them.
   */
  async function refreshSecurity() {
    try {
      var summary = await api("/api/console/security/summary");
      var s = summary.summary || {};
      var cards = $("#securityCards");
      cards.innerHTML = "";
      [
        ["Total Events", s.total_events != null ? s.total_events : "—"],
        ["Blocked", s.blocked_count != null ? s.blocked_count : "—"],
        ["Threats", s.threat_count != null ? s.threat_count : "—"],
        ["Avg Risk", s.avg_risk_score != null ? Number(s.avg_risk_score).toFixed(2) : "—"],
      ].forEach(function(m) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, String(m[1])));
        cards.appendChild(card);
      });
    } catch (_) {}

    try {
      var audit = await api("/api/console/security/audit");
      var auditEl = $("#auditStatus");
      auditEl.innerHTML = "";
      var item = el("div", { class: "list-item" });
      var integrityBadge = el("span", { class: "badge " + (audit.chain_integrity ? "ok" : "error") });
      integrityBadge.textContent = audit.chain_integrity ? "✓ Intact" : "✗ Broken";
      item.appendChild(integrityBadge);
      item.appendChild(el("span", { class: "meta" }, audit.integrity_message || ""));
      item.appendChild(el("span", { class: "meta" }, (audit.entry_count || 0) + " entries"));
      auditEl.appendChild(item);
    } catch (_) {}

    try {
      var events = await api("/api/console/security/events?limit=20");
      var evEl = $("#securityEvents");
      var evList = (events && events.events) || [];
      if (!evList.length) return empty("#securityEvents", "No security events recorded.");
      evEl.innerHTML = "";
      evList.forEach(function(ev) {
        var item = el("div", { class: "list-item" });
        var risk = Number(ev.risk_score || 0);
        var cls = ev.blocked ? "error" : risk > 0.6 ? "warn" : "";
        item.appendChild(el("span", { class: "badge " + cls }, ev.blocked ? "blocked" : "allowed"));
        item.appendChild(el("span", { class: "name" }, ev.category || ev.type || "event"));
        item.appendChild(el("span", { class: "meta" }, "risk " + risk.toFixed(2)));
        item.appendChild(el("span", { class: "meta" }, ev.session_id || ""));
        evEl.appendChild(item);
      });
    } catch (_) {
      empty("#securityEvents", "Security monitor unavailable.");
    }
  }
  $("#refreshSecurity").addEventListener("click", refreshSecurity);

  /**
   * Load the list of scheduled autonomy jobs from the backend and render them into the #scheduleList element.
   */
  async function refreshSchedules() {
    var data = await api("/api/console/autonomy/schedules");
    var list = $("#scheduleList");
    if (!Array.isArray(data.schedules) || !data.schedules.length) return empty("#scheduleList", "No schedules yet.");
    list.innerHTML = "";
    data.schedules.forEach(function(s) {
      var cls = s.enabled ? "ok" : "warn";
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, s.name));
      item.appendChild(el("span", { class: "badge " + cls }, s.enabled ? "enabled" : "disabled"));
      item.appendChild(el("span", { class: "meta" }, s.cron_expression));
      item.appendChild(el("span", { class: "meta" }, (s.metadata && s.metadata.autonomy_job) || ""));

      var actions = el("span", { class: "actions" });
      var actBtn = el("button", { class: s.enabled ? "danger" : "success" });
      actBtn.textContent = s.enabled ? "Disable" : "Enable";
      actBtn.addEventListener("click", function() { schedAction(s.id, s.enabled ? "disable" : "enable"); });
      actions.appendChild(actBtn);

      var delBtn = el("button", { class: "danger" });
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", function() { schedAction(s.id, "delete"); });
      actions.appendChild(delBtn);

      var runBtn = el("button");
      runBtn.textContent = "Run Now";
      runBtn.addEventListener("click", function() { schedAction(s.id, "run-now"); });
      actions.appendChild(runBtn);

      item.appendChild(actions);
      list.appendChild(item);
    });
  }

  /**
   * Execute a named action for a schedule on the server and refresh the schedules list.
   * @param {string|number} id - Identifier of the schedule to act on.
   * @param {string} action - Action to perform ("enable", "disable", "delete", or "run-now").
   */
  async function schedAction(id, action) {
    await api("/api/console/autonomy/schedules/" + id + "/" + action, { method: "POST" });
    await refreshSchedules();
  }
  window._sched = schedAction;

  $("#createSchedule").addEventListener("click", async function() {
    var jobSel = $("#scheduleJob");
    var jobName = jobSel.value || (jobSel.options[0] ? jobSel.options[0].value : "self-audit");
    var r = await api("/api/console/autonomy/schedules", {
      method: "POST",
      body: {
        name: $("#scheduleName").value,
        cron_expression: $("#scheduleCron").value,
        autonomy_job: jobName,
        profile: "supervised",
        execute: false,
        enabled: false,
      },
    });
    await refreshSchedules();
  });

  // Populate schedule job selector
  (async function() {
    var data = await api("/api/console/autonomy/jobs");
    var sel = $("#scheduleJob");
    (data.available_jobs || []).forEach(function(j) {
      var opt = el("option", { value: j.name });
      opt.textContent = j.name;
      sel.appendChild(opt);
    });
  })();

  /**
   * Loads readiness checks from the server and renders each check into the #readinessList element.
   */
  async function refreshReadiness() {
    var data = await api("/api/console/readiness");
    var list = $("#readinessList");
    list.innerHTML = "";
    (data.checks || []).forEach(function(c) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, c.name));
      var cmd = el("span", { class: "meta" });
      cmd.style.fontFamily = "monospace";
      cmd.style.fontSize = "12px";
      cmd.textContent = c.command;
      item.appendChild(cmd);
      list.appendChild(item);
    });
  }

  /**
 * Write text to the output pane.
 *
 * Replaces the contents of the <pre id="output"> element with the provided text.
 * @param {string} text - Text to display in the output pane.
 */
  function writeOutput(text) { $("pre#output").textContent = text; }
  $("#refresh").addEventListener("click", refreshStatus);

  // Initialise: check auth then load everything
  initAuth().then(function() {
    refreshStatus();
    refreshBrowserStatus();
    refreshSecurity();
  });
  setInterval(refreshStatus, 30000);
})();
