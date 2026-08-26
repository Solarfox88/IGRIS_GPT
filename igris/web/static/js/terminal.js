// IGRIS_GPT — Terminal & Files module (#1318)
import { $, $$, esc } from "./utils.js";
import { api } from "./api.js";

  // Terminal
  (function () {
    var loaded = false;
    $$('.tab[data-tab="terminal"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) { loaded = true; loadTerminalCommands(); }
      });
    });
  })();

  export async function loadTerminalCommands() {
    var r = await api("GET", "/api/terminal/commands");
    if (!r.ok) return;
    var container = $("#terminal-commands");
    container.innerHTML = "";
    r.data.commands.forEach(function (cmd) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "cmd-btn";
      b.textContent = cmd;
      b.setAttribute("aria-label", "Run " + cmd);
      b.addEventListener("click", function () { runTerminalCommand(cmd); });
      container.appendChild(b);
    });
  }

  export async function runTerminalCommand(cmdId) {
    var out = $("#terminal-output");
    out.textContent = "Running " + cmdId + "...";
    var r = await api("POST", "/api/terminal/run", { command_id: cmdId });
    if (r.ok) {
      out.textContent = (r.data.stdout || "") + (r.data.stderr ? "\nSTDERR:\n" + r.data.stderr : "");
    } else {
      out.textContent = "Error: " + (r.data.detail || r.data.error || "unknown");
    }
  }

  // Files
  (function () {
    var loaded = false;
    $$('.tab[data-tab="files"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!loaded) { loaded = true; loadFileTree(); }
      });
    });
  })();

  export async function loadFileTree() {
    var r = await api("GET", "/api/files/tree");
    if (!r.ok) return;
    var container = $("#file-tree");
    container.innerHTML = "";
    (r.data.tree || []).forEach(function (dir) {
      var dirEl = document.createElement("div");
      dirEl.className = "ft-dir";
      dirEl.textContent = dir.path === "." ? "/" : dir.path;
      container.appendChild(dirEl);
      (dir.entries || []).forEach(function (e) {
        var el = document.createElement("div");
        el.className = e.type === "dir" ? "ft-dir" : "ft-file";
        el.textContent = (e.type === "dir" ? "\uD83D\uDCC1 " : "\uD83D\uDCC4 ") + e.name;
        if (e.type === "file") {
          var filePath = (dir.path === "." ? "" : dir.path + "/") + e.name;
          el.addEventListener("click", function () { previewFile(filePath); });
        }
        container.appendChild(el);
      });
    });
  }

  async function previewFile(path) {
    var out = $("#file-preview");
    out.textContent = "Loading " + path + "...";
    var r = await api("GET", "/api/files/preview?path=" + encodeURIComponent(path));
    if (r.ok) {
      out.textContent = r.data.preview || "(empty)";
    } else {
      out.textContent = "Error " + r.status + ": " + (r.data.detail || "Access denied or file not found");
    }
  }

