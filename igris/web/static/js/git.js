// IGRIS_GPT — Git module (#1318)
import { $, $$, esc, kvTable } from "./utils.js";
import { api } from "./api.js";

  // Git
  (function () {
    var loaded = false;
    $$('.tab[data-tab="git"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) { loaded = true; loadGit(); loadBranches(); }
      });
    });
  })();

  export async function loadGit() {
    var r = await api("GET", "/api/git/status");
    if (r.ok) {
      $("#git-info").innerHTML = kvTable(r.data);
    } else {
      $("#git-info").innerHTML = '<span class="error">Failed to load git status</span>';
    }
  }

  export async function loadBranches() {
    var r = await api("GET", "/api/git/branches");
    if (r.ok) {
      var d = r.data;
      var html = "<strong>Current:</strong> " + esc(d.current || "unknown") + "<br>";
      html += "<strong>Branches:</strong> " + (d.branches || []).map(function(b) { return esc(b); }).join(", ");
      $("#git-branches").innerHTML = html;
    }
  }

  export async function loadDiff(staged) {
    var url = "/api/git/diff" + (staged ? "?staged=true" : "");
    var r = await api("GET", url);
    if (r.ok) {
      var d = r.data;
      if (!d.diff) {
        $("#git-diff").innerHTML = "<em>No changes</em>";
        return;
      }
      var lines = d.diff.split("\n").map(function(l) {
        if (l.startsWith("+++") || l.startsWith("---")) return '<div class="diff-line diff-hdr">' + esc(l) + '</div>';
        if (l.startsWith("+")) return '<div class="diff-line diff-add">' + esc(l) + '</div>';
        if (l.startsWith("-")) return '<div class="diff-line diff-del">' + esc(l) + '</div>';
        if (l.startsWith("@@")) return '<div class="diff-line diff-hdr">' + esc(l) + '</div>';
        return '<div class="diff-line diff-ctx">' + esc(l) + '</div>';
      }).join("");
      var warn = d.secret_detected ? '<div class="error">⚠ Secret-like content detected and redacted</div>' : '';
      $("#git-diff").innerHTML = warn + lines;
    }
  }

  (function() {
    var el = $("#btn-refresh-git");
    if (el) el.addEventListener("click", function() { loadGit(); loadBranches(); });
    el = $("#btn-load-diff");
    if (el) el.addEventListener("click", function() { loadDiff(false); });
    el = $("#btn-load-staged-diff");
    if (el) el.addEventListener("click", function() { loadDiff(true); });

    el = $("#btn-git-safety");
    if (el) el.addEventListener("click", async function() {
      var r = await api("GET", "/api/git/safety-check");
      if (r.ok) {
        var d = r.data;
        var html = "<strong>Safe:</strong> " + (d.safe ? "✓ Yes" : "✗ No") + "<br>";
        if (d.staged_files && d.staged_files.length) html += "<strong>Staged:</strong> " + d.staged_files.map(esc).join(", ") + "<br>";
        if (d.warnings && d.warnings.length) html += '<div class="error">' + d.warnings.map(esc).join("<br>") + '</div>';
        if (d.secret_files && d.secret_files.length) html += "<strong>Secret files:</strong> " + d.secret_files.map(esc).join(", ") + "<br>";
        if (d.runtime_artifacts && d.runtime_artifacts.length) html += "<strong>Artifacts:</strong> " + d.runtime_artifacts.map(esc).join(", ");
        $("#git-safety").innerHTML = html;
      }
    });

    var branchForm = $("#git-branch-form");
    if (branchForm) branchForm.addEventListener("submit", async function(e) {
      e.preventDefault();
      var name = $("#git-branch-name").value.trim();
      if (!name) return;
      var r = await api("POST", "/api/git/branch", { name: name });
      if (r.ok && r.data.success) {
        $("#git-branch-name").value = "";
        loadGit();
        loadBranches();
      } else {
        alert("Error: " + (r.data.error || "Failed to create branch"));
      }
    });

    var commitForm = $("#git-commit-form");
    if (commitForm) commitForm.addEventListener("submit", async function(e) {
      e.preventDefault();
      var msg = $("#git-commit-msg").value.trim();
      if (!msg) return;
      var r = await api("POST", "/api/git/commit-proposal", { message: msg });
      if (r.ok) {
        var d = r.data;
        var html = "<strong>Message:</strong> " + esc(d.message) + "<br>";
        html += "<strong>Safe:</strong> " + (d.safe ? "✓ Yes" : "✗ No") + "<br>";
        if (d.files && d.files.length) html += "<strong>Files:</strong> " + d.files.map(esc).join(", ") + "<br>";
        if (d.warnings && d.warnings.length) html += '<div class="error">' + d.warnings.map(esc).join("<br>") + '</div>';
        if (d.blocked_files && d.blocked_files.length) html += "<strong>Blocked:</strong> " + d.blocked_files.map(esc).join(", ") + "<br>";
        if (d.secret_files && d.secret_files.length) html += "<strong>Secret files:</strong> " + d.secret_files.map(esc).join(", ");
        $("#git-commit-proposal").innerHTML = html;
      }
    });

    var prBtn = $("#btn-pr-summary");
    if (prBtn) prBtn.addEventListener("click", async function() {
      var r = await api("GET", "/api/git/pr-summary");
      if (r.ok) {
        var d = r.data;
        if (d.error) { $("#git-pr-summary").innerHTML = '<span class="error">' + esc(d.error) + '</span>'; return; }
        var html = "<strong>Branch:</strong> " + esc(d.branch) + " → " + esc(d.base) + "<br>";
        html += "<strong>Commits:</strong> " + (d.commit_count || 0) + "<br>";
        if (d.commits && d.commits.length) html += "<pre>" + d.commits.map(esc).join("\n") + "</pre>";
        if (d.summary) html += "<strong>Summary:</strong> " + esc(d.summary) + "<br>";
        if (d.stat) html += "<pre>" + esc(d.stat) + "</pre>";
        $("#git-pr-summary").innerHTML = html;
      }
    });
  })();

  // Tests
  (function () {
    var btn = $("#btn-run-tests");
    if (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        btn.textContent = "Running...";
        var out = $("#test-output");
        out.textContent = "Running tests...";
        var r = await api("POST", "/api/tests/run");
        btn.disabled = false;
        btn.textContent = "Run Tests";
        if (r.ok) {
          var prefix = r.data.success ? "PASSED\n" : "FAILED\n";
          out.textContent = prefix + (r.data.stdout || "") + (r.data.stderr ? "\nSTDERR:\n" + r.data.stderr : "");
        } else {
          out.textContent = "Error: " + (r.data.detail || "unknown");
        }
      });
    }
  })();

  // Logs
  (function () {
    var btn = $("#btn-refresh-logs");
    if (btn) {
      btn.addEventListener("click", async function () {
        var out = $("#logs-output");
        out.textContent = "Loading logs...";
        var r = await api("GET", "/api/logs");
        out.textContent = r.ok ? (r.data.logs || "(empty)") : "Error loading logs";
      });
    }
  })();

  // Agent Timeline
  (function () {
    var btn = $("#btn-refresh-timeline");
    if (btn) {
      btn.addEventListener("click", loadTimeline);
    }
    $$('.tab[data-tab="agent"]').forEach(function (b) {
      b.addEventListener("click", loadTimeline);
    });
  })();

  export async function loadTimeline() {
    var container = $("#timeline-list");
    container.innerHTML = '<span class="loading">Loading...</span>';
    var r = await api("GET", "/api/agent/timeline");
    if (!r.ok) { container.innerHTML = '<span class="error">Failed</span>'; return; }
    var events = r.data.timeline || [];
    if (!events.length) { container.innerHTML = "<em>No events yet.</em>"; return; }
    container.innerHTML = "";
    events.reverse().forEach(function (ev) {
      var d = document.createElement("div");
      d.className = "timeline-event";
      var severity = ev.severity || "info";
      var icon = severity === "warning" ? "\u26A0" : severity === "error" ? "\u274C" : "\u2022";
      var typeLabel = ev.type ? "[" + ev.type + "] " : "";
      var title = ev.title || ev.event || "";
      var detail = ev.detail || "";
      d.innerHTML = '<span class="te-icon">' + icon + '</span> ' +
        '<span class="te-type">' + esc(typeLabel) + '</span>' +
        '<strong>' + esc(title) + '</strong>' +
        (detail ? ' <span class="te-detail">' + esc(detail) + '</span>' : '') +
        (ev.timestamp ? ' <span class="te-time">' + esc(ev.timestamp) + '</span>' : '');
      container.appendChild(d);
    });
  }

  // Tasks
  (function () {
    var loaded = false;
    $$('.tab[data-tab="tasks"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) loaded = true;
        loadTasks();
      });
    });
    var form = $("#task-form");
    if (form) {
      form.addEventListener("submit", async function (e) {
        e.preventDefault();
        var desc = $("#task-input").value.trim();
        var title = $("#task-title-input") ? $("#task-title-input").value.trim() : "";
        if (!desc) return;
        var body = { description: desc };
        if (title) body.title = title;
        await api("POST", "/api/tasks", body);
        if ($("#task-input")) $("#task-input").value = "";
        if ($("#task-title-input")) $("#task-title-input").value = "";
        loadTasks();
      });
    }
  })();

  async function loadTasks() {
    var container = $("#task-list");
    container.innerHTML = '<span class="loading">Loading...</span>';
    var r = await api("GET", "/api/tasks");
    if (!r.ok) { container.innerHTML = '<span class="error">Failed</span>'; return; }
    var tasks = r.data.tasks || [];
    if (!tasks.length) { container.innerHTML = "<em>No tasks.</em>"; return; }
    container.innerHTML = "";
    tasks.forEach(function (t) {
      var d = document.createElement("div");
      d.className = "task-item";
      d.innerHTML =
        '<div class="task-header">' + statusBadge(t.status) +
        ' <strong>' + esc(t.title || t.description) + '</strong>' +
        ' <span class="task-meta">#' + t.id + ' | ' + esc(t.family || "other") + ' | ' + esc(t.source || "user") + '</span></div>' +
        (t.description && t.title ? '<div class="task-desc">' + esc(t.description) + '</div>' : '') +
        '<div class="task-actions">' +
        (t.status === "pending" || t.status === "running" ?
          '<button type="button" class="btn-sm" data-action="complete" data-id="' + t.id + '" aria-label="Complete task">Complete</button>' +
          '<button type="button" class="btn-sm btn-warn" data-action="block" data-id="' + t.id + '" aria-label="Block task">Block</button>' : "") +
        '</div>';
      container.appendChild(d);
    });
    container.querySelectorAll("button[data-action]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        await api("POST", "/api/tasks/" + btn.dataset.id + "/" + btn.dataset.action, {});
        loadTasks();
      });
    });
  }

  // Safety
  (function () {
    $$('.tab[data-tab="safety"]').forEach(function (btn) {
      btn.addEventListener("click", loadSafety);
    });
    var refreshBtn = $("#btn-refresh-safety");
    if (refreshBtn) refreshBtn.addEventListener("click", loadSafety);
  })();

  async function loadSafety() {
    var r = await api("GET", "/api/safety/status");
    if (r.ok) {
      var html = "<strong>Anti-Loop Status</strong>" + kvTable(r.data);
      // Add outcome router info
      var outcomes = await api("GET", "/api/outcome/recent");
      if (outcomes.ok && outcomes.data.outcomes && outcomes.data.outcomes.length) {
        html += "<strong>Recent Outcomes</strong><table><tr><th>Action</th><th>Reason</th></tr>";
        outcomes.data.outcomes.forEach(function (o) {
          html += "<tr><td>" + esc(o.next_action || "none") + "</td><td>" + esc(o.reason || "") + "</td></tr>";
        });
        html += "</table>";
      }
      $("#safety-info").innerHTML = html;
    }
    loadReports();
  }

