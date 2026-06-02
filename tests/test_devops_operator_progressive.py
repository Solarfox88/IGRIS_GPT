from __future__ import annotations

from igris.core.devops_manager import CommandResult, DevOpsManager, FakeCommandRunner, HostConfig


def test_host_config_environment_and_allowed_domains_roundtrip() -> None:
    host = HostConfig(hostname="vps.example", environment="staging", allowed_domains=["example.com"])
    loaded = HostConfig.from_dict(host.to_dict())
    assert loaded.environment == "staging"
    assert loaded.allowed_domains == ["example.com"]


def test_run_deploy_rejects_invalid_environment(tmp_path) -> None:
    mgr = DevOpsManager(str(tmp_path), runner=FakeCommandRunner())
    mgr.register_host(HostConfig(hostname="vps", policy="operator", environment="invalid-env"))
    result = mgr.run_deploy(hostname="vps", dry_run=True)
    assert result["deployed"] is False
    assert "invalid host environment" in result["abort_reason"]


def test_run_deploy_blocks_production_without_approval(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result(
        "df -P",
        CommandResult(
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/root 1000 400 600 40% /\n",
        ),
    )
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    mgr.register_host(
        HostConfig(
            hostname="localhost",
            policy="operator",
            environment="production",
            allowed_domains=["prod.example.com"],
        )
    )
    blocked = mgr.run_deploy(
        hostname="localhost",
        health_url="https://prod.example.com/health",
        dry_run=False,
        strategy="git_pull_restart",
    )
    assert blocked["deployed"] is False
    assert "production_approval" in blocked["abort_reason"]


def test_run_deploy_blocks_staging_without_explicit_approval(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result(
        "df -P",
        CommandResult(
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/root 1000 400 600 40% /\n",
        ),
    )
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    mgr.register_host(
        HostConfig(
            hostname="localhost",
            policy="operator",
            environment="staging",
            allowed_paths=[str(tmp_path)],
            allowed_services=["igris"],
            allowed_domains=["staging.example.com"],
        )
    )
    blocked = mgr.run_deploy(
        hostname="localhost",
        health_url="https://staging.example.com/health",
        dry_run=False,
        strategy="git_pull_restart",
    )
    assert blocked["deployed"] is False
    assert "staging deploy requires explicit deployment_approval" in blocked["abort_reason"]
    assert blocked["approval"]["required"] is True


def test_run_deploy_allows_staging_with_explicit_approval(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result(
        "df -P",
        CommandResult(
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/root 1000 400 600 40% /\n",
        ),
    )
    runner.set_result("git pull --ff-only", CommandResult(returncode=0, stdout="Already up to date.\n"))
    runner.set_result("systemctl restart igris", CommandResult(returncode=0, stderr="restarted"))
    runner.set_result("git rev-parse HEAD", CommandResult(returncode=0, stdout="abc123\n"))
    runner.set_result("nc -z -w 3 localhost 7778", CommandResult(returncode=0))
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    mgr.run_smoke_test = lambda url="": {  # type: ignore[assignment]
        "ok": True,
        "status_code": 200,
        "response_time_ms": 12,
        "url": url,
        "body_preview": "ok",
    }
    mgr.run_browser_smoke = lambda url="", selector="body", runner=None: {  # type: ignore[assignment]
        "ok": True,
        "url": url,
        "selector": selector,
        "status": "passed",
        "evidence": "browser smoke ok",
    }
    mgr.register_host(
        HostConfig(
            hostname="localhost",
            policy="operator",
            environment="staging",
            allowed_paths=[str(tmp_path)],
            allowed_services=["igris"],
            allowed_domains=["staging.example.com"],
        )
    )
    allowed = mgr.run_deploy(
        hostname="localhost",
        health_url="https://staging.example.com/health",
        dry_run=False,
        strategy="git_pull_restart",
        deploy_approval="approved",
        mission_id="mission-7",
        run_id="run-9",
    )
    assert allowed["deployed"] is True
    assert allowed["approval"]["granted"] is True
    assert allowed["context"] == {"mission_id": "mission-7", "run_id": "run-9"}
    assert allowed["postcheck"]["checks"]["http_health"]["url"] == "https://staging.example.com/health"
    assert "browser" in allowed["postcheck"]["checks"]


def test_run_deploy_allows_production_with_explicit_approval(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result(
        "df -P",
        CommandResult(
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/root 1000 400 600 40% /\n",
        ),
    )
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    mgr.register_host(
        HostConfig(
            hostname="localhost",
            policy="operator",
            environment="production",
            allowed_domains=["prod.example.com"],
        )
    )
    allowed = mgr.run_deploy(
        hostname="localhost",
        health_url="https://prod.example.com/health",
        dry_run=True,
        strategy="dry_run",
        production_approval="approved",
    )
    assert "dry_run_evidence" in allowed


def test_devops_audit_file_created(tmp_path) -> None:
    mgr = DevOpsManager(str(tmp_path), runner=FakeCommandRunner())
    mgr.run_deploy(dry_run=True, strategy="dry_run", mission_id="mission-a", run_id="run-b", health_url="https://safe.example.com/health?token=abc123")
    audit_file = tmp_path / ".igris" / "devops_operator_audit.jsonl"
    assert audit_file.exists()
    content = audit_file.read_text(encoding="utf-8").strip()
    assert content
    assert "mission-a" in content
    assert "run-b" in content
    assert "abc123" not in content
    assert "[REDACTED]" in content


def test_run_deploy_enforces_allowed_domains(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result(
        "df -P",
        CommandResult(
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/root 1000 400 600 40% /\n",
        ),
    )
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    mgr.register_host(
        HostConfig(
            hostname="localhost",
            policy="operator",
            environment="staging",
            allowed_domains=["allowed.example.com"],
        )
    )
    blocked = mgr.run_deploy(hostname="localhost", health_url="https://blocked.example.com/health", dry_run=True)
    assert blocked["deployed"] is False
    assert "domain is not allowed" in blocked["abort_reason"]

    allowed = mgr.run_deploy(hostname="localhost", health_url="https://allowed.example.com/health", dry_run=True)
    assert allowed["deployed"] is False
    assert "dry_run_evidence" in allowed


def test_run_rollback_dry_run_does_not_execute_commands(tmp_path) -> None:
    runner = FakeCommandRunner()
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    result = mgr.run_rollback(pre_deploy_sha="abc123", dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert "commands" in result["steps"]["plan"]


def test_run_diagnostics_returns_structured_sections_and_redacts(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result("systemctl is-active igris", CommandResult(returncode=0, stdout="active\n"))
    runner.set_result("systemctl is-active nginx", CommandResult(returncode=0, stdout="active\n"))
    runner.set_result("systemctl is-active docker", CommandResult(returncode=0, stdout="active\n"))
    runner.set_result("docker ps", CommandResult(returncode=0, stdout="igris\n"))
    runner.set_result("nginx -t", CommandResult(returncode=0, stderr="ok"))
    runner.set_result("ss -tln", CommandResult(returncode=0, stdout="LISTEN 0 128 0.0.0.0:80\n"))
    runner.set_result("ps -eo", CommandResult(returncode=0, stdout="1 python 1.0 1.0\n"))
    runner.set_result("df -h", CommandResult(returncode=0, stdout="Filesystem Size Used Avail Use% Mounted on\n"))
    runner.set_result("journalctl -u igris", CommandResult(returncode=0, stdout="token=abc123"))
    runner.set_result("journalctl -u nginx", CommandResult(returncode=0, stdout="password=abc123"))
    runner.set_result("openssl s_client", CommandResult(returncode=0, stdout="CONNECTED"))
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    report = mgr.run_diagnostics(ssl_target="example.com:443", mission_id="mission-x", run_id="run-y")
    assert "systemd" in report
    assert "docker" in report
    assert "nginx" in report
    assert "ports" in report
    assert "processes" in report
    assert "disk" in report
    assert "logs" in report
    assert report["logs"]["igris"]["stdout"] == "[REDACTED]"
    assert report["logs"]["nginx"]["stdout"] == "[REDACTED]"
    assert report["context"] == {"mission_id": "mission-x", "run_id": "run-y"}
    assert "browser" in report


def test_run_rollback_returns_evidence_and_context(tmp_path) -> None:
    runner = FakeCommandRunner()
    runner.set_result("git reset --hard", CommandResult(returncode=0, stdout="reset\n"))
    runner.set_result("systemctl restart igris", CommandResult(returncode=0, stderr="restarted"))
    mgr = DevOpsManager(str(tmp_path), runner=runner)
    result = mgr.run_rollback(
        pre_deploy_sha="abc123",
        mission_id="mission-r",
        run_id="run-r",
    )
    assert result["ok"] is True
    assert result["context"] == {"mission_id": "mission-r", "run_id": "run-r"}
    assert result["evidence"]["mode"] == "apply"
    assert result["evidence"]["verified"] is True
