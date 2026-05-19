(function () {
  "use strict";
  var state = {
    profiles: [],
    pathProfiles: [],
    activePath: null,
    workspace: null,
    token: "",
    githubDevice: null,
    lastRun: null,
    thinking: null,
    config: null,
    modelDiscovery: null,
    operator: null,
    evolution: null,
    latency: null,
    capabilityPack: null,
    localModels: null,
    remote: null,
    trust: null,
  };

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

  function openTab(name) {
    var tab = $(".tab[data-tab='" + name + "']");
    if (tab) tab.click();
  }

  function renderOperatorSummary(data) {
    state.operator = data;
    var cards = $("#operatorCards");
    var warnings = $("#operatorWarnings");
    if (!cards || !warnings) return;
    cards.innerHTML = "";
    (data.cards || []).forEach(function(cardData) {
      var card = el("div", { class: "card operator-card", "data-target": cardData.action || "status" });
      card.appendChild(el("h3", null, cardData.label || cardData.id));
      card.appendChild(el("div", { class: "value" }, cardData.status || "unknown"));
      card.appendChild(el("div", { class: "hint" }, "Open " + (cardData.action || "status")));
      card.addEventListener("click", function() { openTab(cardData.action || "status"); });
      cards.appendChild(card);
    });
    warnings.innerHTML = "";
    var warningList = data.warnings || [];
    if (!warningList.length) {
      warnings.appendChild(el("div", { class: "list-item" }, "Ghost readiness has no blocking warnings."));
    } else {
      warningList.forEach(function(w) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "badge warn" }, "warning"));
        item.appendChild(el("span", { class: "meta" }, w));
        warnings.appendChild(item);
      });
    }
  }

  async function refreshOperatorSummary() {
    try {
      var data = await api("/api/console/operator/summary");
      renderOperatorSummary(data);
    } catch (e) {
      empty("#operatorWarnings", "Operator summary unavailable: " + e.message);
    }
  }

  async function recordSetupStep(step, target) {
    try {
      var data = await api("/api/console/operator/setup-step", { method: "POST", body: { step: step } });
      if (data && data.summary) renderOperatorSummary(data.summary);
      if (target) openTab(target);
      toast("Setup step recorded.", "ok");
      await refreshTimeline();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  function renderTimeline(data) {
    var list = $("#activityTimeline");
    if (!list) return;
    list.innerHTML = "";
    var events = (data && data.events) || [];
    if (!events.length) {
      list.appendChild(el("div", { class: "empty" }, "No operator events yet."));
      return;
    }
    events.slice().reverse().forEach(function(event) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge ok" }, event.event_type || "event"));
      item.appendChild(el("span", { class: "name" }, new Date((event.timestamp || 0) * 1000).toLocaleString()));
      item.appendChild(el("span", { class: "meta mono" }, JSON.stringify(event.detail || {}).slice(0, 220)));
      list.appendChild(item);
    });
  }

  async function refreshTimeline() {
    try {
      renderTimeline(await api("/api/console/operator/timeline"));
    } catch (e) {
      empty("#activityTimeline", "Activity unavailable: " + e.message);
    }
  }

  function renderLatency(data) {
    state.latency = data;
    var cards = $("#latencyCards");
    var routes = $("#latencyRoutes");
    var recs = $("#latencyRecommendations");
    var events = $("#latencyEvents");
    if (!cards || !routes || !recs || !events) return;
    cards.innerHTML = "";
    [
      ["Status", data.status || "unknown"],
      ["Events", String(data.event_count || 0)],
      ["P50", String(data.p50_ms || 0) + " ms"],
      ["P95", String(data.p95_ms || 0) + " ms"],
      ["Max", String(data.max_ms || 0) + " ms"],
      ["Over budget", String(data.over_budget_count || 0)],
    ].forEach(function(row) {
      var card = el("div", { class: "card" });
      card.appendChild(el("h3", null, row[0]));
      card.appendChild(el("div", { class: "value" }, row[1]));
      cards.appendChild(card);
    });

    routes.innerHTML = "";
    (data.routes || []).slice(0, 12).forEach(function(route) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge " + (route.over_budget_count ? "warn" : "ok") }, route.p95_ms + " ms p95"));
      item.appendChild(el("span", { class: "name mono" }, route.route));
      item.appendChild(el("span", { class: "meta" }, "count " + route.count + " | budget " + route.budget_ms + " ms | over " + route.over_budget_count));
      routes.appendChild(item);
    });
    if (!(data.routes || []).length) empty("#latencyRoutes", "Latency telemetry will appear after Console API calls.");

    recs.innerHTML = "";
    (data.recommendations || []).forEach(function(text) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge ok" }, "tip"));
      item.appendChild(el("span", { class: "meta" }, text));
      recs.appendChild(item);
    });

    events.innerHTML = "";
    (data.slow_events || []).slice(0, 10).forEach(function(event) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge " + (event.over_budget ? "warn" : "ok") }, String(event.duration_ms) + " ms"));
      item.appendChild(el("span", { class: "name mono" }, event.method + " " + event.route));
      item.appendChild(el("span", { class: "meta" }, new Date((event.timestamp || 0) * 1000).toLocaleString()));
      events.appendChild(item);
    });
    if (!(data.slow_events || []).length) empty("#latencyEvents", "No latency events yet.");
  }

  async function refreshLatency() {
    try {
      renderLatency(await api("/api/console/operator/latency"));
    } catch (e) {
      empty("#latencyRoutes", "Latency unavailable: " + e.message);
    }
  }

  function sourceBadge(status) {
    if (status === "approved") return "ok";
    if (status === "revoked" || status === "denied") return "error";
    return "warn";
  }

  function renderEvolutionSources(sources) {
    var list = $("#learningSourceList");
    if (!list) return;
    list.innerHTML = "";
    if (!sources.length) {
      list.appendChild(el("div", { class: "empty" }, "No learning sources yet."));
      return;
    }
    sources.forEach(function(source) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge " + sourceBadge(source.consent_status) }, source.consent_status || "pending"));
      item.appendChild(el("span", { class: "name" }, source.label || source.source_type));
      item.appendChild(el("span", { class: "meta" }, [source.source_type, source.scope, source.risk_level, source.uri].filter(Boolean).join(" | ")));
      var actions = el("span", { class: "actions" });
      var approve = el("button", { class: "success" }, "Approve");
      approve.addEventListener("click", function() { setLearningSourceConsent(source.id, "approve"); });
      var revoke = el("button", { class: "danger" }, "Revoke");
      revoke.addEventListener("click", function() { setLearningSourceConsent(source.id, "revoke"); });
      actions.appendChild(approve);
      actions.appendChild(revoke);
      item.appendChild(actions);
      list.appendChild(item);
    });
  }

  function renderEvolutionCandidates(candidates) {
    var list = $("#evolutionCandidateList");
    if (!list) return;
    list.innerHTML = "";
    if (!candidates.length) {
      list.appendChild(el("div", { class: "empty" }, "No evolution candidates yet."));
      return;
    }
    candidates.forEach(function(candidate) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge " + (candidate.status === "promoted" || candidate.status === "active" ? "ok" : "warn") }, candidate.status));
      item.appendChild(el("span", { class: "name" }, candidate.title || candidate.candidate_type));
      item.appendChild(el("span", { class: "meta" }, [candidate.candidate_type, (candidate.required_permissions || []).join(", ")].filter(Boolean).join(" | ")));
      var actions = el("span", { class: "actions" });
      [
        ["review", "Review", ""],
        ["promote", "Promote", "primary"],
        ["reject", "Reject", "danger"],
      ].forEach(function(action) {
        var btn = el("button", { class: action[2] }, action[1]);
        btn.addEventListener("click", function() { setCandidateStatus(candidate.id, action[0]); });
        actions.appendChild(btn);
      });
      item.appendChild(actions);
      list.appendChild(item);
    });
  }

  async function refreshEvolution() {
    try {
      var sources = await api("/api/console/evolution/sources");
      var candidates = await api("/api/console/evolution/candidates");
      state.evolution = { sources: sources.sources || [], candidates: candidates.candidates || [] };
      renderEvolutionSources(state.evolution.sources);
      renderEvolutionCandidates(state.evolution.candidates);
    } catch (e) {
      empty("#learningSourceList", "Self-Evolution unavailable: " + e.message);
    }
  }

  async function addLearningSource() {
    try {
      var label = ($("#evolutionSourceLabel").value || "").trim();
      var uri = ($("#evolutionSourceUri").value || "").trim();
      var data = await api("/api/console/evolution/sources", {
        method: "POST",
        body: {
          source_type: $("#evolutionSourceType").value,
          label: label || uri,
          uri: uri,
          scope: $("#evolutionSourceScope").value,
          risk_level: $("#evolutionRisk").value,
        },
      });
      if (!data.ok) { toast(data.error || "Source rejected.", "error"); return; }
      $("#evolutionSourceLabel").value = "";
      $("#evolutionSourceUri").value = "";
      toast("Learning source added for review.", "ok");
      await refreshEvolution();
      await refreshOperatorSummary();
      await refreshTimeline();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function setLearningSourceConsent(id, action) {
    try {
      var data = await api("/api/console/evolution/sources/" + encodeURIComponent(id) + "/" + action, { method: "POST", body: {} });
      if (!data.ok) { toast(data.error || "Source update failed.", "error"); return; }
      toast(action === "approve" ? "Learning source approved." : "Learning source revoked.", action === "approve" ? "ok" : "warn");
      await refreshEvolution();
      await refreshOperatorSummary();
      await refreshTimeline();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function setCandidateStatus(id, action) {
    try {
      var data = await api("/api/console/evolution/candidates/" + encodeURIComponent(id) + "/" + action, { method: "POST", body: {} });
      if (!data.ok) { toast(data.error || "Candidate update failed.", "error"); return; }
      toast("Candidate " + action + " recorded.", "ok");
      await refreshEvolution();
      await refreshOperatorSummary();
      await refreshTimeline();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  function selectedProviderOption() {
    if (!state.config || !Array.isArray(state.config.provider_options)) return null;
    var id = $("#configProvider") ? $("#configProvider").value : "";
    return state.config.provider_options.find(function(option) { return option.id === id; }) || null;
  }

  function renderConfig(data) {
    state.config = data;
    var providerOptions = data.provider_options || [];
    var provider = (data.model && data.model.provider) || "";
    var select = $("#configProvider");
    var modelInput = $("#configModel");
    var baseUrl = $("#configBaseUrl");
    var models = $("#configModelOptions");
    if (!select || !modelInput || !baseUrl || !models) return;

    select.innerHTML = "";
    providerOptions.forEach(function(option) {
      var opt = el("option", { value: option.id }, option.name);
      if (option.id === provider) opt.selected = true;
      select.appendChild(opt);
    });
    if (!select.value && providerOptions.length) select.value = providerOptions[0].id;
    modelInput.value = (data.model && data.model.model) || "";
    baseUrl.value = (data.model && data.model.base_url) || "";
    $("#configApiKey").value = "";
    renderConfigModelOptions();

    var summary = $("#configSummary");
    summary.innerHTML = "";
    [
      ["Provider", provider || "not set"],
      ["Model", (data.model && data.model.model) || "not set"],
      ["API Key", data.model && data.model.api_key_configured ? "configured" : "not set"],
      ["Config File", data.config_path || "local state"],
    ].forEach(function(m) {
      var card = el("div", { class: "card" });
      card.appendChild(el("h3", null, m[0]));
      card.appendChild(el("div", { class: "value" }, m[1]));
      summary.appendChild(card);
    });

    var guardrails = $("#configGuardrails");
    guardrails.innerHTML = "";
    var production = data.runtime && data.runtime.policy && data.runtime.policy.production || {};
    [
      ["Mode", production.deployment_mode || "development", production.is_production || production.deployment_mode === "production"],
      ["Isolation", production.external_isolation || "not set", !!production.external_isolation],
      ["Security Reviewed", production.security_reviewed ? "yes" : "no", production.security_reviewed],
      ["Human Approval", production.human_approval_required ? "required" : "not required", production.human_approval_required],
      ["Trusted Inputs", production.trusted_inputs_only ? "only" : "untrusted allowed", production.trusted_inputs_only],
    ].forEach(function(row) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, row[0]));
      item.appendChild(el("span", { class: "badge " + (row[2] ? "ok" : "warn") }, row[1]));
      guardrails.appendChild(item);
    });

    var modules = $("#configModules");
    modules.innerHTML = "";
    (data.modules || []).forEach(function(mod) {
      var btn = el("button", { class: "module-btn", type: "button" });
      btn.appendChild(el("span", null, mod.label));
      btn.appendChild(el("span", { class: "meta" }, mod.enabled ? "available" : "disabled"));
      btn.addEventListener("click", function() { openTab(mod.tab); });
      modules.appendChild(btn);
    });

    $("#configOutput").textContent = JSON.stringify({
      env_file: data.env_file,
      env_preview: data.env_preview || {},
      security: data.security || {},
    }, null, 2);
  }

  function renderConfigModelOptions() {
    var option = selectedProviderOption();
    var models = $("#configModelOptions");
    if (!models) return;
    models.innerHTML = "";
    ((option && option.models) || []).forEach(function(model) {
      if (model) models.appendChild(el("option", { value: model }));
    });
    if (option && option.default_base_url && !$("#configBaseUrl").value) {
      $("#configBaseUrl").value = option.default_base_url;
    }
    $("#configKeyHint").textContent = option && option.requires_api_key
      ? (option.api_key_label + " is write-only; leave blank to keep the saved key.")
      : "This provider does not require a hosted API key.";
  }

  function selectedModelDiscoverySources() {
    return Array.from(document.querySelectorAll(".model-source"))
      .filter(function(input) { return input.checked; })
      .map(function(input) { return input.value; });
  }

  function modelCompatibilityBadge(status) {
    if (status === "ready") return { text: "Ready", cls: "ok" };
    if (status === "needs_key") return { text: "Needs API key", cls: "warn" };
    if (status === "candidate_only") return { text: "Candidate only", cls: "warn" };
    return { text: "Unsupported", cls: "error" };
  }

  function providerDefaultBaseUrl(provider) {
    var option = (state.config && state.config.provider_options || []).find(function(item) {
      return item.id === provider;
    });
    return option && option.default_base_url ? option.default_base_url : "";
  }

  function previewDiscoveredModel(model) {
    $("#configProvider").value = model.provider;
    $("#configModel").value = model.model_id;
    var base = providerDefaultBaseUrl(model.provider);
    if (base) $("#configBaseUrl").value = base;
    renderConfigModelOptions();
    openTab("config");
    toast("Model loaded into Config. Click Save Config to activate.", "ok");
  }

  async function selectDiscoveredModel(model) {
    try {
      var data = await api("/api/console/models/discovery/select", {
        method: "POST",
        body: { source: model.source, provider: model.provider, model_id: model.model_id },
      });
      if (!data.ok) {
        toast(data.error || "Model selection failed.", "error");
        return;
      }
      renderConfig(data);
      await refreshModelDiscovery(false);
      await refreshStatus();
      toast(data.requires_api_key ? "Model selected. Add an API key in Config before running." : "Model selected.", data.requires_api_key ? "warn" : "ok");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function pingDiscoveredModel(model) {
    try {
      var data = await api("/api/console/models/discovery/ping", {
        method: "POST",
        body: {
          provider: model.provider,
          model_id: model.model_id,
          base_url: providerDefaultBaseUrl(model.provider),
        },
      });
      toast(data.ok ? "Compatibility ping passed." : (data.error || "Compatibility ping failed."), data.ok ? "ok" : "error");
      $("#configOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) {
      toast(e.message, "error");
      $("#configOutput").textContent = e.message;
    }
  }

  function renderModelDiscovery(data) {
    state.modelDiscovery = data;
    var grid = $("#modelDiscoveryGrid");
    var status = $("#modelDiscoveryStatus");
    if (!grid || !status) return;
    grid.innerHTML = "";
    var models = data.models || [];
    var sourceStates = data.sources || {};
    var sourceNotes = Object.keys(sourceStates).map(function(source) {
      var state = sourceStates[source] || {};
      return source + ": " + (state.ok ? (state.count || 0) + " models" : (state.error || "unavailable"));
    });
    status.textContent = models.length
      ? models.length + " discovered models. " + sourceNotes.join(" | ")
      : "No cached models yet. Refresh OpenRouter first, then add Vultr/Hugging Face/local sources as needed.";
    if (data.alerts && data.alerts.length) {
      status.textContent += " Alerts: " + data.alerts.slice(0, 3).map(function(alert) {
        return alert.kind + " " + alert.model_id;
      }).join(", ");
    }
    models.slice(0, 80).forEach(function(model) {
      var compat = modelCompatibilityBadge(model.compatibility_status);
      var card = el("div", { class: "model-card " + (model.compatibility_status === "ready" ? "ready" : "candidate") });
      var title = el("div", { class: "model-title" }, model.display_name || model.model_id);
      card.appendChild(title);
      card.appendChild(el("div", { class: "model-id" }, model.provider + " / " + model.model_id));
      var badges = el("div", { class: "model-badges" });
      badges.appendChild(el("span", { class: "badge " + compat.cls }, compat.text));
      badges.appendChild(el("span", { class: "badge" }, model.source));
      if (model.cost_class) badges.appendChild(el("span", { class: "badge" }, "cost: " + model.cost_class));
      if (model.context_length) badges.appendChild(el("span", { class: "badge" }, String(model.context_length) + " ctx"));
      (model.capability_badges || []).slice(0, 6).forEach(function(badgeText) {
        badges.appendChild(el("span", { class: "badge" }, badgeText));
      });
      card.appendChild(badges);
      card.appendChild(el("div", { class: "model-desc" }, (model.description || "Compatible model candidate.").slice(0, 240)));
      var useCases = (model.recommended_use_cases || []).slice(0, 4).join(", ");
      if (useCases) card.appendChild(el("div", { class: "hint" }, "Best for: " + useCases));
      var actions = el("div", { class: "model-actions" });
      var preview = el("button", { type: "button" }, "Preview");
      preview.addEventListener("click", function() { previewDiscoveredModel(model); });
      var ping = el("button", { type: "button" }, "Ping");
      ping.addEventListener("click", function() { pingDiscoveredModel(model); });
      var select = el("button", { type: "button", class: "primary" }, "Select Model");
      if (["ready", "needs_key"].indexOf(model.compatibility_status) === -1) {
        select.disabled = true;
      }
      select.addEventListener("click", function() { selectDiscoveredModel(model); });
      actions.appendChild(preview);
      actions.appendChild(ping);
      actions.appendChild(select);
      card.appendChild(actions);
      grid.appendChild(card);
    });
  }

  async function refreshModelDiscovery(useNetwork) {
    try {
      var sources = selectedModelDiscoverySources();
      if (!sources.length) sources = ["openrouter"];
      if (useNetwork) {
        $("#modelDiscoveryStatus").textContent = "Refreshing model catalogs...";
        await api("/api/console/models/discovery/refresh", {
          method: "POST",
          body: { sources: sources },
        });
      }
      var capability = $("#modelCapabilityFilter").value || "";
      var query = ($("#modelDiscoveryQuery").value || "").trim();
      var params = new URLSearchParams();
      params.set("sources", sources.join(","));
      if (capability) params.set("capabilities", capability);
      if (query) params.set("query", query);
      var data = await api("/api/console/models/discovery?" + params.toString());
      renderModelDiscovery(data);
    } catch (e) {
      $("#modelDiscoveryStatus").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function refreshConfig() {
    try {
      var data = await api("/api/console/config");
      renderConfig(data);
    } catch (e) {
      $("#configOutput").textContent = e.message;
    }
  }

  async function saveConfig(clearKey) {
    try {
      var data = await api("/api/console/config", {
        method: "POST",
        body: {
          provider: $("#configProvider").value,
          model: $("#configModel").value,
          base_url: $("#configBaseUrl").value,
          api_key: $("#configApiKey").value,
          clear_api_key: !!clearKey,
        },
      });
      renderConfig(data);
      toast(data.ok ? "Config saved." : (data.error || "Config save failed."), data.ok ? "ok" : "error");
      await refreshStatus();
    } catch (e) {
      $("#configOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }
  $("#configProvider").addEventListener("change", renderConfigModelOptions);
  $("#configSave").addEventListener("click", function() { saveConfig(false); });
  $("#configClearKey").addEventListener("click", function() { saveConfig(true); });
  $("#configRefresh").addEventListener("click", refreshConfig);
  $("#modelDiscoveryRefresh").addEventListener("click", function() { refreshModelDiscovery(true); });
  $("#modelDiscoveryQuery").addEventListener("input", function() { refreshModelDiscovery(false); });
  $("#modelCapabilityFilter").addEventListener("change", function() { refreshModelDiscovery(false); });
  document.querySelectorAll(".model-source").forEach(function(input) {
    input.addEventListener("change", function() { refreshModelDiscovery(false); });
  });

  async function refreshPathProfiles() {
    try {
      var data = await api("/api/console/paths");
      state.pathProfiles = data.profiles || [];
      var select = $("#pathProfile");
      var ragSelect = $("#ragProfile");
      var summary = $("#pathSummary");
      if (!select || !summary) return;
      select.innerHTML = "";
      if (ragSelect) ragSelect.innerHTML = "";
      summary.innerHTML = "";
      state.pathProfiles.forEach(function(profile) {
        select.appendChild(el("option", { value: profile.id }, profile.name));
        if (ragSelect) ragSelect.appendChild(el("option", { value: profile.id }, profile.name));
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, profile.name));
        card.appendChild(el("div", { class: "hint" }, profile.description));
        if (profile.personalization_sources && profile.personalization_sources.length) {
          card.appendChild(el("div", { class: "meta" }, "Learns from: " + profile.personalization_sources.slice(0, 4).join(", ")));
        }
        if (profile.tool_domains && profile.tool_domains.length) {
          card.appendChild(el("div", { class: "meta" }, "Operates: " + profile.tool_domains.slice(0, 4).join(", ")));
        }
        summary.appendChild(card);
      });
      await refreshActivePath();
      if (state.pathProfiles.length) synthesizeSelectedPath();
    } catch (e) {
      empty("#pathSummary", "Path profiles unavailable.");
      toast(e.message, "error");
    }
  }

  function selectedPathPreferences() {
    return {
      training_mode: $("#pathTrainingMode").value,
      approval_level: $("#pathApprovalLevel").value,
    };
  }

  function renderActivePath(path) {
    state.activePath = path || null;
    var active = $("#pathActive");
    if (!active) return;
    var role = path && path.synthesis && path.synthesis.role ? path.synthesis.role : {};
    badge(active, role.name || path && path.profile_id || "default", path && path.profile_id ? "ok" : "warn");
  }

  async function refreshActivePath() {
    try {
      var data = await api("/api/console/paths/active");
      var path = data.path || {};
      var profile = $("#pathProfile");
      if (profile && path.profile_id) profile.value = path.profile_id;
      if (path.preferences) {
        if ($("#pathTrainingMode") && path.preferences.training_mode) $("#pathTrainingMode").value = path.preferences.training_mode;
        if ($("#pathApprovalLevel") && path.preferences.approval_level) $("#pathApprovalLevel").value = path.preferences.approval_level;
      }
      renderActivePath(path);
    } catch (e) {
      renderActivePath(null);
    }
  }

  async function synthesizeSelectedPath() {
    try {
      var profile = $("#pathProfile");
      if (!profile || !profile.value) return;
      var data = await api("/api/console/paths/synthesize", {
        method: "POST",
        body: {
          profile_id: profile.value,
          preferences: selectedPathPreferences(),
        },
      });
      $("#pathOutput").textContent = JSON.stringify(data.path || data, null, 2);
    } catch (e) {
      $("#pathOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function saveSelectedPath() {
    try {
      var profile = $("#pathProfile");
      if (!profile || !profile.value) return;
      var data = await api("/api/console/paths/active", {
        method: "POST",
        body: { profile_id: profile.value, preferences: selectedPathPreferences() },
      });
      renderActivePath(data.path || null);
      $("#pathOutput").textContent = JSON.stringify(data.path || data, null, 2);
      toast(data.ok ? "Ghost path saved." : (data.error || "Path save failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#pathOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }
  async function confirmPathMiniMind() {
    try {
      var profile = $("#pathProfile");
      if (!profile || !profile.value) return;
      var data = await api("/api/console/paths/confirm-minimind", {
        method: "POST",
        body: { profile_id: profile.value, preferences: selectedPathPreferences() },
      });
      $("#pathOutput").textContent = JSON.stringify(data, null, 2);
      toast(data.confirmation || "MiniMind path confirmation generated.", "ok");
    } catch (e) {
      $("#pathOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }
  $("#pathSynthesize").addEventListener("click", synthesizeSelectedPath);
  $("#pathConfirmMiniMind").addEventListener("click", confirmPathMiniMind);
  $("#pathSave").addEventListener("click", saveSelectedPath);

  async function refreshGithubStatus() {
    try {
      var data = await api("/api/console/github/status");
      var summary = $("#githubSummary");
      if (!summary) return;
      summary.innerHTML = "";
      [
        ["Status", data.ok ? "ready" : "unavailable"],
        ["Auth", data.auth_mode || "unknown"],
        ["Token", data.has_token ? "configured" : "not set"],
        ["User", data.user && data.user.login ? data.user.login : "not signed in"],
        ["Device Flow", data.device_flow_configured ? "configured" : "needs client id"],
        ["Self-Evolution", data.self_evolution_policy ? data.self_evolution_policy.mode : "guarded"],
      ].forEach(function(m) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, m[1]));
        summary.appendChild(card);
      });
    } catch (e) {
      empty("#githubSummary", "GitHub integration unavailable.");
    }
  }

  async function startGithubDeviceSignIn() {
    try {
      var data = await api("/api/console/github/device/start", {
        method: "POST",
        body: { scope: ($("#githubDeviceScopes").value || "read:user repo").trim() },
      });
      if (!data.ok) {
        $("#githubAuthOutput").textContent = JSON.stringify(data, null, 2);
        toast(data.error || "GitHub sign-in unavailable.", "warn");
        return;
      }
      state.githubDevice = data;
      $("#githubAuthOutput").textContent = [
        "Open: " + data.verification_uri,
        "Code: " + data.user_code,
        "Then approve the app in GitHub and click 'I Approved It'.",
        "",
        JSON.stringify({ scope: data.scope, expires_in: data.expires_in, interval: data.interval }, null, 2),
      ].join("\n");
      if (data.verification_uri) window.open(data.verification_uri, "_blank", "noopener");
    } catch (e) {
      $("#githubAuthOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function pollGithubDeviceSignIn() {
    try {
      if (!state.githubDevice || !state.githubDevice.device_code) {
        toast("Start GitHub sign-in first.", "warn");
        return;
      }
      var data = await api("/api/console/github/device/poll", {
        method: "POST",
        body: { device_code: state.githubDevice.device_code },
      });
      $("#githubAuthOutput").textContent = JSON.stringify(data, null, 2);
      if (data.ok) {
        state.githubDevice = null;
        await refreshGithubStatus();
        toast("GitHub signed in.", "ok");
      } else {
        toast(data.pending ? "Still waiting for GitHub approval." : (data.error || "Sign-in failed."), data.pending ? "warn" : "error");
      }
    } catch (e) {
      $("#githubAuthOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function logoutGithub() {
    try {
      var data = await api("/api/console/github/logout", { method: "POST", body: {} });
      state.githubDevice = null;
      $("#githubAuthOutput").textContent = JSON.stringify(data, null, 2);
      await refreshGithubStatus();
      toast("GitHub console token cleared.", "ok");
    } catch (e) {
      $("#githubAuthOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function previewSelfEvolution() {
    try {
      var materials = [];
      if ($("#selfEvolveSkills").checked) materials.push("verified_skills");
      if ($("#selfEvolveMcp").checked) materials.push("mcp_servers");
      if ($("#selfEvolveOpenSource").checked) materials.push("open_source_reference_materials");
      var repos = ($("#selfEvolveRepos").value || "").split(",").map(function(item) { return item.trim(); }).filter(Boolean);
      var data = await api("/api/console/github/self-evolution/preview", {
        method: "POST",
        body: { materials: materials, repos: repos },
      });
      $("#githubSelfEvolutionOutput").textContent = JSON.stringify(data, null, 2);
      toast("Self-evolution preview generated.", data.ok ? "ok" : "warn");
    } catch (e) {
      $("#githubSelfEvolutionOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function planGithubIssue() {
    try {
      var issueNumber = Number(($("#githubIssue").value || "").trim());
      var data = await api("/api/console/github/plan", {
        method: "POST",
        body: {
          repo: ($("#githubRepo").value || "").trim(),
          issue: issueNumber,
          title: ($("#githubTitle").value || "").trim(),
        },
      });
      $("#githubOutput").textContent = data.ok ? data.objective : data.error;
    } catch (e) {
      $("#githubOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function previewGithubPolicy() {
    try {
      var data = await api("/api/console/github/policy-simulate", {
        method: "POST",
        body: {
          action: { action: $("#githubPolicyAction").value, autonomous: true },
          controls: {
            allow_push: $("#githubAllowPush").checked,
            allow_autonomy: $("#githubAllowAutonomy").checked,
          },
        },
      });
      $("#githubOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) {
      $("#githubOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }
  $("#githubDeviceStart").addEventListener("click", startGithubDeviceSignIn);
  $("#githubDevicePoll").addEventListener("click", pollGithubDeviceSignIn);
  $("#githubLogout").addEventListener("click", logoutGithub);
  $("#githubSelfEvolutionPreview").addEventListener("click", previewSelfEvolution);
  $("#githubPlan").addEventListener("click", planGithubIssue);
  $("#githubPolicyPreview").addEventListener("click", previewGithubPolicy);

  // Remote Control
  function renderRemote(data) {
    state.remote = data;
    var policy = data.policy || {};
    if ($("#remoteEnabled")) $("#remoteEnabled").checked = policy.enabled !== false;
    if ($("#remoteDirectExecution")) $("#remoteDirectExecution").checked = !!policy.direct_execution_enabled;
    if ($("#remoteDefaultDirectAdmins")) $("#remoteDefaultDirectAdmins").checked = !!policy.default_direct_execution_for_admins;

    var summary = $("#remoteSummary");
    if (summary) {
      summary.innerHTML = "";
      [
        ["Paired", data.counts ? data.counts.paired_peers : 0],
        ["Pairings", data.counts ? data.counts.pending_pairings : 0],
        ["Approvals", data.counts ? data.counts.pending_approvals : 0],
        ["Direct", policy.direct_execution_enabled ? "enabled" : "approval-first"],
      ].forEach(function(m) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, String(m[1])));
        summary.appendChild(card);
      });
    }

    var peers = $("#remotePeers");
    if (peers) {
      peers.innerHTML = "";
      if (!Array.isArray(data.peers) || !data.peers.length) {
        peers.appendChild(el("div", { class: "empty" }, "No paired peers yet."));
      } else {
        data.peers.forEach(function(peer) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge " + (peer.status === "paired" ? "ok" : "warn") }, peer.status || "peer"));
          item.appendChild(el("span", { class: "name" }, (peer.display_name || peer.peer_id || "peer")));
          item.appendChild(el("span", { class: "meta" }, (peer.channel || "") + " / " + (peer.allow_direct_execution ? "direct enabled" : "approval required")));
          var actions = el("span", { class: "actions" });
          var direct = el("button", { "data-id": peer.id, "data-action": "direct" }, peer.allow_direct_execution ? "Disable Direct" : "Enable Direct");
          direct.addEventListener("click", function() { updateRemotePeer(peer.id, "direct", !peer.allow_direct_execution); });
          var revoke = el("button", { class: "danger", "data-id": peer.id, "data-action": "revoke" }, "Revoke");
          revoke.addEventListener("click", function() { updateRemotePeer(peer.id, "revoke", false); });
          actions.appendChild(direct);
          actions.appendChild(revoke);
          item.appendChild(actions);
          peers.appendChild(item);
        });
      }
    }

    var pairings = $("#remotePairings");
    if (pairings) {
      pairings.innerHTML = "";
      if (!Array.isArray(data.pairings) || !data.pairings.length) {
        pairings.appendChild(el("div", { class: "empty" }, "No pending pairings."));
      } else {
        data.pairings.forEach(function(pairing) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge warn" }, pairing.status || "pending"));
          item.appendChild(el("span", { class: "name" }, pairing.channel + " / " + pairing.peer_id));
          item.appendChild(el("span", { class: "meta mono" }, "code " + (pairing.code_preview || "")));
          var actions = el("span", { class: "actions" });
          var approve = el("button", { "data-id": pairing.id }, "Approve");
          approve.addEventListener("click", function() { approveRemotePairing(pairing.id, ""); });
          actions.appendChild(approve);
          item.appendChild(actions);
          pairings.appendChild(item);
        });
      }
    }

    var channels = $("#remoteChannels");
    if (channels) {
      channels.innerHTML = "";
      (data.channels || []).forEach(function(channel) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "badge " + (channel.send_enabled ? "ok" : channel.configured ? "warn" : "") }, channel.id || "channel"));
        item.appendChild(el("span", { class: "name" }, channel.adapter_status || "metadata_only"));
        var fields = (channel.secret_fields_configured || []).join(", ") || "no credentials";
        var signed = (channel.secret_fields_configured || []).indexOf("signing_secret") >= 0 ? " / signed webhooks required" : " / unsigned webhooks allowed";
        item.appendChild(el("span", { class: "meta" }, fields + " / outbound " + (channel.send_enabled ? "enabled" : "disabled") + signed));
        channels.appendChild(item);
      });
    }

    var approvals = $("#remoteApprovals");
    if (approvals) {
      approvals.innerHTML = "";
      if (!Array.isArray(data.approvals) || !data.approvals.length) {
        approvals.appendChild(el("div", { class: "empty" }, "No pending remote approvals."));
      } else {
        data.approvals.forEach(function(approval) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge warn" }, approval.status || "pending"));
          item.appendChild(el("span", { class: "name" }, approval.command || "command"));
          item.appendChild(el("span", { class: "meta" }, approval.objective || ""));
          var actions = el("span", { class: "actions" });
          var approve = el("button", { "data-id": approval.id }, "Approve");
          approve.addEventListener("click", function() { resolveRemoteApproval(approval.id, "approve"); });
          var deny = el("button", { class: "danger", "data-id": approval.id }, "Deny");
          deny.addEventListener("click", function() { resolveRemoteApproval(approval.id, "deny"); });
          actions.appendChild(approve);
          actions.appendChild(deny);
          item.appendChild(actions);
          approvals.appendChild(item);
        });
      }
    }

    var examples = $("#remoteWebhookExamples");
    if (examples) {
      examples.innerHTML = "";
      ["telegram", "discord", "slack", "whatsapp", "signal", "webhook"].forEach(function(channel) {
        var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge ok" }, channel));
          item.appendChild(el("span", { class: "name" }, "/api/console/remote/webhook/" + channel));
          item.appendChild(el("span", { class: "meta" }, "Normalizes inbound payloads and returns a token-free reply_preview. If a signing secret is saved, the raw body must match the SHA-256 signature."));
        examples.appendChild(item);
      });
    }
  }

  async function refreshRemote() {
    try {
      renderRemote(await api("/api/console/remote/status"));
    } catch (e) {
      empty("#remotePeers", "Remote control unavailable: " + e.message);
    }
  }

  async function saveRemotePolicy() {
    try {
      var data = await api("/api/console/remote/policy", {
        method: "POST",
        body: {
          enabled: $("#remoteEnabled").checked,
          direct_execution_enabled: $("#remoteDirectExecution").checked,
          default_direct_execution_for_admins: $("#remoteDefaultDirectAdmins").checked,
        },
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast("Remote policy saved.", data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function createRemotePairing() {
    try {
      var data = await api("/api/console/remote/pairing/create", {
        method: "POST",
        body: {
          channel: $("#remotePairChannel").value,
          peer_id: $("#remotePairPeer").value,
          display_name: $("#remotePairName").value,
        },
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Pairing code created." : (data.error || "Pairing failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function approveRemotePairing(pairingId, code) {
    try {
      var data = await api("/api/console/remote/pairing/approve", {
        method: "POST",
        body: { pairing_id: pairingId, code: code || "" },
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Remote peer paired." : (data.error || "Pairing approval failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function updateRemotePeer(peerId, action, allow) {
    try {
      var data = await api("/api/console/remote/peers/" + encodeURIComponent(peerId) + "/" + action, {
        method: "POST",
        body: { allow: !!allow },
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Remote peer updated." : (data.error || "Update failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function saveRemoteChannel(clearSecrets) {
    try {
      var channel = $("#remoteConfigChannel").value;
      var body = {
        enabled: $("#remoteConfigEnabled").checked,
        send_enabled: $("#remoteConfigSendEnabled").checked,
        clear_secrets: !!clearSecrets,
        bot_token: $("#remoteConfigToken").value,
        api_token: $("#remoteConfigToken").value,
        webhook_url: $("#remoteConfigWebhook").value,
        phone_number_id: $("#remoteConfigPhone").value,
        signing_secret: $("#remoteConfigSigning").value,
      };
      var data = await api("/api/console/remote/channels/" + encodeURIComponent(channel), {
        method: "POST",
        body: body,
      });
      $("#remoteConfigToken").value = "";
      $("#remoteConfigWebhook").value = "";
      $("#remoteConfigPhone").value = "";
      $("#remoteConfigSigning").value = "";
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Remote channel config saved." : (data.error || "Channel config failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function sendRemoteTestReply() {
    try {
      var data = await api("/api/console/remote/send-test", {
        method: "POST",
        body: {
          channel: $("#remoteSendChannel").value,
          reply_target: $("#remoteSendTarget").value,
          text: $("#remoteSendText").value,
        },
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Remote test reply sent." : (data.error || "Remote send failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function sendRemoteSimulation() {
    try {
      var data = await api("/api/console/remote/inbound", {
        method: "POST",
        body: {
          channel: $("#remoteSimChannel").value,
          peer_id: $("#remoteSimPeer").value,
          text: $("#remoteSimText").value,
          display_name: $("#remoteSimPeer").value,
        },
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Remote command processed." : (data.error || data.message || "Remote command blocked."), data.ok ? "ok" : "warn");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function resolveRemoteApproval(id, action) {
    try {
      var data = await api("/api/console/remote/approvals/" + encodeURIComponent(id) + "/" + action, {
        method: "POST",
        body: {},
      });
      $("#remoteOutput").textContent = JSON.stringify(data, null, 2);
      await refreshRemote();
      await refreshTimeline();
      toast(data.ok ? "Remote approval resolved." : (data.error || "Approval failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#remoteOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  $("#remoteSavePolicy").addEventListener("click", saveRemotePolicy);
  $("#remoteRefresh").addEventListener("click", refreshRemote);
  $("#remoteCreatePairing").addEventListener("click", createRemotePairing);
  $("#remoteSimSend").addEventListener("click", sendRemoteSimulation);
  $("#remoteSaveChannel").addEventListener("click", function() { saveRemoteChannel(false); });
  $("#remoteClearChannel").addEventListener("click", function() { saveRemoteChannel(true); });
  $("#remoteSendTest").addEventListener("click", sendRemoteTestReply);

  // Trust Runtime
  function renderTrust(data) {
    state.trust = data;
    var summary = data.summary || {};
    var cards = $("#trustCards");
    if (cards) {
      cards.innerHTML = "";
      [
        ["Journal", summary.journal && summary.journal.ok ? "ready" : "review"],
        ["Runs", summary.runs ? summary.runs.total : 0],
        ["Approvals", summary.approvals ? summary.approvals.pending : 0],
        ["MCP Trust", summary.mcp_trust ? summary.mcp_trust.status : "review"],
        ["Eval Baseline", summary.eval_baseline ? summary.eval_baseline.status : "missing"],
        ["Eval Cases", data.eval_cases ? data.eval_cases.length : 0],
        ["Admission", summary.capability_admission && summary.capability_admission.production_ready ? "ready" : "review"],
        ["Trace Export", summary.trace_health ? summary.trace_health.status : "local"],
      ].forEach(function(cardData) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, cardData[0]));
        card.appendChild(el("div", { class: "value" }, String(cardData[1])));
        cards.appendChild(card);
      });
    }

    var runs = $("#trustRuns");
    if (runs) {
      runs.innerHTML = "";
      if (!Array.isArray(data.runs) || !data.runs.length) {
        runs.appendChild(el("div", { class: "empty" }, "No durable runs recorded yet."));
      } else {
        data.runs.forEach(function(run) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge" }, run.status || "unknown"));
          item.appendChild(el("span", { class: "name" }, run.objective || run.run_id));
          item.appendChild(el("span", { class: "meta" }, (run.source || "local") + " | " + run.run_id));
          var actions = el("span", { class: "actions" });
          var resume = el("button", null, "Resume");
          resume.addEventListener("click", function() { resumeTrustRun(run.run_id); });
          var trace = el("button", null, "Trace");
          trace.addEventListener("click", function() { exportTrustTrace(run.run_id); });
          actions.appendChild(resume);
          actions.appendChild(trace);
          item.appendChild(actions);
          runs.appendChild(item);
        });
      }
    }

    var approvals = $("#trustApprovals");
    if (approvals) {
      approvals.innerHTML = "";
      if (!Array.isArray(data.approvals) || !data.approvals.length) {
        approvals.appendChild(el("div", { class: "empty" }, "No pending Trust Runtime approvals."));
      } else {
        data.approvals.forEach(function(approval) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge warn" }, approval.status || "pending"));
          item.appendChild(el("span", { class: "name" }, approval.reason || approval.id));
          item.appendChild(el("span", { class: "meta" }, approval.run_id || ""));
          var actions = el("span", { class: "actions" });
          var approve = el("button", null, "Approve");
          approve.addEventListener("click", function() { resolveTrustApproval(approval.id, "approve"); });
          var deny = el("button", { class: "danger" }, "Deny");
          deny.addEventListener("click", function() { resolveTrustApproval(approval.id, "deny"); });
          actions.appendChild(approve);
          actions.appendChild(deny);
          item.appendChild(actions);
          approvals.appendChild(item);
        });
      }
    }

    var mcp = $("#trustMcp");
    if (mcp) {
      mcp.innerHTML = "";
      if (!Array.isArray(data.mcp_servers) || !data.mcp_servers.length) {
        mcp.appendChild(el("div", { class: "empty" }, "No MCP servers reviewed yet."));
      } else {
        data.mcp_servers.forEach(function(server) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge" }, server.status || "review"));
          item.appendChild(el("span", { class: "name" }, server.server_id || "mcp-server"));
          item.appendChild(el("span", { class: "meta" }, "risk ceiling: " + (server.risk_ceiling || "medium")));
          var actions = el("span", { class: "actions" });
          var approve = el("button", null, "Approve");
          approve.addEventListener("click", function() { updateMcpTrust(server.server_id, "approve"); });
          var revoke = el("button", { class: "danger" }, "Revoke");
          revoke.addEventListener("click", function() { updateMcpTrust(server.server_id, "revoke"); });
          actions.appendChild(approve);
          actions.appendChild(revoke);
          item.appendChild(actions);
          mcp.appendChild(item);
        });
      }
    }

    var evalCases = $("#trustEvalCases");
    if (evalCases) {
      evalCases.innerHTML = "";
      if (!Array.isArray(data.eval_cases) || !data.eval_cases.length) {
        evalCases.appendChild(el("div", { class: "empty" }, "No promoted eval cases yet. Promote a durable run to make it reusable for regression checks."));
      } else {
        data.eval_cases.forEach(function(testCase) {
          var item = el("div", { class: "list-item" });
          item.appendChild(el("span", { class: "badge" }, testCase.severity || "P2"));
          item.appendChild(el("span", { class: "name" }, testCase.label || testCase.case_id));
          item.appendChild(el("span", { class: "meta" }, "run: " + (testCase.run_id || "unknown") + " | steps: " + String((testCase.step_types || []).length)));
          evalCases.appendChild(item);
        });
      }
    }

    var admission = $("#admissionRecords");
    if (admission) {
      admission.innerHTML = "";
      if (!Array.isArray(data.admission_records) || !data.admission_records.length) {
        admission.appendChild(el("div", { class: "empty" }, "No capability records yet. Add models, MCP servers, skills, tools, or RAG sources for explicit review before activation."));
      } else {
        data.admission_records.forEach(function(record) {
          var item = el("div", { class: "list-item" });
          var badgeClass = record.status === "active" || record.status === "approved" ? "ok" : record.status === "quarantined" || record.status === "revoked" ? "error" : "warn";
          item.appendChild(el("span", { class: "badge " + badgeClass }, record.status || "discovered"));
          item.appendChild(el("span", { class: "name" }, record.name || record.id));
          item.appendChild(el("span", { class: "meta" }, (record.capability_kind || "capability") + " | risk: " + (record.risk_level || "medium") + " | " + (record.source || "local")));
          var actions = el("span", { class: "actions" });
          [
            ["Approve", "approve", null],
            ["Activate", "activate", null],
            ["Revoke", "revoke", "danger"],
            ["Quarantine", "quarantine", "danger"],
          ].forEach(function(actionData) {
            var btn = el("button", actionData[2] ? { class: actionData[2] } : null, actionData[0]);
            btn.addEventListener("click", function() { updateCapabilityAdmission(record.id, actionData[1]); });
            actions.appendChild(btn);
          });
          item.appendChild(actions);
          admission.appendChild(item);
        });
      }
    }
  }

  async function refreshTrust() {
    try {
      var summary = await api("/api/console/trust/summary");
      var runs = await api("/api/console/trust/runs");
      var approvals = await api("/api/console/trust/approvals");
      var mcp = await api("/api/console/mcp/trust");
      var evals = await api("/api/console/trust/evals");
      var evalCases = await api("/api/console/trust/eval-cases");
      var admission = await api("/api/console/capability-admission");
      summary.capability_admission = admission.summary || {};
      renderTrust({
        summary: summary,
        runs: runs.runs || [],
        approvals: approvals.approvals || [],
        mcp_servers: mcp.servers || [],
        evals: evals,
        eval_cases: evalCases.cases || [],
        admission_records: admission.records || [],
      });
    } catch (e) {
      empty("#trustRuns", "Trust Runtime unavailable: " + e.message);
    }
  }

  async function resumeTrustRun(runId) {
    try {
      var data = await api("/api/console/trust/runs/" + encodeURIComponent(runId) + "/resume", { method: "POST", body: {} });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "Trust run resumed." : (data.error || "Run cannot resume."), data.ok ? "ok" : "warn");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function resolveTrustApproval(id, action) {
    try {
      var data = await api("/api/console/trust/approvals/" + encodeURIComponent(id) + "/" + action, { method: "POST", body: {} });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "Trust approval resolved." : (data.error || "Approval failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function updateMcpTrust(serverId, action) {
    try {
      var data = await api("/api/console/mcp/trust/" + encodeURIComponent(serverId) + "/" + action, {
        method: "POST",
        body: { risk_ceiling: "medium" },
      });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "MCP trust updated." : (data.error || "MCP trust update failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function createTrustBaseline() {
    try {
      var data = await api("/api/console/trust/evals/baseline", { method: "POST", body: {} });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "Trust baseline created." : (data.error || "Baseline failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function promoteTrustEvalCase() {
    var runId = ($("#trustEvalRunId").value || "").trim();
    if (!runId && state.trust && Array.isArray(state.trust.runs) && state.trust.runs.length) {
      runId = state.trust.runs[0].run_id;
    }
    if (!runId) {
      toast("Run id is required before promoting an eval case.", "warn");
      return;
    }
    try {
      var data = await api("/api/console/trust/eval-cases/promote", {
        method: "POST",
        body: {
          run_id: runId,
          label: ($("#trustEvalLabel").value || "").trim(),
          severity: $("#trustEvalSeverity").value || "P2",
        },
      });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "Eval case promoted." : (data.error || "Eval case promotion failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function registerCapabilityAdmission() {
    var name = ($("#admissionName").value || "").trim();
    if (!name) {
      toast("Capability name is required.", "warn");
      return;
    }
    var permissions = ($("#admissionPermissions").value || "")
      .split(",")
      .map(function(item) { return item.trim(); })
      .filter(Boolean);
    try {
      var data = await api("/api/console/capability-admission", {
        method: "POST",
        body: {
          capability_kind: $("#admissionKind").value || "tool",
          name: name,
          source: ($("#admissionSource").value || "").trim() || "console",
          risk_level: $("#admissionRisk").value || "medium",
          permissions: permissions,
          metadata: { intake: "operator_console" },
        },
      });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "Capability queued for review." : (data.error || "Capability admission failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function updateCapabilityAdmission(recordId, action) {
    try {
      var data = await api("/api/console/capability-admission/" + encodeURIComponent(recordId) + "/" + action, {
        method: "POST",
        body: { reviewer: "console", reason: action + " from Trust Runtime dashboard" },
      });
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      await refreshTrust();
      await refreshTimeline();
      toast(data.ok ? "Capability admission updated." : (data.error || "Capability admission update failed."), data.ok ? "ok" : "error");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  async function exportTrustTrace(runId) {
    try {
      var target = runId || "latest";
      var data = await api("/api/console/trust/traces/" + encodeURIComponent(target) + "/export");
      $("#trustOutput").textContent = JSON.stringify(data, null, 2);
      toast(data.ok ? "Trace bundle exported." : (data.error || "Trace export unavailable."), data.ok ? "ok" : "warn");
    } catch (e) {
      $("#trustOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }

  $("#trustRefresh").addEventListener("click", refreshTrust);
  $("#trustBaseline").addEventListener("click", createTrustBaseline);
  $("#trustTraceExport").addEventListener("click", function() { exportTrustTrace("latest"); });
  $("#trustPromoteEvalCase").addEventListener("click", promoteTrustEvalCase);
  $("#admissionInspect").addEventListener("click", registerCapabilityAdmission);

  // ── Status ───────────────────────────────────────────────────────────────
  function renderThinking(data) {
    state.thinking = data;
    var summary = $("#thinkingSummary");
    if (!summary) return;
    summary.innerHTML = "";
    [
      ["Path", data.active_path && data.active_path.profile_id ? data.active_path.profile_id : "default"],
      ["MiniMind", data.minimind && data.minimind.ready ? "ready" : "guarded"],
      ["Workspace", (data.workspace ? data.workspace.evidence_count : 0) + " evidence"],
      ["Capabilities", data.capabilities ? (data.capabilities.covered + "/" + data.capabilities.total) : "unknown"],
    ].forEach(function(m) {
      var card = el("div", { class: "card" });
      card.appendChild(el("h3", null, m[0]));
      card.appendChild(el("div", { class: "value" }, m[1]));
      summary.appendChild(card);
    });

    var nodes = data.nodes || [];
    var positions = {
      objective: [90, 70], policy: [280, 70], path: [470, 70], memory: [660, 70], planner: [850, 70],
      scheduler: [185, 245], tools: [400, 245], verification: [615, 245], audit: [830, 245],
    };
    var edgeSvg = (data.edges || []).map(function(edge) {
      var a = positions[edge.from] || [0, 0];
      var b = positions[edge.to] || [0, 0];
      return '<line x1="' + a[0] + '" y1="' + a[1] + '" x2="' + b[0] + '" y2="' + b[1] + '" class="think-edge" />';
    }).join("");
    var nodeSvg = nodes.map(function(n) {
      var p = positions[n.id] || [120, 120];
      var cls = "think-node-svg " + esc(n.status || "ready");
      return [
        '<g class="' + cls + '" transform="translate(' + p[0] + ' ' + p[1] + ')">',
        '<rect x="-72" y="-31" width="144" height="62" rx="8"></rect>',
        '<text y="-4" text-anchor="middle" class="think-label">' + esc(n.label) + '</text>',
        '<text y="17" text-anchor="middle" class="think-layer">' + esc(n.layer || "") + '</text>',
        '</g>',
      ].join("");
    }).join("");
    $("#thinkingGraph").innerHTML = [
      '<svg class="thinking-svg" viewBox="0 0 1000 330" role="img" aria-label="Ghost Chimera thinking trace">',
      edgeSvg,
      nodeSvg,
      '</svg>',
      '<div class="thinking-note">' + esc(data.note || "Explainability trace") + '</div>',
    ].join("");

    var trace = $("#thinkingTrace");
    trace.innerHTML = "";
    nodes.forEach(function(n) {
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "badge " + (n.status === "active" ? "ok" : n.status === "guarded" ? "warn" : "") }, n.status || "ready"));
      item.appendChild(el("span", { class: "name" }, n.label));
      item.appendChild(el("span", { class: "meta" }, n.detail || ""));
      trace.appendChild(item);
    });
    if (state.lastRun) {
      var last = el("div", { class: "list-item" });
      last.appendChild(el("span", { class: "badge " + (state.lastRun.ok ? "ok" : "error") }, "last run"));
      last.appendChild(el("span", { class: "name" }, state.lastRun.ok ? "completed" : "failed"));
      last.appendChild(el("span", { class: "meta" }, JSON.stringify(state.lastRun).slice(0, 240)));
      trace.appendChild(last);
    }
  }

  async function refreshThinking() {
    try {
      var data = await api("/api/console/thinking");
      renderThinking(data);
    } catch (e) {
      empty("#thinkingTrace", "Thinking trace unavailable: " + e.message);
      toast(e.message, "error");
    }
  }
  $("#refreshThinking").addEventListener("click", refreshThinking);

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

      await Promise.allSettled([
        refreshJobs(),
        refreshSchedules(),
        refreshWorkspace(),
        refreshMemory(),
        refreshPersonalMiniMind(),
        refreshRagBuilder(),
        refreshCapabilities(),
        refreshReadiness(),
        refreshOperatorSummary(),
        refreshLatency(),
        refreshRemote(),
        refreshTrust(),
      ]);
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
    var hint = el("p", { class: "hint" }, "Use the Config tab to switch providers without editing code or environment files.");
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
      state.lastRun = r;
      renderRunSummary(r);
      writeOutput(JSON.stringify(r, null, 2));
      pushHistory(obj, r.ok);
      refreshThinking();
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

  // ── RAG Builder tab ───────────────────────────────────────────────────────
  function ragRepoLines() {
    return ($("#ragOpenSourceRepos").value || "").split(/\r?\n/).map(function(x) { return x.trim(); }).filter(Boolean);
  }
  async function refreshRagBuilder() {
    try {
      var data = await api("/api/console/rag/builder/status");
      var status = data.status || {};
      var list = $("#ragBuilderStatus");
      if (!list) return;
      list.innerHTML = "";
      [
        ["MiniMind enabled", status.enabled ? "yes" : "no", status.enabled ? "ok" : "warn"],
        ["Dataset records", String(status.dataset_count || 0), (status.dataset_count || 0) > 0 ? "ok" : "warn"],
        ["RAG handoff", status.readiness && status.readiness.primary_model_handoff_ready ? "ready" : "not ready", status.readiness && status.readiness.primary_model_handoff_ready ? "ok" : "warn"],
      ].forEach(function(row) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "name" }, row[0]));
        item.appendChild(el("span", { class: "badge " + row[2] }, row[1]));
        list.appendChild(item);
      });
    } catch (_) { empty("#ragBuilderStatus", "RAG Builder status unavailable."); }
  }
  async function buildRagPlan(executeBootstrap) {
    try {
      var profile = ($("#ragProfile").value || $("#pathProfile").value || "").trim();
      if (!profile) { toast("Select a path profile first.", "warn"); return; }
      var data = await api("/api/console/rag/builder", {
        method: "POST",
        body: {
          profile_id: profile,
          objective: ($("#ragObjective").value || "").trim(),
          training_mode: ($("#ragTrainingMode").value || "rag-first").trim(),
          approval_level: ($("#pathApprovalLevel").value || "supervised").trim(),
          open_source_repos: ragRepoLines(),
          execute_bootstrap: !!executeBootstrap,
        },
      });
      $("#ragBuilderOutput").textContent = JSON.stringify(data, null, 2);
      toast(executeBootstrap ? "RAG builder plan executed." : "RAG builder plan generated.", "ok");
      await refreshRagBuilder();
      await refreshPersonalMiniMind();
    } catch (e) {
      $("#ragBuilderOutput").textContent = e.message;
      toast(e.message, "error");
    }
  }
  $("#ragBuildPlan").addEventListener("click", function() { buildRagPlan(false); });
  $("#ragBuildAndBootstrap").addEventListener("click", function() { buildRagPlan(true); });

  // ── MCP tab ───────────────────────────────────────────────────────────────
  async function refreshMcpStatus() {
    try {
      var data = await api("/api/console/mcp/status");
      var list = $("#mcpStatus");
      if (!list) return;
      list.innerHTML = "";
      [
        ["Registered", data.registered ? "yes" : "no", data.registered ? "ok" : "warn"],
        ["Enabled", data.enabled ? "yes" : "no", data.enabled ? "ok" : "warn"],
        ["Tools", String(data.tool_count || 0), (data.tool_count || 0) > 0 ? "ok" : "warn"],
      ].forEach(function(row) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "name" }, row[0]));
        item.appendChild(el("span", { class: "badge " + row[2] }, row[1]));
        list.appendChild(item);
      });
      $("#mcpOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) {
      empty("#mcpStatus", "MCP unavailable.");
      $("#mcpOutput").textContent = e.message;
    }
  }
  $("#mcpRefresh").addEventListener("click", refreshMcpStatus);
  $("#mcpEnable").addEventListener("click", async function() {
    try {
      var data = await api("/api/console/mcp/chimeralang/enable", { method: "POST", body: {} });
      $("#mcpOutput").textContent = JSON.stringify(data, null, 2);
      toast(data.ok ? "chimeralang-mcp enabled." : (data.error || "Enable failed."), data.ok ? "ok" : "error");
      await refreshMcpStatus();
    } catch (e) {
      $("#mcpOutput").textContent = e.message;
      toast(e.message, "error");
    }
  });
  $("#mcpDisable").addEventListener("click", async function() {
    try {
      var data = await api("/api/console/mcp/chimeralang/disable", { method: "POST", body: {} });
      $("#mcpOutput").textContent = JSON.stringify(data, null, 2);
      toast("MCP disabled.", "ok");
      await refreshMcpStatus();
    } catch (e) {
      $("#mcpOutput").textContent = e.message;
      toast(e.message, "error");
    }
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
  async function discoverSkills(repos, install) {
    try {
      var body = {
        query: ($("#skillDiscoveryQuery").value || "").trim(),
        limit: 6,
        repos: Array.isArray(repos) ? repos : [],
        install: !!install,
      };
      var data = await api("/api/console/skills/discover", { method: "POST", body: body });
      $("#skillDiscoveryOutput").textContent = JSON.stringify(data, null, 2);
      if (data.installed_count) {
        toast("Installed " + data.installed_count + " compatibility skill(s).", "ok");
        await refreshSkills();
      }
      return data;
    } catch (e) {
      $("#skillDiscoveryOutput").textContent = e.message;
      toast(e.message, "error");
      return null;
    }
  }
  $("#discoverSkills").addEventListener("click", async function() {
    var data = await discoverSkills([], false);
    if (!data || !Array.isArray(data.candidates)) return;
    var list = $("#skillList");
    data.candidates.forEach(function(candidate) {
      if (!candidate || !candidate.full_name) return;
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, candidate.full_name));
      item.appendChild(el("span", { class: "badge ok" }, "github"));
      item.appendChild(el("span", { class: "meta" }, candidate.description || candidate.html_url || ""));
      var actions = el("span", { class: "actions" });
      var convert = el("button", { class: "primary" }, "Convert");
      convert.addEventListener("click", function() { discoverSkills([candidate.full_name], true); });
      actions.appendChild(convert);
      item.appendChild(actions);
      list.appendChild(item);
    });
  });
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

  async function runPrReview() {
    try {
      var data = await api("/api/console/review-pr", {
        method: "POST",
        body: {
          base: ($("#reviewBase").value || "origin/main").trim(),
          head: ($("#reviewHead").value || "HEAD").trim(),
        },
      });
      var summary = $("#reviewSummary");
      summary.innerHTML = "";
      [
        ["Status", data.ok ? "ok" : "blocked"],
        ["Files", String(data.file_count || 0)],
        ["Findings", String(data.finding_count || 0)],
        ["Risk", String(data.risk_score || 0)],
      ].forEach(function(m) {
        var card = el("div", { class: "card" });
        card.appendChild(el("h3", null, m[0]));
        card.appendChild(el("div", { class: "value" }, m[1]));
        summary.appendChild(card);
      });

      var list = $("#reviewFindings");
      list.innerHTML = "";
      (data.findings || []).forEach(function(finding) {
        var item = el("div", { class: "list-item" });
        var cls = finding.severity === "P0" || finding.severity === "P1" ? "error" : finding.severity === "P2" ? "warn" : "ok";
        item.appendChild(el("span", { class: "badge " + cls }, finding.severity || "P3"));
        item.appendChild(el("span", { class: "name" }, finding.title || "finding"));
        item.appendChild(el("span", { class: "meta" }, (finding.path || "repository") + (finding.line ? ":" + finding.line : "")));
        item.appendChild(el("span", { class: "meta" }, finding.recommendation || finding.detail || ""));
        list.appendChild(item);
      });
      if (!(data.findings || []).length) empty("#reviewFindings", data.summary || "No findings.");
      toast("Review complete.", data.ok ? "ok" : "warn");
    } catch (e) {
      empty("#reviewFindings", "PR review failed.");
      toast(e.message, "error");
    }
  }
  $("#runPrReview").addEventListener("click", runPrReview);

  // -- Native absorption panels ------------------------------------------------
  function renderLocalModels(data) {
    state.localModels = data;
    var cards = $("#localModelCards");
    if (!cards) return;
    cards.innerHTML = "";
    var models = (data && data.models) || [];
    [
      ["Status", data && data.ok ? "ready" : "unknown"],
      ["Models", String((data && data.count) || models.length || 0)],
      ["Policy", ((data && data.policy) || {}).activation || "preview_only"],
    ].forEach(function(row) {
      var card = el("div", { class: "card" });
      card.appendChild(el("h3", null, row[0]));
      card.appendChild(el("div", { class: "value" }, row[1]));
      cards.appendChild(card);
    });
  }

  async function refreshLocalModels() {
    try {
      var data = await api("/api/console/local-models/inventory");
      renderLocalModels(data);
      $("#localModelOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) { $("#localModelOutput").textContent = "Error: " + e.message; }
  }

  async function resolveLocalModel() {
    var source = ($("#localModelSource").value || "").trim();
    if (!source) { toast("Enter a model source first.", "warn"); return; }
    try {
      var data = await api("/api/console/local-models/resolve", { method: "POST", body: { source: source } });
      $("#localModelOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) { $("#localModelOutput").textContent = "Error: " + e.message; }
  }

  async function refreshCognitionTrace() {
    try {
      var goal = encodeURIComponent(($("#cognitionGoal").value || "operator request").trim());
      var data = await api("/api/console/cognition/trace?goal=" + goal);
      var list = $("#cognitionTraceList");
      list.innerHTML = "";
      (data.stages || []).forEach(function(stage) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "name" }, stage.stage));
        item.appendChild(el("span", { class: "badge ok" }, stage.status));
        item.appendChild(el("span", { class: "meta" }, typeof stage.detail === "string" ? stage.detail : JSON.stringify(stage.detail || "")));
        list.appendChild(item);
      });
      $("#cognitionOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) { $("#cognitionOutput").textContent = "Error: " + e.message; }
  }

  async function runCognitionGuard() {
    try {
      var data = await api("/api/console/cognition/guard", {
        method: "POST",
        body: {
          confidence: parseFloat($("#cognitionConfidence").value) || 0,
          variance: parseFloat($("#cognitionVariance").value) || 0,
        },
      });
      $("#cognitionOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) { $("#cognitionOutput").textContent = "Error: " + e.message; }
  }

  function renderCapabilityPack(data) {
    state.capabilityPack = data;
    var list = $("#capabilityPackList");
    var select = $("#capabilityToolSelect");
    if (!list || !select) return;
    list.innerHTML = "";
    select.innerHTML = "";
    (data.tools || []).forEach(function(tool) {
      var opt = el("option", { value: tool.id }, tool.id);
      select.appendChild(opt);
      var item = el("div", { class: "list-item" });
      item.appendChild(el("span", { class: "name" }, tool.name));
      item.appendChild(el("span", { class: "badge ok" }, tool.category));
      item.appendChild(el("span", { class: "meta" }, tool.description));
      list.appendChild(item);
    });
  }

  async function refreshCapabilityPack() {
    try {
      var data = await api("/api/console/capability-pack");
      renderCapabilityPack(data);
    } catch (e) { empty("#capabilityPackList", "Capability pack unavailable: " + e.message); }
  }

  async function runCapabilityTool() {
    var args = {};
    try { args = JSON.parse($("#capabilityToolArgs").value || "{}"); } catch (e) { toast("Arguments must be valid JSON.", "error"); return; }
    try {
      var data = await api("/api/console/capability-pack/run", { method: "POST", body: { tool_id: $("#capabilityToolSelect").value, arguments: args } });
      $("#capabilityPackOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) { $("#capabilityPackOutput").textContent = "Error: " + e.message; }
  }

  async function runSandboxJourney() {
    try {
      var data = await api("/api/console/sandbox/journey");
      var list = $("#sandboxSteps");
      list.innerHTML = "";
      (data.steps || []).forEach(function(step) {
        var item = el("div", { class: "list-item" });
        item.appendChild(el("span", { class: "name" }, step.name));
        item.appendChild(el("span", { class: "badge " + (step.status === "warning" ? "warn" : "ok") }, step.status));
        item.appendChild(el("span", { class: "meta" }, step.detail || ""));
        list.appendChild(item);
      });
      $("#sandboxOutput").textContent = JSON.stringify(data, null, 2);
    } catch (e) { $("#sandboxOutput").textContent = "Error: " + e.message; }
  }

  $("#refreshLocalModels").addEventListener("click", refreshLocalModels);
  $("#resolveLocalModel").addEventListener("click", resolveLocalModel);
  $("#refreshCognitionTrace").addEventListener("click", refreshCognitionTrace);
  $("#runCognitionGuard").addEventListener("click", runCognitionGuard);
  $("#refreshCapabilityPack").addEventListener("click", refreshCapabilityPack);
  $("#runCapabilityTool").addEventListener("click", runCapabilityTool);
  $("#runSandboxJourney").addEventListener("click", runSandboxJourney);

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
  document.querySelectorAll("#setupSteps button").forEach(function(btn) {
    btn.addEventListener("click", function() {
      recordSetupStep(btn.getAttribute("data-step"), btn.getAttribute("data-target"));
    });
  });
  $("#addEvolutionSource").addEventListener("click", addLearningSource);
  $("#refreshActivity").addEventListener("click", refreshTimeline);
  $("#refreshLatency").addEventListener("click", refreshLatency);
  $("#operatorReadiness").addEventListener("click", async function() {
    try {
      var data = await api("/api/console/operator/readiness", { method: "POST", body: {} });
      renderOperatorSummary(data);
      await refreshTimeline();
      toast((data.warnings || []).length ? "Readiness check has warnings." : "Readiness check passed.", (data.warnings || []).length ? "warn" : "ok");
    } catch (e) {
      toast(e.message, "error");
    }
  });

  // ── Boot ──────────────────────────────────────────────────────────────────
  renderQuickActions();
  renderHistory();
  initAuth().then(function() {
    refreshStatus();
    refreshConfig();
    refreshModelDiscovery(false);
    refreshBrowserStatus();
    refreshSecurity();
    refreshSkills();
    refreshCapabilities();
    refreshPathProfiles();
    refreshGithubStatus();
    refreshThinking();
    refreshMcpStatus();
    refreshOperatorSummary();
    refreshEvolution();
    refreshTimeline();
    refreshLatency();
    refreshLocalModels();
    refreshCapabilityPack();
    refreshCognitionTrace();
    refreshTrust();
  });
  setInterval(refreshStatus, 30000);
})();
