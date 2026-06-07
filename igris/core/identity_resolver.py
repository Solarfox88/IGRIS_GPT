"""
Identity Resolver — Layer 1 & 2 of the Interlocutor-Aware system (issue #526).

Manages interlocutor profiles: recognize, create, update, persist.
Profiles are stored in .igris/interlocutor_profiles.json and optionally
in MemoryGraph as 'identity_fact' nodes.

Extended in #1272 PR2:
- Added first_name, last_name fields
- Default communication_style="conversational" for new profiles
- Default expertise_level="unknown" for new profiles
- Added "conversational" to COMM_STYLES, "unknown" to EXPERTISE_LEVELS
- Normalization helpers for safe enum handling
- create_enrolled_limited_profile() helper for enrollment flow
- Removed silent except in persist_to_memory_graph()

Security note: callers must enforce authorization before creating/elevating
trusted/admin profiles. create() itself does NOT check caller permissions —
this is enforced at the API layer (PR 3+).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROFILES_FILE = ".igris/interlocutor_profiles.json"

TRUST_LEVELS = ["untrusted", "limited", "trusted", "admin"]
EXPERTISE_LEVELS = ["unknown", "novice", "intermediate", "expert", "owner"]
COMM_STYLES = ["conversational", "formal", "casual", "technical"]

# Default scopes granted to enrolled (limited) users
_ENROLLED_LIMITED_SCOPES: List[str] = ["chat", "memory_basic", "read_own_profile"]


# ── Normalization helpers ─────────────────────────────────────────────────────

def _normalize_expertise(value: str) -> str:
    """Return value if valid, else 'unknown'."""
    return value if value in EXPERTISE_LEVELS else "unknown"


def _normalize_comm_style(value: str) -> str:
    """Return value if valid, else 'conversational'."""
    return value if value in COMM_STYLES else "conversational"


def _normalize_trust(value: str) -> str:
    """Return value if valid, else 'untrusted'."""
    return value if value in TRUST_LEVELS else "untrusted"


def _normalize_scopes(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(s) for s in value]
    return []


def _normalize_flags(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _normalize_delegation_keys(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(k) for k in value]
    return []


# ── InterlocutorProfile ───────────────────────────────────────────────────────

@dataclass
class InterlocutorProfile:
    """Persistent profile for a known interlocutor.

    NOTE: This profile is purely descriptive/behavioral — it contains NO
    authentication credentials (password, token, email, mobile_phone).
    Auth data lives in AuthCredential (igris/core/interlocutor_auth.py).
    """

    profile_id: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    expertise_level: str = "unknown"
    communication_style: str = "conversational"
    trust_level: str = "untrusted"
    authorized_scopes: List[str] = field(default_factory=list)
    persistent_flags: Dict[str, Any] = field(default_factory=dict)
    delegation_keys: List[str] = field(default_factory=list)
    interaction_count: int = 0
    first_seen_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InterlocutorProfile":
        """Load profile from dict with full backward compatibility.

        Old profiles without first_name/last_name load with empty strings.
        Old profiles with communication_style="technical" preserve "technical".
        Old profiles with expertise_level="intermediate" preserve "intermediate".
        Invalid enum values are normalized to safe defaults.
        """
        return cls(
            profile_id=str(d["profile_id"]),
            display_name=str(d.get("display_name", d["profile_id"])),
            first_name=str(d.get("first_name", "")),
            last_name=str(d.get("last_name", "")),
            expertise_level=_normalize_expertise(str(d.get("expertise_level", "unknown"))),
            communication_style=_normalize_comm_style(str(d.get("communication_style", "conversational"))),
            trust_level=_normalize_trust(str(d.get("trust_level", "untrusted"))),
            authorized_scopes=_normalize_scopes(d.get("authorized_scopes", [])),
            persistent_flags=_normalize_flags(d.get("persistent_flags", {})),
            delegation_keys=_normalize_delegation_keys(d.get("delegation_keys", [])),
            interaction_count=int(d.get("interaction_count", 0)),
            first_seen_at=float(d.get("first_seen_at", time.time())),
            last_seen_at=float(d.get("last_seen_at", time.time())),
        )

    def has_scope(self, scope: str) -> bool:
        return scope in self.authorized_scopes

    def is_at_least(self, min_trust: str) -> bool:
        try:
            return TRUST_LEVELS.index(self.trust_level) >= TRUST_LEVELS.index(min_trust)
        except ValueError:
            return False

    def touch(self) -> None:
        self.last_seen_at = time.time()
        self.interaction_count += 1


# ── Storage helpers ───────────────────────────────────────────────────────────

def _profiles_path(project_root: str) -> Path:
    return Path(project_root) / _PROFILES_FILE


def load_profiles(project_root: str) -> Dict[str, InterlocutorProfile]:
    path = _profiles_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: InterlocutorProfile.from_dict(v) for k, v in data.items()}
    except Exception as exc:
        logger.warning("load_profiles: failed to load %s: %s", path, exc)
        return {}


def save_profiles(project_root: str, profiles: Dict[str, InterlocutorProfile]) -> None:
    path = _profiles_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: v.to_dict() for k, v in profiles.items()}, indent=2),
        encoding="utf-8",
    )


# ── Built-in trusted profiles (always available, not persisted to disk) ───────

BUILTIN_PROFILES: Dict[str, InterlocutorProfile] = {
    "system": InterlocutorProfile(
        profile_id="system",
        display_name="IGRIS Internal",
        first_name="IGRIS",
        last_name="Internal",
        trust_level="admin",
        authorized_scopes=["*"],
        expertise_level="expert",
        communication_style="technical",
    ),
    "owner": InterlocutorProfile(
        profile_id="owner",
        display_name="Christian (Owner)",
        first_name="Christian",
        last_name="Ricci",
        trust_level="admin",
        authorized_scopes=["*"],
        expertise_level="owner",
        communication_style="technical",
    ),
}


# ── IdentityResolver ──────────────────────────────────────────────────────────

class IdentityResolver:
    """Resolve and manage interlocutor identities."""

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        self._profiles: Optional[Dict[str, InterlocutorProfile]] = None

    def _load(self) -> Dict[str, InterlocutorProfile]:
        if self._profiles is None:
            self._profiles = load_profiles(self.project_root)
        return self._profiles

    def resolve(self, name_or_id: str) -> InterlocutorProfile:
        """Resolve an identity.

        Returns built-in profile, known profile, or an ephemeral untrusted profile.
        Unknown profiles are untrusted + conversational + unknown (not persisted).
        trust_level="limited" is only granted via create_enrolled_limited_profile().
        """
        # Check built-in privileged profiles first (always trusted, no disk lookup needed)
        if name_or_id in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[name_or_id]
        profiles = self._load()
        if name_or_id in profiles:
            profile = profiles[name_or_id]
            profile.touch()
            return profile
        lower = name_or_id.lower()
        for p in profiles.values():
            if p.display_name.lower() == lower:
                p.touch()
                return p
        # Unknown interlocutor: ephemeral untrusted profile — NOT persisted
        profile = InterlocutorProfile(
            profile_id=name_or_id.lower().replace(" ", "_"),
            display_name=name_or_id,
            first_name="",
            last_name="",
            trust_level="untrusted",
            expertise_level="unknown",
            communication_style="conversational",
        )
        profile.touch()
        return profile

    def update(self, profile: InterlocutorProfile) -> None:
        profiles = self._load()
        profiles[profile.profile_id] = profile
        self._profiles = profiles
        save_profiles(self.project_root, profiles)

    def create(
        self,
        profile_id: str,
        display_name: str,
        first_name: str = "",
        last_name: str = "",
        trust_level: str = "untrusted",
        authorized_scopes: Optional[List[str]] = None,
        expertise_level: str = "unknown",
        communication_style: str = "conversational",
        persistent_flags: Optional[Dict[str, Any]] = None,
    ) -> InterlocutorProfile:
        """Create and persist a new interlocutor profile.

        Security note: callers must enforce authorization before creating/elevating
        trusted/admin profiles. This method does NOT check caller permissions.
        Authorization enforcement is handled at the API layer (PR 3+).
        """
        profile = InterlocutorProfile(
            profile_id=profile_id,
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            trust_level=_normalize_trust(trust_level),
            authorized_scopes=_normalize_scopes(authorized_scopes or []),
            expertise_level=_normalize_expertise(expertise_level),
            communication_style=_normalize_comm_style(communication_style),
            persistent_flags=_normalize_flags(persistent_flags or {}),
        )
        self.update(profile)
        return profile

    def create_enrolled_limited_profile(
        self,
        profile_id: str,
        first_name: str,
        last_name: str,
        display_name: str | None = None,
    ) -> InterlocutorProfile:
        """Create a newly-enrolled limited profile with safe default scopes.

        This is the canonical factory for enrollment flow (PR 3+).
        Does NOT ask for role/style/expertise from user — all set to safe defaults.

        Grants: trust_level="limited", scopes=["chat","memory_basic","read_own_profile"]
        Never grants: deploy, delete, merge, github_write, run_command, admin, "*"
        """
        _display = display_name or f"{first_name} {last_name}".strip() or profile_id
        profile = InterlocutorProfile(
            profile_id=profile_id,
            display_name=_display,
            first_name=first_name,
            last_name=last_name,
            trust_level="limited",
            authorized_scopes=list(_ENROLLED_LIMITED_SCOPES),
            expertise_level="unknown",
            communication_style="conversational",
            persistent_flags={"enrolled": True},
            delegation_keys=[],
        )
        self.update(profile)
        return profile

    def grant_scope(self, profile_id: str, scope: str) -> bool:
        profiles = self._load()
        if profile_id not in profiles:
            return False
        if scope not in profiles[profile_id].authorized_scopes:
            profiles[profile_id].authorized_scopes.append(scope)
        self._profiles = profiles
        save_profiles(self.project_root, profiles)
        return True

    def revoke_scope(self, profile_id: str, scope: str) -> bool:
        profiles = self._load()
        if profile_id not in profiles:
            return False
        profiles[profile_id].authorized_scopes = [
            s for s in profiles[profile_id].authorized_scopes if s != scope
        ]
        self._profiles = profiles
        save_profiles(self.project_root, profiles)
        return True

    def set_flag(self, profile_id: str, flag: str, value: Any) -> bool:
        profiles = self._load()
        if profile_id not in profiles:
            return False
        profiles[profile_id].persistent_flags[flag] = value
        self._profiles = profiles
        save_profiles(self.project_root, profiles)
        return True

    def get_all(self) -> List[InterlocutorProfile]:
        """Return all persisted profiles (disk only, not built-in defaults)."""
        return list(self._load().values())

    def get_all_including_builtins(self) -> List[InterlocutorProfile]:
        """Return all profiles: built-ins merged with persisted disk profiles."""
        persisted = self._load()
        merged: Dict[str, InterlocutorProfile] = dict(BUILTIN_PROFILES)
        merged.update(persisted)
        return list(merged.values())

    def persist_to_memory_graph(self, profile: InterlocutorProfile) -> None:
        try:
            from igris.core.memory_graph import MemoryGraph
            mg = MemoryGraph(self.project_root)
            mg.add_node(
                "identity_fact",
                {
                    "profile_id": profile.profile_id,
                    "display_name": profile.display_name,
                    "first_name": profile.first_name,
                    "last_name": profile.last_name,
                    "trust_level": profile.trust_level,
                    "expertise_level": profile.expertise_level,
                    "communication_style": profile.communication_style,
                    "authorized_scopes": profile.authorized_scopes,
                    "interaction_count": profile.interaction_count,
                    "last_seen_at": profile.last_seen_at,
                },
                confidence=0.9,
            )
        except Exception as exc:
            logger.debug("IdentityResolver.persist_to_memory_graph skipped/degraded: %s", exc)
