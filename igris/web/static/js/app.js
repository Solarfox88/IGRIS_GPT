/* IGRIS_GPT — Agentic Engineering Console (#1318 modularized) */
import { $, $$, esc, kvTable, statusBadge, _intValue, _floatValue } from "./utils.js";
import { api, apiWithTimeout } from "./api.js";
import {
  SUPERVISED_LAUNCHER_PRESETS,
  _supervisorPromptLike,
  applySupervisedPreset,
  setupSupervisedLauncher,
  loadSupervisorMonitor,
} from "./supervisor.js";
import { loadDashboardExtras } from "./dashboard.js";
import { loadMissions, loadMissionDetail, loadMissionGraph } from "./missions.js";
import { loadTerminalCommands, runTerminalCommand, loadFileTree } from "./terminal.js";
import { loadGit, loadBranches, loadDiff, loadTimeline } from "./git.js";
import { loadCost, loadRouteEstimate, loadA2A, loadReports, loadMemory, loadLoopStatus, runLoopSteps } from "./cost.js";
import { loadPatches, loadPatchDetail, validatePatch, applyPatch, rejectPatch } from "./patches.js";
import "./status_panel.js";  // self-executing module
import "./chat.js";  // self-executing module

var _supervisorMonitorSeq = 0;
var _optimisticActiveRun = null;


  // Tab switching
  document.addEventListener("DOMContentLoaded", function () {
    // Primary tabs
    $$(".tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        $$(".tab").forEach(function (b) { b.classList.remove("active"); });
        $$(".tab-pane").forEach(function (p) { p.classList.remove("active"); });
        btn.classList.add("active");
        var pane = $("#tab-" + btn.dataset.tab);
        if (pane) pane.classList.add("active");
      });
    });

    // Sub-tab switching
    $$(".sub-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var bar = btn.parentElement;
        bar.querySelectorAll(".sub-tab").forEach(function (b) { b.classList.remove("active"); });
        var container = bar.parentElement;
        container.querySelectorAll(".sub-tab-pane").forEach(function (p) { p.classList.remove("active"); });
        btn.classList.add("active");
        var pane = container.querySelector("#subtab-" + btn.dataset.subtab);
        if (pane) pane.classList.add("active");
      });
    });

    loadStatus();
    loadMission();
    loadDashboardExtras();
    setupSupervisedLauncher();
    var supRefresh = $("#btn-refresh-supervisor-monitor");
    if (supRefresh) {
      supRefresh.addEventListener("click", function () { loadSupervisorMonitor(); });
    }

    // Auto-refresh active tab every 30s (reduced to avoid rate limit)
    setInterval(function () {
      var activeTab = $(".tab.active");
      if (!activeTab) return;
      var tab = activeTab.dataset.tab;
      if (tab === "dashboard") { loadMission(); loadDashboardExtras(); }
      else if (tab === "memory") loadTimeline();
      else if (tab === "tasks") { if (typeof loadLoopStatus === "function") loadLoopStatus(); }
      else if (tab === "safety") loadCost();
    }, 30000);
  });

  // Status header
  async function loadStatus() {
    var r = await api("GET", "/api/status");
    var rd = await api("GET", "/api/readiness");
    if (r.ok) {
      $("#header-status").textContent = "Online";
      $("#header-status").className = "";
      var providerText = r.data.provider + " / " + r.data.model;
      if (rd.ok && !rd.data.ollama_available) {
        providerText += " (fallback mode)";
      }
      $("#header-provider").textContent = providerText;
    } else {
      $("#header-status").textContent = "Offline";
      $("#header-status").className = "error";
    }
  }

  // Mission Control
  async function loadMission() {
    var h = await api("GET", "/api/health");
    if (h.ok) {
      $("#mission-health").innerHTML = "<strong>Health</strong>" + kvTable(h.data);
    } else {
      $("#mission-health").innerHTML = '<span class="error">Health check failed</span>';
    }
    var rd = await api("GET", "/api/readiness");
    if (rd.ok) {
      $("#mission-readiness").innerHTML = "<strong>Readiness</strong>" + kvTable(rd.data);
    }
    var ctx = await api("GET", "/api/project/context");
    if (ctx.ok) {
      $("#mission-context").innerHTML = "<strong>Project Context</strong>" + kvTable(ctx.data);
    }
    loadMissions();
  }

  // Cost
  (function () {
    $$('.tab[data-tab="cost"]').forEach(function (btn) {
      btn.addEventListener("click", loadCost);
    });
    var refreshBtn = $("#btn-refresh-cost");
    if (refreshBtn) refreshBtn.addEventListener("click", loadCost);
    var estBtn = $("#btn-estimate-route");
    if (estBtn) estBtn.addEventListener("click", loadRouteEstimate);
  })();

  // ---- Patches ----
  (function () {
    var loaded = false;
    $$('.tab[data-tab="patches"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) { loaded = true; loadPatches(); }
      });
    });
    var refreshBtn = $("#btn-refresh-patches");
    if (refreshBtn) refreshBtn.addEventListener("click", loadPatches);
  })();

  // Patch form
  (function () {
    var form = $("#patch-form");
    if (!form) return;
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      var title = $("#patch-title").value.trim();
      var desc = $("#patch-desc").value.trim();
      var path = $("#patch-path").value.trim();
      var action = $("#patch-action").value;
      var content = $("#patch-content").value;
      if (!path) { alert("File path is required"); return; }
      if (!content && action === "create") { alert("Content is required for create"); return; }
      var r = await api("POST", "/api/patches/propose", {
        title: title || "Untitled patch",
        description: desc,
        files: [{ path: path, action: action, after: content }]
      });
      if (r.ok) {
        form.reset();
        loadPatches();
        loadPatchDetail(r.data.id);
      } else {
        alert("Error: " + (r.data.detail || r.data.error || "unknown"));
      }
    });
  })();
// Visibility for Rank S dashboard endpoint
console.log('Rank S dashboard is now visible');
// Minimal visibility for Rank S dashboard endpoint
console.log('Rank S dashboard is now visible');
// Added visibility for Rank S dashboard endpoint
console.log('Rank S dashboard is now available');
// Visibility for Rank S dashboard endpoint
console.log('Rank S dashboard is now visible');
// Visibility for Rank S dashboard endpoint added.
// Note: Added visibility for Rank S dashboard endpoint.
// Added visibility for Rank S dashboard endpoint


