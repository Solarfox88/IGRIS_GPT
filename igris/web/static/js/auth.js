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
    return { ok: r.ok && data.ok !== false, status: r.status, data: data };
  } catch (e) {
    return { ok: false, status: 0, data: { error: String(e.message || e) } };
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
async function authUpdateUI() {
  var r = await authMe();
  if (r.ok && r.profile) {
    var p = r.profile;
    var tbName = document.getElementById("tb-name");
    var tbAvatar = document.getElementById("tb-avatar");
    var tbTrust = document.getElementById("tb-trust");
    var tbAuthBtn = document.getElementById("tb-auth-btn");
    var tbLogoutBtn = document.getElementById("tb-logout-btn");
    if (tbName) tbName.textContent = p.display_name || p.profile_id;
    if (tbAvatar) tbAvatar.textContent = (p.display_name || p.profile_id || "?")[0].toUpperCase();
    if (tbTrust) tbTrust.textContent = p.trust_level || "";
    if (tbAuthBtn) tbAuthBtn.style.display = "none";
    if (tbLogoutBtn) tbLogoutBtn.style.display = "";
    // Expose profile_id for chat (read-only display, not auth)
    window._igrisAuthProfileId = p.profile_id;
  } else {
    _authClearUI();
  }
}

function _authClearUI() {
  var tbName = document.getElementById("tb-name");
  var tbAvatar = document.getElementById("tb-avatar");
  var tbTrust = document.getElementById("tb-trust");
  var tbAuthBtn = document.getElementById("tb-auth-btn");
  var tbLogoutBtn = document.getElementById("tb-logout-btn");
  if (tbName) tbName.textContent = "—";
  if (tbAvatar) tbAvatar.textContent = "?";
  if (tbTrust) tbTrust.textContent = "—";
  if (tbAuthBtn) tbAuthBtn.style.display = "";
  if (tbLogoutBtn) tbLogoutBtn.style.display = "none";
  window._igrisAuthProfileId = null;
}

// ── Modal helpers ────────────────────────────────────────────────────────────

function _showModal(id) {
  var m = document.getElementById(id);
  if (m) { m.style.display = "flex"; m.setAttribute("aria-hidden", "false"); }
}

function _hideModal(id) {
  var m = document.getElementById(id);
  if (m) { m.style.display = "none"; m.setAttribute("aria-hidden", "true"); }
}

function _setModalError(elId, msg) {
  var el = document.getElementById(elId);
  if (el) { el.textContent = msg || ""; el.style.display = msg ? "" : "none"; }
}

// ── Login modal flow ─────────────────────────────────────────────────────────

function authShowLogin() { _showModal("auth-login-modal"); }
function authHideLogin() {
  _hideModal("auth-login-modal");
  _setModalError("auth-login-error", "");
}

async function authSubmitLogin() {
  var uname = (document.getElementById("auth-login-username") || {}).value || "";
  var pw = (document.getElementById("auth-login-password") || {}).value || "";
  if (!uname || !pw) {
    _setModalError("auth-login-error", "Inserisci username e password.");
    return;
  }
  var btn = document.getElementById("auth-login-submit");
  if (btn) btn.disabled = true;

  var r = await authLogin({ username: uname, password: pw });
  // Clear password field immediately — never keep in DOM longer than needed
  var pwField = document.getElementById("auth-login-password");
  if (pwField) pwField.value = "";

  if (r.ok) {
    authHideLogin();
    await authUpdateUI();
  } else {
    _setModalError("auth-login-error", "Credenziali non valide.");
  }
  if (btn) btn.disabled = false;
}

// ── Enrollment modal flow (2 steps) ──────────────────────────────────────────

var _enrollmentToken = null;  // held in memory between step 1 and step 2

function authShowEnroll() {
  _enrollmentToken = null;
  _showModal("auth-enroll-modal");
  _showEnrollStep(1);
}
function authHideEnroll() {
  _hideModal("auth-enroll-modal");
  _setModalError("auth-enroll-error", "");
  _enrollmentToken = null;
}

function _showEnrollStep(n) {
  var s1 = document.getElementById("auth-enroll-step1");
  var s2 = document.getElementById("auth-enroll-step2");
  if (s1) s1.style.display = n === 1 ? "" : "none";
  if (s2) s2.style.display = n === 2 ? "" : "none";
}

async function authSubmitEnrollStep1() {
  var vals = {
    username: (document.getElementById("auth-enroll-username") || {}).value || "",
    firstName: (document.getElementById("auth-enroll-firstname") || {}).value || "",
    lastName: (document.getElementById("auth-enroll-lastname") || {}).value || "",
    email: (document.getElementById("auth-enroll-email") || {}).value || "",
    mobilePhone: (document.getElementById("auth-enroll-phone") || {}).value || "",
  };
  if (!vals.username || !vals.firstName || !vals.lastName || !vals.email || !vals.mobilePhone) {
    _setModalError("auth-enroll-error", "Compila tutti i campi.");
    return;
  }
  var btn = document.getElementById("auth-enroll-step1-btn");
  if (btn) btn.disabled = true;

  var r = await authEnrollStart(vals);

  if (r.ok && r.enrollment_token) {
    _enrollmentToken = r.enrollment_token;
    _setModalError("auth-enroll-error", "");
    _showEnrollStep(2);
  } else {
    var detail = r.details ? r.details.join(", ") : (r.error || "Errore sconosciuto.");
    _setModalError("auth-enroll-error", "Errore: " + detail);
  }
  if (btn) btn.disabled = false;
}

async function authSubmitEnrollStep2() {
  var pw = (document.getElementById("auth-enroll-password") || {}).value || "";
  var pw2 = (document.getElementById("auth-enroll-confirm") || {}).value || "";
  if (!pw || !pw2) {
    _setModalError("auth-enroll-error", "Inserisci e conferma la password.");
    return;
  }
  var btn = document.getElementById("auth-enroll-step2-btn");
  if (btn) btn.disabled = true;

  var r = await authEnrollComplete({
    enrollmentToken: _enrollmentToken,
    password: pw,
    confirmPassword: pw2,
  });

  // Clear password fields immediately
  var pf1 = document.getElementById("auth-enroll-password");
  var pf2 = document.getElementById("auth-enroll-confirm");
  if (pf1) pf1.value = "";
  if (pf2) pf2.value = "";
  _enrollmentToken = null;

  if (r.ok) {
    authHideEnroll();
    await authUpdateUI();
  } else {
    _setModalError("auth-enroll-error", "Errore: " + (r.error || "enroll_failed"));
  }
  if (btn) btn.disabled = false;
}

// ── Logout ───────────────────────────────────────────────────────────────────

async function authDoLogout() {
  await authLogout();
  _authClearUI();
}

// ── Init on page load ─────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", function () {
  // Restore UI state from existing session if any
  if (getSessionToken()) {
    authUpdateUI().catch(function () { _authClearUI(); });
  }
});
