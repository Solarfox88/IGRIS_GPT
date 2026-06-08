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
    // Expose profile_id for chat and diagnostics panel (read-only display, not auth)
    window._igrisAuthProfileId = p.profile_id;
    // Notify app.js so sidebar/chat state is reconciled
    if (typeof window.onAuthStateChanged === "function") window.onAuthStateChanged(p);
  } else {
    _authClearUI();
  }
}

function _authClearUI() {
  // Always clear session token — prevents stale tokens from bypassing the
  // frontend auth gate. This is called when /api/auth/me returns non-ok
  // (expired/invalid session) as well as on explicit logout.
  clearSessionToken();
  var tbName = document.getElementById("tb-name");
  var tbAvatar = document.getElementById("tb-avatar");
  var tbTrust = document.getElementById("tb-trust");
  var tbAuthBtn = document.getElementById("tb-auth-btn");
  var tbLogoutBtn = document.getElementById("tb-logout-btn");
  if (tbName) tbName.textContent = "non autenticato";
  if (tbAvatar) tbAvatar.textContent = "?";
  if (tbTrust) tbTrust.textContent = "";
  if (tbAuthBtn) tbAuthBtn.style.display = "";
  if (tbLogoutBtn) tbLogoutBtn.style.display = "none";
  window._igrisAuthProfileId = null;
  // Notify app.js to reset sidebar/chat state
  if (typeof window.onAuthStateCleared === "function") window.onAuthStateCleared();
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

/** Map error codes returned by /api/auth/enroll/start to Italian UI messages. */
function _enrollErrorMsg(r) {
  var _MESSAGES = {
    username_taken:            "Nome utente già in uso. Scegline un altro.",
    invalid_username_format:   "Nome utente non valido (usa solo lettere minuscole, numeri, _ . -).",
    invalid_email:             "Indirizzo email non valido.",
    invalid_mobile_phone:      "Numero di telefono non valido (includi prefisso internazionale, es. +39…).",
    forbidden_field:           "Uno dei campi non è consentito.",
    validation_failed:         "Dati non validi: " + (r.details ? r.details.join("; ") : "controlla i campi."),
    route_not_found:           "Servizio di registrazione non disponibile. Riprova tra qualche istante.",
    internal_error:            "Errore interno del server. Riprova tra qualche istante.",
    network_error:             "Impossibile raggiungere il server. Controlla la connessione.",
    unknown_error:             "Errore sconosciuto. Riprova o contatta il supporto.",
  };
  // validation_failed may have details inline — rebuild with actual details
  if (r.error === "validation_failed" && r.details && r.details.length) {
    return "Dati non validi: " + r.details.join("; ");
  }
  return _MESSAGES[r.error] || ("Errore: " + (r.error || "sconosciuto"));
}

/** Map error codes returned by /api/auth/enroll/complete to Italian UI messages. */
function _enrollStep2ErrorMsg(r) {
  var _MESSAGES = {
    password_mismatch:          "Le due password non coincidono.",
    password_too_short_min_8:   "La password deve essere di almeno 8 caratteri.",
    password_requires_letter:   "La password deve contenere almeno una lettera.",
    password_requires_digit:    "La password deve contenere almeno un numero.",
    invalid_enrollment_token:   "Token di registrazione non valido. Ricomincia dal passo 1.",
    expired_enrollment_token:   "Il token di registrazione è scaduto. Ricomincia dal passo 1.",
    credential_already_exists:  "Utente già registrato. Accedi invece di registrarti.",
    create_failed:              "Errore durante la creazione dell'account. Riprova.",
    session_create_failed:      "Registrazione completata, ma accesso automatico fallito. Accedi manualmente.",
    internal_error:             "Errore interno del server. Riprova tra qualche istante.",
    network_error:              "Impossibile raggiungere il server. Controlla la connessione.",
    validation_failed:          "Dati non validi: token di registrazione mancante. Ricomincia dal passo 1.",
  };
  return _MESSAGES[r.error] || ("Errore: " + (r.error || "sconosciuto"));
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
    _setModalError("auth-enroll-error", _enrollErrorMsg(r));
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

  // Clear password fields immediately (security — never keep raw password in DOM)
  var pf1 = document.getElementById("auth-enroll-password");
  var pf2 = document.getElementById("auth-enroll-confirm");
  if (pf1) pf1.value = "";
  if (pf2) pf2.value = "";
  // _enrollmentToken cleared ONLY on success — on failure keep it so the user
  // can fix the password and retry without restarting from step 1.

  if (r.ok) {
    _enrollmentToken = null;  // consumed — clear now
    authHideEnroll();
    await authUpdateUI();
  } else {
    _setModalError("auth-enroll-error", _enrollStep2ErrorMsg(r));
  }
  if (btn) btn.disabled = false;
}

// ── Logout ───────────────────────────────────────────────────────────────────

async function authDoLogout() {
  await authLogout();
  _authClearUI();
}

// ── Auth-first onboarding gate (#1278) ───────────────────────────────────────

/** Enrollment intent keywords (Italian + English). */
var _ENROLL_KEYWORDS = [
  "registrarmi", "censirmi", "voglio registrarmi", "vorrei registrarmi",
  "voglio censirmi", "vorrei censirmi", "censiscimi", "registrami",
  "crea profilo", "creami un profilo", "nuovo profilo", "iscrivimi",
  "create profile", "sign up", "register", "enroll",
];

/** Login intent keywords. */
var _LOGIN_KEYWORDS = [
  "login", "accedi", "voglio accedere", "fai login", "autenticami",
  "sono già registrato", "ho già un profilo", "sign in", "log in",
  "accesso", "già registrato", "ho un account",
];

/**
 * Return true if text contains enrollment intent.
 * Never call LLM for these when unauthenticated.
 */
function isEnrollmentIntent(text) {
  if (!text) return false;
  var lower = text.toLowerCase().trim();
  for (var i = 0; i < _ENROLL_KEYWORDS.length; i++) {
    if (lower.indexOf(_ENROLL_KEYWORDS[i]) >= 0) return true;
  }
  return false;
}

/**
 * Return true if text contains login intent.
 * Never call LLM for these when unauthenticated.
 */
function isLoginIntent(text) {
  if (!text) return false;
  var lower = text.toLowerCase().trim();
  for (var i = 0; i < _LOGIN_KEYWORDS.length; i++) {
    if (lower.indexOf(_LOGIN_KEYWORDS[i]) >= 0) return true;
  }
  return false;
}

/** Return true if text is any auth-related intent. */
function isAuthIntent(text) {
  return isEnrollmentIntent(text) || isLoginIntent(text);
}

/**
 * Handle a chat message from an unauthenticated user.
 * Shows a deterministic UI message and opens the appropriate modal.
 * NEVER calls fetch() to the backend chat endpoint.
 *
 * @param {string} text - The message the user typed.
 * @param {function} [addMsgFn] - Optional function to add a UI message (text, role).
 * @returns {boolean} true = handled (caller must NOT call fetch), false = pass through.
 */
function handleUnauthenticatedMessage(text, addMsgFn) {
  if (isEnrollmentIntent(text)) {
    if (typeof addMsgFn === "function") {
      addMsgFn("Per creare il tuo profilo compila il modulo di registrazione.", "assistant");
    }
    authShowEnroll();
    return true;
  }
  if (isLoginIntent(text)) {
    if (typeof addMsgFn === "function") {
      addMsgFn("Accedi con username e password.", "assistant");
    }
    authShowLogin();
    return true;
  }
  // Generic unauthenticated message
  if (typeof addMsgFn === "function") {
    addMsgFn(
      "Prima di continuare devo riconoscerti. Accedi oppure registrati.",
      "assistant"
    );
  }
  // Show login by default for generic messages
  authShowLogin();
  return true;
}

// ── Init on page load ─────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", function () {
  // Wire up auth button event listeners (no inline onclick in HTML)
  var _wire = function (id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
  };

  // Topbar buttons
  _wire("tb-auth-btn",    function () { authShowLogin(); });
  _wire("tb-enroll-btn",  function () { authShowEnroll(); });
  _wire("tb-logout-btn",  function () { authDoLogout(); });

  // Login modal
  _wire("auth-login-submit",   function () { authSubmitLogin(); });
  _wire("auth-login-cancel",   function () { authHideLogin(); });
  _wire("auth-login-to-enroll", function (e) {
    e.preventDefault();
    authHideLogin();
    authShowEnroll();
  });

  // Enrollment modal
  _wire("auth-enroll-step1-btn", function () { authSubmitEnrollStep1(); });
  _wire("auth-enroll-cancel1",   function () { authHideEnroll(); });
  _wire("auth-enroll-step2-btn", function () { authSubmitEnrollStep2(); });
  _wire("auth-enroll-cancel2",   function () { authHideEnroll(); });

  // Restore UI state from existing session if any
  if (getSessionToken()) {
    authUpdateUI().catch(function () { _authClearUI(); });
  }
});
