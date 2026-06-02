"""Tests for the safe network diagnostics gateway (#950)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from igris.core.network_diag_gateway import NetworkDiagGateway
from igris.web.server import create_app


@dataclass
class FakeNetworkRunner:
    dns_calls: list[str] = None
    tcp_calls: list[tuple[str, int, float]] = None
    http_calls: list[tuple[str, float]] = None
    trace_calls: list[tuple[str, int, float]] = None

    def __post_init__(self) -> None:
        self.dns_calls = []
        self.tcp_calls = []
        self.http_calls = []
        self.trace_calls = []

    def dns_lookup(self, host: str):
        self.dns_calls.append(host)
        return ["93.184.216.34"]

    def tcp_connect(self, host: str, port: int, timeout: float):
        self.tcp_calls.append((host, port, timeout))
        return {"reachable": True, "latency_ms": 12, "host": host, "port": port}

    def http_latency(self, url: str, timeout: float):
        self.http_calls.append((url, timeout))
        return {"status_code": 200, "latency_ms": 34, "url": url}

    def traceroute(self, host: str, max_hops: int, timeout: float):
        self.trace_calls.append((host, max_hops, timeout))
        return {"available": True, "hops": [{"hop": 1, "host": "router"}], "host": host}


def test_read_only_inspection_blocks_unscoped_host():
    gateway = NetworkDiagGateway(runner=FakeNetworkRunner())
    result = gateway.dns_lookup("example.com")
    assert result["success"] is False
    assert result["status"] == "blocked"
    assert gateway.get_audit_log()[-1]["status"] == "BLOCKED"


def test_dns_tcp_http_traceroute_with_allowed_scope_and_redaction():
    runner = FakeNetworkRunner()
    gateway = NetworkDiagGateway(runner=runner)
    allowed_hosts = ["github.com", "api.github.com"]
    allowed_domains = ["github.com"]

    dns = gateway.dns_lookup("github.com", allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
    tcp = gateway.tcp_connect("github.com", 443, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
    http = gateway.http_latency("https://github.com/?token=super-secret", allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
    trace = gateway.traceroute("github.com", allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)

    assert dns["success"] is True and dns["status"] == "ok"
    assert tcp["result"]["reachable"] is True
    assert http["result"]["latency_ms"] == 34
    assert trace["status"] == "ok"
    assert runner.dns_calls == ["github.com"]
    assert runner.tcp_calls == [("github.com", 443, 5.0)]
    assert "super-secret" not in str(gateway.get_audit_log())


def test_port_check_rejects_invalid_port():
    gateway = NetworkDiagGateway(runner=FakeNetworkRunner())
    result = gateway.port_check("localhost", 70000)
    assert result["success"] is False
    assert result["status"] == "blocked"


def test_traceroute_degrades_when_unavailable():
    class NoTraceRunner(FakeNetworkRunner):
        def traceroute(self, host: str, max_hops: int, timeout: float):
            return {"available": False, "status": "degraded", "reason": "not installed"}

    gateway = NetworkDiagGateway(runner=NoTraceRunner())
    result = gateway.traceroute("localhost", allowed_hosts=["localhost"])
    assert result["success"] is True
    assert result["status"] == "degraded"


def test_inventory_and_provisioning_are_scoped_and_audited(tmp_path):
    gateway = NetworkDiagGateway(runner=FakeNetworkRunner(), audit_path=str(tmp_path / "network_diag_audit.jsonl"))
    inventory = gateway.inventory(
        "github.com",
        port=443,
        url="https://github.com",
        allowed_hosts=["github.com"],
        allowed_domains=["github.com"],
    )
    proposal = gateway.propose_provisioning_hook(
        "github.com",
        "dns->tcp->http smoke",
        approval=False,
        dry_run=True,
        allowed_hosts=["github.com"],
        allowed_domains=["github.com"],
    )

    assert inventory["allowed"] is True
    assert inventory["checks"]["dns"] is True
    assert inventory["checks"]["tcp"] is True
    assert inventory["checks"]["http_latency"] is True
    assert proposal["success"] is True
    assert proposal["dry_run"] is True
    audit_text = (tmp_path / "network_diag_audit.jsonl").read_text(encoding="utf-8")
    assert "github.com" in audit_text
    assert "super-secret" not in audit_text


def test_api_routes_use_gateway_and_fake_runner(monkeypatch):
    from igris.api.routes import network as network_routes

    runner = FakeNetworkRunner()
    monkeypatch.setattr(network_routes, "gateway", NetworkDiagGateway(runner=runner))

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/network/dns?host=localhost")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = client.get("/api/network/http-latency?url=https://localhost&allowed_hosts=localhost")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = client.get("/api/network/audit-log")
    assert r.status_code == 200
    assert isinstance(r.json()["audit_log"], list)

    r = client.get("/api/network/inventory?host=localhost&port=7778&url=http://localhost&allowed_hosts=localhost")
    assert r.status_code == 200
    assert r.json()["allowed"] is True

    r = client.post("/api/network/proposals/provisioning", json={"target": "localhost", "hook": "smoke", "dry_run": True, "approval": False, "allowed_hosts": "localhost"})
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
