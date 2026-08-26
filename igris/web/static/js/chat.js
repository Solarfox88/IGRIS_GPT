// IGRIS_GPT — Chat module (#1318)
// Extracted from app.js: chat UI, messages, streaming, markdown rendering.
import { $, $$, esc } from "./utils.js";
import { api, apiWithTimeout } from "./api.js";

  // Chat
    var sessionId = null;
    var form = $("#chat-form");
    if (!form) return;
    var chatContainer = $("#chat-messages");
    var userNearBottom = true;

    // Track scroll position for auto-scroll
    if (chatContainer) {
      chatContainer.addEventListener("scroll", function () {
        var threshold = 60;
        userNearBottom = (chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight) < threshold;
      });
    }

    // ---- AUTH GATE HELPERS (#1285) ─────────────────────────────────────────
    // MUST be inside this IIFE to access addMsg (closure scope).
    function isAuthenticatedForChat() {
      return typeof getSessionToken === "function" && !!getSessionToken();
    }
    function requireAuthBeforeChat(message) {
      if (isAuthenticatedForChat()) return false;
      if (typeof handleUnauthenticatedMessage === "function") {
        handleUnauthenticatedMessage(message, function(text, role) {
          addMsg(role || "assistant", text);
        });
      } else {
        addMsg("assistant", "Prima di continuare devo riconoscerti. Accedi oppure registrati.");
      }
      return true;
    }

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      var inp = $("#chat-input");
      var msg = inp.value.trim();
      if (!msg) return;
      if (_supervisorPromptLike(msg)) {
        addMsg("user", msg);
        inp.value = "";
        addMsg(
          "assistant",
          "This looks like a supervised rank mission request. Use the Dashboard launcher: Start Supervised Mission in Rank / Mission Launcher."
        );
        return;
      }
      // Auth-first gate (#1278/#1285): central check — all send paths must use requireAuthBeforeChat
      if (requireAuthBeforeChat(msg)) return;
      addMsg("user", msg);
      inp.value = "";
      if (!sessionId) {
        var s = await api("POST", "/api/sessions");
        if (s.ok) sessionId = s.data.id;
      }
      if (!sessionId) { addMsg("assistant", "Failed to create session"); return; }
      addMsg("assistant", "...", "typing");
      // PR4/PR5: session token is source of truth — send via Authorization header.
      // interlocutor_id retained as local fallback when no session is active.
      var _iid = window._igrisInterlocutorId || "owner";
      var _chatHeaders = (typeof authHeaders === "function") ? authHeaders() : {};
      var r = await api("POST", "/api/sessions/" + sessionId + "/messages",
        { message: msg, interlocutor_id: _iid },
        _chatHeaders);
      removeTyping();
      if (r.ok) {
        // Operator-grade block message (v4)
        if (r.data.blocked) {
          var blockMsg = [
            "⛔ **Richiesta bloccata**",
            "",
            r.data.response || "Accesso negato.",
            "",
            "**Trust level**: " + (r.data.trust_level || "unknown"),
            "**Per sbloccare**: fornisci una delegation key o identifica il tuo profilo."
          ].join("\n");
          addMsg("assistant", blockMsg, "blocked");
        } else {
          var meta = {
            provider: r.data.provider,
            model: r.data.model,
            latency_ms: r.data.latency_ms,
            fallback_used: r.data.fallback_used,
            intent: r.data.intent_detected || null,
            actions: r.data.suggested_actions || [],
          };
          addMsg("assistant", r.data.response, null, meta);
          // Show intent strip if intent detected (v4)
          var intentStrip = $("#intent-strip");
          if (intentStrip && r.data.intent_detected) {
            intentStrip.style.display = "flex";
            var intentAction = $("#intent-action");
            var intentRisk = $("#intent-risk");
            var intentTarget = $("#intent-target");
            if (intentAction) intentAction.textContent = r.data.intent_detected || "—";
            if (intentRisk) intentRisk.textContent = r.data.risk_level || r.data.risk || "—";
            if (intentTarget) intentTarget.textContent = r.data.target || "—";
          }
        }
      } else {
        addMsg("assistant", "Error: " + (r.data.detail || "unknown"));
      }
    });

    // Safe markdown renderer — no raw HTML injection
    function renderMarkdown(text) {
      if (!text) return "";
      // Escape HTML first to prevent XSS
      var escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

      // Code blocks (```...```)
      escaped = escaped.replace(/```(\w*)\n?([\s\S]*?)```/g, function (m, lang, code) {
        return '<pre><code class="lang-' + lang + '">' + code.trim() + '</code><button class="copy-btn" onclick="igrisCopyCode(this)">copy</button></pre>';
      });

      // Inline code (`...`)
      escaped = escaped.replace(/`([^`\n]+)`/g, '<code>$1</code>');

      // Bold (**...**)
      escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

      // Split into blocks by double newline
      var blocks = escaped.split(/\n\n+/);
      var html = "";
      for (var i = 0; i < blocks.length; i++) {
        var block = blocks[i].trim();
        if (!block) continue;
        if (block.startsWith("<pre>")) {
          html += block;
        } else if (/^[-*]\s/.test(block) || /^\n?[-*]\s/.test(block)) {
          // Bullet list
          var items = block.split(/\n/).filter(function (l) { return l.trim(); });
          html += "<ul>";
          for (var j = 0; j < items.length; j++) {
            html += "<li>" + items[j].replace(/^[-*]\s+/, "") + "</li>";
          }
          html += "</ul>";
        } else if (/^\d+\.\s/.test(block)) {
          // Numbered list
          var items2 = block.split(/\n/).filter(function (l) { return l.trim(); });
          html += "<ol>";
          for (var k = 0; k < items2.length; k++) {
            html += "<li>" + items2[k].replace(/^\d+\.\s+/, "") + "</li>";
          }
          html += "</ol>";
        } else {
          // Handle single newlines as line items within a paragraph-like block
          var lines = block.split(/\n/);
          if (lines.length > 1 && lines.every(function (l) { return /^[-*]\s/.test(l.trim()); })) {
            html += "<ul>";
            for (var m = 0; m < lines.length; m++) {
              html += "<li>" + lines[m].replace(/^[-*]\s+/, "") + "</li>";
            }
            html += "</ul>";
          } else {
            html += "<p>" + block.replace(/\n/g, "<br>") + "</p>";
          }
        }
      }
      return html;
    }

    function addMsg(role, text, cls, meta) {
      var container = $("#chat-messages");
      var d = document.createElement("div");
      d.className = "msg msg-" + role + (cls ? " " + cls : "");

      if (role === "assistant" && !cls) {
        // Render markdown for assistant messages
        d.innerHTML = renderMarkdown(text);
        // Add suggested action buttons if available
        if (meta && meta.actions && meta.actions.length > 0) {
          var actionsDiv = document.createElement("div");
          actionsDiv.className = "suggested-actions";
          for (var ai = 0; ai < meta.actions.length; ai++) {
            var act = meta.actions[ai];
            var btn = document.createElement("button");
            btn.className = "action-card" + (act.approval_required ? " action-gated" : "");
            btn.innerHTML = '<span class="action-label">' + escapeHtml(act.label) + '</span>' +
              '<span class="action-desc">' + escapeHtml(act.description) + '</span>' +
              (act.approval_required ? '<span class="action-lock">requires approval</span>' : '');
            btn.dataset.endpoint = act.endpoint;
            btn.dataset.method = act.method || "GET";
            btn.dataset.payload = act.payload ? JSON.stringify(act.payload) : "";
            btn.addEventListener("click", handleActionClick);
            actionsDiv.appendChild(btn);
          }
          d.appendChild(actionsDiv);
        }
        // Add metadata line if available
        if (meta && meta.provider) {
          var metaDiv = document.createElement("div");
          metaDiv.className = "msg-meta";
          var provLabel = meta.provider === "igris_personality" ? "IGRIS" :
                          meta.provider === "deterministic" ? "fallback" :
                          meta.provider + "/" + meta.model;
          metaDiv.innerHTML = '<span class="meta-provider">' + escapeHtml(provLabel) + '</span>' +
            (meta.latency_ms != null ? '<span>' + meta.latency_ms + 'ms</span>' : '') +
            (meta.intent ? '<span>intent: ' + escapeHtml(meta.intent) + '</span>' : '');
          d.appendChild(metaDiv);
        }
      } else {
        d.textContent = text;
      }

      container.appendChild(d);
      if (userNearBottom) {
        container.scrollTop = container.scrollHeight;
      }
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    async function handleActionClick(e) {
      var btn = e.currentTarget;
      var endpoint = btn.dataset.endpoint;
      var method = btn.dataset.method || "GET";
      var payloadStr = btn.dataset.payload;

      btn.disabled = true;
      btn.classList.add("action-loading");

      var payload = payloadStr ? JSON.parse(payloadStr) : null;
      var r;
      if (method === "POST") {
        r = await api("POST", endpoint, payload || {});
      } else {
        r = await api("GET", endpoint);
      }

      btn.disabled = false;
      btn.classList.remove("action-loading");

      if (r.ok) {
        var resultText = JSON.stringify(r.data, null, 2);
        if (resultText.length > 2000) resultText = resultText.substring(0, 2000) + "\n...";
        addMsg("assistant", "```json\n" + resultText + "\n```");
      } else {
        addMsg("assistant", "Error: " + (r.data.detail || "request failed"));
      }
    }

    function removeTyping() {
      var el = $(".msg.typing");
      if (el) el.remove();
    }

  // Global copy function for code blocks
  window.igrisCopyCode = function (btn) {
    var pre = btn.parentElement;
    var code = pre.querySelector("code");
    if (code) {
      navigator.clipboard.writeText(code.textContent).then(function () {
        btn.textContent = "copied!";
        setTimeout(function () { btn.textContent = "copy"; }, 1500);
      });
    }
  };

