/**
 * vidhi-panel.js
 * ─────────────────────────────────────────────────────────────────
 * Anchor-triggered Vidhi side panel for φ¹ and φ² post pages.
 *
 * Post-agnostic: concept config from each page; POST /vidhi/api/chat;
 * streams via AkeruRenderer when present.
 *
 * Public API
 *   VidhiPanel.init(options)
 *   VidhiPanel.open(conceptKey, conceptConfig)
 *   VidhiPanel.close()
 *
 * Alias: VIdhiPanel (legacy typo) → VidhiPanel
 *
 * Repo path: shared/panel/vidhi-panel.js
 */

(function (global) {
  "use strict";

  const UNLOCK_KEY = "vidhi_gemini_unlock_code";

  const DEFAULTS = {
    apiBase: "https://api.akeru.dev",
    model: "ollama/llama3.1:8b",
    accessCode: "",
    postId: "phi1",
  };

  let _cfg = { ...DEFAULTS };

  let _panel = null;
  let _header = null;
  let _messages = null;
  let _textarea = null;
  let _sendBtn = null;
  let _closeBtn = null;

  let _history = [];
  let _streaming = false;
  let _sessionId = _uuid();
  let _currentKey = null;
  /** Full concept row from registry — preserved for follow-ups */
  let _currentConfig = null;

  function init(options = {}) {
    _cfg = { ...DEFAULTS, ...options };
    _ensureDOM();
    _attachKeyHandler();
  }

  function open(conceptKey, conceptConfig) {
    if (!_panel) _ensureDOM();

    if (_currentKey === conceptKey && _panel.classList.contains("vp-open")) return;

    _currentKey = conceptKey;
    _currentConfig = conceptConfig
      ? { ...conceptConfig, concept_key: conceptConfig.concept_key || conceptKey }
      : { concept_key: conceptKey, section: "general", context: "", opening_mode: "answer" };
    _history = [];
    _sessionId = _uuid();
    _streaming = false;

    _header.textContent = (_currentConfig && _currentConfig.label) || conceptKey;
    _messages.innerHTML = "";

    document.querySelectorAll(".vidhi-anchor").forEach(function (el) {
      el.classList.toggle("vp-active", el.dataset.concept === conceptKey);
    });

    _panel.classList.add("vp-open");
    document.body.classList.add("vp-body-open");

    _fireRequest(_currentConfig, null);
  }

  function close() {
    if (!_panel) return;
    _panel.classList.remove("vp-open");
    document.body.classList.remove("vp-body-open");

    document.querySelectorAll(".vidhi-anchor").forEach(function (el) {
      el.classList.remove("vp-active");
    });

    _currentKey = null;
    _currentConfig = null;
    _history = [];
    _streaming = false;
  }

  function _ensureDOM() {
    if (_panel) return;

    _panel = _el("aside", { class: "vidhi-panel" });

    const headerRow = _el("div", { class: "vp-header" });
    const labelWrap = _el("div", { class: "vp-label-wrap" });
    const eyebrow = _el("span", { class: "vp-eyebrow" });
    eyebrow.textContent = "Vidhi · विधि";
    _header = _el("div", { class: "vp-concept-label" });
    labelWrap.append(eyebrow, _header);

    _closeBtn = _el("button", { class: "vp-close", "aria-label": "Close" });
    _closeBtn.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    _closeBtn.addEventListener("click", close);

    headerRow.append(labelWrap, _closeBtn);

    _messages = _el("div", { class: "vp-messages" });

    const inputRow = _el("div", { class: "vp-input-row" });
    const inputWrap = _el("div", { class: "vp-input-wrap" });
    _textarea = _el("textarea", {
      class: "vp-textarea",
      rows: "1",
      placeholder: "Ask a follow-up…",
      "aria-label": "Ask Vidhi",
    });
    _sendBtn = _el("button", { class: "vp-send-btn" });
    _sendBtn.textContent = "↵";

    _textarea.addEventListener("input", _autoResize);
    _textarea.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!_streaming) _sendFollowUp();
      }
    });
    _sendBtn.addEventListener("click", function () {
      if (!_streaming) _sendFollowUp();
    });

    inputWrap.append(_textarea);
    inputRow.append(inputWrap, _sendBtn);

    _panel.append(headerRow, _messages, inputRow);
    document.body.appendChild(_panel);
  }

  function _attachKeyHandler() {
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  function _accessCode() {
    try {
      return (sessionStorage.getItem(UNLOCK_KEY) || _cfg.accessCode || "").trim();
    } catch (_) {
      return (_cfg.accessCode || "").trim();
    }
  }

  async function _fireRequest(conceptConfig, userMessage) {
    const isFirstTurn = userMessage === null;
    const turnContent = isFirstTurn
      ? "[Exploring: " + (conceptConfig.label || conceptConfig.concept_key || "concept") + "]"
      : userMessage;

    _history.push({ role: "user", content: turnContent });

    const msgEl = _appendAssistantBubble();
    _streaming = true;
    _sendBtn.disabled = true;
    _textarea.disabled = true;

    try {
      const body = {
        model: _cfg.model,
        session_id: _sessionId,
        post_id: _cfg.postId,
        concept_key: conceptConfig.concept_key || "",
        section: conceptConfig.section || "general",
        history: _history,
        access_code: _accessCode(),
        anchor_context: conceptConfig.context || "",
        opening_mode: conceptConfig.opening_mode || "answer",
      };

      const apiBase = (global.VIDHI_API_URL || _cfg.apiBase || "").replace(/\/$/, "");
      const res = await fetch(apiBase + "/vidhi/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) throw new Error("HTTP " + res.status);

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      let out = "";

      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buf += dec.decode(chunk.value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (let li = 0; li < lines.length; li++) {
          const line = lines[li];
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (data === "[DONE]") break;
          try {
            const delta = JSON.parse(data).choices?.[0]?.delta?.content ?? "";
            out += delta;
            if (msgEl._ar) {
              msgEl._ar.appendToken(delta);
            } else {
              msgEl.bodyEl.textContent = out;
            }
          } catch (_) {
            /* ignore malformed SSE lines */
          }
        }
      }

      if (msgEl._ar) {
        msgEl._ar.finalize();
      } else {
        msgEl.bodyEl.textContent = out;
      }

      _history.push({ role: "assistant", content: out });
    } catch (err) {
      const msg = "[Error: " + (err && err.message ? err.message : String(err)) + "]";
      if (msgEl._ar) {
        msgEl._ar.setText(msg);
      } else {
        msgEl.bodyEl.textContent = msg;
      }
    }

    _streaming = false;
    _sendBtn.disabled = false;
    _textarea.disabled = false;
    _textarea.focus();
  }

  function _sendFollowUp() {
    const text = _textarea.value.trim();
    if (!text) return;
    _textarea.value = "";
    _autoResize.call(_textarea);

    _appendUserBubble(text);

    const base =
      _currentConfig ||
      ({
        concept_key: _currentKey,
        section: "general",
        context: "",
        opening_mode: "answer",
      });
    _fireRequest(
      {
        ...base,
        concept_key: base.concept_key || _currentKey,
      },
      text
    );
  }

  function _appendUserBubble(text) {
    const wrap = _el("div", { class: "vp-msg vp-msg--user" });
    const role = _el("div", { class: "vp-role" });
    role.textContent = "You";
    const body = _el("div", { class: "vp-body" });
    body.textContent = text;
    wrap.append(role, body);
    _messages.appendChild(wrap);
    _scrollBottom();
    return { wrap: wrap, bodyEl: body };
  }

  function _appendAssistantBubble() {
    if (typeof global.AkeruRenderer !== "undefined") {
      const ar = global.AkeruRenderer.createMessage(_messages, "assistant");
      _scrollBottom();
      return { wrap: ar.el, bodyEl: ar.bodyEl, _ar: ar };
    }

    const wrap = _el("div", { class: "vp-msg vp-msg--assistant" });
    const role = _el("div", { class: "vp-role" });
    role.textContent = "Vidhi";
    const body = _el("div", { class: "vp-body" });
    const cursor = _el("span", { class: "vp-cursor" });
    body.appendChild(cursor);
    wrap.append(role, body);
    _messages.appendChild(wrap);
    _scrollBottom();
    return { wrap: wrap, bodyEl: body, _ar: null };
  }

  function _scrollBottom() {
    _messages.scrollTop = _messages.scrollHeight;
  }

  function _el(tag, attrs) {
    const el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        el.setAttribute(k, attrs[k]);
      });
    }
    return el;
  }

  function _autoResize() {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 120) + "px";
  }

  function _uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  const api = { init: init, open: open, close: close };
  global.VidhiPanel = api;
  global.VIdhiPanel = api;
})(window);
