"""Tests for per-user rate limiting (#1329)."""
import time

import pytest

from igris.core.user_rate_limiter import (
    UserRateLimiter,
    UserRateLimitState,
    get_user_rate_limiter,
    reset_user_rate_limiter,
)


class TestUserRateLimiter:
    """Unit tests for UserRateLimiter."""

    def test_basic_allow(self) -> None:
        """First request should be allowed."""
        limiter = UserRateLimiter(standard_limit=10)
        allowed, count, limit = limiter.check("user1", "untrusted")
        assert allowed is True
        assert count == 1
        assert limit == 10

    def test_limit_exceeded(self) -> None:
        """Request beyond limit should be denied."""
        limiter = UserRateLimiter(untrusted_limit=3)
        for _ in range(3):
            allowed, _, _ = limiter.check("user1", "untrusted")
            assert allowed is True
        # 4th request should be denied
        allowed, count, limit = limiter.check("user1", "untrusted")
        assert allowed is False
        assert count == 3
        assert limit == 3

    def test_admin_has_higher_limit(self) -> None:
        """Admin should have a higher limit than untrusted."""
        limiter = UserRateLimiter(admin_limit=100, untrusted_limit=5)
        # Admin can make more requests
        for _ in range(10):
            allowed, _, _ = limiter.check("admin1", "admin")
            assert allowed is True
        # Untrusted would be blocked at 5
        for _ in range(5):
            allowed, _, _ = limiter.check("untrusted1", "untrusted")
            assert allowed is True
        allowed, _, _ = limiter.check("untrusted1", "untrusted")
        assert allowed is False

    def test_viewer_has_lower_limit(self) -> None:
        """Viewer/limited should have a lower limit than admin."""
        limiter = UserRateLimiter(admin_limit=100, viewer_limit=20)
        _, _, admin_limit = limiter.check("admin1", "admin")
        _, _, viewer_limit = limiter.check("viewer1", "limited")
        assert admin_limit > viewer_limit

    def test_different_users_independent(self) -> None:
        """Different users should have independent rate limits."""
        limiter = UserRateLimiter(untrusted_limit=3)
        # User1 uses up their limit
        for _ in range(3):
            limiter.check("user1", "untrusted")
        # User2 should still be allowed
        allowed, _, _ = limiter.check("user2", "untrusted")
        assert allowed is True

    def test_sliding_window(self) -> None:
        """Old requests should expire from the window."""
        limiter = UserRateLimiter(untrusted_limit=3, window_seconds=1)
        for _ in range(3):
            limiter.check("user1", "untrusted")
        # Wait for window to expire
        time.sleep(1.1)
        allowed, count, _ = limiter.check("user1", "untrusted")
        assert allowed is True
        assert count == 1

    def test_get_status(self) -> None:
        """get_status should return current usage info."""
        limiter = UserRateLimiter(untrusted_limit=10)
        limiter.check("user1", "untrusted")
        limiter.check("user1", "untrusted")
        status = limiter.get_status("user1")
        assert status["profile_id"] == "user1"
        assert status["current"] == 2
        assert status["limit"] == 10
        assert status["remaining"] == 8
        assert status["trust_level"] == "untrusted"

    def test_get_status_unknown_user(self) -> None:
        """get_status for unknown user should return defaults."""
        limiter = UserRateLimiter()
        status = limiter.get_status("unknown")
        assert status["current"] == 0
        assert status["remaining"] == status["limit"]

    def test_reset_user(self) -> None:
        """reset should clear state for a specific user."""
        limiter = UserRateLimiter(untrusted_limit=3)
        for _ in range(3):
            limiter.check("user1", "untrusted")
        limiter.reset("user1")
        allowed, count, _ = limiter.check("user1", "untrusted")
        assert allowed is True
        assert count == 1

    def test_reset_all(self) -> None:
        """reset(None) should clear all users."""
        limiter = UserRateLimiter(untrusted_limit=3)
        limiter.check("user1", "untrusted")
        limiter.check("user2", "untrusted")
        limiter.reset()
        assert len(limiter._buckets) == 0

    def test_list_users(self) -> None:
        """list_users should return status for all tracked users."""
        limiter = UserRateLimiter()
        limiter.check("user1", "admin")
        limiter.check("user2", "untrusted")
        users = limiter.list_users()
        assert len(users) == 2
        profile_ids = [u["profile_id"] for u in users]
        assert "user1" in profile_ids
        assert "user2" in profile_ids

    def test_trust_level_change_updates_limit(self) -> None:
        """Changing trust level should update the user's limit."""
        limiter = UserRateLimiter(admin_limit=100, untrusted_limit=5)
        # Start as untrusted
        limiter.check("user1", "untrusted")
        _, _, limit1 = limiter.check("user1", "untrusted")
        assert limit1 == 5
        # Change to admin
        _, _, limit2 = limiter.check("user1", "admin")
        assert limit2 == 100

    def test_anonymous_user(self) -> None:
        """Empty profile_id should be treated as 'anonymous'."""
        limiter = UserRateLimiter(untrusted_limit=3)
        allowed, _, _ = limiter.check("", "untrusted")
        assert allowed is True
        status = limiter.get_status("")
        assert status["profile_id"] == "anonymous"

    def test_owner_treated_as_admin(self) -> None:
        """'owner' trust level should get admin limits."""
        limiter = UserRateLimiter(admin_limit=100, untrusted_limit=5)
        _, _, limit = limiter.check("owner1", "owner")
        assert limit == 100

    def test_global_limiter_singleton(self) -> None:
        """get_user_rate_limiter should return a singleton."""
        reset_user_rate_limiter()
        limiter1 = get_user_rate_limiter()
        limiter2 = get_user_rate_limiter()
        assert limiter1 is limiter2
        reset_user_rate_limiter()
