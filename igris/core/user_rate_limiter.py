"""Per-user rate limiting (#1329).

Extends the existing per-IP rate limiting with per-session/per-user
rate buckets and role-based limits.

Environment variables:
- IGRIS_RATE_LIMIT_USER_STANDARD   Max req/min per user (standard). Default: 60.
- IGRIS_RATE_LIMIT_USER_ADMIN      Max req/min per user (admin). Default: 120.
- IGRIS_RATE_LIMIT_USER_VIEWER     Max req/min per user (viewer/limited). Default: 30.
- IGRIS_RATE_LIMIT_USER_UNTRUSTED  Max req/min per user (untrusted). Default: 10.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

_log = logging.getLogger(__name__)

# Default rate limits per user (requests per minute)
DEFAULT_USER_STANDARD = int(os.environ.get("IGRIS_RATE_LIMIT_USER_STANDARD", "60"))
DEFAULT_USER_ADMIN = int(os.environ.get("IGRIS_RATE_LIMIT_USER_ADMIN", "120"))
DEFAULT_USER_VIEWER = int(os.environ.get("IGRIS_RATE_LIMIT_USER_VIEWER", "30"))
DEFAULT_USER_UNTRUSTED = int(os.environ.get("IGRIS_RATE_LIMIT_USER_UNTRUSTED", "10"))

# Trust level to rate limit mapping
TRUST_LEVEL_LIMITS: Dict[str, int] = {
    "admin": DEFAULT_USER_ADMIN,
    "owner": DEFAULT_USER_ADMIN,
    "limited": DEFAULT_USER_VIEWER,
    "viewer": DEFAULT_USER_VIEWER,
    "untrusted": DEFAULT_USER_UNTRUSTED,
}


@dataclass
class UserRateLimitState:
    """Rate limit state for a single user."""
    profile_id: str
    trust_level: str = "untrusted"
    requests: list = field(default_factory=list)  # timestamps
    limit: int = DEFAULT_USER_STANDARD
    last_exceeded: float = 0.0


class UserRateLimiter:
    """Per-user rate limiter with role-based limits.

    Maintains a sliding window of request timestamps per user (profile_id).
    Limits are differentiated by trust_level:
    - admin/owner: higher limit (default 120/min)
    - limited/viewer: lower limit (default 30/min)
    - untrusted: minimal limit (default 10/min)
    """

    def __init__(
        self,
        standard_limit: int = DEFAULT_USER_STANDARD,
        admin_limit: int = DEFAULT_USER_ADMIN,
        viewer_limit: int = DEFAULT_USER_VIEWER,
        untrusted_limit: int = DEFAULT_USER_UNTRUSTED,
        window_seconds: int = 60,
    ) -> None:
        self.standard_limit = standard_limit
        self.admin_limit = admin_limit
        self.viewer_limit = viewer_limit
        self.untrusted_limit = untrusted_limit
        self.window_seconds = window_seconds
        self._buckets: Dict[str, UserRateLimitState] = {}

    def _get_limit_for_trust(self, trust_level: str) -> int:
        """Get the rate limit for a given trust level."""
        tl = trust_level.lower()
        if tl in ("admin", "owner"):
            return self.admin_limit
        if tl in ("limited", "viewer"):
            return self.viewer_limit
        if tl == "untrusted":
            return self.untrusted_limit
        return self.standard_limit

    def check(
        self,
        profile_id: str,
        trust_level: str = "untrusted",
    ) -> Tuple[bool, int, int]:
        """Check if a request is allowed for the given user.

        Returns (allowed, current_count, limit).
        """
        if not profile_id:
            profile_id = "anonymous"

        now = time.time()
        limit = self._get_limit_for_trust(trust_level)

        # Get or create user state
        if profile_id not in self._buckets:
            self._buckets[profile_id] = UserRateLimitState(
                profile_id=profile_id,
                trust_level=trust_level,
                limit=limit,
            )

        state = self._buckets[profile_id]

        # Update trust level and limit if changed
        if state.trust_level != trust_level:
            state.trust_level = trust_level
            state.limit = limit

        # Prune old entries (sliding window)
        state.requests = [
            t for t in state.requests
            if now - t < self.window_seconds
        ]

        # Check limit
        if len(state.requests) >= limit:
            state.last_exceeded = now
            return False, len(state.requests), limit

        # Allow and record
        state.requests.append(now)
        return True, len(state.requests), limit

    def get_status(self, profile_id: str) -> Dict[str, Any]:
        """Get rate limit status for a user.

        Returns a dict with current usage, limit, and remaining.
        """
        if not profile_id:
            profile_id = "anonymous"

        now = time.time()
        state = self._buckets.get(profile_id)

        if state is None:
            return {
                "profile_id": profile_id,
                "current": 0,
                "limit": self.standard_limit,
                "remaining": self.standard_limit,
                "trust_level": "untrusted",
                "window_seconds": self.window_seconds,
            }

        # Prune old entries
        state.requests = [
            t for t in state.requests
            if now - t < self.window_seconds
        ]

        current = len(state.requests)
        remaining = max(0, state.limit - current)

        return {
            "profile_id": profile_id,
            "current": current,
            "limit": state.limit,
            "remaining": remaining,
            "trust_level": state.trust_level,
            "window_seconds": self.window_seconds,
        }

    def reset(self, profile_id: Optional[str] = None) -> None:
        """Reset rate limit state for a user (or all users if None)."""
        if profile_id is None:
            self._buckets.clear()
        else:
            self._buckets.pop(profile_id, None)

    def list_users(self) -> list:
        """List all users with rate limit state."""
        return [
            self.get_status(pid)
            for pid in sorted(self._buckets.keys())
        ]


# Global instance for the application
_global_limiter: Optional[UserRateLimiter] = None


def get_user_rate_limiter() -> UserRateLimiter:
    """Get the global UserRateLimiter instance."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = UserRateLimiter()
    return _global_limiter


def reset_user_rate_limiter() -> None:
    """Reset the global UserRateLimiter (for testing)."""
    global _global_limiter
    _global_limiter = None
