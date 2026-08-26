// IGRIS_GPT — Patches module (#1318)
// Extracted from app.js: patch list, detail, validate, apply, reject.
import { $, esc, statusBadge } from "./utils.js";
import { api } from "./api.js";

  export async function loadPatches() {
    var container = $("#patches-list");
    if (!container) return;
    container.innerHTML = '<span class="loading">Loading...</span>';
    var r = await api("GET", "/api/patches");
    if (!r.ok) { container.innerHTML = '<span class="error">Failed to load patches</span>'; return; }
    var patches = r.data.patches || [];
    if (!patches.length) { container.innerHTML = "<em>No patch proposals yet.</em>"; return; }
    var html = "";
    patches.forEach(function (p) {
      html += '<div class="patch-item" data-patch-id="' + esc(p.id) + '">' +
        '<span class="pi-title">' + esc(p.title) + '</span> ' +
        '<span class="patch-status ' + esc(p.status) + '">' + esc(p.status) + '</span>' +
        '<div class="pi-meta">' + esc(p.file_count) + ' file(s) | risk: ' + esc(p.risk) + ' | ' + esc(p.created_at) + '</div>' +
        '</div>';
    });
    container.innerHTML = html;
    $$(".patch-item").forEach(function (el) {
      el.addEventListener("click", function () { loadPatchDetail(el.dataset.patchId); });
    });
  }

  export async function loadPatchDetail(id) {
    var detail = $("#patch-detail");
    var diffBox = $("#patch-diff");
    var actions = $("#patch-actions");
    if (!detail) return;
    detail.innerHTML = '<span class="loading">Loading...</span>';
    if (diffBox) diffBox.innerHTML = "";
    if (actions) actions.innerHTML = "";

    var r = await api("GET", "/api/patches/" + id);
    if (!r.ok) { detail.innerHTML = '<span class="error">Failed to load proposal</span>'; return; }
    var p = r.data;

    var html = "<strong>" + esc(p.title) + "</strong> " +
      '<span class="patch-status ' + esc(p.status) + '">' + esc(p.status) + '</span>' +
      "<p>" + esc(p.description) + "</p>" +
      "<p>Risk: " + esc(p.risk) + " | Files: " + p.files.length + "</p>";
    if (p.validation) {
      html += "<p><strong>Validation:</strong> " + (p.validation.valid ? "PASSED" : "FAILED") + " (risk: " + esc(p.validation.risk) + ")</p>";
      if (p.validation.reasons && p.validation.reasons.length) {
        html += "<ul>";
        p.validation.reasons.forEach(function (r) { html += "<li>" + esc(r) + "</li>"; });
        html += "</ul>";
      }
    }
    if (p.safety_notes) html += "<p><em>" + esc(p.safety_notes) + "</em></p>";
    if (p.rollback_notes) html += "<p>Rollback: " + esc(p.rollback_notes) + "</p>";
    if (p.reject_reason) html += "<p>Rejection: " + esc(p.reject_reason) + "</p>";
    detail.innerHTML = html;

    // Render diffs
    if (diffBox && p.files) {
      var dhtml = "";
      p.files.forEach(function (f) {
        dhtml += '<div class="diff-line diff-hdr">--- ' + esc(f.path) + ' (' + esc(f.action) + ')</div>';
        if (f.diff) {
          f.diff.split("\n").forEach(function (line) {
            var cls = "diff-ctx";
            if (line.startsWith("+")) cls = "diff-add";
            else if (line.startsWith("-")) cls = "diff-del";
            else if (line.startsWith("@@")) cls = "diff-hdr";
            dhtml += '<div class="diff-line ' + cls + '">' + esc(line) + '</div>';
          });
        } else {
          dhtml += '<div class="diff-line diff-ctx">(no diff)</div>';
        }
      });
      diffBox.innerHTML = dhtml;
    }

    // Action buttons
    if (actions) {
      var btns = "";
      if (p.status === "proposed" || p.status === "validated") {
        btns += '<button type="button" class="action-btn" id="btn-patch-validate">Validate</button> ';
      }
      if (p.status === "validated") {
        btns += '<button type="button" class="action-btn" id="btn-patch-apply" style="background:#238636">Apply</button> ';
      }
      if (p.status !== "applied" && p.status !== "rejected") {
        btns += '<button type="button" class="action-btn" id="btn-patch-reject" style="background:#da3633">Reject</button>';
      }
      actions.innerHTML = btns;

      var valBtn = $("#btn-patch-validate");
      if (valBtn) valBtn.addEventListener("click", function () { validatePatch(id); });
      var appBtn = $("#btn-patch-apply");
      if (appBtn) appBtn.addEventListener("click", function () { applyPatch(id); });
      var rejBtn = $("#btn-patch-reject");
      if (rejBtn) rejBtn.addEventListener("click", function () { rejectPatch(id); });
    }
  }

  export async function validatePatch(id) {
    var detail = $("#patch-detail");
    var r = await api("POST", "/api/patches/" + id + "/validate");
    if (r.ok) {
      loadPatchDetail(id);
      loadPatches();
    } else {
      if (detail) detail.innerHTML += '<p class="error">Validation error: ' + esc(r.data.detail || "unknown") + '</p>';
    }
  }

  export async function applyPatch(id) {
    var detail = $("#patch-detail");
    var r = await api("POST", "/api/patches/" + id + "/apply");
    if (r.ok) {
      loadPatchDetail(id);
      loadPatches();
    } else {
      if (detail) detail.innerHTML += '<p class="error">Apply error: ' + esc(r.data.detail || "unknown") + '</p>';
    }
  }

  export async function rejectPatch(id) {
    var reason = prompt("Rejection reason (optional):");
    var r = await api("POST", "/api/patches/" + id + "/reject", { reason: reason || "" });
    if (r.ok) {
      loadPatchDetail(id);
      loadPatches();
    }
  }

