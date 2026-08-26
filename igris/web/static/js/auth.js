/**
 * IGRIS Auth Client — #1272 PR5
 *
 * Handles enrollment, login, logout, session token storage.
 *
 * SECURITY:
 * - Passwords never sent as chat messages
 * - Session token stored in sessionStorage (not localStorage, not URL)
 * - Token used only in Authorization: Bearer header
 * - No console.log of password or token
 * - Generic error messages for login failure (no user enumeration)
 */

/* global sessionStorage, fetch */

// ── Storage key ─────────────────────────────────────────────────────────────

var _IGRIS_TOKEN_KEY = "igris_session_token";

/**
 * Return the stored session token or empty string.
 * Never log the result.
 */
function getSessionToken() {
  try {
    return sessionStorage.getItem(_IGRIS_TOKEN_KEY) || "";
  } catch (e) {
    return "";
  }
}

function setSessionToken(token) {
  try {
    if (token) {
      sessionStorage.setItem(_IGRIS_TOKEN_KEY, token);
    }
  } catch (e) {
    /* storage unavailable — best-effort */
  }
}

function clearSessionToken() {
  try {
    sessionStorage.removeItem(_IGRIS_TOKEN_KEY);
  } catch (e) {
    /* best-effort */
  }
}

/**
 * Return Authorization headers for authenticated requests.
 * Returns empty object if no token.
 */
function authHeaders() {
  var tok = getSessionToken();
  if (!tok) return {};
  return { "Authorization": "Bearer " + tok };
}

// ── API helpers ──────────────────────────────────────────────────────────────

/**
 * Normalize FastAPI / Pydantic error responses into our standard
 * { ok: false, error: "...", details: [...] } shape.
 * FastAPI uses { "detail": "Not Found" } for 404 and
 * { "detail": [{loc, msg, type}, ...] } for 422 validation errors.
 */
function _normalizeApiError(httpStatus, data) {
  // Already in our format
  if (data.error !== undefined) return data;
  // FastAPI detail
  if (data.detail !== undefined) {
    var d = data.detail;
    if (typeof d === "string") {
      // 404 "Not Found" → route_not_found; 403 → forbidden; etc.
      var errCode = httpStatus === 404 ? "route_not_found"
                  : httpStatus === 403 ? "forbidden"
                  : httpStatus === 422 ? "validation_failed"
                  : httpStatus >= 500  ? "internal_error"
                  : "request_error";
      return { ok: false, error: errCode, details: [d] };
    }
    if (Array.isArray(d)) {
      var msgs = d.map(function(e) { return e.msg || JSON.stringify(e); });
      return { ok: false, error: "validation_failed", details: msgs };
    }
  }
  return { ok: false, error: "unknown_error" };
}

async function _authFetch(method, path, body) {
  var opts = {
    method: method,
    headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
  };
  if (body !== undefined && body !== null) {
    opts.body = JSON.stringify(body);
  }
  try {
    var r = await fetch(path, opts);
    var data = await r.json();
    // Normalize FastAPI error format to our { ok, error, details } shape
    if (!r.ok || data.ok === false) {
      data = _normalizeApiError(r.status, data);
    }
    return { ok: r.ok && data.ok !== false, status: r.status, data: data };
  } catch (e) {
    return { ok: false, status: 0, data: { ok: false, error: "network_error", details: [String(e.message || e)] } };
  }
}

// ── Auth flows ───────────────────────────────────────────────────────────────

/**
 * Start enrollment — step 1.
 * Returns { ok, enrollment_token, expires_at, profile_id, error, details }
 */
async function authEnrollStart({ username, firstName, lastName, email, mobilePhone }) {
  var r = await _authFetch("POST", "/api/auth/enroll/start", {
    username: username,
    first_name: firstName,
    last_name: lastName,
    email: email,
    mobile_phone: mobilePhone,
  });
  return r.data || { ok: false, error: "network_error" };
}

/**
 * Complete enrollment — step 2. Sets session token if successful.
 * Returns { ok, session_token, profile_id, error }
 */
async function authEnrollComplete({ enrollmentToken, password, confirmPassword }) {
  // SECURITY: password sent over HTTPS POST body only, never in URL or chat
  var r = await _authFetch("POST", "/api/auth/enroll/complete", {
    enrollment_token: enrollmentToken,
    password: password,
    confirm_password: confirmPassword,
  });
  var d = r.data || { ok: false, error: "network_error" };
  if (d.ok && d.session_token) {
    setSessionToken(d.session_token);
    // Return without the raw token in the result for callers — they use getSessionToken()
    return { ok: true, profile_id: d.profile_id, expires_at: d.expires_at };
  }
  return { ok: false, error: d.error || "enroll_failed" };
}

/**
 * Login — sets session token if successful.
 * Returns { ok, profile_id } or { ok: false, error: "invalid_credentials" }
 */
async function authLogin({ username, password }) {
  var r = await _authFetch("POST", "/api/auth/login", {
    username: username,
    password: password,
  });
  var d = r.data || { ok: false, error: "network_error" };
  if (d.ok && d.session_token) {
    setSessionToken(d.session_token);
    return { ok: true, profile_id: d.profile_id, expires_at: d.expires_at };
  }
  // Always return generic error — no user enumeration
  return { ok: false, error: "invalid_credentials" };
}

/**
 * Logout — revokes server-side session and clears local token.
 */
async function authLogout() {
  var tok = getSessionToken();
  if (tok) {
    // Best-effort server revoke
    try {
      await _authFetch("POST", "/api/auth/logout");
    } catch (e) {
      /* best-effort */
    }
  }
  clearSessionToken();
  return { ok: true };
}

/**
 * Fetch current user profile (no sensitive fields).
 * Returns { ok, profile: { profile_id, display_name, trust_level, ... } }
 * or { ok: false, error: "authentication_required" }
 */
async function authMe() {
  var r = await _authFetch("GET", "/api/auth/me");
  return r.data || { ok: false, error: "network_error" };
}

// ── UI state management ──────────────────────────────────────────────────────

/**
 * Update topbar identity display from session.
 * Called after login / enrollment / on page load.
 */
