// IGRIS_GPT — Utility functions (#1318)
// Extracted from app.js to reduce monolith size.

export function $(sel) { return document.querySelector(sel); }
export function $$(sel) { return document.querySelectorAll(sel); }

export function esc(s) {
  var d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

export function kvTable(obj) {
  var h = "<table>";
  for (var k in obj) {
    if (!obj.hasOwnProperty(k)) continue;
    var v = obj[k];
    var val = typeof v === "object" ? JSON.stringify(v) : String(v);
    h += "<tr><th>" + esc(k) + "</th><td>" + esc(val) + "</td></tr>";
  }
  return h + "</table>";
}

export function statusBadge(status) {
  var cls = status === "completed" ? "completed" : status === "blocked" ? "blocked" : status === "running" ? "running" : "pending";
  return '<span class="task-status ' + cls + '">' + esc(status) + "</span>";
}

export function _intValue(id, fallback) {
  var el = document.getElementById(id);
  if (!el || el.value === "") return fallback;
  var v = parseInt(el.value, 10);
  return isNaN(v) ? fallback : v;
}

export function _floatValue(id, fallback) {
  var el = document.getElementById(id);
  if (!el || el.value === "") return fallback;
  var v = parseFloat(el.value);
  return isNaN(v) ? fallback : v;
}
