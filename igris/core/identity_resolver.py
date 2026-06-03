"""
Identity Resolver — Layer 1 & 2 of the Interlocutor-Aware system (issue #526).

Manages interlocutor profiles: recognize, create, update, persist.
Profiles are stored in .igris/interlocutor_profiles.json and optionally
in MemoryGraph as 'identity_fact' nodes.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROFILES_FILE = ".igris/interlocutor_profiles.json"

TRUST_LEVELS = ["untrusted", "limited", "trusted", "admin"]
EXPERTISE_LEVELS = ["novice", "intermediate", "expert", "owner"]
COMM_STYLES = ["formal", "casual", "technical"]


@dataclass
class InterlocutorProfile:
    """Persistent profile for a known interlocutor."""

    profile_id: str
    display_name: str
    expertise_level: str = "intermediate"
    communication_style: str = "technical"
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
        return cls(
            profile_id=str(d["profile_id"]),
            display_name=str(d.get("display_name", d["profile_id"])),
            expertise_level=str(d.get("expertise_level", "intermediate")),
            communication_style=str(d.get("communication_style", "technical")),
            trust_level=str(d.get("trust_level", "untrusted")),
            authorized_scopes=list(d.get("authorized_scopes", [])),
            persistent_flags=dict(d.get("persistent_flags", {})),
            delegation_keys=list(d.get("delegation_keys", [])),
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


def _profiles_path(project_root: str) -> Path:
    return Path(project_root) / _PROFILES_FILE


def load_profiles(project_root: str) -> Dict[str, InterlocutorProfile]:
    path = _profiles_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: InterlocutorProfile.from_dict(v) for k, v in data.items()}
    except Exception:
        return {}


def save_profiles(project_root: str, profiles: Dict[str, InterlocutorProfile]) -> None:
    path = _profiles_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: v.to_dict() for k, v in profiles.items()}, indent=2),
        encoding="utf-8",
    )



# ---------------------------------------------------------------------------
# Built-in trusted profiles (always available, not persisted to disk)
# ---------------------------------------------------------------------------
BUILTIN_PROFILES: Dict[str, InterlocutorProfile] = {
    "system": InterlocutorProfile(
        profile_id="system",
        display_name="IGRIS Internal",
        trust_level="admin",
        authorized_scopes=["*"],
        expertise_level="expert",
        communication_style="technical",
    ),
    "owner": InterlocutorProfile(
        profile_id="owner",
        display_name="Christian (Owner)",
        trust_level="admin",
        authorized_scopes=["*"],
        expertise_level="owner",
        communication_style="technical",
    ),
}

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
        profile = InterlocutorProfile(
            profile_id=name_or_id.lower().replace(" ", "_"),
            display_name=name_or_id,
            trust_level="untrusted",
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
        trust_level: str = "untrusted",
        authorized_scopes: Optional[List[str]] = None,
        expertise_level: str = "intermediate",
        communication_style: str = "technical",
        persistent_flags: Optional[Dict[str, Any]] = None,
    ) -> InterlocutorProfile:
        profile = InterlocutorProfile(
            profile_id=profile_id,
            display_name=display_name,
            trust_level=trust_level,
            authorized_scopes=authorized_scopes or [],
            expertise_level=expertise_level,
            communication_style=communication_style,
            persistent_flags=persistent_flags or {},
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
                    "trust_level": profile.trust_level,
                    "expertise_level": profile.expertise_level,
                    "communication_style": profile.communication_style,
                    "authorized_scopes": profile.authorized_scopes,
                    "interaction_count": profile.interaction_count,
                    "last_seen_at": profile.last_seen_at,
                },
                confidence=0.9,
            )
        except Exception:
            pass
