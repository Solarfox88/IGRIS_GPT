"""
Delegation Key system for IGRIS authorization model (issue #526).
Hardened: salted PBKDF2 hash, backward compat with plain SHA256,
to_public_dict(), single-use, expiry, bearer-mismatch, scope inheritance.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_KEYS_FILE = ".igris/delegation_keys.json"
_PBKDF2_ITERATIONS = 100_000
_SALT_BYTES = 16


def _hash_passphrase(raw: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Return (hash_hex, salt_hex). Always uses PBKDF2."""
    if salt is None:
        salt = secrets.token_hex(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256", raw.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return dk.hex(), salt


def _verify_passphrase(raw: str, stored_hash: str, salt: Optional[str]) -> bool:
    """Verify passphrase; supports legacy plain SHA256 (no salt) for compat."""
    if salt:
        computed, _ = _hash_passphrase(raw, salt)
        return computed == stored_hash
    # Legacy: plain sha256
    legacy = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return legacy == stored_hash


@dataclass
class DelegationKey:
    key_id: str
    passphrase_hash: str
    granted_by: str
    granted_to: Optional[str]
    authorized_scopes: List[str]
    expires_at: Optional[float]
    created_at: float
    single_use: bool = False
    used: bool = False
    salt: Optional[str] = None  # None = legacy (plain SHA256)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def is_valid(self) -> bool:
        if self.is_expired():
            return False
        if self.single_use and self.used:
            return False
        return True

    def verify_passphrase(self, raw: str) -> bool:
        return _verify_passphrase(raw, self.passphrase_hash, self.salt)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        """Safe dict for API responses — never exposes hash or salt."""
        return {
            "key_id": self.key_id,
            "granted_by": self.granted_by,
            "granted_to": self.granted_to,
            "authorized_scopes": self.authorized_scopes,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "single_use": self.single_use,
            "used": self.used,
            "is_expired": self.is_expired(),
            "is_valid": self.is_valid(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DelegationKey":
        return cls(
            key_id=str(d["key_id"]),
            passphrase_hash=str(d["passphrase_hash"]),
            granted_by=str(d["granted_by"]),
            granted_to=d.get("granted_to"),
            authorized_scopes=list(d.get("authorized_scopes", [])),
            expires_at=d.get("expires_at"),
            created_at=float(d.get("created_at", 0.0)),
            single_use=bool(d.get("single_use", False)),
            used=bool(d.get("used", False)),
            salt=d.get("salt"),
        )


def _keys_path(project_root: str) -> Path:
    return Path(project_root) / _KEYS_FILE


def load_keys(project_root: str) -> Dict[str, DelegationKey]:
    path = _keys_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: DelegationKey.from_dict(v) for k, v in data.items()}
    except Exception:
        return {}


def save_keys(project_root: str, keys: Dict[str, DelegationKey]) -> None:
    path = _keys_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: v.to_dict() for k, v in keys.items()}, indent=2),
        encoding="utf-8",
    )


def create_key(
    project_root: str,
    granted_by: str,
    grantor_scopes: List[str],
    authorized_scopes: List[str],
    raw_passphrase: str,
    granted_to: Optional[str] = None,
    expires_in_seconds: Optional[float] = None,
    single_use: bool = False,
) -> DelegationKey:
    invalid_scopes = [s for s in authorized_scopes if s not in grantor_scopes]
    if invalid_scopes:
        raise ValueError(
            f"Scope inheritance violation: grantor '{granted_by}' does not possess "
            f"scope(s): {invalid_scopes}. Key creation denied."
        )
    key_id = secrets.token_hex(16)
    expires_at = (time.time() + expires_in_seconds) if expires_in_seconds else None
    passphrase_hash, salt = _hash_passphrase(raw_passphrase)
    key = DelegationKey(
        key_id=key_id,
        passphrase_hash=passphrase_hash,
        granted_by=granted_by,
        granted_to=granted_to,
        authorized_scopes=list(authorized_scopes),
        expires_at=expires_at,
        created_at=time.time(),
        single_use=single_use,
        used=False,
        salt=salt,
    )
    keys = load_keys(project_root)
    keys[key_id] = key
    save_keys(project_root, keys)
    return key


def verify_key(
    project_root: str,
    key_id: str,
    raw_passphrase: str,
    requested_scopes: List[str],
    bearer: Optional[str] = None,
) -> Tuple[bool, str]:
    keys = load_keys(project_root)
    key = keys.get(key_id)
    if key is None:
        return False, "key_not_found"
    if not key.verify_passphrase(raw_passphrase):
        return False, "passphrase_mismatch"
    if not key.is_valid():
        if key.is_expired():
            return False, "key_expired"
        return False, "key_consumed"
    if key.granted_to is not None and bearer is not None and key.granted_to != bearer:
        return False, "bearer_mismatch"
    missing = [s for s in requested_scopes if s not in key.authorized_scopes]
    if missing:
        return False, f"scope_not_covered:{missing}"
    if key.single_use:
        key.used = True
        keys[key_id] = key
        save_keys(project_root, keys)
    return True, "ok"


def revoke_key(project_root: str, key_id: str) -> bool:
    keys = load_keys(project_root)
    if key_id not in keys:
        return False
    del keys[key_id]
    save_keys(project_root, keys)
    return True


def list_keys(project_root: str, granted_by: Optional[str] = None) -> List[DelegationKey]:
    keys = load_keys(project_root)
    result = list(keys.values())
    if granted_by is not None:
        result = [k for k in result if k.granted_by == granted_by]
    return result
