// IGRIS_GPT — Missions module (#1318)
import { $, esc, statusBadge } from "./utils.js";
import { api } from "./api.js";

  var _selectedMissionId = null;

  export async function loadMissions() {
    var r = await api("GET", "/api/missions");
    var el = $("#mission-list");
    if (!el) return;
    if (!r.ok) { el.innerHTML = "<em>Failed to load missions</em>"; return; }
    var missions = r.data.missions || [];
    if (!missions.length) { el.innerHTML = "<em>No missions yet</em>"; return; }
    var h = "";
    missions.forEach(function (m) {
      h += '<div class="patch-item" data-mid="' + esc(m.id) + '" style="cursor:pointer">';
      h += "<strong>" + esc(m.title) + "</strong> " + statusBadge(m.status);
      h += "<br><small>" + (m.step_count || 0) + " steps | " + (m.task_ids || []).length + " tasks | " + esc(m.created_at) + "</small>";
      h += "</div>";
    });
    el.innerHTML = h;
    el.querySelectorAll(".patch-item").forEach(function (item) {
      item.addEventListener("click", function () {
        loadMissionDetail(item.dataset.mid);
      });
    });
  }

  export async function loadMissionDetail(missionId) {
    _selectedMissionId = missionId;
    var r = await api("GET", "/api/missions/" + missionId);
    var el = $("#mission-detail");
    if (!el) return;
    if (!r.ok) { el.innerHTML = "<em>Mission not found</em>"; return; }
    var m = r.data;
    var h = "<strong>" + esc(m.title) + "</strong> " + statusBadge(m.status);
    h += "<br>" + esc(m.description || "");
    h += "<br><small>Steps: " + (m.step_count || 0) + " | Tasks: " + (m.task_ids || []).length + "</small>";
    h += '<div style="margin-top:.5rem">';
    if (m.status === "created") {
      h += '<button type="button" class="action-btn" id="btn-plan-mission">Generate Plan</button> ';
    }
    if (m.status === "planned") {
      h += '<button type="button" class="action-btn" id="btn-materialize-mission">Materialize Tasks</button> ';
    }
    h += '<button type="button" class="action-btn" id="btn-graph-mission">Show Graph</button>';
    h += "</div>";
    if (m.steps && m.steps.length) {
      h += "<h5>Plan Steps</h5>";
      m.steps.forEach(function (s, i) {
        h += '<div class="info-block" style="margin:.3rem 0;padding:.4rem .6rem">';
        h += "<strong>" + (i + 1) + ".</strong> " + esc(s.title) + " " + statusBadge(s.status);
        h += " <small>[" + esc(s.family) + "]</small>";
        if (s.dependencies && s.dependencies.length) {
          h += " <small>deps: " + s.dependencies.length + "</small>";
        }
        if (s.success_criteria && s.success_criteria.length) {
          h += "<br><small>Criteria: " + s.success_criteria.map(esc).join(", ") + "</small>";
        }
        h += "</div>";
      });
    }
    el.innerHTML = h;

    var planBtn = $("#btn-plan-mission");
    if (planBtn) {
      planBtn.addEventListener("click", async function () {
        var pr = await api("POST", "/api/missions/" + missionId + "/plan");
        if (pr.ok) { loadMissionDetail(missionId); loadMissions(); }
        else alert("Plan error: " + (pr.data.detail || "unknown"));
      });
    }
    var matBtn = $("#btn-materialize-mission");
    if (matBtn) {
      matBtn.addEventListener("click", async function () {
        var mr = await api("POST", "/api/missions/" + missionId + "/materialize-tasks");
        if (mr.ok) { loadMissionDetail(missionId); loadMissions(); }
        else alert("Materialize error: " + (mr.data.detail || "unknown"));
      });
    }
    var graphBtn = $("#btn-graph-mission");
    if (graphBtn) {
      graphBtn.addEventListener("click", function () { loadMissionGraph(missionId); });
    }
  }

  export async function loadMissionGraph(missionId) {
    var r = await api("GET", "/api/missions/" + missionId + "/graph");
    var el = $("#mission-graph");
    if (!el) return;
    if (!r.ok) { el.innerHTML = "<em>Graph not available</em>"; return; }
    var g = r.data;
    var h = "<strong>" + esc(g.title) + "</strong> " + statusBadge(g.status);
    h += "<br><small>Nodes: " + g.nodes.length + " | Edges: " + g.edges.length + "</small>";
    h += '<div style="margin-top:.4rem">';
    g.nodes.forEach(function (n) {
      h += '<div style="display:inline-block;background:#21262d;border:1px solid #30363d;border-radius:4px;padding:.3rem .5rem;margin:.2rem;font-size:.78rem">';
      h += esc(n.title) + " " + statusBadge(n.status);
      h += "</div>";
    });
    if (g.edges.length) {
      h += "<br><small>Dependencies: ";
      g.edges.forEach(function (e) { h += esc(e.from.substring(0,6)) + "→" + esc(e.to.substring(0,6)) + " "; });
      h += "</small>";
    }
    h += "</div>";
    el.innerHTML = h;
  }

  // Mission form
  (function () {
    var form = $("#mission-form");
    if (!form) return;
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      var title = $("#mission-title").value.trim();
      var desc = $("#mission-desc").value.trim();
      if (!title) { alert("Mission title required"); return; }
      var r = await api("POST", "/api/missions", { title: title, description: desc });
      if (r.ok) {
        form.reset();
        loadMissions();
        loadMissionDetail(r.data.id);
      } else {
        alert("Error: " + (r.data.detail || r.data.error || "unknown"));
      }
    });
  })();

  // Mission refresh button
  (function () {
    var btn = $("#btn-refresh-missions");
    if (btn) btn.addEventListener("click", loadMissions);
  })();

