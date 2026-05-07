(function () {
  "use strict";
  var state = { profiles: [], workspace: null };

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

  // --- Tabs ---
  $$$("#tabBar .tab").forEach(function(tab) {
    tab.addEventListener("click", function() {
      $$$("#.tab").forEach(function(t) { t.classList.remove("active"); });
      $$$(".tab-content").forEach(function(c) { c.classList.remove("active"); });
      tab.classList.add("active");
      $("#" + tab.dataset.tab).classList.add("active");
    });
  });

  /**
   * Send an HTTP request and return the parsed JSON response.
   *
   * Ensures the request has a Content-Type of "application/json" and, if `opts.body` is a plain object, JSON-stringifies it before delegating to fetch.
   * @param {string} path - Request URL or path.
   * @param {RequestInit} [opts] - Fetch options; `headers` may be provided and `body` may be an object (will be JSON-stringified).
   * @returns {any} The parsed JSON response body.
   */
  async function api(path, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    opts.headers["Content-Type"] = "application/json";
    if (opts.body && typeof opts.body === "object") opts.body = JSON.stringify(opts.body);
    var r = await fetch(path, opts);
    return r.json();
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
   *
   * Fetches the current console status, updates the health badge, stores returned profiles in application state, renders the status metric cards, populates the autonomy level and job profile selectors and description, and then refreshes jobs, schedules, workspace, and readiness views. On failure, marks the health badge as offline.
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
    var r = await api("/api/console/autonomy", { method: "POST", body: { level: $("#autonomyLevel").value } });
    writeOutput(JSON.stringify(r, null, 2));
    await refreshStatus();
  });

  // --- Run ---
  $("#runObjective").addEventListener("click", async function() {
    var obj = $("#objective").value.trim();
    if (!obj) return writeOutput("Enter an objective first.");
    writeOutput("Running...");
    var r = await api("/api/console/run", { method: "POST", body: { objective: obj } });
    writeOutput(JSON.stringify(r, null, 2));
  });
  $("#clearOutput").addEventListener("click", function() { writeOutput("Ready."); });

  /**
   * Load available autonomy jobs and render the job selector and recent job history in the UI.
   *
   * Fetches job data from the autonomy jobs API, populates the #jobName select with available jobs,
   * and renders up to the 20 most recent history entries (most recent first) into #jobHistory.
   * If there is no history, replaces #jobHistory with a placeholder message "No autonomy jobs yet."
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
    if (!data.history.length) return empty("#jobHistory", "No autonomy jobs yet.");
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
   *
   * Fetches workspace data from "/api/console/workspace", assigns the response to `state.workspace`,
   * and replaces the contents of the `#workspaceDetail` element with rows for:
   * identity, evidence count, reflections count, uncertainty score, quality (needs review count),
   * and last-updated time.
   *
   * Uncertainty is shown with two decimal places when available; counts default to 0 and missing
   * values render as "—".
   */
  async function refreshWorkspace() {
    var data = await api("/api/console/workspace");
    state.workspace = data;
    var lines = [
      ["Identity", data.self_model && data.self_model.identity],
      ["Evidence", (data.working_memory && data.working_memory.evidence ? data.working_memory.evidence.length : 0)],
      ["Reflections", (data.working_memory && data.working_memory.reflections ? data.working_memory.reflections.length : 0)],
      ["Uncertainty", (data.uncertainty && data.uncertainty.score ? Number(data.uncertainty.score).toFixed(2) : "—")],
      ["Quality", (data.quality ? (data.quality.needs_review || 0) + " needs review" : "—")],
      ["Updated", data.updated_at || "—"],
    ];
    var wd = $("#workspaceDetail");
    wd.innerHTML = "";
    lines.forEach(function(l) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, l[0]));
      item.appendChild(el("span", { class: "meta" }, String(l[1] || "—")));
      wd.appendChild(item);
    });
  }
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

  /**
   * Load the list of scheduled autonomy jobs from the backend and render them into the #scheduleList element.
   *
   * If no schedules are returned, replaces the list with a placeholder message "No schedules yet." For each schedule,
   * creates a list item showing name, enabled state, cron expression, optional metadata, and action buttons for
   * enable/disable, delete, and run-now.
   */
  async function refreshSchedules() {
    var data = await api("/api/console/autonomy/schedules");
    var list = $("#scheduleList");
    if (!data.schedules.length) return empty("#scheduleList", "No schedules yet.");
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
      runBtn.addEventListener("click", function() { schedAction(s.id, "run"); });
      actions.appendChild(runBtn);

      item.appendChild(actions);
      list.appendChild(item);
    });
  }

  /**
   * Execute a named action for a schedule on the server and refresh the schedules list.
   * @param {string|number} id - Identifier of the schedule to act on.
   * @param {string} action - Action to perform ("enable", "disable", "delete", or "run").
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
   *
   * Each check is shown as a list item containing the check name and the check command rendered in monospace.
   */
  async function refreshReadiness() {
    var data = await api("/api/console/readiness");
    var list = $("#readinessList");
    list.innerHTML = "";
    data.checks.forEach(function(c) {
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
  refreshStatus();
  setInterval(refreshStatus, 30000);
})();
