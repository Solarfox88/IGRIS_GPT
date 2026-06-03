"""Tests for Network Diagnostics phase 2 (#1209).

Phase 2 additions:
- Expanded allowed-host/domain inventory (multi-host, subdomain matching)
- Provisioning hook backend planning with richer metadata
- Audit/redaction persists across multiple operations
- Blocked hosts never leak into provisioning calls
- Dry-run mode is consistent across all operations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from igris.core.network_diag_gateway import NetworkDiagGateway


@dataclass
class FakeNetworkRunner:
    dns_calls: list = field(default_factory=list)
    tcp_calls: list = field(default_factory=list)
    http_calls: list = field(default_factory=list)
    trace_calls: list = field(default_factory=list)

    def dns_lookup(self, host: str):
        self.dns_calls.append(host)
        return ["1.2.3.4", "5.6.7.8"]

    def tcp_connect(self, host: str, port: int, timeout: float):
        self.tcp_calls.append((host, port, timeout))
        return {"reachable": True, "latency_ms": 5, "host": host, "port": port}

    def http_latency(self, url: str, timeout: float):
        self.http_calls.append((url, timeout))
        return {"status_code": 200, "latency_ms": 20, "url": url, "body_bytes": 256}

    def traceroute(self, host: str, max_hops: int, timeout: float):
        self.trace_calls.append((host, max_hops, timeout))
        return {"available": True, "command": "traceroute", "hops": [{"hop": 1, "host": "10.0.0.1"}], "host": host}


@dataclass
class FakeProvisioningBackend:
    inventory_calls: list = field(default_factory=list)
    proposal_calls: list = field(default_factory=list)

    def inspect_inventory(self, target, *, host, port, url, allowed_hosts, allowed_domains):
        call = dict(target=target, host=host, port=port, url=url,
                    allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        self.inventory_calls.append(call)
        return {
            "target": target,
            "host": host,
            "port": port,
            "url": url,
            "allowed_hosts": allowed_hosts,
            "allowed_domains": allowed_domains,
            "stages": ["dns", "tcp", "http_latency", "traceroute", "provisioning_hook"],
            "provisioning_backend": "fake_v2",
            "metadata": {"version": "2", "plan_id": "plan-001"},
        }

    def propose_provisioning_hook(self, target, hook, *, approval, dry_run, allowed_hosts, allowed_domains):
        call = dict(target=target, hook=hook, approval=approval, dry_run=dry_run,
                    allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        self.proposal_calls.append(call)
        return {
            "target": target,
            "hook": hook,
            "approval": approval,
            "dry_run": dry_run,
            "allowed_hosts": allowed_hosts,
            "allowed_domains": allowed_domains,
            "status": "backend_planned",
            "plan_id": "plan-001",
        }


# ---------------------------------------------------------------------------
# Expanded allowed-host/domain inventory
# ---------------------------------------------------------------------------

def test_expanded_inventory_multi_host():
    """Inventory expands safely when multiple allowed hosts are given."""
    runner = FakeNetworkRunner()
    backend = FakeProvisioningBackend()
    gw = NetworkDiagGateway(runner=runner, provisioning_backend=backend,
                             default_allowed_hosts=["localhost"],
                             default_allowed_domains=[])
    allowed_hosts = ["api.example.com", "cdn.example.com", "localhost"]
    allowed_domains = ["example.com"]

    inv = gw.inventory("api.example.com", port=443,
                        url="https://api.example.com/health",
                        allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)

    assert inv["allowed"] is True
    assert "api.example.com" in inv["allowed_hosts"]
    assert "cdn.example.com" in inv["allowed_hosts"]
    assert "example.com" in inv["allowed_domains"]
    assert inv["checks"]["dns"] is True
    assert inv["checks"]["tcp"] is True
    assert inv["checks"]["http_latency"] is True
    assert inv["endpoint_inventory"]["provisioning_hook"]["mode"] == "backend_planned"
    assert inv["endpoint_inventory"]["provisioning_hook"]["approval_required"] is True
    # backend was called with the expanded scope
    assert backend.inventory_calls
    call = backend.inventory_calls[0]
    assert "api.example.com" in call["allowed_hosts"]


def test_inventory_subdomain_matching():
    """Subdomains of allowed domains are accepted."""
    gw = NetworkDiagGateway(runner=FakeNetworkRunner())
    inv = gw.inventory("sub.allowed.tld", allowed_domains=["allowed.tld"])
    assert inv["allowed"] is True


def test_inventory_blocked_host_stays_blocked():
    """Hosts outside the allowed scope remain blocked even with provisioning backend."""
    backend = FakeProvisioningBackend()
    gw = NetworkDiagGateway(runner=FakeNetworkRunner(), provisioning_backend=backend)
    inv = gw.inventory("evil.com", allowed_hosts=["localhost"])
    assert inv["allowed"] is False
    # backend should not be called for blocked hosts
    assert not backend.inventory_calls


def test_inventory_backend_metadata_included():
    """Backend inspect_inventory result is included in inventory response."""
    backend = FakeProvisioningBackend()
    gw = NetworkDiagGateway(runner=FakeNetworkRunner(), provisioning_backend=backend)
    inv = gw.inventory("localhost", port=80, url="http://localhost",
                        allowed_hosts=["localhost"])
    assert inv["backend_inventory"]["provisioning_backend"] == "fake_v2"
    assert inv["backend_inventory"]["metadata"]["plan_id"] == "plan-001"


# ---------------------------------------------------------------------------
# Approval-gated provisioning hooks
# ---------------------------------------------------------------------------

def test_provisioning_hook_requires_approval_by_default():
    """Proposal in dry_run=True / approval=False stays dry_run and never calls backend."""
    backend = FakeProvisioningBackend()
    gw = NetworkDiagGateway(runner=FakeNetworkRunner(), provisioning_backend=backend)
    result = gw.propose_provisioning_hook(
        "localhost", "smoke",
        approval=False, dry_run=True,
        allowed_hosts=["localhost"],
    )
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["status"] == "dry_run"
    assert not backend.proposal_calls


def test_provisioning_hook_backend_called_when_approved():
    """When approval=True and dry_run=False, backend is invoked."""
    backend = FakeProvisioningBackend()
    gw = NetworkDiagGateway(runner=FakeNetworkRunner(), provisioning_backend=backend)
    result = gw.propose_provisioning_hook(
        "localhost", "smoke",
        approval=True, dry_run=False,
        allowed_hosts=["localhost"],
    )
    assert result["success"] is True
    assert result["status"] == "backend_planned"
    assert backend.proposal_calls
    call = backend.proposal_calls[0]
    assert call["approval"] is True
    assert call["dry_run"] is False


def test_provisioning_hook_blocked_for_unscoped_host():
    """Provisioning hook is blocked for hosts not in the allowed scope."""
    backend = FakeProvisioningBackend()
    gw = NetworkDiagGateway(runner=FakeNetworkRunner(), provisioning_backend=backend)
    result = gw.propose_provisioning_hook(
        "evil.com", "smoke",
        approval=True, dry_run=False,
        allowed_hosts=["localhost"],
    )
    assert result["success"] is False
    assert result["status"] == "blocked"
    assert not backend.proposal_calls


def test_provisioning_hook_blocked_without_backend():
    """Without a backend and with approval, returns blocked (not an error)."""
    gw = NetworkDiagGateway(runner=FakeNetworkRunner())
    result = gw.propose_provisioning_hook(
        "localhost", "smoke",
        approval=True, dry_run=False,
        allowed_hosts=["localhost"],
    )
    assert result["success"] is False
    assert result["status"] == "blocked"
    assert result.get("approval_required") is True


# ---------------------------------------------------------------------------
# Audit / redaction
# ---------------------------------------------------------------------------

def test_audit_persists_across_multiple_operations(tmp_path):
    """Multiple operations all appear in the persisted audit log."""
    runner = FakeNetworkRunner()
    audit_path = str(tmp_path / "net_audit.jsonl")
    gw = NetworkDiagGateway(runner=runner, audit_path=audit_path,
                             default_allowed_hosts=["localhost"])

    gw.dns_lookup("localhost")
    gw.tcp_connect("localhost", 80)
    gw.http_latency("http://localhost")
    gw.traceroute("localhost")

    lines = Path(audit_path).read_text().strip().splitlines()
    import json
    entries = [json.loads(line) for line in lines]
    actions = [e["action"] for e in entries]
    assert "dns.lookup" in actions
    assert "tcp.connect" in actions
    assert "http.latency" in actions
    assert "traceroute" in actions


def test_audit_redacts_secret_tokens_from_urls(tmp_path):
    """Secret query params in URLs are redacted in the audit log."""
    runner = FakeNetworkRunner()
    audit_path = str(tmp_path / "net_audit.jsonl")
    gw = NetworkDiagGateway(runner=runner, audit_path=audit_path,
                             default_allowed_hosts=["localhost"])

    gw.http_latency("http://localhost?token=my-super-secret-token")
    gw.http_latency("http://localhost?auth=bearer-xyz&page=1")

    text = Path(audit_path).read_text()
    assert "my-super-secret-token" not in text
    assert "bearer-xyz" not in text
    assert "[REDACTED]" in text


def test_diagnose_full_pipeline(tmp_path):
    """diagnose() runs dns + tcp + http_latency + traceroute and audits all."""
    runner = FakeNetworkRunner()
    audit_path = str(tmp_path / "net_audit.jsonl")
    gw = NetworkDiagGateway(runner=runner, audit_path=audit_path)

    report = gw.diagnose(
        "localhost",
        port=80,
        url="http://localhost",
        allowed_hosts=["localhost"],
    )

    assert report["status"] in ("ok", "dry_run")
    results = report["results"]
    assert "dns" in results
    assert "tcp" in results
    assert "http_latency" in results
    assert "traceroute" in results
    assert runner.dns_calls == ["localhost"]


def test_dry_run_mode_skips_real_calls():
    """In dry_run mode no real runner calls are made."""
    runner = FakeNetworkRunner()
    gw = NetworkDiagGateway(runner=runner, dry_run=True,
                             default_allowed_hosts=["localhost"])

    gw.dns_lookup("localhost")
    gw.tcp_connect("localhost", 80)
    gw.http_latency("http://localhost")
    gw.traceroute("localhost")

    # No real calls should have been made
    assert runner.dns_calls == []
    assert runner.tcp_calls == []
    assert runner.http_calls == []
    assert runner.trace_calls == []
