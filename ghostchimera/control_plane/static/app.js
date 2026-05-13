(function () {
  "use strict";
  var state = { profiles: [], workspace: null, token: "" };

  function $(sel) { return document.querySelector(sel); }
  function $$$(sel) { return document.querySelectorAll(sel); }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function(k) { e.setAttribute(k, attrs[k]); });
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function(c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function empty(id, msg) { var d = $(id); d.innerHTML = ""; d.appendChild(el("div", { class: "empty" }, msg)); }

  // ── Toast notifications ──────────────────────────────────────────────────
  function toast(msg, type, duration) {
    var container = $("#toastContainer");
    var t = el("div", { class: "toast " + (type || "") }, msg);
    container.appendChild(t);
    setTimeout(function() {
      t.style.opacity = "0";
      t.style.transition = "opacity .3s";
      setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 320);
    }, duration || 3500);
  }

  // ── Run history (localStorage) ───────────────────────────────────────────
  var HISTORY_KEY = "ghostchimera_run_history";
  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch (e) { console.warn("Failed to load run history:", e); return []; }
  }
  function saveHistory(hist) {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(hist.slice(0, 20))); } catch (_) {}
  }
  function pushHistory(objective, ok) {
    var hist = loadHistory();
    hist.unshift({ objective: objective, ok: ok, ts: Date.now() });
    saveHistory(hist);
    renderHistory();
  }
  function renderHistory() {
    var hist = loadHistory();
    var container = $("#runHistory");
    if (!container) return;
    container.innerHTML = "";
    if (!hist.length) { container.appendChild(el("div", { class: "empty" }, "No runs yet.")); return; }
    hist.forEach(function(h) {
      var item = el("div", { class: "history-item" });
      item.appendChild(el("span", { class: "badge " + (h.ok ? "ok" : "error") }, h.ok ? "✓" : "✗"));
      var obj = el("span", { class: "hi-obj" }, h.objective);
      item.appendChild(obj);
      var d = new Date(h.ts);
      item.appendChild(el("span", { class: "hi-meta" }, d.toLocaleTimeString()));
      item.addEventListener("click", function() {
        $("#objective").value = h.objective;
        $(".tab[data-tab='run']").click();
        $("#objective").focus();
      });
      container.appendChild(item);
    });
  }

  // ── Quick actions ────────────────────────────────────────────────────────
  var QUICK_ACTIONS = [
    { label: "🩺 Self-audit", obj: "Run a self-audit: check all backends, validate config, and report system health." },
    { label: "📋 Summarize work", obj: "Summarize my recent work and pending goals based on my workspace and memory." },
    { label: "🔍 Inspect status", obj: "Inspect the current Chimera Pilot status and list all registered backends." },
    { label: "🧹 Review memory", obj: "Review recent memory entries and highlight any stale or low-confidence items." },
    { label: "📊 Usage report", obj: "Generate a usage and autonomy report for the last 24 hours." },
    { label: "🔐 Security scan", obj: "Run a security scan: check audit chain integrity and report recent threat events." },
    { label: "🤖 Local model check", obj: "Check the local MiniMind model status, dataset size, and readiness for fine-tuning." },
    { label: "📅 Schedule review", obj: "List all active schedules and summarize what they do and when they run." },
  ];
  function renderQuickActions() {
    var container = $("#quickActions");
    if (!container) return;
    container.innerHTML = "";
    QUICK_ACTIONS.forEach(function(qa) {
      var chip = el("button", { class: "qa-chip" }, qa.label);
      chip.addEventListener("click", function() {
        $("#objective").value = qa.obj;
        $("#objective").focus();
      });
      container.appendChild(chip);
    });
  }

  // ── Token auth ───────────────────────────────────────────────────────────
  function showTokenOverlay() { $("#tokenOverlay").style.display = "flex"; }
  function hideTokenOverlay() { $("#tokenOverlay").style.display = "none"; }
  $("#tokenSubmit").addEventListener("click", function() {
    var t = ($("#tokenInput").value || "").trim();
    if (!t) return;
    state.token = t;
    try { localStorage.setItem("ghostchimera_console_token", t); } catch (_) {}
    hideTokenOverlay();
    refreshStatus();
  });
  $("#tokenInput").addEventListener("keydown", function(e) { if (e.key === "Enter") $("#tokenSubmit").click(); });

  async function initAuth() {
    try {
      var meta = await fetch("/api/console/token").then(function(r) { return r.json(); });
      if (meta && meta.auth_enabled) {
        var stored = "";
        try { stored = localStorage.getItem("ghostchimera_console_token") || ""; } catch (_) {}
        if (stored) { state.token = stored; } else { showTokenOverlay(); }
      }
    } catch (_) {}
  }

  // ── Tabs ─────────────────────────────────────────────────────────────────
  $$$("#tabBar .tab").forEach(function(tab) {
    tab.addEventListener("click", function() {
      $$$(".tab").forEach(function(t) { t.classList.remove("active"); });
      $$$(".tab-content").forEach(function(c) { c.classList.remove("active"); });
      tab.classList.add("active");
      $("#tab-" + tab.dataset.tab).classList.add("active");
    });
  });

  // ── API helper ───────────────────────────────────────────────────────────
  async function api(path, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    opts.headers["Content-Type"] = "application/json";
    if (state.token) opts.headers["X-Gateway-Token"] = state.token;
    if (opts.body && typeof opts.body === "object") opts.body = JSON.stringify(opts.body);
    var r = await fetch(path, opts);
    if (r.status === 401) {
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

  function badge(el, text, cls) { el.textContent = text; el.className = "badge " + (cls || ""); }

  // ── Status ───────────────────────────────────────────────────────────────
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
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, String(m[1])));
        cards.appendChild(card);
      });

      // Autonomy profile selector
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

      // Job profile selector
      var jSel = $("#jobProfile");
      jSel.innerHTML = "";
      state.profiles.forEach(function(p) {
        var opt = el("option", { value: p.name });
        opt.textContent = p.name;
        jSel.appendChild(opt);
      });
      if (jSel.children.length) jSel.value = data.autonomy.resolved_profile.name;

      // Provider panel
      renderProviderPanel(data.runtime);

      // Backend panel
      renderBackendPanel(data.gateway.backends || []);

      await refreshJobs();
      await refreshSchedules();
      await refreshWorkspace();
      await refreshMemory();
      await refreshPersonalMiniMind();
      await refreshCapabilities();
      await refreshReadiness();
    } catch (e) {
      badge($("#health"), "offline", "error");
    }
  }

  function renderProviderPanel(runtime) {
    var container = $("#providerStatus");
    if (!container) return;
    container.innerHTML = "";
    var provider = (runtime && runtime.model_provider) || "—";
    var model = (runtime && runtime.local_model && runtime.local_model.profile) || "—";
    var item = el("div", { class: "list-item" });
    item.appendChild(el("span", { class: "name" }, "Provider"));
    item.appendChild(el("span", { class: "badge ok" }, provider));
    item.appendChild(el("span", { class: "meta" }, "model profile: " + model));
    container.appendChild(item);
    var hint = el("p", { class: "hint" }, "Set a different provider by configuring the GHOSTCHIMERA_MODEL_PROVIDER environment variable before starting the server.");
    hint.style.marginTop = "6px";
    container.appendChild(hint);
  }

  function renderBackendPanel(backends) {
    var container = $("#backendList");
    if (!container) return;
    if (!Array.isArray(backends) || !backends.length) {
      empty("#backendList", "No backends registered.");
      return;
    }
    container.innerHTML = "";
    backends.forEach(function(b) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, b.id || b.name || "backend"));
      item.appendChild(el("span", { class: "badge ok" }, b.status || "registered"));
      if (b.capabilities && b.capabilities.length) {
        item.appendChild(el("span", { class: "meta" }, b.capabilities.join(", ")));
      }
      container.appendChild(item);
    });
  }

  // ── Autonomy ─────────────────────────────────────────────────────────────
  $("#autonomyLevel").addEventListener("change", function() {
    var p = state.profiles.find(function(p) { return p.name === $("#autonomyLevel").value; });
    $("#autonomyDesc").textContent = p ? p.description : "";
  });
  $("#saveAutonomy").addEventListener("click", async function() {
    try {
      await api("/api/console/autonomy", {
        method: "POST",
        body: {
          level: $("#autonomyLevel").value,
          true_autonomy_desktop: $("#trueAutonomyDesktop").checked,
          personal_context: $("#personalContext").checked,
        },
      });
      toast("Autonomy profile saved.", "ok");
      await refreshStatus();
    } catch (e) {
      toast("Failed to save: " + e.message, "error");
    }
  });

  // ── Run ──────────────────────────────────────────────────────────────────
  function renderRunSummary(r) {
    var summaryEl = $("#runSummary");
    summaryEl.innerHTML = "";
    summaryEl.style.display = "block";
    var overall = el("div", { class: "list-item" });
    var statusBadge = el("span", { class: "badge " + (r.ok ? "ok" : "error") }, r.ok ? "✓ Completed" : "✗ Failed");
    overall.appendChild(statusBadge);
    if (r.error) overall.appendChild(el("span", { class: "meta" }, r.error));
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

  async function runObjective() {
    var obj = $("#objective").value.trim();
    if (!obj) { toast("Enter an objective first.", "warn"); return; }
    $("#runSummary").style.display = "none";
    writeOutput("Running…");
    $("#runObjective").disabled = true;
    try {
      var r = await api("/api/console/run", { method: "POST", body: { objective: obj } });
      renderRunSummary(r);
      writeOutput(JSON.stringify(r, null, 2));
      pushHistory(obj, r.ok);
      toast(r.ok ? "Run completed." : "Run failed: " + (r.error || "unknown"), r.ok ? "ok" : "error");
    } catch (e) {
      writeOutput("Error: " + e.message);
      pushHistory(obj, false);
      toast("Error: " + e.message, "error");
    } finally {
      $("#runObjective").disabled = false;
    }
  }

  $("#runObjective").addEventListener("click", runObjective);
  $("#objective").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runObjective();
  });
  $("#clearOutput").addEventListener("click", function() {
    $("#runSummary").style.display = "none";
    writeOutput("Ready.");
  });

  // ── Jobs ─────────────────────────────────────────────────────────────────
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
    if (!Array.isArray(data.history) || !data.history.length) { empty("#jobHistory", "No autonomy jobs yet."); return; }
    history.innerHTML = "";
    data.history.slice().reverse().slice(0, 20).forEach(function(j) {
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
    try {
      var r = await api("/api/console/autonomy/jobs", {
        method: "POST",
        body: { job: $("#jobName").value, profile: $("#jobProfile").value, execute: $("#jobExecute").checked, run_now: true },
      });
      writeOutput(JSON.stringify(r, null, 2));
      toast("Job enqueued.", "ok");
      await refreshJobs();
    } catch (e) {
      toast("Failed: " + e.message, "error");
    }
  });

  // ── Workspace ─────────────────────────────────────────────────────────────
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
    var goals = (data.self_model && data.self_model.goals) ? data.self_model.goals : {};
    var goalKeys = Object.keys(goals);
    if (goalKeys.length) {
      var goalHdr = el("div", { class: "list-item" });
      goalHdr.appendChild(el("span", { class: "name" }, "Goals"));
      goalHdr.appendChild(el("span", { class: "badge ok" }, String(goalKeys.length)));
      wd.appendChild(goalHdr);
      goalKeys.forEach(function(k) {
        var item = el("div", { class: "list-item" });
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
    await api("/api/console/workspace/goals", { method: "POST", body: { name: name, description: desc } });
    $("#goalName").value = "";
    $("#goalDescription").value = "";
    toast("Goal saved.", "ok");
    await refreshWorkspace();
  });
  $("#addEvidence").addEventListener("click", async function() {
    await api("/api/console/workspace/evidence", {
      method: "POST",
      body: { source: $("#evidenceSource").value, content: $("#evidenceContent").value, confidence: parseFloat($("#evidenceConfidence").value) || 0.5 },
    });
    toast("Evidence added.", "ok");
    await refreshWorkspace();
    await refreshJobs();
  });
  $("#addReflection").addEventListener("click", async function() {
    await api("/api/console/workspace/reflections", {
      method: "POST",
      body: { action: $("#reflectionAction").value, outcome: $("#reflectionOutcome").value, confidence: parseFloat($("#reflectionConfidence").value) || 0.5 },
    });
    toast("Reflection recorded.", "ok");
    await refreshWorkspace();
    await refreshJobs();
  });
  $("#syncMemory").addEventListener("click", async function() {
    try {
      var r = await api("/api/console/workspace/sync-memory", { method: "POST", body: { min_confidence: 0.0, stale_after_days: 30 } });
      writeOutput(JSON.stringify(r, null, 2));
      toast("Synced to CWR memory.", "ok");
    } catch (e) { toast("Sync failed: " + e.message, "error"); }
  });

  // ── Memory ────────────────────────────────────────────────────────────────
  async function refreshMemory() {
    try {
      var st = await api("/api/console/memory/status");
      var ms = $("#memoryStatus");
      ms.innerHTML = "";
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, "Documents in memory"));
      item.appendChild(el("span", { class: "badge ok" }, String(st.count || 0)));
      item.appendChild(el("span", { class: "meta" }, st.memory_db || ""));
      ms.appendChild(item);
    } catch (_) { empty("#memoryStatus", "Memory unavailable."); }
  }

  function memOut(r) { $("#memoryOutput").textContent = JSON.stringify(r, null, 2); }

  $("#emailIngestFile").addEventListener("click", async function() {
    var path = ($("#emailFilePath").value || "").trim();
    if (!path) { toast("Enter a path to a .eml or .mbox file.", "warn"); return; }
    try {
      var r = await api("/api/console/memory/ingest-email", { method: "POST", body: { path: path } });
      memOut(r);
      if (r.ok) { toast("Ingested " + r.ingested + " email(s).", "ok"); await refreshMemory(); }
      else toast(r.error || "Ingest failed.", "error");
    } catch (e) { toast(e.message, "error"); }
  });

  $("#emailIngestRaw").addEventListener("click", async function() {
    var raw = ($("#emailRaw").value || "").trim();
    if (!raw) { toast("Paste a raw email first.", "warn"); return; }
    try {
      var r = await api("/api/console/memory/ingest-email", { method: "POST", body: { raw: raw } });
      $("#emailRaw").value = "";
      memOut(r);
      if (r.ok) { toast("Email ingested.", "ok"); await refreshMemory(); }
      else toast(r.error || "Ingest failed.", "error");
    } catch (e) { toast(e.message, "error"); }
  });

  $("#fileIngest").addEventListener("click", async function() {
    var path = ($("#fileIngestPath").value || "").trim();
    if (!path) { toast("Enter a file or directory path.", "warn"); return; }
    var source = ($("#fileIngestSource").value || "").trim();
    try {
      var r = await api("/api/console/memory/ingest-file", { method: "POST", body: { path: path, source: source } });
      memOut(r);
      if (r.ok) { toast("Ingested " + (r.chunks || r.ingested || "?") + " chunk(s).", "ok"); await refreshMemory(); }
      else toast(r.error || "Ingest failed.", "error");
    } catch (e) { toast(e.message, "error"); }
  });

  $("#memoryIngest").addEventListener("click", async function() {
    var source = ($("#memorySource").value || "").trim();
    var content = ($("#memoryContent").value || "").trim();
    if (!source || !content) { toast("Fill in both source and content.", "warn"); return; }
    try {
      var r = await api("/api/console/memory/ingest", { method: "POST", body: { source: source, content: content } });
      $("#memoryContent").value = "";
      memOut(r);
      toast("Added to memory.", "ok");
      await refreshMemory();
    } catch (e) { toast(e.message, "error"); }
  });

  $("#memorySearch").addEventListener("click", async function() {
    var q = ($("#memoryQuery").value || "").trim();
    if (!q) return;
    try {
      var r = await api("/api/console/memory/search", { method: "POST", body: { query: q, limit: 5 } });
      memOut(r);
    } catch (e) { toast(e.message, "error"); }
  });
  // Ctrl+Enter in search
  $("#memoryQuery").addEventListener("keydown", function(e) {
    if (e.key === "Enter") $("#memorySearch").click();
  });

  $("#teachSave").addEventListener("click", async function() {
    var prompt = ($("#teachPrompt").value || "").trim();
    var response = ($("#teachResponse").value || "").trim();
    if (!prompt || !response) { toast("Enter both a prompt and a response.", "warn"); return; }
    try {
      var r = await api("/api/console/training/teach", { method: "POST", body: { prompt: prompt, response: response } });
      if (r.ok) { $("#teachPrompt").value = ""; $("#teachResponse").value = ""; toast("Training example saved.", "ok"); }
      else toast(r.error || "Save failed.", "error");
      memOut(r);
    } catch (e) { toast(e.message, "error"); }
  });

  $("#trainingStatus").addEventListener("click", async function() {
    try { memOut(await api("/api/console/training/status")); } catch (e) { toast(e.message, "error"); }
  });
  $("#minimindStatus").addEventListener("click", async function() {
    try { memOut(await api("/api/console/minimind/status")); } catch (e) { toast(e.message, "error"); }
  });
  $("#exportDataset").addEventListener("click", async function() {
    var raw = ($("#datasetRecords").value || "").trim();
    if (!raw) return;
    var records;
    try { records = JSON.parse(raw); } catch (e) { toast("Invalid JSON: " + e.message, "error"); return; }
    try {
      var r = await api("/api/console/minimind/dataset", { method: "POST", body: { records: records } });
      memOut(r);
      if (r.ok) toast("Dataset exported to " + r.path, "ok");
    } catch (e) { toast(e.message, "error"); }
  });

  // Personal MiniMind
  function pathLines(id) {
    return ($("#" + id).value || "").split(/\r?\n/).map(function(x) { return x.trim(); }).filter(Boolean);
  }
  function setPathLines(id, values) {
    $("#" + id).value = Array.isArray(values) ? values.join("\n") : "";
  }
  function pmOut(r) { $("#pmOutput").textContent = JSON.stringify(r, null, 2); }

  async function refreshPersonalMiniMind() {
    var panel = $("#personalMiniMindStatus");
    if (!panel) return;
    try {
      var data = await api("/api/console/minimind/personal/status");
      var st = data.status || {};
      var consent = st.consent || {};
      $("#pmAdmin").checked = !!consent.admin_controls;
      $("#pmSystemSpecs").checked = !!consent.allow_system_specs;
      $("#pmFiles").checked = !!consent.allow_files;
      $("#pmEmail").checked = !!consent.allow_email;
      $("#pmMachineCrawl").checked = !!consent.allow_machine_crawl;
      $("#pmEmailCrawl").checked = !!consent.allow_email_crawl;
      $("#pmAutonomy").checked = !!consent.allow_autonomy;
      $("#pmTraining").checked = !!consent.allow_training;
      setPathLines("pmFilePaths", consent.file_paths || []);
      setPathLines("pmEmailPaths", consent.email_paths || []);
      setPathLines("pmCrawlRoots", consent.crawl_roots || []);
      setPathLines("pmExcludePaths", consent.exclude_paths || []);

      panel.innerHTML = "";
      [
        ["Enabled", st.enabled ? "yes" : "no", st.enabled ? "ok" : "warn"],
        ["Memory", String(st.memory_count || 0), "ok"],
        ["Dataset", String(st.dataset_count || 0), (st.dataset_count || 0) > 0 ? "ok" : "warn"],
        ["RAG handoff", st.readiness && st.readiness.primary_model_handoff_ready ? "ready" : "not ready", st.readiness && st.readiness.primary_model_handoff_ready ? "ok" : "warn"],
        ["Machine crawl", st.readiness && st.readiness.whole_machine_crawl_ready ? "on" : "off", st.readiness && st.readiness.whole_machine_crawl_ready ? "warn" : ""],
      ].forEach(function(row) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "name" }, row[0]));
        item.appendChild(el("span", { class: "badge " + row[2] }, row[1]));
        if (row[0] === "Dataset") item.appendChild(el("span", { class: "meta" }, st.dataset_path || ""));
        panel.appendChild(item);
      });
    } catch (_) { empty("#personalMiniMindStatus", "Personal MiniMind unavailable."); }
  }

  $("#pmSaveConsent").addEventListener("click", async function() {
    try {
      var r = await api("/api/console/minimind/personal/consent", {
        method: "POST",
        body: {
          admin_controls: $("#pmAdmin").checked,
          allow_system_specs: $("#pmSystemSpecs").checked,
          allow_files: $("#pmFiles").checked,
          allow_email: $("#pmEmail").checked,
          allow_machine_crawl: $("#pmMachineCrawl").checked,
          allow_email_crawl: $("#pmEmailCrawl").checked,
          allow_autonomy: $("#pmAutonomy").checked,
          allow_training: $("#pmTraining").checked,
          file_paths: pathLines("pmFilePaths"),
          email_paths: pathLines("pmEmailPaths"),
          crawl_roots: pathLines("pmCrawlRoots"),
          exclude_paths: pathLines("pmExcludePaths"),
        },
      });
      pmOut(r);
      toast(r.ok ? "Personal MiniMind consent saved." : (r.error || "Consent rejected."), r.ok ? "ok" : "error");
      await refreshPersonalMiniMind();
    } catch (e) { toast(e.message, "error"); }
  });

  $("#pmRevokeConsent").addEventListener("click", async function() {
    try {
      var r = await api("/api/console/minimind/personal/revoke", { method: "POST" });
      pmOut(r);
      toast("Personal MiniMind consent revoked.", "ok");
      await refreshPersonalMiniMind();
    } catch (e) { toast(e.message, "error"); }
  });

  $("#pmBootstrap").addEventListener("click", async function() {
    try {
      var r = await api("/api/console/minimind/personal/bootstrap", {
        method: "POST",
        body: {
          include_system_specs: $("#pmSystemSpecs").checked,
          file_paths: pathLines("pmFilePaths"),
          email_paths: pathLines("pmEmailPaths"),
          crawl_roots: pathLines("pmCrawlRoots"),
          exclude_paths: pathLines("pmExcludePaths"),
        },
      });
      pmOut(r);
      toast(r.ok ? "Personal MiniMind bootstrap complete." : (r.error || "Bootstrap blocked."), r.ok ? "ok" : "error");
      await refreshPersonalMiniMind();
      await refreshMemory();
    } catch (e) { toast(e.message, "error"); }
  });

  $("#pmHandoff").addEventListener("click", async function() {
    var objective = ($("#pmObjective").value || "").trim();
    if (!objective) { toast("Enter an objective first.", "warn"); return; }
    try {
      var r = await api("/api/console/minimind/personal/handoff", { method: "POST", body: { objective: objective } });
      pmOut(r);
      toast(r.ok ? "Handoff ready." : (r.error || "Handoff failed."), r.ok ? "ok" : "error");
    } catch (e) { toast(e.message, "error"); }
  });

  // ── Skills tab ────────────────────────────────────────────────────────────
  async function refreshSkills() {
    try {
      var data = await api("/api/console/skills");
      var skills = (data && data.skills) || [];
      var list = $("#skillList");
      var sel = $("#skillSelect");
      list.innerHTML = "";
      sel.innerHTML = "";
      if (!skills.length) { empty("#skillList", "No skills registered."); return; }
      skills.forEach(function(s) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "name" }, s.name));
        item.appendChild(el("span", { class: "badge ok" }, s.domain || "general"));
        if (s.description) item.appendChild(el("span", { class: "meta" }, s.description));
        list.appendChild(item);

        var opt = el("option", { value: s.name });
        opt.textContent = s.name;
        sel.appendChild(opt);
      });
    } catch (_) { empty("#skillList", "Skills unavailable."); }
  }
  $("#runSkill").addEventListener("click", async function() {
    var skillName = $("#skillSelect").value;
    var input = ($("#skillInput").value || "").trim();
    if (!skillName) { toast("Select a skill first.", "warn"); return; }
    var objective = (input || "Run skill: " + skillName) + " (skill:" + skillName + ")";
    $("#skillOutput").textContent = "Running skill…";
    try {
      var r = await api("/api/console/run", { method: "POST", body: { objective: objective } });
      $("#skillOutput").textContent = JSON.stringify(r, null, 2);
      toast(r.ok ? "Skill completed." : "Skill failed.", r.ok ? "ok" : "error");
    } catch (e) {
      $("#skillOutput").textContent = "Error: " + e.message;
      toast(e.message, "error");
    }
  });

  // ── Browser ───────────────────────────────────────────────────────────────
  async function refreshBrowserStatus() {
    try {
      var data = await api("/api/console/browser/status");
      var avail = data && data.available;
      badge($("#browserStatusBadge"), avail ? "available" : "unavailable", avail ? "ok" : "warn");
      $("#browserStatusDetail").textContent = (data && data.detail) ? data.detail : "";
    } catch (e) { badge($("#browserStatusBadge"), "error", "error"); }
  }
  $("#browserFetch").addEventListener("click", async function() {
    var url = $("#browserFetchUrl").value.trim();
    if (!url) return;
    $("#browserOutput").textContent = "Fetching…";
    try {
      var r = await api("/api/console/browser/fetch", { method: "POST", body: { url: url } });
      if (r.ok) {
        $("#browserOutput").textContent = (r.content || "").slice(0, 2000) + (r.truncated ? "\n\n[truncated]" : "");
        toast("Page fetched.", "ok");
      } else { $("#browserOutput").textContent = "Error: " + (r.error || "unknown"); toast(r.error, "error"); }
    } catch (e) { $("#browserOutput").textContent = "Error: " + e.message; toast(e.message, "error"); }
  });
  $("#browserFetchUrl").addEventListener("keydown", function(e) { if (e.key === "Enter") $("#browserFetch").click(); });
  $("#browserOpen").addEventListener("click", async function() {
    var url = $("#browserOpenUrl").value.trim();
    if (!url) return;
    try {
      var r = await api("/api/console/browser/open", { method: "POST", body: { url: url } });
      $("#browserOutput").textContent = JSON.stringify(r, null, 2);
    } catch (e) { $("#browserOutput").textContent = "Error: " + e.message; }
  });
  $("#browserSnapshot").addEventListener("click", async function() {
    var url = $("#browserOpenUrl").value.trim();
    try {
      var r = await api("/api/console/browser/snapshot", { method: "POST", body: { url: url } });
      $("#browserOutput").textContent = (r.ok && r.output) ? r.output : JSON.stringify(r, null, 2);
    } catch (e) { $("#browserOutput").textContent = "Error: " + e.message; }
  });

  // ── Security ──────────────────────────────────────────────────────────────
  async function refreshSecurity() {
    try {
      var summary = await api("/api/console/security/summary");
      var s = summary.summary || {};
      var cards = $("#securityCards");
      cards.innerHTML = "";
      [["Total Events", s.total_events], ["Blocked", s.blocked_count], ["Threats", s.threat_count], ["Avg Risk", s.avg_risk_score != null ? Number(s.avg_risk_score).toFixed(2) : "—"]].forEach(function(m) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, m[1] != null ? String(m[1]) : "—"));
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
      if (!evList.length) { empty("#securityEvents", "No security events recorded."); return; }
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
    } catch (_) { empty("#securityEvents", "Security monitor unavailable."); }
  }
  $("#refreshSecurity").addEventListener("click", refreshSecurity);

  // ── Schedules ─────────────────────────────────────────────────────────────
  async function refreshSchedules() {
    var data = await api("/api/console/autonomy/schedules");
    var list = $("#scheduleList");
    if (!Array.isArray(data.schedules) || !data.schedules.length) { empty("#scheduleList", "No schedules yet."); return; }
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
  async function schedAction(id, action) {
    await api("/api/console/autonomy/schedules/" + id + "/" + action, { method: "POST" });
    toast("Schedule " + action + " done.", "ok");
    await refreshSchedules();
  }
  window._sched = schedAction;
  $("#createSchedule").addEventListener("click", async function() {
    var jobSel = $("#scheduleJob");
    var jobName = jobSel.value || (jobSel.options[0] ? jobSel.options[0].value : "self-audit");
    try {
      await api("/api/console/autonomy/schedules", {
        method: "POST",
        body: { name: $("#scheduleName").value, cron_expression: $("#scheduleCron").value, autonomy_job: jobName, profile: "supervised", execute: false, enabled: false },
      });
      toast("Schedule created (disabled by default).", "ok");
      await refreshSchedules();
    } catch (e) { toast(e.message, "error"); }
  });
  (async function() {
    var data = await api("/api/console/autonomy/jobs");
    var sel = $("#scheduleJob");
    (data.available_jobs || []).forEach(function(j) {
      var opt = el("option", { value: j.name });
      opt.textContent = j.name;
      sel.appendChild(opt);
    });
  })();

  // ── Readiness ─────────────────────────────────────────────────────────────
  async function refreshCapabilities() {
    try {
      var data = await api("/api/console/capabilities");
      var summary = $("#capabilitySummary");
      summary.innerHTML = "";
      [
        ["Grade", data.grade || "unknown"],
        ["Score", String(data.score_ratio || 0)],
        ["Complete", String(data.complete_count || 0) + " / " + String(data.capability_count || 0)],
        ["Gaps", String((data.top_gaps || []).length)],
      ].forEach(function(m) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, m[1]));
        summary.appendChild(card);
      });

      var list = $("#capabilityList");
      list.innerHTML = "";
      (data.capabilities || []).forEach(function(cap) {
        var item = el("div", { class: "list-item capability-item" });
        var cls = cap.status === "complete" ? "ok" : cap.status === "partial" ? "warn" : "error";
        item.appendChild(el("span", { class: "name" }, cap.name));
        item.appendChild(el("span", { class: "badge " + cls }, cap.status));
        item.appendChild(el("span", { class: "meta" }, "coverage " + cap.coverage));
        item.appendChild(el("span", { class: "meta" }, (cap.competitors || []).join(", ")));
        if (cap.release_gate) item.appendChild(el("span", { class: "meta mono" }, cap.release_gate));
        list.appendChild(item);
      });
      if (!(data.capabilities || []).length) empty("#capabilityList", "No capability data available.");
    } catch (e) {
      empty("#capabilityList", "Capability matrix unavailable.");
    }
  }
  $("#refreshCapabilities").addEventListener("click", refreshCapabilities);

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

  // ── Output helper ─────────────────────────────────────────────────────────
  function writeOutput(text) { $("pre#output").textContent = text; }
  $("#refresh").addEventListener("click", refreshStatus);

  // ── Boot ──────────────────────────────────────────────────────────────────
  renderQuickActions();
  renderHistory();
  initAuth().then(function() {
    refreshStatus();
    refreshBrowserStatus();
    refreshSecurity();
    refreshSkills();
    refreshCapabilities();
  });
  setInterval(refreshStatus, 30000);
})();
