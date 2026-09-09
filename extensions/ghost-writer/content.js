/* Ghost Writer content script: gray completions on typing pause.
 * - Triggers 1s after typing stops in textareas / contenteditable fields.
 * - Asks the local Ghost console (/api/stealth/ghost-write); stays silent
 *   when no model is configured (never fakes completions).
 * - Tab accepts, Esc dismisses. Overlay is clearly Ghost's, never the page's.
 */
(function () {
  "use strict";

  var DEBOUNCE_MS = 1000;
  var MIN_CHARS = 5;
  var timer = null;
  var activeEl = null;
  var overlay = null;

  function backendBase() {
    try {
      return localStorage.getItem("ghost_writer_backend") || "http://127.0.0.1:8766";
    } catch (_) {
      return "http://127.0.0.1:8766";
    }
  }

  function currentText(el) {
    if ("value" in el && typeof el.value === "string") return el.value;
    return el.innerText || "";
  }

  function hideOverlay() {
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    overlay = null;
    activeEl = null;
  }

  function showOverlay(el, suggestion) {
    hideOverlay();
    activeEl = el;
    overlay = document.createElement("div");
    overlay.className = "ghost-writer-overlay";
    overlay.textContent = suggestion;
    overlay.title = "Ghost suggestion — Tab to accept, Esc to dismiss";
    overlay.addEventListener("mousedown", function (e) {
      e.preventDefault();
      acceptSuggestion();
    });
    var rect = el.getBoundingClientRect();
    overlay.style.top = rect.bottom + window.scrollY + 4 + "px";
    overlay.style.left = rect.left + window.scrollX + "px";
    overlay.style.maxWidth = rect.width + "px";
    document.body.appendChild(overlay);
  }

  function acceptSuggestion() {
    if (!activeEl || !overlay) return;
    var suggestion = overlay.textContent || "";
    if ("value" in activeEl && typeof activeEl.value === "string") {
      activeEl.value = (activeEl.value.replace(/\s+$/, "") + " " + suggestion).trimStart();
      activeEl.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      activeEl.innerText = (activeEl.innerText || "").replace(/\s+$/, "") + " " + suggestion;
    }
    hideOverlay();
    if (activeEl.focus) activeEl.focus();
  }

  async function fetchSuggestion(el) {
    var text = currentText(el);
    if (text.trim().length < MIN_CHARS) return;
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 8000);
    try {
      var res = await fetch(backendBase() + "/api/stealth/ghost-write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_context: text.slice(-2000), url: location.href }),
        signal: controller.signal,
      });
      if (!res.ok) return;
      var data = await res.json();
      if (data && data.ok && data.ghost_suggestion && document.contains(el)) {
        showOverlay(el, String(data.ghost_suggestion));
      }
    } catch (_) {
      /* silent: backend down or no model — never interrupt typing */
    } finally {
      clearTimeout(timeout);
    }
  }

  function attach(el) {
    if (el.dataset.ghostWriterAttached) return;
    el.dataset.ghostWriterAttached = "1";
    el.addEventListener("keyup", function (evt) {
      if (evt.key === "Escape") { hideOverlay(); return; }
      if (evt.key === "Tab" && overlay && activeEl === el) {
        evt.preventDefault();
        acceptSuggestion();
        return;
      }
      clearTimeout(timer);
      timer = setTimeout(function () { fetchSuggestion(el); }, DEBOUNCE_MS);
    });
    el.addEventListener("blur", function () {
      setTimeout(hideOverlay, 200);
    });
  }

  document.addEventListener("focusin", function (e) {
    var t = e.target;
    if (t && (t.tagName === "TEXTAREA" || t.isContentEditable)) attach(t);
  });
})();
