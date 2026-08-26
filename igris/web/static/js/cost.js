// IGRIS_GPT — Cost/Routing/A2A/Reports/Memory/Loop module (#1318)
import { $, $$, esc, kvTable } from "./utils.js";
import { api, apiWithTimeout } from "./api.js";

  export async function loadCost() {
    // Availability
    var av = await api("GET", "/api/routing/availability");
    if (av.ok) {
      var d = av.data;
      var html = "";
      var providers = ["ollama", "openai", "vastai"];
      providers.forEach(function (p) {
        var info = d[p] || {};
        var dot = info.available ? "ok" : "off";
        html += '<div class="provider-card"><span class="status-dot ' + dot + '"></span>';
        html += "<strong>" + esc(p) + "</strong>";
        if (info.model) html += " <small>(" + esc(info.model) + ")</small>";
        html += " <small>$" + (info.cost_per_call || 0) + "/call</small>";
        if (info.auto_provision === false) html += " <small>[no auto]</small>";
        html += "</div>";
      });
      $("#cost-availability").innerHTML = html;
    }
    // Budget
    var bg = await api("GET", "/api/cost/budget");
    if (bg.ok) {
      var b = bg.data;
      var pct = Math.min(b.usage_percent || 0, 100);
      var cls = b.exceeded ? "exceeded" : b.warning ? "warn" : "ok";
      var bhtml = '<div class="budget-bar"><div class="budget-fill ' + cls + '" style="width:' + pct + '%"></div></div>';
      bhtml += "<small>$" + (b.spent || 0) + " / $" + (b.max_session_cost || 0) + " (" + pct + "%)</small>";
      if (b.warning) bhtml += ' <span class="error"> Budget warning</span>';
      $("#cost-budget").innerHTML = bhtml;
    }
    // Summary
    var s = await api("GET", "/api/cost/summary");
    if (s.ok) {
      var sd = s.data;
      $("#cost-summary").innerHTML = kvTable({
        total_calls: sd.total_calls,
        local_calls: sd.local_calls,
        fallback_calls: sd.fallback_calls,
        estimated_cost_total: "$" + sd.estimated_cost_total,
        last_provider: sd.last_provider || "none",
      });
    }
    // Explain
    var e = await api("GET", "/api/routing/explain");
    if (e.ok) {
      $("#routing-explain").innerHTML = esc(e.data.explanation || "No routing decision yet.");
    }
  }

  export async function loadRouteEstimate() {
    var r = await api("POST", "/api/routing/estimate", {task_type: "chat", complexity: "low"});
    if (r.ok) {
      var d = r.data;
      var html = kvTable({
        recommended_provider: d.recommended_provider,
        model: d.model,
        reason: d.reason,
        estimated_cost: "$" + d.estimated_cost,
        budget_remaining: "$" + d.budget_remaining,
        would_exceed_budget: d.would_exceed_budget,
      });
      $("#cost-estimate").innerHTML = html;
    } else {
      $("#cost-estimate").innerHTML = '<span class="error">Failed to estimate route</span>';
    }
  }

  // A2A
  (function () {
    $$('.tab[data-tab="a2a"]').forEach(function (btn) {
      btn.addEventListener("click", loadA2A);
    });
    var refreshBtn = $("#btn-refresh-a2a");
    if (refreshBtn) refreshBtn.addEventListener("click", loadA2A);
  })();

  export async function loadA2A() {
    var card = await api("GET", "/.well-known/agent-card.json");
    if (card.ok) {
      $("#a2a-card").innerHTML = kvTable(card.data);
    }
    var caps = await api("GET", "/api/a2a/capabilities");
    if (caps.ok) {
      var list = caps.data.capabilities || [];
      var h = "<table><tr><th>ID</th><th>Name</th><th>Risk</th><th>Safe</th></tr>";
      list.forEach(function (c) {
        h += "<tr><td>" + esc(c.id) + "</td><td>" + esc(c.name) + "</td><td>" + esc(c.risk) + "</td><td>" + esc(c.safe) + "</td></tr>";
      });
      h += "</table>";
      $("#a2a-capabilities").innerHTML = h;
    }
    // A2A Store tasks
    var tasks = await api("GET", "/api/a2a/store/tasks");
    if (tasks.ok) {
      var tl = tasks.data.tasks || [];
      if (tl.length) {
        var th = "<table><tr><th>ID</th><th>Title</th><th>Status</th></tr>";
        tl.forEach(function (t) {
          th += "<tr><td>" + esc(t.id) + "</td><td>" + esc(t.title || t.description || "") + "</td><td>" + statusBadge(t.status) + "</td></tr>";
        });
        th += "</table>";
        $("#a2a-tasks").innerHTML = th;
      } else {
        $("#a2a-tasks").innerHTML = "<em>No A2A tasks.</em>";
      }
    } else {
      $("#a2a-tasks").innerHTML = "<em>No A2A tasks.</em>";
    }
  }

  // Teacher Remediation button
  (function () {
    var btn = $("#btn-teacher-remediate");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      btn.disabled = true;
      btn.textContent = "Analyzing...";
      var out = $("#teacher-output");
      out.textContent = "Building teacher payload...";
      var r = await api("POST", "/api/teacher/remediate", { create: false });
      btn.disabled = false;
      btn.textContent = "Ask Teacher";
      if (!r.ok) {
        out.textContent = "Error: " + (r.data.detail || "unknown");
        return;
      }
      var d = r.data;
      var html = "<strong>Proposed Task</strong>" + kvTable(d.proposed_task || {});
      if (d.validation) {
        html += "<strong>Validation</strong>" + kvTable(d.validation);
      }
      html += '<br><button type="button" id="btn-teacher-create" class="cmd-btn" aria-label="Create remediation task">Create This Task</button>';
      out.innerHTML = html;

      var createBtn = $("#btn-teacher-create");
      if (createBtn) {
        createBtn.addEventListener("click", async function () {
          createBtn.disabled = true;
          var cr = await api("POST", "/api/teacher/remediate", { create: true });
          if (cr.ok && cr.data.created_task_id) {
            out.innerHTML += '<br><span style="color:#4caf50">Task #' + cr.data.created_task_id + ' created!</span>';
          } else {
            out.innerHTML += '<br><span class="error">Could not create task (validation failed or no proposal)</span>';
          }
        });
      }
    });
  })();

  // Reports (loaded with Safety tab)
  (function () {
    // loadReports is called from loadSafety
  })();

  export async function loadReports() {
    var container = $("#reports-list");
    if (!container) return;
    container.innerHTML = '<span class="loading">Loading...</span>';
    var r = await api("GET", "/api/reports/recent");
    if (!r.ok) { container.innerHTML = '<span class="error">Failed</span>'; return; }
    var reports = r.data.reports || [];
    if (!reports.length) { container.innerHTML = "<em>No reports yet.</em>"; return; }
    var html = "<table><tr><th>Command</th><th>Success</th><th>Duration</th><th>Time</th></tr>";
    reports.reverse().forEach(function (rp) {
      html += "<tr><td>" + esc(rp.command_id) + "</td><td>" +
        (rp.success ? "Yes" : "No") + "</td><td>" +
        esc(rp.duration_ms + "ms") + "</td><td>" +
        esc(rp.started_at || "") + "</td></tr>";
    });
    html += "</table>";
    container.innerHTML = html;
  }

  // ---- Memory ----
  export async function loadMemory() {
    var cEl = $("#memory-constraints");
    var dEl = $("#memory-decisions");
    var fEl = $("#memory-failures");
    var cr = await api("GET", "/api/memory/saturation");
    if (cr.ok && cEl) {
      var c = cr.data.constraints || {};
      var h = "<strong>Recommendation:</strong> " + esc(c.recommendation || "No constraints");
      h += "<br><small>Saturated: " + (c.saturated_families || []).map(esc).join(", ");
      h += " | Failures: " + (c.recent_failure_count || 0);
      h += " | Decisions: " + (c.recent_decision_count || 0);
      h += " | Remediations: " + (c.remediation_count || 0) + "</small>";
      if ((c.avoid_families || []).length) {
        h += '<br><span class="task-status blocked">Avoid: ' + c.avoid_families.map(esc).join(", ") + "</span>";
      }
      cEl.innerHTML = h;
    }
    var dr = await api("GET", "/api/memory/decisions?limit=10");
    if (dr.ok && dEl) {
      var evts = dr.data.events || [];
      if (!evts.length) { dEl.innerHTML = "<em>No decisions yet</em>"; }
      else {
        var h2 = "";
        evts.forEach(function (e) {
          h2 += '<div class="info-block" style="margin:.2rem 0;padding:.3rem .5rem">';
          h2 += statusBadge(e.outcome || "pending") + " <strong>" + esc(e.title) + "</strong>";
          h2 += " <small>[" + esc(e.family || "—") + "]</small>";
          if (e.reason) h2 += "<br><small>" + esc(e.reason) + "</small>";
          h2 += "</div>";
        });
        dEl.innerHTML = h2;
      }
    }
    var fr = await api("GET", "/api/memory/failures?limit=10");
    if (fr.ok && fEl) {
      var fevts = fr.data.events || [];
      if (!fevts.length) { fEl.innerHTML = "<em>No failures recorded</em>"; }
      else {
        var h3 = "";
        fevts.forEach(function (e) {
          h3 += '<div class="info-block" style="margin:.2rem 0;padding:.3rem .5rem">';
          h3 += '<span class="task-status blocked">failure</span> <strong>' + esc(e.title) + "</strong>";
          h3 += " <small>[" + esc(e.family || "—") + "]</small>";
          if (e.reason) h3 += "<br><small>" + esc(e.reason) + "</small>";
          h3 += "</div>";
        });
        fEl.innerHTML = h3;
      }
    }
  }

  (function () {
    var loaded = false;
    $$('.tab[data-tab="memory"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) { loaded = true; loadMemory(); }
      });
    });
    var refreshBtn = $("#btn-refresh-memory");
    if (refreshBtn) refreshBtn.addEventListener("click", loadMemory);

    var form = $("#memory-event-form");
    if (form) {
      form.addEventListener("submit", async function (e) {
        e.preventDefault();
        var evType = $("#memory-event-type").value;
        var title = $("#memory-event-title").value.trim();
        var family = $("#memory-event-family").value.trim();
        var desc = $("#memory-event-desc").value.trim();
        var r = await api("POST", "/api/memory/events", {
          event_type: evType, title: title, family: family, description: desc
        });
        if (r.ok) { form.reset(); loadMemory(); }
        else alert("Error: " + (r.data.detail || "unknown"));
      });
    }
  })();

  // ---- Loop ----
  export async function loadLoopStatus() {
    var sEl = $("#loop-status");
    var rEl = $("#loop-recent");
    var sr = await api("GET", "/api/loop/status");
    if (sr.ok && sEl) {
      var s = sr.data;
      var h = "<strong>Running:</strong> " + (s.running ? "Yes" : "No");
      h += " | <strong>Steps:</strong> " + (s.steps_completed || 0) + "/" + (s.max_steps || 0);
      if (s.stopped_reason) h += '<br><span class="task-status blocked">' + esc(s.stopped_reason) + "</span>";
      if (s.started_at) h += "<br><small>Started: " + esc(s.started_at) + "</small>";
      if (s.finished_at) h += " <small>Finished: " + esc(s.finished_at) + "</small>";
      sEl.innerHTML = h;
    }
    var rr = await api("GET", "/api/loop/recent?limit=10");
    if (rr.ok && rEl) {
      var steps = rr.data.steps || [];
      if (!steps.length) { rEl.innerHTML = "<em>No steps executed yet</em>"; }
      else {
        var h2 = "";
        steps.forEach(function (s) {
          h2 += '<div class="info-block" style="margin:.2rem 0;padding:.3rem .5rem">';
          h2 += "<strong>#" + s.step_number + "</strong> ";
          h2 += statusBadge(s.outcome || "pending") + " ";
          h2 += esc(s.action_type || "") + " ";
          if (s.task_title) h2 += "— " + esc(s.task_title);
          if (s.action_detail) h2 += "<br><small>" + esc(s.action_detail) + "</small>";
          if (s.reason) h2 += "<br><small>" + esc(s.reason) + "</small>";
          h2 += "</div>";
        });
        rEl.innerHTML = h2;
      }
    }
  }

  export async function runLoopSteps(n) {
    var sEl = $("#loop-status");
    if (sEl) sEl.innerHTML = '<span class="loading">Running ' + n + ' step(s)...</span>';
    var r;
    if (n === 1) {
      r = await api("POST", "/api/loop/step");
    } else {
      r = await api("POST", "/api/loop/run", { max_steps: n });
    }
    loadLoopStatus();
  }

  (function () {
    var loaded = false;
    $$('.tab[data-tab="loop"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) { loaded = true; loadLoopStatus(); }
      });
    });
    var refreshBtn = $("#btn-refresh-loop");
    if (refreshBtn) refreshBtn.addEventListener("click", loadLoopStatus);
    var stepBtn = $("#btn-loop-step");
    if (stepBtn) stepBtn.addEventListener("click", function () { runLoopSteps(1); });
    var run3Btn = $("#btn-loop-run3");
    if (run3Btn) run3Btn.addEventListener("click", function () { runLoopSteps(3); });
    var run5Btn = $("#btn-loop-run5");
    if (run5Btn) run5Btn.addEventListener("click", function () { runLoopSteps(5); });
  })();

