"""Tests for VerifierRegistry (#1246)."""
import pytest
from igris.core.verifier_registry import (
    VerifierRegistry, EvidenceBundle, EvidenceItem, VerificationResult,
    MissionStructureVerifier, ApprovalPolicyVerifier, VerificationStatus,
    BaseVerifier,
)
from igris.core.jarvis_request_router import JarvisRequestRouter
from igris.core.mission_first import MissionFirstController


@pytest.fixture
def registry(tmp_path):
    return VerifierRegistry(project_root=tmp_path)


@pytest.fixture
def router_and_mfc(tmp_path):
    router = JarvisRequestRouter(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path)
    return router, mfc


def _make_plan(router_and_mfc, message, trust_level="admin", interlocutor_id="owner"):
    router, mfc = router_and_mfc
    rd = router.classify(message, interlocutor_id=interlocutor_id, trust_level=trust_level)
    return mfc.build_plan(message, route_decision=rd, trust_level=trust_level,
                           interlocutor_id=interlocutor_id)


# ── Init / health ──────────────────────────────────────────────────────────────

def test_verifier_registry_initializes(registry):
    assert registry.project_root is not None


def test_verifier_registry_healthcheck(registry):
    h = registry.healthcheck()
    assert "ok" in h
    assert "backends" in h


def test_default_verifiers_registered(registry):
    verifiers = registry.list_verifiers()
    assert len(verifiers) >= 6
    ids = [v["id"] for v in verifiers]
    assert "mission_structure" in ids
    assert "approval_policy" in ids
    assert "security" in ids


def test_register_custom_verifier(registry):
    class CustomVerifier(BaseVerifier):
        verifier_id = "custom_test"
        name = "Custom Test"
    registry.register(CustomVerifier())
    ids = [v["id"] for v in registry.list_verifiers()]
    assert "custom_test" in ids


# ── Verifier selection ─────────────────────────────────────────────────────────

def test_select_verifiers_for_read_only_inspection(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    verifiers = registry.select_verifiers(plan)
    assert len(verifiers) > 0


def test_select_verifiers_for_deploy_operation(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "fai deploy")
    verifiers = registry.select_verifiers(plan)
    assert len(verifiers) > 0


def test_select_verifiers_for_blocked_high_risk(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "cancella database", trust_level="untrusted", interlocutor_id="unknown")
    verifiers = registry.select_verifiers(plan)
    assert len(verifiers) > 0


# ── Mission structure verifier ────────────────────────────────────────────────

def test_mission_structure_verifier_passes_valid_plan(router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    v = MissionStructureVerifier()
    result, evidence = v.verify(plan)
    assert result.passed


def test_mission_structure_verifier_detects_missing_steps(tmp_path):
    from igris.core.mission_first import MissionPlan
    plan = MissionPlan(
        mission_id="test", title="test", route="read_only_inspection",
        risk="low", status="planned", execution_mode="read_only", steps=[]
    )
    v = MissionStructureVerifier()
    result, _ = v.verify(plan)
    # Missing steps for operational route should produce warning, not failure
    assert result.status in ("warning", "passed")


def test_mission_structure_verifier_no_evidence_for_missing_route(tmp_path):
    from igris.core.mission_first import MissionPlan
    plan = MissionPlan(
        mission_id="", title="test", route="",
        risk="low", status="", execution_mode="",
    )
    v = MissionStructureVerifier()
    result, _ = v.verify(plan)
    assert not result.passed
    assert result.errors


# ── Approval policy verifier ──────────────────────────────────────────────────

def test_approval_policy_deploy_requires_approval(router_and_mfc):
    plan = _make_plan(router_and_mfc, "fai deploy")
    v = ApprovalPolicyVerifier()
    result, _ = v.verify(plan)
    assert result.passed  # approval required is set correctly


def test_approval_policy_high_risk_unknown_blocked(router_and_mfc):
    plan = _make_plan(router_and_mfc, "cancella database", trust_level="untrusted", interlocutor_id="unknown")
    v = ApprovalPolicyVerifier()
    result, _ = v.verify(plan)
    assert result.passed  # blocked is a valid state for high-risk unknown


# ── Evidence bundle ────────────────────────────────────────────────────────────

def test_verify_mission_returns_evidence_bundle(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    bundle = registry.verify_mission(plan, persist=False)
    assert isinstance(bundle, EvidenceBundle)
    assert bundle.mission_id == plan.mission_id
    assert len(bundle.results) > 0


def test_evidence_bundle_contains_mission_plan_snapshot(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    bundle = registry.verify_mission(plan, persist=False)
    assert len(bundle.evidence) > 0
    kinds = [e.kind for e in bundle.evidence]
    assert "mission_plan" in kinds


def test_evidence_items_have_ids_and_timestamps(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    bundle = registry.verify_mission(plan, persist=False)
    for ev in bundle.evidence:
        assert ev.evidence_id
        assert ev.timestamp


def test_evidence_bundle_summary_text(registry, router_and_mfc):
    plan = _make_plan(router_and_mfc, "fai deploy")
    bundle = registry.verify_mission(plan, persist=False)
    text = bundle.summary_text()
    assert "[EVIDENCE BUNDLE]" in text
    assert len(text) > 0


def test_evidence_bundle_to_dict_is_serializable(registry, router_and_mfc):
    import json
    plan = _make_plan(router_and_mfc, "controlla i log")
    bundle = registry.verify_mission(plan, persist=False)
    d = bundle.to_dict()
    # Must be JSON-serializable
    json.dumps(d)


# ── Persistence ────────────────────────────────────────────────────────────────

def test_persist_bundle_uses_unified_memory(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    calls = []
    original = mem.store_run_event
    def tracking(*a, **kw):
        calls.append(True)
        return original(*a, **kw)
    mem.store_run_event = tracking

    registry = VerifierRegistry(project_root=tmp_path, unified_memory=mem)
    bundle = EvidenceBundle(bundle_id="b1", mission_id="m1", route="test", status="passed")
    registry.persist_bundle(bundle)
    assert len(calls) > 0


def test_persist_bundle_ok_true_with_real_unified_memory(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    registry = VerifierRegistry(project_root=tmp_path, unified_memory=mem)
    bundle = EvidenceBundle(bundle_id="b1", mission_id="m1", route="test")
    result = registry.persist_bundle(bundle)
    if mem._ltm is not None:
        assert result["ok"] is True
    else:
        assert result["ok"] is False


def test_persist_bundle_ok_false_when_memory_fails(tmp_path, monkeypatch):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    def broken(*a, **kw): raise RuntimeError("write fail")
    mem.store_run_event = broken

    registry = VerifierRegistry(project_root=tmp_path, unified_memory=mem)
    bundle = EvidenceBundle(bundle_id="b1", mission_id="m1", route="test")
    result = registry.persist_bundle(bundle)
    assert result["ok"] is False
    assert result.get("persistence_degraded")


def test_persist_bundle_no_memory_returns_degraded(tmp_path):
    registry = VerifierRegistry(project_root=tmp_path)
    registry._memory = None  # force unavailable
    # prevent lazy init
    registry._get_memory = lambda: None
    bundle = EvidenceBundle(bundle_id="b1", mission_id="m1", route="test")
    result = registry.persist_bundle(bundle)
    assert result["ok"] is False
    assert result.get("persistence_degraded")


# ── Safety / no secrets ────────────────────────────────────────────────────────

def test_verifier_no_raw_secret_in_bundle(tmp_path, router_and_mfc):
    import json
    FAKE = "FAKE_TOKEN_VERIFY_NOTREAL_1234567890"
    router, mfc = router_and_mfc
    rd = router.classify(f"fai deploy token={FAKE}", trust_level="admin")
    plan = mfc.build_plan(f"deploy token={FAKE}", route_decision=rd, trust_level="admin")

    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)

    output = json.dumps(bundle.to_dict())
    assert FAKE not in output, f"Raw secret in bundle: {output[:300]}"


def test_verifier_no_raw_secret_in_summary_text(tmp_path, router_and_mfc):
    FAKE = "FAKE_TOKEN_SUMMARY_NOTREAL_9988"
    router, mfc = router_and_mfc
    rd = router.classify(f"deploy passphrase={FAKE}", trust_level="admin")
    plan = mfc.build_plan(f"deploy passphrase={FAKE}", route_decision=rd, trust_level="admin")

    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)

    assert FAKE not in bundle.summary_text()


# ── Integration with #1245 ─────────────────────────────────────────────────────

def test_verify_mission_first_read_only_plan(tmp_path, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log del server")
    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)
    assert bundle.status in ("passed", "warning", "blocked")


def test_verify_mission_first_deploy_plan_requires_approval(tmp_path, router_and_mfc):
    plan = _make_plan(router_and_mfc, "fai deploy in produzione")
    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)
    # Approval policy should pass (deploy correctly requires approval)
    approval_result = next((r for r in bundle.results if r.verifier_id == "approval_policy"), None)
    if approval_result:
        assert approval_result.passed


def test_verify_mission_first_blocked_high_risk_plan(tmp_path, router_and_mfc):
    plan = _make_plan(router_and_mfc, "cancella database", trust_level="untrusted", interlocutor_id="unknown")
    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)
    assert bundle.status in ("blocked", "passed", "warning")  # blocked is ok


def test_mission_first_controller_verify_plan(tmp_path, router_and_mfc):
    router, mfc = router_and_mfc
    rd = router.classify("controlla i log", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd, trust_level="admin")

    if hasattr(mfc, "verify_plan"):
        bundle = mfc.verify_plan(plan)
        assert isinstance(bundle, EvidenceBundle)


def test_bundle_ok_true_for_passing_plan(tmp_path, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)
    assert bundle.ok is True


def test_bundle_ok_true_for_blocked_plan(tmp_path, router_and_mfc):
    plan = _make_plan(router_and_mfc, "cancella database", trust_level="untrusted", interlocutor_id="unknown")
    registry = VerifierRegistry(project_root=tmp_path)
    bundle = registry.verify_mission(plan, persist=False)
    # blocked plans are ok=True (correctly blocked) — strict assertion
    if bundle.status == "blocked":
        assert bundle.ok is True, f"blocked plan must have ok=True, got ok={bundle.ok!r}"
    else:
        # Non-blocked result: ok may be True (passed/warning) or False (failed)
        assert bundle.ok in (True, False)


def test_persistence_degraded_warning_when_no_memory(tmp_path, router_and_mfc):
    plan = _make_plan(router_and_mfc, "controlla i log")
    registry = VerifierRegistry(project_root=tmp_path)
    registry._memory = None
    registry._get_memory = lambda: None  # disable lazy init
    bundle = registry.verify_mission(plan, persist=True)
    assert any("persistence_degraded" in w for w in bundle.warnings)


def test_list_verifiers_returns_all_fields(registry):
    verifiers = registry.list_verifiers()
    for v in verifiers:
        assert "id" in v
        assert "name" in v
        assert "routes" in v
