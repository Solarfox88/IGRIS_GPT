"""Fix #1295 — Dangerous intent routing tests.

Verifies that high-risk / destructive / write-operation intents are NEVER
classified as chat_only and are correctly blocked or require approval
according to the interlocutor trust level.
"""
from __future__ import annotations

import pytest

from igris.core.jarvis_request_router import (
    JarvisRequestRouter,
    JarvisRouteDecision,
    RequestRoute,
    RequestRisk,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def router():
    return JarvisRequestRouter(project_root="/tmp/igris_router_test")


def _classify(router, msg, trust):
    return router.classify(msg, interlocutor_id="test", trust_level=trust)


def _not_chat_only(d: JarvisRouteDecision) -> bool:
    return str(d.route) not in ("chat_only", RequestRoute.CHAT_ONLY)


def _is_blocked(d: JarvisRouteDecision) -> bool:
    return d.blocked is True


def _requires_approval(d: JarvisRouteDecision) -> bool:
    return d.requires_approval is True


def _is_high_risk(d: JarvisRouteDecision) -> bool:
    return str(d.risk) in ("high", "destructive",
                            RequestRisk.HIGH, RequestRisk.DESTRUCTIVE)


# ══ Shell / destructive commands ══════════════════════════════════════════════

class TestShellDestructiveCommands:

    def test_rm_rf_never_chat_only_for_untrusted(self, router):
        d = _classify(router, "rm -rf /", "untrusted")
        assert _not_chat_only(d), f"rm -rf / must not be chat_only (got {d.route})"
        assert _is_blocked(d), f"rm -rf / must be blocked for untrusted (got blocked={d.blocked})"

    def test_rm_rf_never_chat_only_for_limited(self, router):
        d = _classify(router, "rm -rf /", "limited")
        assert _not_chat_only(d), f"rm -rf / must not be chat_only for limited"
        assert _is_blocked(d), f"rm -rf / must be blocked for limited"

    def test_rm_rf_requires_approval_for_admin(self, router):
        d = _classify(router, "rm -rf /", "admin")
        assert _not_chat_only(d), f"rm -rf / must not be chat_only for admin"
        assert not d.blocked, "admin should not be blocked, but requires approval"
        assert _requires_approval(d), f"rm -rf / must require approval for admin"
        assert _is_high_risk(d), f"rm -rf / must have high/destructive risk"

    def test_rm_rf_home_blocked_for_limited(self, router):
        for msg in ("rm -rf /home/igris", "esegui rm -rf /home/igris"):
            d = _classify(router, msg, "limited")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert _is_blocked(d), f"{msg!r} must be blocked for limited"

    def test_sudo_reboot_never_chat_only(self, router):
        for trust in ("untrusted", "limited"):
            d = _classify(router, "sudo reboot", trust)
            assert _not_chat_only(d), f"sudo reboot must not be chat_only for {trust}"
            assert _is_blocked(d), f"sudo reboot must be blocked for {trust}"

    def test_sudo_reboot_admin_requires_approval(self, router):
        d = _classify(router, "sudo reboot", "admin")
        assert _not_chat_only(d)
        assert not d.blocked
        assert _requires_approval(d)

    def test_shutdown_never_chat_only(self, router):
        for msg in ("sudo shutdown -h now", "shutdown -h now", "reboot"):
            for trust in ("untrusted", "limited"):
                d = _classify(router, msg, trust)
                assert _not_chat_only(d), f"{msg!r} must not be chat_only for {trust}"
                assert _is_blocked(d), f"{msg!r} must be blocked for {trust}"

    def test_esegui_shell_command_high_risk(self, router):
        for msg in (
            "esegui rm -rf /tmp",
            "esegui bash -c 'rm -rf /'",
            "lancia questo comando: rm -rf /",
        ):
            d = _classify(router, msg, "limited")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert _is_blocked(d) or _is_high_risk(d), (
                f"{msg!r}: expected blocked or high risk (got blocked={d.blocked}, risk={d.risk})"
            )

    def test_unknown_dangerous_intent_blocked(self, router):
        for msg in ("rm -rf /", "sudo shutdown now", "esegui rm -rf /etc"):
            d = _classify(router, msg, "untrusted")
            assert _is_blocked(d), f"untrusted + {msg!r} must be blocked"

    def test_risk_metadata_present(self, router):
        """Every decision must expose a non-empty risk field."""
        for msg, trust in [
            ("rm -rf /", "admin"),
            ("crea una issue GitHub", "admin"),
            ("sudo reboot", "admin"),
            ("come stai?", "untrusted"),
        ]:
            d = _classify(router, msg, trust)
            assert d.risk, f"risk field must not be empty for {msg!r}"
            assert str(d.risk) not in ("", "none"), f"risk must be set for {msg!r}"


# ══ GitHub write operations ═══════════════════════════════════════════════════

class TestGitHubWriteOperations:

    def test_crea_issue_github_is_github_operation(self, router):
        for msg in ("crea una issue GitHub", "apri una issue su GitHub",
                    "create a GitHub issue", "open a new issue"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert str(d.route) in ("github_operation", RequestRoute.GITHUB_OPERATION), (
                f"{msg!r} must route to github_operation, got {d.route}"
            )

    def test_crea_issue_github_blocked_for_limited(self, router):
        d = _classify(router, "crea una issue GitHub", "limited")
        assert _is_blocked(d), "limited cannot create GitHub issues"

    def test_commenta_issue_github_is_github_operation(self, router):
        for msg in ("commenta la issue #1293", "aggiungi un commento alla issue #1",
                    "comment on issue #42"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert str(d.route) in ("github_operation", RequestRoute.GITHUB_OPERATION)

    def test_chiudi_issue_github_is_github_operation(self, router):
        for msg in ("chiudi la issue #1293", "close issue #42", "riapri issue #10"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert str(d.route) in ("github_operation", RequestRoute.GITHUB_OPERATION)

    def test_mergia_pr_requires_approval(self, router):
        d = _classify(router, "mergia la PR #1311", "admin")
        assert _not_chat_only(d)
        assert str(d.route) in ("github_operation", RequestRoute.GITHUB_OPERATION)
        assert _requires_approval(d), "PR merge must require approval"

    def test_trigger_workflow_requires_approval(self, router):
        # "run workflow deploy" contains "deploy" keyword → deploy_operation is also correct
        for msg in ("triggera il workflow", "trigger the GitHub action",
                    "rilancia la pipeline", "run ci pipeline"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert str(d.route) in (
                "github_operation", "deploy_operation",
                RequestRoute.GITHUB_OPERATION, RequestRoute.DEPLOY_OPERATION,
            ), f"{msg!r} expected github_operation or deploy_operation, got {d.route}"
            assert _requires_approval(d), f"{msg!r} must require approval"

    def test_github_write_blocked_for_untrusted(self, router):
        for msg in ("crea una issue GitHub", "commenta la issue #1", "mergia la PR #1"):
            d = _classify(router, msg, "untrusted")
            assert _is_blocked(d), f"untrusted + {msg!r} must be blocked"


# ══ Git local operations ══════════════════════════════════════════════════════

class TestGitLocalOperations:

    def test_git_commit_not_chat_only(self, router):
        for msg in ("fai git commit", "committa le modifiche", "git commit -m 'fix'"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"

    def test_git_push_not_chat_only(self, router):
        for msg in ("git push", "fai push", "git push origin main"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"

    def test_git_reset_hard_destructive(self, router):
        d = _classify(router, "git reset --hard", "admin")
        assert _not_chat_only(d)
        assert _is_high_risk(d), "git reset --hard must be high/destructive risk"
        assert _requires_approval(d)

    def test_git_reset_hard_blocked_for_limited(self, router):
        d = _classify(router, "git reset --hard", "limited")
        assert _is_blocked(d), "git reset --hard must be blocked for limited"

    def test_git_push_blocked_for_limited(self, router):
        d = _classify(router, "git push", "limited")
        assert _is_blocked(d), "git push must be blocked for limited"


# ══ Deploy / server / system ══════════════════════════════════════════════════

class TestDeployAndServer:

    def test_deploy_requires_approval(self, router):
        for msg in ("fai deploy", "deploy in produzione", "deploy to production"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d)
            assert _requires_approval(d), f"{msg!r} must require approval"

    def test_riavvia_server_blocked_for_limited(self, router):
        d = _classify(router, "riavvia il server", "limited")
        assert _is_blocked(d), "riavvia il server must be blocked for limited"

    def test_riavvia_server_requires_approval_for_admin(self, router):
        d = _classify(router, "riavvia il server", "admin")
        assert _not_chat_only(d)
        assert _requires_approval(d)

    def test_systemctl_restart_high_risk(self, router):
        for msg in ("systemctl restart igris", "service nginx restart"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert _requires_approval(d)

    def test_rollback_is_deploy_operation(self, router):
        d = _classify(router, "rollback produzione", "admin")
        assert _not_chat_only(d)
        assert _requires_approval(d)


# ══ Filesystem write / patch ══════════════════════════════════════════════════

class TestFilesystemWrite:

    def test_scrivi_file_not_chat_only(self, router):
        for msg in ("scrivi un file su disco", "write file to disk",
                    "salva su disco il file"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"

    def test_scrivi_file_blocked_for_limited(self, router):
        d = _classify(router, "scrivi un file su disco", "limited")
        assert _is_blocked(d), "limited cannot write files"

    def test_applica_patch_code_change_or_high_risk(self, router):
        for msg in ("applica questa patch", "apply patch", "apply the diff"):
            d = _classify(router, msg, "admin")
            assert _not_chat_only(d), f"{msg!r} must not be chat_only"
            assert str(d.route) in (
                "code_change", "high_risk_operation",
                RequestRoute.CODE_CHANGE, RequestRoute.HIGH_RISK_OPERATION,
            ), f"{msg!r} expected code_change or high_risk, got {d.route}"

    def test_cancella_database_blocked_for_limited(self, router):
        d = _classify(router, "cancella il database di produzione", "limited")
        assert _is_blocked(d), "limited cannot delete database"

    def test_cancella_database_blocked_for_untrusted(self, router):
        d = _classify(router, "cancella il database di produzione", "untrusted")
        assert _is_blocked(d)


# ══ Trust level differentiation ═══════════════════════════════════════════════

class TestTrustLevelDifferentiation:

    def test_limited_dangerous_shell_blocked(self, router):
        for msg in ("rm -rf /", "sudo reboot", "esegui rm -rf /home/igris"):
            d = _classify(router, msg, "limited")
            assert _is_blocked(d), f"limited + {msg!r} must be blocked"

    def test_admin_dangerous_shell_requires_approval_not_blocked(self, router):
        for msg in ("rm -rf /", "sudo reboot"):
            d = _classify(router, msg, "admin")
            assert not d.blocked, f"admin should not be blocked for {msg!r}"
            assert _requires_approval(d), f"admin + {msg!r} must require approval"

    def test_code_change_limited_blocked(self, router):
        """limited users must be BLOCKED (not just approval_required) for code_change."""
        for msg in ("modifica il file config.py aggiungendo debug=True",
                    "fix the authentication bug in write_auth.py"):
            d = _classify(router, msg, "limited")
            assert _is_blocked(d), (
                f"limited + code_change must be blocked, got blocked={d.blocked} route={d.route}"
            )

    def test_code_change_admin_requires_approval_not_blocked(self, router):
        """admin users get approval_required (not blocked) for code_change."""
        d = _classify(router, "modifica il file config.py aggiungendo debug=True", "admin")
        assert not d.blocked, "admin should not be blocked for code_change"
        assert _requires_approval(d), "admin code_change must require approval"

    def test_code_change_limited_not_same_as_admin(self, router):
        """Limited and admin must receive different treatment for code_change."""
        msg = "modifica il file config.py aggiungendo debug=True"
        d_limited = _classify(router, msg, "limited")
        d_admin = _classify(router, msg, "admin")
        # limited blocked, admin not blocked
        assert d_limited.blocked is True, "limited must be blocked for code_change"
        assert d_admin.blocked is False, "admin must not be blocked for code_change"
        # They should NOT be identical
        assert d_limited.blocked != d_admin.blocked, (
            "limited and admin code_change decisions must differ"
        )

    def test_github_write_limited_blocked(self, router):
        for msg in ("crea una issue GitHub", "commenta la issue #1",
                    "chiudi la issue #1293"):
            d = _classify(router, msg, "limited")
            assert _is_blocked(d), f"limited + {msg!r} must be blocked"

    def test_github_write_admin_requires_approval(self, router):
        for msg in ("crea una issue GitHub", "commenta la issue #1",
                    "chiudi la issue #1293"):
            d = _classify(router, msg, "admin")
            assert not d.blocked, f"admin should not be blocked for {msg!r}"
            assert _requires_approval(d), f"admin + {msg!r} must require approval"

    def test_owner_mirrors_admin_for_dangerous(self, router):
        """owner trust level should behave like admin — not blocked, approval required."""
        for msg in ("rm -rf /", "crea una issue GitHub", "fai deploy"):
            d = _classify(router, msg, "owner")
            assert not d.blocked, f"owner should not be blocked for {msg!r}"
            assert _requires_approval(d), f"owner + {msg!r} must require approval"

    def test_unknown_dangerous_intent_blocked(self, router):
        for msg in ("rm -rf /", "sudo shutdown now", "crea una issue GitHub"):
            d = _classify(router, msg, "unknown")
            assert _is_blocked(d), f"unknown trust + {msg!r} must be blocked"


# ══ Safe messages must remain chat_only ══════════════════════════════════════

class TestSafeMessagesUnaffected:

    def test_innocuous_chat_stays_chat_only(self, router):
        for msg in ("come stai?", "ciao", "what time is it?",
                    "dimmi qualcosa di interessante", "hello"):
            d = _classify(router, msg, "untrusted")
            assert str(d.route) in ("chat_only", RequestRoute.CHAT_ONLY), (
                f"Innocuous message {msg!r} should stay chat_only, got {d.route}"
            )
            assert not d.blocked, f"{msg!r} must not be blocked for untrusted"

    def test_read_only_inspection_not_blocked(self, router):
        for msg in ("controlla i log", "mostra il report", "show the status"):
            for trust in ("untrusted", "limited", "admin"):
                d = _classify(router, msg, trust)
                assert not d.blocked, f"{msg!r} must not be blocked for {trust}"
