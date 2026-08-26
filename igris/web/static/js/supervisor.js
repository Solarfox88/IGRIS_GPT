// IGRIS_GPT — Supervisor module (#1318)
// Extracted from app.js: presets, launcher, monitor.
import { $, esc, _intValue, _floatValue } from "./utils.js";
import { api, apiWithTimeout } from "./api.js";

var _supervisorMonitorSeq = 0;
var _optimisticActiveRun = null;

export var SUPERVISED_LAUNCHER_PRESETS = {
  "rank-b": {
    rank_id: "B",
    goal: "Complete Rank B supervised mission with backend endpoint and tests.",
    max_rank_attempts: 1,
    max_repair_cycles: 2,
    allow_github_pr: false,
    allow_merge_if_green: false,
    allow_api_escalation: false,
    max_api_escalations_per_run: 0,
    max_api_budget_usd: 0.0,
    max_tokens_per_escalation: 1200,
    service_restart_command: "sudo -n systemctl restart igris",
    required_smoke_endpoints: [
      "http://127.0.0.1:7778/api/health",
      "http://127.0.0.1:7778/api/readiness",
      "http://127.0.0.1:7778/api/ping"
    ]
  },
  "rank-a": {
    rank_id: "A",
    goal: "Complete Rank A supervised mission with backend and tests, then verify runtime smoke.",
    max_rank_attempts: 2,
    max_repair_cycles: 4,
    allow_github_pr: true,
    allow_merge_if_green: true,
    allow_api_escalation: false,
    max_api_escalations_per_run: 0,
    max_api_budget_usd: 0.0,
    max_tokens_per_escalation: 1200,
    service_restart_command: "sudo -n systemctl restart igris",
    required_smoke_endpoints: [
      "http://127.0.0.1:7778/api/health",
      "http://127.0.0.1:7778/api/readiness",
      "http://127.0.0.1:7778/api/ping",
      "http://127.0.0.1:7778/api/rank/runs"
    ]
  },
  "rank-a-plus-plus-ui": {
    rank_id: "A++-ui",
    goal: "Complete Rank A++ UI supervised mission with dashboard visibility, tests, and CI workflow.",
    max_rank_attempts: 2,
    max_repair_cycles: 6,
    allow_github_pr: true,
    allow_merge_if_green: true,
    allow_api_escalation: true,
    max_api_escalations_per_run: 1,
    max_api_budget_usd: 0.75,
    max_tokens_per_escalation: 2400,
    service_restart_command: "sudo -n systemctl restart igris",
    required_smoke_endpoints: [
      "http://127.0.0.1:7778/api/health",
      "http://127.0.0.1:7778/api/readiness",
      "http://127.0.0.1:7778/api/ping",
      "http://127.0.0.1:7778/api/rank/runs"
    ]
  },
  "rank-s-full-e2e": {
    rank_id: "S-full-e2e",
    goal: "Complete a full Rank S supervised end-to-end mission. Add GET /api/rank/s-dashboard returning exactly {\"app\":\"IGRIS_GPT\",\"rank\":\"S\",\"status\":\"ok\",\"capability\":\"end-to-end-supervised\",\"checks\":{\"backend\":true,\"ui\":true,\"tests\":true,\"workflow\":true}}. Add dedicated backend tests in tests/test_rank_s_dashboard.py. Add mandatory minimal UI/dashboard visibility for the Rank S dashboard endpoint and add/update relevant UI/dashboard smoke tests. Add a minimal operational note if safe and consistent. Run targeted tests and full pytest. Produce a truthful final report. Do not push directly to main.",
    max_rank_attempts: 3,
    max_repair_cycles: 8,
    allow_github_pr: true,
    allow_merge_if_green: true,
    allow_api_escalation: true,
    max_api_escalations_per_run: 2,
    max_api_budget_usd: 1.50,
    max_tokens_per_escalation: 4000,
    test_timeout_seconds: 120,
    test_hard_cap_seconds: 3600,
    service_restart_command: "sudo -n systemctl restart igris",
    required_smoke_endpoints: [
      "http://127.0.0.1:7778/api/health",
      "http://127.0.0.1:7778/api/readiness",
      "http://127.0.0.1:7778/api/ping",
      "http://127.0.0.1:7778/api/rank/runs"
    ]
  }
};

export function _supervisorPromptLike(text) {
  var t = String(text || "").toLowerCase();
  return (
    t.indexOf("run-supervised") !== -1 ||
    t.indexOf("rank s") !== -1 ||
    t.indexOf("max_repair_cycles") !== -1 ||
    t.indexOf("allow_api_escalation") !== -1
  );
}

export function applySupervisedPreset(presetId) {
  var cfg = SUPERVISED_LAUNCHER_PRESETS[presetId];
  if (!cfg) return;
  $("#supervised-rank-id").value = cfg.rank_id || "";
  $("#supervised-goal").value = cfg.goal || "";
  $("#supervised-max-rank-attempts").value = String(cfg.max_rank_attempts || 1);
  $("#supervised-max-repair-cycles").value = String(cfg.max_repair_cycles || 0);
  $("#supervised-allow-github-pr").checked = !!cfg.allow_github_pr;
  $("#supervised-allow-merge-if-green").checked = !!cfg.allow_merge_if_green;
  $("#supervised-allow-api-escalation").checked = !!cfg.allow_api_escalation;
  $("#supervised-max-api-escalations-per-run").value = String(cfg.max_api_escalations_per_run || 0);
  $("#supervised-max-api-budget-usd").value = String(cfg.max_api_budget_usd || 0);
  $("#supervised-max-tokens-per-escalation").value = String(cfg.max_tokens_per_escalation || 1200);
  $("#supervised-service-restart-command").value = cfg.service_restart_command || "";
  $("#supervised-required-smoke-endpoints").value = (cfg.required_smoke_endpoints || []).join("\n");
}

export function setupSupervisedLauncher() {
  var form = $("#supervised-launcher-form");
  if (!form) return;

  var preset = $("#supervised-preset");
  if (preset) {
    applySupervisedPreset(preset.value || "rank-b");
    preset.addEventListener("change", function () {
      applySupervisedPreset(preset.value);
    });
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    var result = $("#supervised-launcher-result");
    if (result) result.textContent = "Launching supervised mission...";

    var payload = {
      rank_id: ($("#supervised-rank-id").value || "").trim(),
      goal: ($("#supervised-goal").value || "").trim(),
      max_rank_attempts: _intValue("supervised-max-rank-attempts", 1),
      max_repair_cycles: _intValue("supervised-max-repair-cycles", 0),
      allow_github_pr: !!$("#supervised-allow-github-pr").checked,
      allow_merge_if_green: !!$("#supervised-allow-merge-if-green").checked,
      allow_api_escalation: !!$("#supervised-allow-api-escalation").checked,
      max_api_escalations_per_run: _intValue("supervised-max-api-escalations-per-run", 0),
      max_api_budget_usd: _floatValue("supervised-max-api-budget-usd", 0),
      max_tokens_per_escalation: _intValue("supervised-max-tokens-per-escalation", 1200),
      service_restart_command: ($("#supervised-service-restart-command").value || "").trim(),
      required_smoke_endpoints: ($("#supervised-required-smoke-endpoints").value || "")
        .split("\n")
        .map(function (line) { return line.trim(); })
        .filter(function (line) { return !!line; }),
    };

    var resp = await api("POST", "/api/rank/run-supervised", payload);
    if (!resp.ok) {
      if (result) result.textContent = "Launch failed: " + String((resp.data || {}).detail || (resp.data || {}).error || "unknown");
      return;
    }
    window._lastStartedSupervisorRun = resp.data || {};
    _optimisticActiveRun = resp.data || null;
    if (result) {
      result.innerHTML =
        "Supervised mission started. run_id=<strong>" + esc(String((resp.data || {}).run_id || "")) + "</strong>";
    }
    await loadSupervisorMonitor();
  });
}

export async function loadSupervisorMonitor() {
  var seq = ++_supervisorMonitorSeq;
  var monitorEl = $("#dash-supervisor-monitor");
  if (!monitorEl) return;
  monitorEl.innerHTML = "Loading supervisor runs...";
  var finalHtml = "";
  try {
    var active = await apiWithTimeout("GET", "/api/rank/runs/active", null, 5000);
    var audit = await apiWithTimeout("GET", "/api/rank/audit/summary", null, 5000);
    if (seq !== _supervisorMonitorSeq) return;
    if (!active.ok) {
      var errMsg = ((active.data || {}).detail || (active.data || {}).error || ("HTTP " + String(active.status || 0)));
      finalHtml = "Supervisor monitor unavailable: " + esc(String(errMsg));
    } else {
      var rows = [];
      rows.push("<div><strong>Rank / Mission Monitor</strong></div>");
      var runs = (active.data.runs || []).slice();
      var activeRunIds = {};
      var lastStarted = _optimisticActiveRun || window._lastStartedSupervisorRun || null;
      if (active.ok && (active.data.runs || []).length === 0) {
        _optimisticActiveRun = null;
        window._lastStartedSupervisorRun = null;
      }
      if (lastStarted && lastStarted.run_id) {
        var found = runs.some(function (item) { return item.run_id === lastStarted.run_id; });
        if (!found) {
          runs.unshift({
            run_id: lastStarted.run_id,
            rank_id: lastStarted.rank_id || "",
            status: lastStarted.status || "running",
            outcome: lastStarted.outcome || "",
            current_stage: "",
            failed_stage: "",
            failure_class: "",
            repair_cycles_used: lastStarted.repair_cycles_used || 0,
            api_escalations_used: lastStarted.api_escalations_used || 0,
            api_budget_used_usd: lastStarted.api_budget_used_usd || 0,
            escalation_issue_url: "",
            audit_summary: { counts: {} },
            next_action: "wait:next_event",
          });
        }
      }
      if (!runs.length) {
        rows.push("<div><strong>Supervisor Runs:</strong> 0 active</div>");
        rows.push("<div>No active supervisor runs. Start a supervised mission or view recent audit history.</div>");
      } else {
        rows.push("<div><strong>Supervisor Runs:</strong> " + esc(String(runs.length)) + " active</div>");
        runs.slice(0, 3).forEach(function (run) {
          activeRunIds[String(run.run_id || "")] = true;
          var stage = run.current_stage || "idle";
          var failedStage = run.failed_stage || "-";
          var next = run.next_action || "";
          var issueUrl = run.escalation_issue_url || "";
          var issueHtml = issueUrl ? ('<a href="' + esc(issueUrl) + '" target="_blank" rel="noopener noreferrer">issue</a>') : "-";
          var runIdSafe = esc(String(run.run_id || ""));
          var cancelBtn = '<button type="button" class="action-btn btn-cancel-supervised-run" data-run-id="' + runIdSafe + '">Stop safely</button>';
          rows.push(
            '<div class="dash-report-item">' +
            runIdSafe +
            " | rank=" + esc(run.rank_id || "-") +
            " | status=" + esc(run.status || "") +
            " | outcome=" + esc(run.outcome || "-") +
            " | stage=" + esc(stage) +
            " | failed_stage=" + esc(failedStage) +
            " | failure=" + esc(run.failure_class || "-") +
            " | repairs=" + esc(String(run.repair_cycles_used || 0)) +
            " | api=" + esc(String(run.api_escalations_used || 0)) +
            " ($" + esc(String(run.api_budget_used_usd || 0)) + ")" +
            " | escalation_issue=" + issueHtml +
            " | audit_new=" + esc(String((((run.audit_summary || {}).counts || {})["audit-new"]) || 0)) +
            " | audit_reviewed=" + esc(String((((run.audit_summary || {}).counts || {})["audit-reviewed"]) || 0)) +
            " | audit_fixed=" + esc(String((((run.audit_summary || {}).counts || {})["audit-fixed"]) || 0)) +
            " | audit_deferred=" + esc(String((((run.audit_summary || {}).counts || {})["audit-deferred"]) || 0)) +
            " | state_conflict=" + esc(String(!!run.state_conflict)) +
            (run.warning ? (" | warning=" + esc(run.warning)) : "") +
            " | next=" + esc(next) +
            " | " + cancelBtn +
            "</div>"
          );
        });
      }

      if (audit.ok) {
        var inMem = (((audit.data || {}).in_memory || {}).counts) || {};
        var persisted = (((audit.data || {}).persisted || {}).counts) || {};
        rows.push("<div><strong>Audit & Escalations</strong></div>");
        rows.push(
          "<div><strong>Audit (memory):</strong> " +
          "new=" + esc(String(inMem["audit-new"] || 0)) + ", " +
          "reviewed=" + esc(String(inMem["audit-reviewed"] || 0)) + ", " +
          "fixed=" + esc(String(inMem["audit-fixed"] || 0)) + ", " +
          "deferred=" + esc(String(inMem["audit-deferred"] || 0)) +
          "</div>"
        );
        rows.push(
          "<div><strong>Audit (persisted):</strong> " +
          "new=" + esc(String(persisted["audit-new"] || 0)) + ", " +
          "reviewed=" + esc(String(persisted["audit-reviewed"] || 0)) + ", " +
          "fixed=" + esc(String(persisted["audit-fixed"] || 0)) + ", " +
          "deferred=" + esc(String(persisted["audit-deferred"] || 0)) + ", " +
          "deferred_due=" + esc(String((((audit.data || {}).persisted || {}).deferred_due_count) || 0)) +
          "</div>"
        );
        var recent = ((audit.data || {}).recent_runs) || [];
        var suppressed = [];
        if (recent.length) {
          rows.push("<div><strong>Recent Runs:</strong></div>");
          recent.slice(0, 3).forEach(function (run) {
            var rid = String(run.run_id || "");
            if (activeRunIds[rid]) {
              suppressed.push(rid);
              return;
            }
            rows.push(
              '<div class="dash-report-item">' +
              esc(rid) +
              " | status=" + esc(run.status || "") +
              " | outcome=" + esc(run.outcome || "-") +
              " | failure=" + esc(run.failure_class || "-") +
              " | state_conflict=" + esc(String(!!run.state_conflict)) +
              (run.warning ? (" | warning=" + esc(run.warning)) : "") +
              (run.cancelled_reason ? (" | reason=" + esc(run.cancelled_reason)) : "") +
              "</div>"
            );
          });
          if (suppressed.length) {
            rows.push(
              "<div><strong>Recent Runs:</strong> suppressed duplicate run ids already shown in active: " +
              esc(suppressed.join(", ")) +
              "</div>"
            );
          }
        } else {
          rows.push("<div><strong>Recent Runs:</strong> not available (in-memory history reset after restart).</div>");
        }
      }
      finalHtml = rows.join("");
    }
  } catch (err) {
    finalHtml = "Supervisor monitor unavailable: " + esc(String((err && err.message) || err || "unknown"));
  } finally {
    if (!finalHtml || finalHtml.indexOf("Loading supervisor runs...") !== -1) {
      finalHtml = "Supervisor monitor unavailable: no data";
    }
    monitorEl.innerHTML = finalHtml;
    monitorEl.querySelectorAll(".btn-cancel-supervised-run").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        var runId = btn.getAttribute("data-run-id") || "";
        if (!runId) return;
        var ok = window.confirm("Stop supervised run " + runId + " safely?");
        if (!ok) return;
        btn.disabled = true;
        var resp = await api("POST", "/api/rank/runs/" + encodeURIComponent(runId) + "/cancel", {
          reason: "Cancelled by user from Supervisor Monitor",
        });
        if (!resp.ok) {
          btn.disabled = false;
        }
        await loadSupervisorMonitor();
      });
    });
  }
}
