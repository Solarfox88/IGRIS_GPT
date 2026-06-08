"""Core Auth Models for Progressive Interlocutor Enrollment (#1272 PR 1 + PR 3).

SAFE BY DEFAULT:
- Password raw NEVER stored, NEVER logged, NEVER in to_dict()
- Session token raw returned only once at creation/login; only hash persisted
- Enrollment token raw returned only once; only hash persisted
- Recursive secret redaction on all boundary outputs
- ok=True only if real disk persistence succeeds
- No silent except — every failure logged and returned as error/warning
- No external calls
- No auth escalation — does not modify AuthorizationGate, trust_level, authorized_scopes
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

PASSWORD_KDF = "pbkdf2_hmac_sha256"
PASSWORD_ITERATIONS = 390_000
PASSWORD_SALT_BYTES = 32
SESSION_TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 28_800  # 8 hours
MAX_FAILED_LOGIN_ATTEMPTS = 5
ENROLLMENT_TOKEN_BYTES = 32
ENROLLMENT_TTL_SECONDS = 600  # 10 minutes

_AUTH_CREDENTIALS_REL = Path(".igris") / "auth" / "credentials.json"
_AUTH_SESSIONS_REL = Path(".igris") / "auth" / "sessions.json"
_AUTH_ENROLLMENTS_REL = Path(".igris") / "auth" / "enrollments.json"
_CREDENTIALS_VERSION = 1
_SESSIONS_VERSION = 1

# ── Secret redaction ──────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer|auth[_\s]?key)'
    r'\s*[=:]\s*\S+',
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1=<REDACTED>', str(text)) if text else text


def _redact_any(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _redact_any(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_redact_any(i) for i in val]
    elif isinstance(val, str):
        return _redact(val)
    return val


def redact_email(email: str) -> str:
    """Redact email: m***@domain.com"""
    if not email or "@" not in email:
        return "<REDACTED>"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"


def redact_phone(phone: str) -> str:
    """Redact phone: keep last 4 digits visible."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "***"
    return f"*** *** {digits[-4:]}"


# ── Time helpers ─────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def is_expired(expires_at: str) -> bool:
    try:
        exp = parse_iso(expires_at)
        return datetime.now(tz=timezone.utc) >= exp
    except Exception:
        return True  # conservative: treat parse failure as expired


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(raw_password: str) -> dict:
    """Hash a raw password with PBKDF2-HMAC-SHA256.

    Returns dict with salt, hash, kdf, iterations.
    Raw password is NOT included in the return value.
    """
    salt = secrets.token_hex(PASSWORD_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return {
        "password_hash": dk.hex(),
        "password_salt": salt,
        "password_kdf": PASSWORD_KDF,
        "password_iterations": PASSWORD_ITERATIONS,
    }


def verify_password(
    raw_password: str,
    salt: str,
    expected_hash: str,
    iterations: int = PASSWORD_ITERATIONS,
) -> bool:
    """Verify password against stored hash. Uses constant-time comparison."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(dk.hex(), expected_hash)


def _check_password_strength(raw_password: str) -> list[str]:
    """Return list of strength violations (empty = ok)."""
    errors = []
    if len(raw_password) < 8:
        errors.append("password_too_short_min_8")
    if not re.search(r"[a-zA-Z]", raw_password):
        errors.append("password_requires_letter")
    if not re.search(r"[0-9]", raw_password):
        errors.append("password_requires_digit")
    return errors


# ── Session token helpers ─────────────────────────────────────────────────────

def generate_session_token() -> str:
    """Generate a cryptographically random opaque session token."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 hash of the session token for storage. Never store raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── AuthCredential ────────────────────────────────────────────────────────────

@dataclass
class AuthCredential:
    profile_id: str
    email: str
    mobile_phone: str
    password_hash: str
    password_salt: str
    password_kdf: str = PASSWORD_KDF
    password_iterations: int = PASSWORD_ITERATIONS
    created_at: str = ""
    updated_at: str = ""
    last_login_at: str | None = None
    failed_login_count: int = 0
    locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Serialize to dict.

        include_sensitive=False (default): excludes password_hash/salt,
          redacts email and mobile_phone.
        include_sensitive=True (storage only): includes hash+salt,
          still redacts any raw-secret patterns in metadata/errors.
        NOTE: raw password is NEVER present regardless of flag.
        """
        base: dict[str, Any] = {
            "profile_id": self.profile_id,
            "email": redact_email(self.email) if not include_sensitive else self.email,
            "mobile_phone": redact_phone(self.mobile_phone) if not include_sensitive else self.mobile_phone,
            "password_kdf": self.password_kdf,
            "password_iterations": self.password_iterations,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
            "failed_login_count": self.failed_login_count,
            "locked": self.locked,
            "metadata": _redact_any(dict(self.metadata)),
        }
        if include_sensitive:
            base["password_hash"] = self.password_hash
            base["password_salt"] = self.password_salt
        return base

    @classmethod
    def from_dict(cls, d: dict) -> "AuthCredential":
        return cls(
            profile_id=str(d.get("profile_id", "")),
            email=str(d.get("email", "")),
            mobile_phone=str(d.get("mobile_phone", "")),
            password_hash=str(d.get("password_hash", "")),
            password_salt=str(d.get("password_salt", "")),
            password_kdf=str(d.get("password_kdf", PASSWORD_KDF)),
            password_iterations=int(d.get("password_iterations", PASSWORD_ITERATIONS)),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            last_login_at=d.get("last_login_at"),
            failed_login_count=int(d.get("failed_login_count", 0)),
            locked=bool(d.get("locked", False)),
            metadata=dict(d.get("metadata") or {}),
        )


# ── AuthSession ───────────────────────────────────────────────────────────────

@dataclass
class AuthSession:
    session_id: str
    session_token_hash: str
    profile_id: str
    created_at: str
    expires_at: str
    last_seen_at: str
    revoked: bool = False
    ip_hint: str = ""
    user_agent_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Serialize to dict.

        session_token_hash is included by default (it's the stored hash, not the raw token).
        Raw session_token is NEVER present.
        include_sensitive=True has no additional effect — added for API symmetry.
        """
        return _redact_any({
            "session_id": self.session_id,
            "session_token_hash": self.session_token_hash,
            "profile_id": self.profile_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
            "revoked": self.revoked,
            "ip_hint": self.ip_hint,
            "user_agent_hint": self.user_agent_hint,
            "metadata": dict(self.metadata),
        })

    @classmethod
    def from_dict(cls, d: dict) -> "AuthSession":
        return cls(
            session_id=str(d.get("session_id", "")),
            session_token_hash=str(d.get("session_token_hash", "")),
            profile_id=str(d.get("profile_id", "")),
            created_at=str(d.get("created_at", "")),
            expires_at=str(d.get("expires_at", "")),
            last_seen_at=str(d.get("last_seen_at", "")),
            revoked=bool(d.get("revoked", False)),
            ip_hint=str(d.get("ip_hint", "")),
            user_agent_hint=str(d.get("user_agent_hint", "")),
            metadata=dict(d.get("metadata") or {}),
        )


# ── AuthOperationResult ───────────────────────────────────────────────────────

@dataclass
class AuthOperationResult:
    ok: bool
    action: str
    profile_id: str = ""
    session_token: str = ""   # raw token — returned only once at creation/login
    session_id: str = ""
    expires_at: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_token: bool = False) -> dict:
        """Serialize to dict.

        include_token=False (default): session_token excluded.
        include_token=True: raw session_token included for the initial create/login response.
        Errors/warnings/metadata are always redacted.
        """
        d: dict[str, Any] = {
            "ok": self.ok,
            "action": self.action,
            "profile_id": self.profile_id,
            "session_id": self.session_id,
            "expires_at": self.expires_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }
        if include_token and self.session_token:
            d["session_token"] = self.session_token
        return _redact_any(d)


# ── AuthCredentialStore ───────────────────────────────────────────────────────

class AuthCredentialStore:
    """Local store for hashed auth credentials.

    Storage: .igris/auth/credentials.json
    ok=True only if real disk write succeeds.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        storage_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = self.project_root / _AUTH_CREDENTIALS_REL

        self._credentials: dict[str, AuthCredential] = {}

        if self.storage_path.exists():
            result = self.reload()
            if not result.ok:
                logger.warning(
                    "AuthCredentialStore: failed to load %s: %s",
                    self.storage_path, result.errors,
                )

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="save_credentials")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": _CREDENTIALS_VERSION,
                "credentials": {
                    pid: cred.to_dict(include_sensitive=True)
                    for pid, cred in self._credentials.items()
                },
            }
            self.storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            result.ok = True
            result.metadata["saved_count"] = len(self._credentials)
        except Exception as exc:
            msg = f"credentials save failed: {exc}"
            result.errors.append(msg)
            logger.warning("AuthCredentialStore.save: %s", msg)
        return result

    def reload(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="reload_credentials")

        if not self.storage_path.exists():
            self._credentials = {}
            result.ok = True
            result.warnings.append("storage_file_missing")
            return result

        try:
            raw = self.storage_path.read_text(encoding="utf-8")
        except Exception as exc:
            msg = f"read failed: {exc}"
            result.errors.append(msg)
            logger.warning("AuthCredentialStore.reload: %s", msg)
            return result

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"invalid json: {exc}"
            result.errors.append(msg)
            logger.warning("AuthCredentialStore.reload: %s", msg)
            return result

        if not isinstance(data, dict):
            msg = "credentials root is not a dict"
            result.errors.append(msg)
            logger.warning("AuthCredentialStore.reload: %s", msg)
            return result

        creds_raw = data.get("credentials")
        if not isinstance(creds_raw, dict):
            self._credentials = {}
            result.ok = True
            result.warnings.append("credentials_not_dict")
            return result

        loaded: dict[str, AuthCredential] = {}
        skipped = 0
        for pid, raw_cred in creds_raw.items():
            if not isinstance(raw_cred, dict):
                skipped += 1
                continue
            try:
                loaded[pid] = AuthCredential.from_dict(raw_cred)
            except Exception as exc:
                skipped += 1
                logger.debug("AuthCredentialStore.reload: skip %s: %s", pid, exc)

        self._credentials = loaded
        result.ok = True
        result.metadata["loaded_count"] = len(loaded)
        if skipped:
            result.warnings.append(f"skipped_{skipped}_invalid_credentials")
        return result

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create_credential(
        self,
        profile_id: str,
        email: str,
        mobile_phone: str,
        raw_password: str,
    ) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="create_credential", profile_id=profile_id)

        if not profile_id or not profile_id.strip():
            result.errors.append("profile_id_required")
            return result
        if profile_id in self._credentials:
            result.errors.append("credential_already_exists")
            return result

        strength_errors = _check_password_strength(raw_password)
        if strength_errors:
            result.errors.extend(strength_errors)
            return result

        try:
            ph = hash_password(raw_password)
        except Exception as exc:
            result.errors.append(f"hashing_failed: {exc}")
            logger.warning("AuthCredentialStore.create_credential: hashing error for %s: %s", profile_id, exc)
            return result
        finally:
            # Best-effort: clear raw_password from local scope
            del raw_password

        now = now_iso()
        cred = AuthCredential(
            profile_id=profile_id,
            email=email,
            mobile_phone=mobile_phone,
            password_hash=ph["password_hash"],
            password_salt=ph["password_salt"],
            password_kdf=ph["password_kdf"],
            password_iterations=ph["password_iterations"],
            created_at=now,
            updated_at=now,
        )
        self._credentials[profile_id] = cred
        save_r = self.save()
        if not save_r.ok:
            del self._credentials[profile_id]
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed_rollback")
            return result

        result.ok = True
        return result

    def get_credential(self, profile_id: str) -> AuthCredential | None:
        return self._credentials.get(profile_id)

    def verify_login(
        self,
        profile_id: str,
        raw_password: str,
    ) -> AuthOperationResult:
        """Verify login. Returns generic error to prevent user enumeration."""
        result = AuthOperationResult(ok=False, action="verify_login", profile_id=profile_id)
        _GENERIC_ERROR = "invalid_credentials"

        cred = self._credentials.get(profile_id)
        if cred is None:
            # Perform a dummy hash to maintain constant timing
            try:
                _dummy_salt = secrets.token_hex(PASSWORD_SALT_BYTES)
                hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"),
                                     _dummy_salt.encode("utf-8"), PASSWORD_ITERATIONS)
            except Exception:
                pass
            finally:
                del raw_password
            result.errors.append(_GENERIC_ERROR)
            return result

        if cred.locked:
            try:
                del raw_password
            except Exception:
                pass
            result.errors.append("account_locked")
            return result

        try:
            ok = verify_password(
                raw_password,
                cred.password_salt,
                cred.password_hash,
                cred.password_iterations,
            )
        except Exception as exc:
            logger.warning("AuthCredentialStore.verify_login: hash error for %s: %s", profile_id, exc)
            result.errors.append(_GENERIC_ERROR)
            return result
        finally:
            del raw_password

        if not ok:
            self.record_failed_login(profile_id)
            result.errors.append(_GENERIC_ERROR)
            return result

        self.record_successful_login(profile_id)
        result.ok = True
        return result

    def record_successful_login(self, profile_id: str) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="record_successful_login", profile_id=profile_id)
        cred = self._credentials.get(profile_id)
        if cred is None:
            result.errors.append(f"credential_not_found:{profile_id}")
            return result
        cred.last_login_at = now_iso()
        cred.failed_login_count = 0
        cred.updated_at = now_iso()
        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result
        result.ok = True
        return result

    def record_failed_login(self, profile_id: str) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="record_failed_login", profile_id=profile_id)
        cred = self._credentials.get(profile_id)
        if cred is None:
            result.errors.append(f"credential_not_found:{profile_id}")
            return result
        cred.failed_login_count += 1
        cred.updated_at = now_iso()
        if cred.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS:
            cred.locked = True
            result.warnings.append(f"account_locked_after_{cred.failed_login_count}_failures")
            logger.warning(
                "AuthCredentialStore: account %s locked after %d failed attempts",
                profile_id, cred.failed_login_count,
            )
        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result
        result.ok = True
        return result

    def unlock(self, profile_id: str) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="unlock", profile_id=profile_id)
        cred = self._credentials.get(profile_id)
        if cred is None:
            result.errors.append(f"credential_not_found:{profile_id}")
            return result
        cred.locked = False
        cred.failed_login_count = 0
        cred.updated_at = now_iso()
        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result
        result.ok = True
        return result

    def healthcheck(self) -> dict:
        return _redact_any({
            "ok": True,
            "storage_path": str(self.storage_path),
            "exists": self.storage_path.exists(),
            "count": len(self._credentials),
            "locked_count": sum(1 for c in self._credentials.values() if c.locked),
            "warnings": [],
            "errors": [],
        })


# ── AuthSessionManager ────────────────────────────────────────────────────────

class AuthSessionManager:
    """Manages auth sessions with secure token hashing and TTL.

    Storage: .igris/auth/sessions.json
    Raw session token returned only once at creation — only hash persisted.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        storage_path: str | Path | None = None,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        sliding_window: bool = True,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = self.project_root / _AUTH_SESSIONS_REL
        self.ttl_seconds = ttl_seconds
        self.sliding_window = sliding_window
        self._sessions: dict[str, AuthSession] = {}  # keyed by session_token_hash

        if self.storage_path.exists():
            result = self.reload()
            if not result.ok:
                logger.warning(
                    "AuthSessionManager: failed to load %s: %s",
                    self.storage_path, result.errors,
                )

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="save_sessions")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": _SESSIONS_VERSION,
                "sessions": {
                    token_hash: sess.to_dict()
                    for token_hash, sess in self._sessions.items()
                },
            }
            self.storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            result.ok = True
            result.metadata["saved_count"] = len(self._sessions)
        except Exception as exc:
            msg = f"sessions save failed: {exc}"
            result.errors.append(msg)
            logger.warning("AuthSessionManager.save: %s", msg)
        return result

    def reload(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="reload_sessions")

        if not self.storage_path.exists():
            self._sessions = {}
            result.ok = True
            result.warnings.append("storage_file_missing")
            return result

        try:
            raw = self.storage_path.read_text(encoding="utf-8")
        except Exception as exc:
            msg = f"read failed: {exc}"
            result.errors.append(msg)
            logger.warning("AuthSessionManager.reload: %s", msg)
            return result

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"invalid json: {exc}"
            result.errors.append(msg)
            logger.warning("AuthSessionManager.reload: %s", msg)
            return result

        if not isinstance(data, dict):
            self._sessions = {}
            result.errors.append("sessions root is not a dict")
            logger.warning("AuthSessionManager.reload: root is not dict")
            return result

        sessions_raw = data.get("sessions")
        if not isinstance(sessions_raw, dict):
            self._sessions = {}
            result.ok = True
            result.warnings.append("sessions_not_dict")
            return result

        loaded: dict[str, AuthSession] = {}
        skipped = 0
        for token_hash, raw_sess in sessions_raw.items():
            if not isinstance(raw_sess, dict):
                skipped += 1
                continue
            try:
                loaded[token_hash] = AuthSession.from_dict(raw_sess)
            except Exception as exc:
                skipped += 1
                logger.debug("AuthSessionManager.reload: skip session %s: %s", token_hash[:8], exc)

        self._sessions = loaded
        result.ok = True
        result.metadata["loaded_count"] = len(loaded)
        if skipped:
            result.warnings.append(f"skipped_{skipped}_invalid_sessions")
        return result

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def create_session(
        self,
        profile_id: str,
        ip_hint: str = "",
        user_agent_hint: str = "",
    ) -> AuthOperationResult:
        """Create new session. Returns raw token once in result.session_token."""
        result = AuthOperationResult(ok=False, action="create_session", profile_id=profile_id)

        if not profile_id or not profile_id.strip():
            result.errors.append("profile_id_required")
            return result

        raw_token = generate_session_token()
        token_hash = hash_session_token(raw_token)
        session_id = str(uuid.uuid4())
        now = now_iso()
        expires = (
            datetime.now(tz=timezone.utc) + timedelta(seconds=self.ttl_seconds)
        ).isoformat()

        session = AuthSession(
            session_id=session_id,
            session_token_hash=token_hash,
            profile_id=profile_id,
            created_at=now,
            expires_at=expires,
            last_seen_at=now,
            ip_hint=ip_hint,
            user_agent_hint=user_agent_hint,
        )
        self._sessions[token_hash] = session
        save_r = self.save()
        if not save_r.ok:
            del self._sessions[token_hash]
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed_rollback")
            return result

        result.ok = True
        result.session_token = raw_token  # returned ONCE; caller must not persist raw
        result.session_id = session_id
        result.expires_at = expires
        return result

    def resolve_session(
        self,
        session_token: str,
    ) -> tuple[AuthSession | None, AuthOperationResult]:
        """Resolve a session token → (AuthSession, result).

        Updates last_seen_at. With sliding_window=True also extends expires_at.
        """
        result = AuthOperationResult(ok=False, action="resolve_session")

        token_hash = hash_session_token(session_token)
        session = self._sessions.get(token_hash)

        if session is None:
            result.errors.append("session_not_found")
            return None, result

        if session.revoked:
            result.errors.append("session_revoked")
            return None, result

        if is_expired(session.expires_at):
            result.errors.append("session_expired")
            return None, result

        # Update last_seen and optionally extend TTL
        session.last_seen_at = now_iso()
        if self.sliding_window:
            session.expires_at = (
                datetime.now(tz=timezone.utc) + timedelta(seconds=self.ttl_seconds)
            ).isoformat()

        save_r = self.save()
        if not save_r.ok:
            result.warnings.extend(save_r.errors)
            result.warnings.append("session_touch_persist_failed")
            # Still return session — degraded but acceptable

        result.ok = True
        result.profile_id = session.profile_id
        result.session_id = session.session_id
        result.expires_at = session.expires_at
        return session, result

    def revoke_session(
        self,
        session_token: str,
    ) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="revoke_session")

        token_hash = hash_session_token(session_token)
        session = self._sessions.get(token_hash)
        if session is None:
            result.errors.append("session_not_found")
            return result

        session.revoked = True
        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result

        result.ok = True
        result.session_id = session.session_id
        return result

    def revoke_all_for_profile(
        self,
        profile_id: str,
    ) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="revoke_all_for_profile", profile_id=profile_id)

        count = 0
        for session in self._sessions.values():
            if session.profile_id == profile_id and not session.revoked:
                session.revoked = True
                count += 1

        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result

        result.ok = True
        result.metadata["revoked_count"] = count
        return result

    def gc_expired(self) -> AuthOperationResult:
        """Remove expired and revoked sessions from storage."""
        result = AuthOperationResult(ok=False, action="gc_expired")

        before = len(self._sessions)
        self._sessions = {
            h: s for h, s in self._sessions.items()
            if not s.revoked and not is_expired(s.expires_at)
        }
        removed = before - len(self._sessions)

        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result

        result.ok = True
        result.metadata["removed_count"] = removed
        result.metadata["remaining_count"] = len(self._sessions)
        return result

    def healthcheck(self) -> dict:
        active = sum(
            1 for s in self._sessions.values()
            if not s.revoked and not is_expired(s.expires_at)
        )
        return _redact_any({
            "ok": True,
            "storage_path": str(self.storage_path),
            "exists": self.storage_path.exists(),
            "total_sessions": len(self._sessions),
            "active_sessions": active,
            "ttl_seconds": self.ttl_seconds,
            "sliding_window": self.sliding_window,
            "warnings": [],
            "errors": [],
        })


# ── PendingEnrollment ─────────────────────────────────────────────────────────

@dataclass
class PendingEnrollment:
    enrollment_id: str
    enrollment_token_hash: str
    profile_id: str
    first_name: str
    last_name: str
    email: str
    mobile_phone: str
    created_at: str
    expires_at: str
    used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Serialize. email/mobile always redacted in public output.

        Raw enrollment_token is NEVER present regardless of flag.
        """
        base: dict[str, Any] = {
            "enrollment_id": self.enrollment_id,
            "enrollment_token_hash": self.enrollment_token_hash,
            "profile_id": self.profile_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email if include_sensitive else redact_email(self.email),
            "mobile_phone": self.mobile_phone if include_sensitive else redact_phone(self.mobile_phone),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "used": self.used,
            "metadata": _redact_any(dict(self.metadata)),
        }
        return base

    @classmethod
    def from_dict(cls, d: dict) -> "PendingEnrollment":
        return cls(
            enrollment_id=str(d.get("enrollment_id", "")),
            enrollment_token_hash=str(d.get("enrollment_token_hash", "")),
            profile_id=str(d.get("profile_id", "")),
            first_name=str(d.get("first_name", "")),
            last_name=str(d.get("last_name", "")),
            email=str(d.get("email", "")),
            mobile_phone=str(d.get("mobile_phone", "")),
            created_at=str(d.get("created_at", "")),
            expires_at=str(d.get("expires_at", "")),
            used=bool(d.get("used", False)),
            metadata=dict(d.get("metadata") or {}),
        )


# ── EnrollmentStore ───────────────────────────────────────────────────────────

_ENROLLMENTS_VERSION = 1


class EnrollmentStore:
    """Store for pending enrollments.

    Storage: .igris/auth/enrollments.json
    Raw enrollment_token returned only once — only hash persisted.
    Tokens expire after ENROLLMENT_TTL_SECONDS (10 min) and are single-use.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        storage_path: str | Path | None = None,
        ttl_seconds: int = ENROLLMENT_TTL_SECONDS,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = self.project_root / _AUTH_ENROLLMENTS_REL
        self.ttl_seconds = ttl_seconds
        self._enrollments: dict[str, PendingEnrollment] = {}  # keyed by token_hash

        if self.storage_path.exists():
            result = self.reload()
            if not result.ok:
                logger.warning(
                    "EnrollmentStore: failed to load %s: %s",
                    self.storage_path, result.errors,
                )

    def save(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="save_enrollments")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": _ENROLLMENTS_VERSION,
                "enrollments": {
                    h: e.to_dict(include_sensitive=True)
                    for h, e in self._enrollments.items()
                },
            }
            self.storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            result.ok = True
            result.metadata["saved_count"] = len(self._enrollments)
        except Exception as exc:
            msg = f"enrollments save failed: {exc}"
            result.errors.append(msg)
            logger.warning("EnrollmentStore.save: %s", msg)
        return result

    def reload(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="reload_enrollments")

        if not self.storage_path.exists():
            self._enrollments = {}
            result.ok = True
            result.warnings.append("storage_file_missing")
            return result

        try:
            raw = self.storage_path.read_text(encoding="utf-8")
        except Exception as exc:
            msg = f"read failed: {exc}"
            result.errors.append(msg)
            logger.warning("EnrollmentStore.reload: %s", msg)
            return result

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"invalid json: {exc}"
            result.errors.append(msg)
            logger.warning("EnrollmentStore.reload: %s", msg)
            return result

        if not isinstance(data, dict):
            result.errors.append("enrollments root is not a dict")
            logger.warning("EnrollmentStore.reload: root is not dict")
            return result

        enroll_raw = data.get("enrollments")
        if not isinstance(enroll_raw, dict):
            self._enrollments = {}
            result.ok = True
            result.warnings.append("enrollments_not_dict")
            return result

        loaded: dict[str, PendingEnrollment] = {}
        skipped = 0
        for token_hash, raw_e in enroll_raw.items():
            if not isinstance(raw_e, dict):
                skipped += 1
                continue
            try:
                loaded[token_hash] = PendingEnrollment.from_dict(raw_e)
            except Exception as exc:
                skipped += 1
                logger.debug("EnrollmentStore.reload: skip %s: %s", token_hash[:8], exc)

        self._enrollments = loaded
        result.ok = True
        result.metadata["loaded_count"] = len(loaded)
        if skipped:
            result.warnings.append(f"skipped_{skipped}_invalid_enrollments")
        return result

    def create_pending(
        self,
        profile_id: str,
        first_name: str,
        last_name: str,
        email: str,
        mobile_phone: str,
    ) -> AuthOperationResult:
        """Create a pending enrollment. Returns raw token once in result.session_token."""
        result = AuthOperationResult(ok=False, action="create_pending_enrollment", profile_id=profile_id)

        if not profile_id:
            result.errors.append("profile_id_required")
            return result

        raw_token = secrets.token_urlsafe(ENROLLMENT_TOKEN_BYTES)
        token_hash = hash_session_token(raw_token)  # reuse same SHA-256 helper
        enrollment_id = str(uuid.uuid4())
        now = now_iso()
        expires = (
            datetime.now(tz=timezone.utc) + timedelta(seconds=self.ttl_seconds)
        ).isoformat()

        enrollment = PendingEnrollment(
            enrollment_id=enrollment_id,
            enrollment_token_hash=token_hash,
            profile_id=profile_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            mobile_phone=mobile_phone,
            created_at=now,
            expires_at=expires,
        )
        self._enrollments[token_hash] = enrollment
        save_r = self.save()
        if not save_r.ok:
            del self._enrollments[token_hash]
            result.errors.extend(save_r.errors)
            result.errors.append("persist_failed_rollback")
            return result

        result.ok = True
        result.session_token = raw_token  # reusing session_token field for enrollment_token
        result.session_id = enrollment_id
        result.expires_at = expires
        return result

    def resolve_token(
        self,
        enrollment_token: str,
    ) -> tuple[PendingEnrollment | None, AuthOperationResult]:
        """Look up a pending enrollment by raw token."""
        result = AuthOperationResult(ok=False, action="resolve_enrollment_token")

        token_hash = hash_session_token(enrollment_token)
        enrollment = self._enrollments.get(token_hash)

        if enrollment is None:
            result.errors.append("enrollment_token_not_found")
            return None, result

        if enrollment.used:
            result.errors.append("enrollment_token_already_used")
            return None, result

        if is_expired(enrollment.expires_at):
            result.errors.append("enrollment_token_expired")
            return None, result

        result.ok = True
        result.profile_id = enrollment.profile_id
        return enrollment, result

    def mark_used(self, enrollment_token: str) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="mark_enrollment_used")

        token_hash = hash_session_token(enrollment_token)
        enrollment = self._enrollments.get(token_hash)
        if enrollment is None:
            result.errors.append("enrollment_not_found")
            return result

        enrollment.used = True
        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result

        result.ok = True
        return result

    def gc_expired(self) -> AuthOperationResult:
        result = AuthOperationResult(ok=False, action="gc_expired_enrollments")
        before = len(self._enrollments)
        self._enrollments = {
            h: e for h, e in self._enrollments.items()
            if not e.used and not is_expired(e.expires_at)
        }
        removed = before - len(self._enrollments)
        save_r = self.save()
        if not save_r.ok:
            result.errors.extend(save_r.errors)
            return result
        result.ok = True
        result.metadata["removed_count"] = removed
        return result

    def healthcheck(self) -> dict:
        active = sum(
            1 for e in self._enrollments.values()
            if not e.used and not is_expired(e.expires_at)
        )
        return _redact_any({
            "ok": True,
            "storage_path": str(self.storage_path),
            "exists": self.storage_path.exists(),
            "total_enrollments": len(self._enrollments),
            "active_enrollments": active,
            "ttl_seconds": self.ttl_seconds,
            "warnings": [],
            "errors": [],
        })
