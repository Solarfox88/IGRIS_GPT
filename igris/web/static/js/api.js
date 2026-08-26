// IGRIS_GPT — API wrapper (#1318)
// Extracted from app.js to reduce monolith size.

export async function api(method, url, body, extraHeaders) {
  var hdrs = Object.assign({ "Content-Type": "application/json" }, extraHeaders || {});
  var opts = { method: method, headers: hdrs };
  if (body) opts.body = JSON.stringify(body);
  try {
    var r = await fetch(url, opts);
    return { ok: r.ok, status: r.status, data: await r.json() };
  } catch (e) {
    return { ok: false, status: 0, data: { error: e.message } };
  }
}

export async function apiWithTimeout(method, url, body, timeoutMs) {
  var timeout = typeof timeoutMs === "number" && timeoutMs > 0 ? timeoutMs : 5000;
  return Promise.race([
    api(method, url, body),
    new Promise(function (resolve) {
      setTimeout(function () {
        resolve({
          ok: false,
          status: 0,
          data: { error: "timeout after " + String(timeout) + "ms" },
        });
      }, timeout);
    }),
  ]);
}
