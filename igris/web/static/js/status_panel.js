// IGRIS_GPT — Status Panel module (#1318)
// Extracted from app.js: Status Panel, Hint Chips, Textarea, Advisory Rendering.
import { $, esc } from "./utils.js";


  // ---- STATUS PANEL ----
  function loadStatusPanel() {
    // Load interlocutor/audit from diagnostics summary
    fetch("/api/diagnostics/summary").then(function(r) { return r.json(); }).then(function(d) {
      // Sidebar status dot
      var dot = $("#sidebar-status-dot");
      if (dot) {
        var ok = d.health && d.health.status === "ok";
        dot.style.background = ok ? "#22c55e" : "#ef4444";
      }

      var il = d.interlocutor || {};
      var profiles = il.profiles || [];
      var lastChat = il.last_chat || {};

      // Top bar identity
      var tbName = $("#tb-name");
      var tbTrust = $("#tb-trust");
      var tbAvatar = $("#tb-avatar");
      var tbMode = $("#tb-mode");

      var tbStateBadge = $("#tb-identity-state");
      var tbSafetyNote = $("#tb-safety-note");

      function applyIdentityBadge(trustLevel, interlocutorId) {
        if (!tbStateBadge) return;
        var state = "unknown";
        var label = "unknown";
        var tl = (trustLevel || "").toLowerCase();
        var iid = (interlocutorId || "").toLowerCase();
        if (tl === "admin" || tl === "full" || iid === "owner" || iid === "admin") {
          state = "owner"; label = "🔒 owner/admin";
        } else if (tl === "trusted" || tl === "recognized") {
          state = "recognized"; label = "recognized";
        } else if (tl === "delegated" || iid.indexOf("delegation") >= 0) {
          state = "delegated"; label = "delegated";
        } else if (tl === "system" || tl === "internal" || iid === "system") {
          state = "system"; label = "system";
        } else if (tl === "untrusted" || tl === "unknown" || !trustLevel) {
          state = "unknown"; label = "unknown";
        } else {
          state = "recognized"; label = tl;
        }
        tbStateBadge.className = "identity-state-badge state-" + state;
        tbStateBadge.textContent = label;
        if (tbSafetyNote) {
          if (state === "owner") {
            tbSafetyNote.textContent = "Destructive actions remain gated";
            tbSafetyNote.classList.add("visible");
          } else {
            tbSafetyNote.classList.remove("visible");
          }
        }
      }

      // If auth.js has set an authenticated profile, skip overwriting topbar/sidebar
      // with stale diagnostics data (lastChat is from pre-auth chat, still unknown).
      var _authPid = window._igrisAuthProfileId;
      if (!_authPid) {
        if (lastChat.interlocutor_id) {
          if (tbName) tbName.textContent = lastChat.interlocutor_id;
          if (tbTrust) tbTrust.textContent = lastChat.trust_level || "—";
          if (tbAvatar) tbAvatar.textContent = (lastChat.interlocutor_id || "?")[0].toUpperCase();
          if (tbMode) tbMode.textContent = lastChat.response_mode ? "· " + lastChat.response_mode : "";
          applyIdentityBadge(lastChat.trust_level, lastChat.interlocutor_id);
        } else if (profiles.length > 0) {
          var p0 = profiles[0];
          if (tbName) tbName.textContent = p0.display_name || p0.profile_id || "—";
          if (tbTrust) tbTrust.textContent = p0.trust_level || "—";
          if (tbAvatar) tbAvatar.textContent = ((p0.display_name || p0.profile_id || "?")[0] || "?").toUpperCase();
          applyIdentityBadge(p0.trust_level, p0.profile_id);
        }
      }

      // Chat header meta — skip if auth has already set it
      var chatMeta = $("#chat-interlocutor-meta");
      if (chatMeta && !_authPid && (lastChat.interlocutor_id || profiles.length > 0)) {
        var iname = lastChat.interlocutor_id || (profiles[0] && (profiles[0].display_name || profiles[0].profile_id)) || "";
        var itrust = lastChat.trust_level || (profiles[0] && profiles[0].trust_level) || "";
        chatMeta.textContent = iname ? (iname + (itrust ? " / " + itrust : "")) : "non autenticato";
      }

      // Status panel interlocutor — skip if auth has already set it
      var spIC = $("#sp-interlocutor-content");
      if (spIC && !_authPid) {
        if (profiles.length > 0) {
          var p = profiles[0];
          var name = p.display_name || p.profile_id || "—";
          spIC.innerHTML = '<div class="interlocutor-card">' +
            '<div class="ic-header">' +
            '<div class="ic-avatar">' + esc(name[0].toUpperCase()) + '</div>' +
            '<div><div class="ic-name">' + esc(name) + '</div>' +
            '<div class="ic-sub">' + esc(p.trust_level || "—") + '</div></div>' +
            '</div>' +
            '<div class="ic-badges"><span class="ic-badge trusted">' + esc(p.trust_level || "") + '</span></div>' +
            '</div>';
          if (lastChat.last_intent) {
            spIC.innerHTML += '<div class="kv-row"><span class="kv-key">intent</span><span class="kv-val blue">' + esc(lastChat.last_intent) + '</span></div>';
          }
          if (lastChat.response_mode) {
            spIC.innerHTML += '<div class="kv-row"><span class="kv-key">mode</span><span class="kv-val">' + esc(lastChat.response_mode) + '</span></div>';
          }
        } else {
          // No profiles available — show fallback, never leave as loading
          var fallbackName = (lastChat && lastChat.interlocutor_id) ? lastChat.interlocutor_id : "unknown";
          var fallbackTrust = (lastChat && lastChat.trust_level) ? lastChat.trust_level : "untrusted";
          spIC.innerHTML = '<div class="kv-row"><span class="kv-key">interlocutore</span><span class="kv-val">' + esc(fallbackName) + ' · ' + esc(fallbackTrust) + '</span></div>';
        }
      }

      // Audit trail
      var spAudit = $("#sp-audit-content");
      if (spAudit && il.recent_audit) {
        var html = "";
        var events = il.recent_audit.slice(-5);
        events.forEach(function(e) {
          var dotClass = (e.decision === "denied" || (e.event_type || "").indexOf("denied") >= 0) ? "deny" :
                         ((e.event_type || "").indexOf("advisory") >= 0 || (e.event_type || "").indexOf("warn") >= 0) ? "warn" : "ok";
          html += '<div class="audit-item">' +
            '<div class="audit-dot ' + dotClass + '"></div>' +
            '<div class="audit-text">' + esc((e.event_type || "") + (e.action_type ? ": " + e.action_type : "")) + '</div>' +
            '<div class="audit-time">' + esc((String(e.ts || "")).slice(11, 16)) + '</div>' +
            '</div>';
        });
        spAudit.innerHTML = html || '<span class="sp-empty">Nessun audit recente</span>';
      } else if (spAudit) {
        spAudit.innerHTML = '<span class="sp-empty">Nessun audit recente</span>';
      }
    }).catch(function() {
      // API unavailable — replace loading states with error fallback
      var spIC2 = $("#sp-interlocutor-content");
      if (spIC2 && spIC2.querySelector && spIC2.querySelector(".loading")) {
        spIC2.innerHTML = '<span class="sp-error">Errore caricamento</span>';
      }
      var spAudit2 = $("#sp-audit-content");
      if (spAudit2 && spAudit2.querySelector && spAudit2.querySelector(".loading")) {
        spAudit2.innerHTML = '<span class="sp-error">Errore caricamento</span>';
      }
    });

    // Rank — only reload every 5 minutes (rarely changes)
    if (!window._lastRankLoad || Date.now() - window._lastRankLoad > 300000) {
      window._lastRankLoad = Date.now();
    fetch("/api/rank/gauntlet").then(function(r) { return r.json(); }).then(function(d) {
      var spRank = $("#sp-rank-content");
      var tbRank = $("#tb-rank");
      if (!spRank) return;
      var rank = d.rank || "—";
      var score = Math.round((d.score || 0) * 100);
      if (tbRank) tbRank.textContent = "Rank " + rank;
      var checks = d.checks || [];
      var passed = checks.filter(function(c) { return c.passed; }).length;
      spRank.innerHTML = '<div class="rank-card">' +
        '<div class="rank-card-top">' +
        '<div><div class="rank-letter">' + esc(rank) + '</div>' +
        '<div class="rank-label">' + esc(d.passed ? "passed" : "reserve") + '</div></div>' +
        '<div style="text-align:right"><div style="font-size:18px;font-weight:700;color:#a78bfa">' + score + '%</div>' +
        '<div style="font-size:9px;color:var(--text3)">runtime-wired</div></div>' +
        '</div>' +
        '<div class="rank-score-bar"><div class="rank-score-fill" style="width:' + score + '%"></div></div>' +
        '<div class="rank-score-label">' + esc(passed + "/" + checks.length + " checks") + '</div>' +
        '</div>';
    }).catch(function() {});
    } // end rank throttle

    // CI/Tests from rank status — throttled to every 2 minutes
    if (!window._lastCILoad || Date.now() - window._lastCILoad > 120000) {
      window._lastCILoad = Date.now();
    fetch("/api/rank/status").then(function(r) { return r.json(); }).then(function(d) {
      var spCI = $("#sp-ci-content");
      if (!spCI) return;
      var rankId = d.rank_id || d.rank || "—";
      var isOk = d.status === "ok" || d.status === "green";
      spCI.innerHTML = '<div class="ci-bar">' +
        '<div class="ci-bar-top"><span class="ci-bar-label">System</span>' +
        '<span class="ci-bar-status" style="color:' + (isOk ? 'var(--green)' : 'var(--yellow)') + '">' +
        esc(d.status || "—") + '</span></div>' +
        '<div class="ci-progress"><div class="ci-progress-fill"></div></div>' +
        '<div class="ci-detail">rank_id: ' + esc(rankId) + '</div>' +
        '</div>';
      // Update topbar CI dot
      var ciDot = $("#tb-ci-dot");
      if (ciDot) ciDot.style.background = isOk ? "#22c55e" : "#f59e0b";
    }).catch(function() {});
    } // end CI throttle
  }

  // ---- HINT CHIPS ----
  document.querySelectorAll(".hint-chip").forEach(function(chip) {
    chip.addEventListener("click", function() {
      var inp = $("#chat-input");
      if (inp) { inp.value = chip.dataset.msg || ""; inp.focus(); }
    });
  });

  // ---- INTENT STRIP TOGGLE (v4) ----
  (function() {
    var toggle = $("#intent-toggle");
    var content = $("#intent-content");
    if (!toggle || !content) return;
    // Restore localStorage state
    var collapsed = localStorage.getItem("igris_intent_collapsed") === "1";
    if (collapsed) content.classList.add("collapsed");
    toggle.addEventListener("click", function() {
      collapsed = !collapsed;
      content.classList.toggle("collapsed", collapsed);
      localStorage.setItem("igris_intent_collapsed", collapsed ? "1" : "0");
    });
  })();

  // ---- TEXTAREA AUTO-RESIZE + ENTER TO SEND ----
  (function() {
    var inp = $("#chat-input");
    if (!inp || inp.tagName !== "TEXTAREA") return;
    inp.addEventListener("input", function() {
      inp.style.height = "auto";
      inp.style.height = Math.min(inp.scrollHeight, 120) + "px";
    });
    inp.addEventListener("keydown", function(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        var form = $("#chat-form");
        if (form) form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      }
    });
  })();

  // ---- ADVISORY / AUTH RENDERING (extend existing addMsg) ----
  // Patch the chat response handler to annotate blocked/advisory messages
  var _origChatHandler = null;
  (function() {
    var form = $("#chat-form");
    if (!form) return;
    // We listen for response and patch class on the last assistant message
    var originalSubmit = form.onsubmit;
    // The existing handler is an event listener — we wrap by intercepting
    // fetch responses via MutationObserver on chat-messages
    var chatMessages = $("#chat-messages");
    if (!chatMessages) return;
    var observer = new MutationObserver(function(mutations) {
      mutations.forEach(function(mut) {
        mut.addedNodes.forEach(function(node) {
          if (node.nodeType !== 1) return;
          // Check if it's an assistant message that should be advisory
          if (node.classList && node.classList.contains("msg-assistant") && !node.classList.contains("typing")) {
            var text = node.textContent || "";
            // Already has explicit class from addMsg (e.g. blocked) — skip auto-detect to avoid double labels
            var alreadyLabeled = node.classList.contains("blocked") || node.classList.contains("advisory") ||
                                 node.classList.contains("warning") || node.classList.contains("requires-confirmation");
            if (alreadyLabeled) {
              // Add appropriate label prefix if not present
              if (node.classList.contains("blocked") && !node.querySelector(".blocked-label")) {
                var bl = document.createElement("div");
                bl.className = "blocked-label"; bl.textContent = "⛔ Blocked";
                node.insertBefore(bl, node.firstChild);
              }
              return;
            }
            // Auto-detect advisory patterns
            if (text.indexOf("JudgmentLayer") >= 0 || text.indexOf("Advisory") >= 0 || text.indexOf("advisory") >= 0) {
              node.classList.add("advisory");
              if (!node.querySelector(".advisory-label")) {
                var label = document.createElement("div");
                label.className = "advisory-label";
                label.textContent = "⚠️ Advisory";
                node.insertBefore(label, node.firstChild);
              }
            }
            // Auto-detect warning patterns
            if (text.indexOf("warning") >= 0 || text.indexOf("attenzione") >= 0) {
              node.classList.add("warning");
              if (!node.querySelector(".warning-label")) {
                var wl = document.createElement("div");
                wl.className = "warning-label"; wl.textContent = "🚫 Warning";
                node.insertBefore(wl, node.firstChild);
              }
            }
            // Auto-detect blocked patterns
            if (text.indexOf("bloccata") >= 0 || text.indexOf("denied") >= 0 ||
                (text.indexOf("blocked") >= 0 && !node.classList.contains("advisory"))) {
              node.classList.add("blocked");
              if (!node.querySelector(".blocked-label")) {
                var bll = document.createElement("div");
                bll.className = "blocked-label"; bll.textContent = "⛔ Blocked";
                node.insertBefore(bll, node.firstChild);
              }
            }
            // Auto-detect confirmation patterns
            if (text.indexOf("confirmation") >= 0 || text.indexOf("conferma") >= 0 || text.indexOf("requires_confirmation") >= 0) {
              node.classList.add("requires-confirmation");
              if (!node.querySelector(".confirm-label")) {
                var cl = document.createElement("div");
                cl.className = "confirm-label"; cl.textContent = "🔐 Confirmation Required";
                node.insertBefore(cl, node.firstChild);
              }
            }
          }
        });
      });
    });
    observer.observe(chatMessages, { childList: true });
  })();

  // ---- POST-AUTH STATE RECONCILIATION (#1283) ─────────────────────────────
  // These functions are exposed globally so auth.js can call them after
  // login/enrollment/logout without needing to import app.js internals.

  /**
   * Pre-auth message patterns to detect and remove from the chat history.
   * These are shown before the user authenticates and must be cleared on auth.
   */
  var _PRE_AUTH_PATTERNS = [
    "Prima di continuare devo riconoscerti",
    "Accedi oppure registrati",
    "Per creare il tuo profilo compila il modulo",
    "Accedi con username e password",
    "Non ho ancora un profilo per te",
    "potresti dirmi chi sei",
  ];

  /** Remove all pre-auth assistant messages from the chat DOM. */
  window.clearPreAuthMessages = function () {
    var container = $("#chat-messages");
    if (!container) return;
    var msgs = container.querySelectorAll(".msg-assistant");
    msgs.forEach(function (el) {
      var txt = el.textContent || "";
      var isPreAuth = _PRE_AUTH_PATTERNS.some(function (p) {
        return txt.indexOf(p) >= 0;
      });
      if (isPreAuth) el.remove();
    });
  };

  /** Add a deterministic "Accesso effettuato" message to the chat. */
  window.addAuthSuccessMessage = function (profile) {
    var displayName = (profile && (profile.display_name || profile.profile_id)) || "utente";
    var trust = (profile && profile.trust_level) ? " (" + profile.trust_level + ")" : "";
    addMsg("assistant",
      "✅ Accesso effettuato come **" + displayName + "**" + trust + ". Ora puoi continuare la conversazione.",
      "auth-success");
  };

  /** Update sidebar interlocutor panel and chat header meta from an auth profile. */
  window.updateInterlocutorPanel = function (profile) {
    if (!profile) return;
    var displayName = profile.display_name || profile.profile_id || "—";
    var trust = profile.trust_level || "—";

    // Chat header meta
    var chatMeta = $("#chat-interlocutor-meta");
    if (chatMeta) chatMeta.textContent = displayName + " / " + trust;

    // Status panel interlocutor card
    var spIC = $("#sp-interlocutor-content");
    if (spIC) {
      spIC.innerHTML = '<div class="interlocutor-card">' +
        '<div class="ic-header">' +
        '<div class="ic-avatar">' + esc(displayName[0].toUpperCase()) + '</div>' +
        '<div><div class="ic-name">' + esc(displayName) + '</div>' +
        '<div class="ic-sub">' + esc(trust) + '</div></div>' +
        '</div>' +
        '<div class="ic-badges"><span class="ic-badge trusted">' + esc(trust) + '</span></div>' +
        '</div>';
    }
  };

  /**
   * Full post-auth reconciliation: clear pre-auth messages, update sidebar,
   * add success message. Called by auth.js after login/enrollment success.
   */
  window.onAuthStateChanged = function (profile) {
    window.clearPreAuthMessages();
    window.updateInterlocutorPanel(profile);
    window.addAuthSuccessMessage(profile);
  };

  /**
   * Reset sidebar and chat meta on logout. Called by auth.js _authClearUI.
   */
  window.onAuthStateCleared = function () {
    var chatMeta = $("#chat-interlocutor-meta");
    if (chatMeta) chatMeta.textContent = "non autenticato";
    var spIC = $("#sp-interlocutor-content");
    if (spIC) {
      spIC.innerHTML = '<div class="kv-row"><span class="kv-key">interlocutore</span>' +
        '<span class="kv-val">unknown · untrusted</span></div>';
    }
  };

  // ---- INIT STATUS PANEL (single registration, 60s interval) ----
  var _statusPanelStarted = false;
  function _initStatusPanel() {
    if (_statusPanelStarted) return;
    _statusPanelStarted = true;
    loadStatusPanel();
    setInterval(loadStatusPanel, 60000); // 60s — avoids rate limit
  }
  if (document.readyState === "complete" || document.readyState === "interactive") {
    _initStatusPanel();
  } else {
    document.addEventListener("DOMContentLoaded", _initStatusPanel);
  }

}
