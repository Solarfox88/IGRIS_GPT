// IGRIS_GPT — Dashboard module (#1318)
// Extracted from app.js: dashboard extras, control room, review panel.
import { $, $$, esc, kvTable, statusBadge } from "./utils.js";
import { api, apiWithTimeout } from "./api.js";

  export async function loadDashboardExtras() {
    // Dashboard summary (control room backend payload from #1120)
    var summary = await api("GET", "/api/dashboard/summary");
    var crEl = $("#dash-control-room-status");
    if (crEl) {
      if (summary.ok && summary.data && summary.data.control_room) {
        var cr = summary.data.control_room;
        var mo = cr.mission_overview || {};
        var rs = cr.risk_snapshot || {};
        var na = cr.next_action || {};
        var warnings = cr.warnings || [];
        var riskLevel = String(rs.level || "low").toLowerCase();
        if (["low", "medium", "high"].indexOf(riskLevel) === -1) riskLevel = "low";
        var html = '';
        html += '<div class="cr-kpi-row">';
        html += '<div class="cr-kpi"><div class="cr-kpi-label">Active Tasks</div><div class="cr-kpi-value">' + esc(String(mo.active_task_count || 0)) + '</div></div>';
        html += '<div class="cr-kpi"><div class="cr-kpi-label">Pending</div><div class="cr-kpi-value">' + esc(String(mo.pending_task_count || 0)) + '</div></div>';
        html += '<div class="cr-kpi"><div class="cr-kpi-label">Running Task</div><div class="cr-kpi-value">' + esc(String(mo.running_task_id || "none")) + '</div></div>';
        html += '<div class="cr-kpi"><div class="cr-kpi-label">Risk</div><div class="cr-kpi-value"><span class="risk-chip ' + esc(riskLevel) + '">' + esc(riskLevel.toUpperCase()) + '</span></div></div>';
        html += '</div>';
        html += '<div class="next-action-banner">';
        html += '<div><div class="title">Next Action: ' + esc(na.label || "Open Mission") + '</div><div class="sub">' + esc(na.reason || "default_control_room_hint") + '</div></div>';
        html += '<div class="sub">id=' + esc(na.id || "open_mission") + (na.approval_required ? " | approval required" : "") + '</div>';
        html += '</div>';
        if (warnings.length > 0) {
          html += '<ul class="warning-list">';
          for (var wi = 0; wi < warnings.length; wi++) {
            html += '<li>' + esc(String(warnings[wi])) + '</li>';
          }
          html += '</ul>';
        }
        crEl.innerHTML = html;
      } else {
        crEl.innerHTML = '<span class="dim">Control-room payload unavailable</span>';
      }
    }

    // Diagnostics summary
    var diag = await api("GET", "/api/diagnostics/summary");
    var diagEl = $("#dash-diagnostics-summary");
    if (diagEl) {
      if (diag.ok) {
        var d = diag.data;
        var html = '<div class="dash-summary">';
        html += '<span>Starvation: <strong>' + esc(d.starvation_detected ? "YES" : "OK") + '</strong></span>';
        html += '<span>Blocked: <strong>' + esc(String(d.blocked_task_count || 0)) + '</strong></span>';
        html += '<span>Health: <strong>' + esc(String(d.family_health_issues || 0)) + ' issues</strong></span>';
        html += '</div>';
        diagEl.innerHTML = html;
      } else {
        diagEl.innerHTML = '<span class="dim">Diagnostics unavailable</span>';
      }
    }

    // Loop summary
    var loop = await api("GET", "/api/loop/status");
    var loopEl = $("#dash-loop-info");
    if (loopEl) {
      if (loop.ok) {
        var ls = loop.data;
        var html = '<div class="dash-summary">';
        html += '<span>Steps: <strong>' + esc(String(ls.total_steps || 0)) + '</strong></span>';
        html += '<span>Last: <strong>' + esc(ls.last_action || "none") + '</strong></span>';
        html += '</div>';
        loopEl.innerHTML = html;
      } else {
        loopEl.innerHTML = '<span class="dim">Loop not started</span>';
      }
    }

    // Decision reports
    var reports = await api("GET", "/api/decision-reports");
    var reportsEl = $("#dash-reports");
    if (reportsEl) {
      if (reports.ok && reports.data.reports && reports.data.reports.length > 0) {
        var recent = reports.data.reports.slice(0, 3);
        var html = '';
        for (var i = 0; i < recent.length; i++) {
          var rp = recent[i];
          html += '<div class="dash-report-item">';
          html += '<span class="dim">' + esc(rp.id || "") + '</span> ';
          html += '<span>' + esc(rp.selected_task || rp.outcome || "report") + '</span>';
          html += '</div>';
        }
        reportsEl.innerHTML = html;
      } else {
        reportsEl.innerHTML = '<span class="dim">No decision reports yet</span>';
      }
    }

    // Evidence panel (read-only)
    var interpretedEvidence = null;
    var activeRunId = "";
    var evEl = $("#dash-evidence-summary");
    if (evEl) {
      var activeRuns = await api("GET", "/api/rank/runs/active");
      if (activeRuns.ok && activeRuns.data && activeRuns.data.runs && activeRuns.data.runs.length > 0) {
        var run = activeRuns.data.runs[0];
        activeRunId = run.run_id || run.id || "";
        interpretedEvidence = activeRunId ? await api("GET", "/api/rank/runs/" + encodeURIComponent(activeRunId) + "/evidence/interpreted") : { ok: false };
        if (interpretedEvidence.ok && interpretedEvidence.data) {
          var ed = interpretedEvidence.data;
          var cards = ed.evidence_cards || [];
          var nextActions = ed.next_actions || [];
          var html = '<div class="panel-line"><strong>Active run:</strong> ' + esc(activeRunId) + '</div>';
          html += '<div class="panel-line"><strong>Interpreted cards:</strong> ' + esc(String(ed.card_count || cards.length || 0)) + '</div>';
          html += '<div class="panel-line"><strong>Next actions:</strong> ' + esc(String(nextActions.length || 0)) + '</div>';
          if (cards.length > 0) {
            html += '<div class="panel-card-list">';
            for (var ci = 0; ci < Math.min(cards.length, 3); ci++) {
              var card = cards[ci] || {};
              html += '<div class="panel-card evidence-card">';
              html += '<div class="panel-card-title">' + esc(card.type || "evidence") + ' <span class="dim">' + esc(card.status || "unknown") + '</span></div>';
              html += '<div class="panel-card-summary">' + esc(card.summary || "No summary") + '</div>';
              if (card.details) {
                html += '<div class="panel-card-detail">' + esc(typeof card.details === "string" ? card.details : JSON.stringify(card.details)).slice(0, 240) + '</div>';
              }
              html += '</div>';
            }
            html += '</div>';
          } else {
            html += '<div class="panel-line dim">No evidence cards available for active run</div>';
          }
          evEl.innerHTML = html;
        } else {
          evEl.innerHTML = '<div class="panel-line">Interpreted evidence not available for active run</div>';
        }
      } else {
        evEl.innerHTML = '<div class="panel-line">No active run evidence</div>';
      }
    }

    // GitHub PR/CI panel (read-only)
    var ghEl = $("#dash-github-summary");
    if (ghEl) {
      var gh = await api("GET", "/api/github/pr/status");
      if (gh.ok) {
        var gd = gh.data || {};
        ghEl.innerHTML = '<div class="panel-line"><strong>Enabled:</strong> ' + esc(String(!!gd.enabled)) + '</div>' +
                         '<div class="panel-line"><strong>Last PR:</strong> ' + esc(gd.pr_url || "none") + '</div>' +
                         '<div class="panel-line"><strong>CI:</strong> ' + esc(gd.ci_status || "unknown") + '</div>';
      } else {
        ghEl.innerHTML = '<div class="panel-line">GitHub status unavailable</div>';
      }
    }

    // Memory panel (read-only)
    var memEl = $("#dash-memory-summary");
    if (memEl) {
      var mem = await api("GET", "/api/memory/summary");
      if (mem.ok) {
        var md = mem.data || {};
        memEl.innerHTML = '<div class="panel-line"><strong>Nodes:</strong> ' + esc(String(md.node_count || 0)) + '</div>' +
                          '<div class="panel-line"><strong>Edges:</strong> ' + esc(String(md.edge_count || 0)) + '</div>' +
                          '<div class="panel-line"><strong>DB KB:</strong> ' + esc(String(md.db_size_kb || 0)) + '</div>';
      } else {
        memEl.innerHTML = '<div class="panel-line">Memory snapshot unavailable</div>';
      }
    }

    // DevOps panel (read-only)
    var devEl = $("#dash-devops-summary");
    if (devEl) {
      var dv = await api("GET", "/api/devops/health");
      if (dv.ok) {
        var dvo = dv.data || {};
        devEl.innerHTML = '<div class="panel-line"><strong>Status:</strong> ' + esc(dvo.status || "unknown") + '</div>' +
                          '<div class="panel-line"><strong>Disk:</strong> ' + esc(JSON.stringify(dvo.disk || {})) + '</div>' +
                          '<div class="panel-line"><strong>Memory:</strong> ' + esc(JSON.stringify(dvo.memory || {})) + '</div>';
      } else {
        devEl.innerHTML = '<div class="panel-line">DevOps health unavailable</div>';
      }
    }

    // Browser evidence placeholder/base
    var brEl = $("#dash-browser-summary");
    if (brEl) {
      if (interpretedEvidence && interpretedEvidence.ok && interpretedEvidence.data) {
        var cards2 = interpretedEvidence.data.evidence_cards || [];
        var browserCard = null;
        for (var bi = 0; bi < cards2.length; bi++) {
          if (String(cards2[bi].type || "").toLowerCase() === "browser_evidence") {
            browserCard = cards2[bi];
            break;
          }
        }
        var browserActions = interpretedEvidence.data.next_actions || [];
        var browserAction = browserActions.length > 0 ? browserActions[0] : null;
        if (browserCard) {
          var html = '<div class="panel-line"><strong>Status:</strong> ' + esc(browserCard.status || "unknown") + '</div>';
          html += '<div class="panel-line"><strong>Summary:</strong> ' + esc(browserCard.summary || "No summary") + '</div>';
          if (browserCard.details) {
            html += '<div class="panel-line"><strong>Details:</strong> ' + esc(typeof browserCard.details === "string" ? browserCard.details : JSON.stringify(browserCard.details)).slice(0, 320) + '</div>';
          }
          if (browserAction) {
            html += '<div class="panel-line"><strong>Next:</strong> ' + esc(browserAction.summary || browserAction.label || "review browser evidence") + '</div>';
          }
          brEl.innerHTML = html;
        } else {
          brEl.innerHTML = '<div class="panel-line">Browser evidence card not present yet</div>' +
                           '<div class="panel-line">Run a browser-backed mission to surface actionable evidence here.</div>';
        }
      } else {
        brEl.innerHTML = '<div class="panel-line">Browser evidence integration: base placeholder active</div>' +
                         '<div class="panel-line">No executable browser action exposed from dashboard.</div>';
      }
    }

    var reviewStatusEl = $("#dash-review-status");
    var saveReviewBtn = $("#btn-save-control-room-review");
    var exportReportBtn = $("#btn-export-final-report");
    if (saveReviewBtn) {
      saveReviewBtn.onclick = async function () {
        if (!activeRunId) {
          if (reviewStatusEl) reviewStatusEl.textContent = "No active run to review.";
          return;
        }
        var reviewPayload = {
          action_id: "review_evidence",
          summary: "Persisted review saved from dashboard",
          notes: "Operator reviewed evidence cards and next actions.",
          evidence_ref: "/api/rank/runs/" + encodeURIComponent(activeRunId) + "/report",
          reviewed_by: "dashboard-operator",
        };
        var resp = await api("POST", "/api/rank/runs/" + encodeURIComponent(activeRunId) + "/review", reviewPayload);
        if (reviewStatusEl) {
          reviewStatusEl.textContent = resp.ok
            ? "Review persisted (" + String(((resp.data || {}).review_count) || 0) + " total)."
            : "Review persistence failed: " + String((resp.data || {}).detail || "unknown");
        }
      };
    }
    if (exportReportBtn) {
      exportReportBtn.onclick = async function () {
        if (!activeRunId) {
          if (reviewStatusEl) reviewStatusEl.textContent = "No active run to export.";
          return;
        }
        var resp = await api("GET", "/api/rank/runs/" + encodeURIComponent(activeRunId) + "/final-export");
        if (reviewStatusEl) {
          reviewStatusEl.textContent = resp.ok
            ? "Final export ready with " + String(((resp.data || {}).operator_reviews || []).length || 0) + " persisted reviews."
            : "Final export failed: " + String((resp.data || {}).detail || "unknown");
        }
      };
    }

    await loadSupervisorMonitor();
  }

