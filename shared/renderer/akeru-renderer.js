/**
 * akeru-renderer.js
 * ─────────────────────────────────────────────────────────────────────
 * Shared output formatter for all Akeru agent surfaces.
 * Standardises: SSE stream rendering, markdown parsing, post-processing.
 *
 * Usage
 *   AkeruRenderer.init({ agent, githubBase, postProcessors, theme });
 *   const msg = AkeruRenderer.createMessage(containerEl, "assistant");
 *   msg.appendToken(deltaText);   // call per SSE token
 *   msg.finalize();               // call on [DONE]
 *
 * Agents
 *   vidhi   — architecture agent (enables linkFilePaths, highlightSections)
 *   vanik   — trade compliance agent
 *   default — generic fallback
 *
 * Dependencies
 *   marked.js ≥ 9.x  (loaded by the host page from cdnjs)
 *   No other runtime dependencies.
 *
 * Repo path: shared/renderer/akeru-renderer.js
 */

(function (global) {
  "use strict";

  // ── Default config ────────────────────────────────────────────────
  const DEFAULTS = {
    agent: "default",
    assistantLabel: "Assistant",
    githubBase: "https://github.com/Nishant0203/akeru-dev/blob/main/",
    markedOptions: { breaks: true, gfm: true },
    postProcessors: ["linkFilePaths", "addCopyButtons"],
    theme: "night-sky",
  };

  let _cfg = { ...DEFAULTS };
  let _markedReady = false;

  // ── Post-processor registry ────────────────────────────────────────

  /**
   * linkFilePaths
   * Finds bare file paths like `vanik/nes/extractor.py` or
   * `session_store.py` inside text nodes and wraps them in <a> tags
   * pointing to GitHub. Skips paths already inside <a> or <code>.
   */
  function linkFilePaths(el) {
    if (!_cfg.githubBase) return;

    // Match Python/YAML/shell paths: optional leading `vanik/…` prefix,
    // ends with a known extension.
    const PATH_RE =
      /\b((?:[\w.-]+\/)*[\w.-]+\.(?:py|yaml|yml|sh|txt|md|json|env|toml|cfg|ini))\b/g;

    function walkText(node) {
      if (
        node.nodeType === Node.TEXT_NODE &&
        node.parentElement &&
        !["A", "CODE", "PRE"].includes(node.parentElement.tagName)
      ) {
        const text = node.textContent;
        if (!PATH_RE.test(text)) return;
        PATH_RE.lastIndex = 0;

        const frag = document.createDocumentFragment();
        let last = 0;
        let m;
        while ((m = PATH_RE.exec(text)) !== null) {
          if (m.index > last) {
            frag.appendChild(document.createTextNode(text.slice(last, m.index)));
          }
          const a = document.createElement("a");
          a.href = _cfg.githubBase + m[1];
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.className = "ar-file-link";
          a.textContent = m[1];
          frag.appendChild(a);
          last = m.index + m[0].length;
        }
        if (last < text.length) {
          frag.appendChild(document.createTextNode(text.slice(last)));
        }
        node.parentNode.replaceChild(frag, node);
      } else if (
        node.nodeType === Node.ELEMENT_NODE &&
        !["A", "CODE", "PRE", "SCRIPT", "STYLE"].includes(node.tagName)
      ) {
        // Clone childNodes to avoid live collection mutation during walk
        Array.from(node.childNodes).forEach(walkText);
      }
    }

    walkText(el);
  }

  /**
   * addCopyButtons
   * Appends a copy button to every <pre> block in the message.
   * Button is positioned top-right inside the pre.
   */
  function addCopyButtons(el) {
    el.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".ar-copy-btn")) return; // already added

      const btn = document.createElement("button");
      btn.className = "ar-copy-btn";
      btn.setAttribute("aria-label", "Copy code");
      btn.innerHTML =
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';

      btn.addEventListener("click", async () => {
        const code = pre.querySelector("code")?.textContent ?? pre.textContent;
        try {
          await navigator.clipboard.writeText(code.trim());
          btn.innerHTML =
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
          btn.classList.add("ar-copy-btn--ok");
          setTimeout(() => {
            btn.innerHTML =
              '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
            btn.classList.remove("ar-copy-btn--ok");
          }, 2000);
        } catch (_) {
          btn.textContent = "!";
        }
      });

      // pre needs position:relative for the button to anchor
      pre.style.position = "relative";
      pre.appendChild(btn);
    });
  }

  /**
   * highlightSections
   * Finds "Section N" or "Section N.M" references in text nodes and
   * wraps them in a <span> with a subtle underline + tooltip.
   * Vidhi-specific — architecture doc section references.
   */
  function highlightSections(el) {
    const SECTION_RE = /\bSection\s+(\d+(?:\.\d+)?(?:[a-z])?)\b/g;

    function walkText(node) {
      if (
        node.nodeType === Node.TEXT_NODE &&
        node.parentElement &&
        !["A", "CODE", "PRE"].includes(node.parentElement.tagName) &&
        !node.parentElement.classList.contains("ar-section-ref")
      ) {
        const text = node.textContent;
        if (!SECTION_RE.test(text)) return;
        SECTION_RE.lastIndex = 0;

        const frag = document.createDocumentFragment();
        let last = 0;
        let m;
        while ((m = SECTION_RE.exec(text)) !== null) {
          if (m.index > last) {
            frag.appendChild(document.createTextNode(text.slice(last, m.index)));
          }
          const span = document.createElement("span");
          span.className = "ar-section-ref";
          span.textContent = m[0];
          span.title = `Architecture Document — Section ${m[1]}`;
          frag.appendChild(span);
          last = m.index + m[0].length;
        }
        if (last < text.length) {
          frag.appendChild(document.createTextNode(text.slice(last)));
        }
        node.parentNode.replaceChild(frag, node);
      } else if (
        node.nodeType === Node.ELEMENT_NODE &&
        !["CODE", "PRE", "SCRIPT", "STYLE"].includes(node.tagName)
      ) {
        Array.from(node.childNodes).forEach(walkText);
      }
    }

    walkText(el);
  }

  const PROCESSOR_MAP = {
    linkFilePaths,
    addCopyButtons,
    highlightSections,
  };

  // ── Agent presets ─────────────────────────────────────────────────
  const AGENT_PRESETS = {
    vidhi: {
      assistantLabel: "Vidhi",
      postProcessors: ["linkFilePaths", "addCopyButtons", "highlightSections"],
    },
    vanik: {
      assistantLabel: "Vanik",
      postProcessors: ["addCopyButtons"],
    },
    default: {
      assistantLabel: "Assistant",
      postProcessors: ["addCopyButtons"],
    },
  };

  // ── Markdown setup ────────────────────────────────────────────────
  function _ensureMarked() {
    if (_markedReady) return true;
    if (typeof marked === "undefined") {
      console.warn("[AkeruRenderer] marked.js not loaded. Falling back to plain text.");
      return false;
    }
    marked.setOptions(_cfg.markedOptions);
    // Custom renderer — open links in new tab
    const renderer = new marked.Renderer();
    const _origLink = renderer.link.bind(renderer);
    renderer.link = (href, title, text) => {
      const html = _origLink(href, title, text);
      return html.replace(/^<a /, '<a target="_blank" rel="noopener noreferrer" ');
    };
    marked.use({ renderer });
    _markedReady = true;
    return true;
  }

  function _parseMarkdown(raw) {
    if (!_ensureMarked()) return _escapeHtml(raw).replace(/\n/g, "<br>");
    try {
      return marked.parse(raw);
    } catch (e) {
      console.error("[AkeruRenderer] marked.parse error", e);
      return _escapeHtml(raw);
    }
  }

  function _escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Core API ──────────────────────────────────────────────────────

  /**
   * init(options)
   * Call once per page load. Merges agent preset with explicit options.
   */
  function init(options = {}) {
    const preset = AGENT_PRESETS[options.agent] ?? AGENT_PRESETS.default;
    _cfg = {
      ...DEFAULTS,
      ...preset,
      ...options,
    };
    _markedReady = false; // reset so marked picks up new options
  }

  /**
   * createMessage(containerEl, role)
   * Creates a message bubble in containerEl and returns a controller.
   *
   * role: "user" | "assistant"
   *
   * Returns { el, bodyEl, appendToken(str), finalize(), setText(str) }
   */
  function createMessage(containerEl, role) {
    const wrap = document.createElement("div");
    wrap.className = `ar-msg ar-msg--${role}`;

    const roleEl = document.createElement("div");
    roleEl.className = "ar-msg-role";
    roleEl.textContent = role === "user" ? "You" : (_cfg.assistantLabel || "Assistant");

    const bodyEl = document.createElement("div");
    bodyEl.className = "ar-msg-body";

    wrap.append(roleEl, bodyEl);
    containerEl.appendChild(wrap);

    // Scroll container to bottom
    containerEl.scrollTop = containerEl.scrollHeight;

    let _raw = "";
    let _cursor = null;

    function _addCursor() {
      if (_cursor) return;
      _cursor = document.createElement("span");
      _cursor.className = "ar-cursor";
      bodyEl.appendChild(_cursor);
    }

    function _removeCursor() {
      if (_cursor) {
        _cursor.remove();
        _cursor = null;
      }
    }

    function _scroll() {
      containerEl.scrollTop = containerEl.scrollHeight;
    }

    return {
      el: wrap,
      bodyEl,

      /**
       * appendToken(str)
       * Safe to call 10-100 times per second during SSE stream.
       * Uses textContent — no HTML injection risk during streaming.
       */
      appendToken(delta) {
        _raw += delta;
        _removeCursor();
        bodyEl.textContent = _raw;
        _addCursor();
        _scroll();
      },

      /**
       * finalize()
       * Called once on SSE [DONE]. Parses markdown, runs post-processors.
       */
      finalize() {
        _removeCursor();
        if (!_raw.trim()) {
          bodyEl.textContent = _raw;
          return;
        }

        // Parse markdown → HTML
        bodyEl.innerHTML = _parseMarkdown(_raw);

        // Run post-processors
        const procs = _cfg.postProcessors ?? [];
        procs.forEach((name) => {
          const fn = PROCESSOR_MAP[name];
          if (fn) {
            try {
              fn(bodyEl);
            } catch (e) {
              console.warn(`[AkeruRenderer] post-processor '${name}' error:`, e);
            }
          }
        });

        _scroll();
      },

      /**
       * setText(str)
       * Sets static text without streaming (for error messages, welcome cards).
       * Still runs post-processors.
       */
      setText(str) {
        _raw = str;
        this.finalize();
      },

      /** Raw accumulated text — useful for pushing into history state. */
      get raw() {
        return _raw;
      },
    };
  }

  // ── Public API ────────────────────────────────────────────────────
  global.AkeruRenderer = { init, createMessage };
})(window);
