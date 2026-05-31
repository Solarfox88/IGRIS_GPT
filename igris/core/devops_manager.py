"""DevOps Manager — Epic #1076.

Host registry (persist/load from JSON), server policy enforcement,
deploy patterns with preflight/postcheck, and HTTP smoke-test evidence.

Designed to be imported by igris.web.routers.routes_10 for the /api/devops/*
endpoints.  All operations are best-effort: each step records its own
outcome so that partial failures are visible rather than silent.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Command Runner abstraction — PR 3
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    """Result of a command execution."""
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "returncode": self.returncode,
            "stdout": self.stdout[:500],
            "stderr": self.stderr[:300],
            "ok": self.ok,
        }


class CommandRunner(ABC):
    """Abstract command executor — decouples DevOpsManager from subprocess."""

    @abstractmethod
    def run(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> CommandResult:
        """Execute a command and return a CommandResult."""


class LocalCommandRunner(CommandRunner):
    """Real subprocess-based runner for production use."""

    def run(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> CommandResult:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return CommandResult(
                returncode=r.returncode,
                stdout=r.stdout or "",
                stderr=r.stderr or "",
            )
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=124, stderr=f"command timed out after {timeout}s")
        except Exception as exc:
            return CommandResult(returncode=1, stderr=str(exc)[:300])


class SSHCommandRunner(CommandRunner):
    """Safe remote runner via SSH for stage-1 VPS operations."""

    def __init__(self, hostname: str, user: str = "", port: int = 22) -> None:
        self.hostname = hostname
        self.user = user.strip()
        self.port = int(port or 22)

    def _target(self) -> str:
        return f"{self.user}@{self.hostname}" if self.user else self.hostname

    @staticmethod
    def _quote_cmd(cmd: List[str]) -> str:
        return " ".join(shlex.quote(part) for part in cmd)

    def run(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> CommandResult:
        remote_cmd = self._quote_cmd(cmd)
        if cwd:
            remote_cmd = f"cd {shlex.quote(cwd)} && {remote_cmd}"
        ssh_cmd = [
            "ssh",
            "-p",
            str(self.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            self._target(),
            remote_cmd,
        ]
        try:
            r = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return CommandResult(
                returncode=r.returncode,
                stdout=r.stdout or "",
                stderr=r.stderr or "",
            )
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=124, stderr=f"ssh command timed out after {timeout}s")
        except Exception as exc:
            return CommandResult(returncode=1, stderr=str(exc)[:300])


class FakeCommandRunner(CommandRunner):
    """In-memory fake runner for unit tests.

    Usage:
        runner = FakeCommandRunner()
        runner.set_result("git pull", CommandResult(returncode=0, stdout="Already up to date."))
        runner.set_result("systemctl", CommandResult(returncode=0))
    """

    def __init__(self) -> None:
        self._results: Dict[str, CommandResult] = {}
        self.calls: List[Dict[str, Any]] = []
        self._default_result = CommandResult(returncode=0, stdout="", stderr="")

    def set_result(self, cmd_pattern: str, result: CommandResult) -> None:
        """Register a result for commands matching cmd_pattern (substring match)."""
        self._results[cmd_pattern] = result

    def set_default_result(self, result: CommandResult) -> None:
        """Set the default result for unmatched commands."""
        self._default_result = result

    def run(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> CommandResult:
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "timeout": timeout})
        cmd_str = " ".join(cmd)
        # Longest matching pattern wins
        match = None
        match_len = -1
        for pattern, result in self._results.items():
            if pattern in cmd_str and len(pattern) > match_len:
                match = result
                match_len = len(pattern)
        return match if match is not None else self._default_result


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class HostConfig:
    """A registered deployment host with its policy."""

    hostname: str
    alias: str = ""
    policy: str = "safe"           # safe | operator | trusted
    allowed_paths: List[str] = field(default_factory=lambda: ["/home"])
    allowed_services: List[str] = field(default_factory=list)
    requires_backup: bool = True
    health_url: str = ""           # URL for post-deploy health check
    ssh_user: str = ""
    ssh_port: int = 22

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HostConfig":
        return cls(
            hostname=data.get("hostname", ""),
            alias=data.get("alias", ""),
            policy=data.get("policy", "safe"),
            allowed_paths=data.get("allowed_paths", ["/home"]),
            allowed_services=data.get("allowed_services", []),
            requires_backup=data.get("requires_backup", True),
            health_url=data.get("health_url", ""),
            ssh_user=data.get("ssh_user", ""),
            ssh_port=int(data.get("ssh_port", 22) or 22),
        )


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

# What actions are permitted per policy tier
_POLICY_ACTIONS: Dict[str, List[str]] = {
    "safe": ["status", "logs", "health", "list"],
    "operator": ["status", "logs", "health", "list", "restart", "deploy"],
    "trusted": ["status", "logs", "health", "list", "restart", "deploy", "shell", "backup"],
}

_VALID_POLICIES = ("safe", "operator", "trusted")


def check_action_allowed(policy: str, action: str) -> Dict[str, Any]:
    """Return whether *action* is permitted under *policy*."""
    allowed_actions = _POLICY_ACTIONS.get(policy, _POLICY_ACTIONS["safe"])
    allowed = action in allowed_actions
    return {
        "policy": policy,
        "action": action,
        "allowed": allowed,
        "reason": (
            f"action '{action}' is permitted under policy '{policy}'"
            if allowed
            else f"action '{action}' is not permitted under policy '{policy}'; "
                 f"allowed: {allowed_actions}"
        ),
        "allowed_actions": allowed_actions,
    }


# ---------------------------------------------------------------------------
# DevOpsManager
# ---------------------------------------------------------------------------

class DevOpsManager:
    """Manages host registry, deploy flows, and smoke tests."""

    #: Relative path inside project root for the host registry JSON.
    _REGISTRY_FILE = ".igris/devops_hosts.json"

    def __init__(
        self,
        project_root: str,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self._registry_path = self.project_root / self._REGISTRY_FILE
        self._hosts: Dict[str, HostConfig] = {}
        # PR 3: injectable runner for tests; defaults to real subprocess runner
        self._runner: CommandRunner = runner or LocalCommandRunner()
        self._load_registry()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_registry(self) -> None:
        """Load hosts from the on-disk JSON file (if present)."""
        if self._registry_path.exists():
            try:
                raw = json.loads(self._registry_path.read_text(encoding="utf-8"))
                for entry in raw.get("hosts", []):
                    h = HostConfig.from_dict(entry)
                    self._hosts[h.hostname] = h
            except Exception:
                pass  # corrupt file → start with empty registry

    def _save_registry(self) -> None:
        """Persist the host registry to disk."""
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"hosts": [h.to_dict() for h in self._hosts.values()]}
        self._registry_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Host registry API
    # ------------------------------------------------------------------

    def list_hosts(self) -> List[Dict[str, Any]]:
        """Return all registered hosts as dicts."""
        return [h.to_dict() for h in self._hosts.values()]

    def get_host(self, hostname: str) -> Optional[HostConfig]:
        """Return a registered host or None."""
        return self._hosts.get(hostname)

    def register_host(self, config: HostConfig) -> Dict[str, Any]:
        """Register (or update) a host.  Persists immediately."""
        if config.policy not in _VALID_POLICIES:
            return {
                "registered": False,
                "hostname": config.hostname,
                "error": f"invalid policy '{config.policy}'; must be one of {_VALID_POLICIES}",
            }
        self._hosts[config.hostname] = config
        self._save_registry()
        return {"registered": True, "hostname": config.hostname, "policy": config.policy}

    def remove_host(self, hostname: str) -> Dict[str, Any]:
        """Remove a host from the registry."""
        if hostname not in self._hosts:
            return {"removed": False, "hostname": hostname, "error": "host not found"}
        del self._hosts[hostname]
        self._save_registry()
        return {"removed": True, "hostname": hostname}

    def check_policy(self, hostname: str, action: str) -> Dict[str, Any]:
        """Check whether *action* is allowed on *hostname*."""
        host = self._hosts.get(hostname)
        if host is None:
            return {
                "allowed": False,
                "hostname": hostname,
                "action": action,
                "reason": f"host '{hostname}' is not registered",
            }
        result = check_action_allowed(host.policy, action)
        result["hostname"] = hostname
        return result

    # ------------------------------------------------------------------
    # Preflight check
    # ------------------------------------------------------------------

    def run_preflight(
        self,
        hostname: Optional[str] = None,
        min_disk_pct_free: int = 10,
        runner: Optional[CommandRunner] = None,
    ) -> Dict[str, Any]:
        """Run pre-deploy preflight checks locally.

        Checks:
        - Disk space (df on project root volume)
        - Git working tree state (clean / dirty)
        - Service reachability (nc port 7778)

        Returns a dict with individual check results and an overall ``ok`` flag.
        """
        effective_runner = runner or self._runner
        checks: Dict[str, Any] = {}
        ts = time.time()

        # 1. Disk space
        try:
            _r = effective_runner.run(
                ["df", "-P", str(self.project_root)],
                timeout=5,
            )
            if _r.ok:
                lines = _r.stdout.strip().splitlines()
                if len(lines) >= 2:
                    parts = lines[1].split()
                    use_pct_str = parts[4].rstrip("%") if len(parts) > 4 else "100"
                    used_pct = int(use_pct_str)
                    free_pct = 100 - used_pct
                    checks["disk"] = {
                        "ok": free_pct >= min_disk_pct_free,
                        "used_pct": used_pct,
                        "free_pct": free_pct,
                        "min_free_required": min_disk_pct_free,
                    }
                else:
                    checks["disk"] = {"ok": False, "error": "could not parse df output"}
            else:
                checks["disk"] = {"ok": False, "error": _r.stderr.strip()[:200]}
        except Exception as exc:
            checks["disk"] = {"ok": False, "error": str(exc)[:200]}

        # 2. Git working-tree state
        try:
            _g = effective_runner.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.project_root),
                timeout=5,
            )
            is_clean = _g.ok and not _g.stdout.strip()
            checks["git"] = {"ok": True, "clean": is_clean, "dirty": not is_clean}
        except Exception as exc:
            checks["git"] = {"ok": False, "error": str(exc)[:200]}

        # 3. IGRIS service reachability
        try:
            _nc = effective_runner.run(
                ["nc", "-z", "-w", "2", "localhost", "7778"],
                timeout=5,
            )
            reachable = _nc.ok
            checks["service"] = {
                "ok": True,  # non-blocking: just report, don't fail preflight
                "reachable": reachable,
                "port": 7778,
            }
        except Exception as exc:
            checks["service"] = {"ok": True, "reachable": False, "error": str(exc)[:200]}

        overall_ok = all(c.get("ok", False) for c in checks.values())
        return {
            "ok": overall_ok,
            "hostname": hostname or "localhost",
            "timestamp": ts,
            "checks": checks,
        }

    # ------------------------------------------------------------------
    # Postcheck
    # ------------------------------------------------------------------

    def run_postcheck(
        self,
        hostname: Optional[str] = None,
        health_url: str = "",
        runner: Optional[CommandRunner] = None,
    ) -> Dict[str, Any]:
        """Post-deploy verification.

        Checks:
        - Service reachability (port 7778)
        - HTTP health endpoint (if health_url given)

        Returns a dict with results and an overall ``ok`` flag.
        """
        effective_runner = runner or self._runner
        checks: Dict[str, Any] = {}

        # Service port
        try:
            _nc = effective_runner.run(
                ["nc", "-z", "-w", "3", "localhost", "7778"],
                timeout=6,
            )
            checks["service"] = {
                "ok": _nc.ok,
                "port": 7778,
                "reachable": _nc.ok,
            }
        except Exception as exc:
            checks["service"] = {"ok": False, "error": str(exc)[:200]}

        # HTTP health endpoint
        if health_url:
            smoke = self.run_smoke_test(health_url)
            checks["http_health"] = {
                "ok": smoke["ok"],
                "url": health_url,
                "status_code": smoke.get("status_code"),
                "response_time_ms": smoke.get("response_time_ms"),
            }

        overall_ok = all(c.get("ok", False) for c in checks.values())
        return {
            "ok": overall_ok,
            "hostname": hostname or "localhost",
            "checks": checks,
        }

    # ------------------------------------------------------------------
    # Deploy flow
    # ------------------------------------------------------------------

    #: Valid deploy strategies
    VALID_STRATEGIES = frozenset({
        "git_pull_restart", "systemd_app", "docker_compose", "static_nginx", "dry_run",
    })

    def run_deploy(
        self,
        strategy: str = "git_pull_restart",
        hostname: Optional[str] = None,
        health_url: str = "",
        dry_run: bool = False,
        min_disk_pct_free: int = 10,
        service_name: str = "igris",
        compose_file: str = "docker-compose.yml",
        nginx_webroot: str = "/var/www/html",
        auto_rollback: bool = True,
    ) -> Dict[str, Any]:
        """Execute a deploy cycle: preflight → snapshot → action → postcheck → rollback.

        PR 3 additions:
        - Strategies: git_pull_restart | systemd_app | docker_compose | static_nginx | dry_run
        - Snapshot pre-deploy SHA for rollback reference
        - auto_rollback: if postcheck fails after action, run_rollback() automatically

        Returns a full deploy report.
        """
        report: Dict[str, Any] = {
            "strategy": strategy,
            "hostname": hostname or "localhost",
            "dry_run": dry_run,
            "timestamp": time.time(),
            "auto_rollback": auto_rollback,
        }

        if strategy not in self.VALID_STRATEGIES:
            report["deployed"] = False
            report["abort_reason"] = f"unknown strategy: {strategy!r}; valid: {sorted(self.VALID_STRATEGIES)}"
            return report

        host_cfg = self._hosts.get(hostname) if hostname else None
        if host_cfg is not None:
            policy = check_action_allowed(host_cfg.policy, "deploy")
            report["policy"] = {
                "hostname": host_cfg.hostname,
                "allowed": policy["allowed"],
                "reason": policy["reason"],
            }
            if not policy["allowed"]:
                report["deployed"] = False
                report["abort_reason"] = policy["reason"]
                return report
        runner = self._effective_runner(host_cfg)

        # Preflight
        preflight = self.run_preflight(
            hostname=hostname,
            min_disk_pct_free=min_disk_pct_free,
            runner=runner,
        )
        report["preflight"] = preflight
        if not preflight["ok"]:
            report["deployed"] = False
            report["abort_reason"] = "preflight failed"
            return report

        if dry_run or strategy == "dry_run":
            report["deployed"] = False
            report["note"] = "dry_run: preflight passed, no action taken"
            report["dry_run_evidence"] = self._build_dry_run_evidence(
                strategy=strategy,
                hostname=hostname,
                health_url=health_url,
                host_cfg=host_cfg,
                runner=runner,
            )
            return report

        # Snapshot pre-deploy git SHA for rollback
        pre_sha_r = runner.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.project_root),
            timeout=5,
        )
        pre_deploy_sha = pre_sha_r.stdout.strip() if pre_sha_r.ok else ""
        report["pre_deploy_sha"] = pre_deploy_sha

        # Deploy action
        action_result = self._run_deploy_strategy(
            strategy=strategy,
            service_name=service_name,
            compose_file=compose_file,
            nginx_webroot=nginx_webroot,
            runner=runner,
            host_cfg=host_cfg,
        )
        report["action"] = action_result
        action_ok = all(v.get("ok", False) for v in action_result.values() if isinstance(v, dict))
        report["deployed"] = action_ok

        # Postcheck (only if action succeeded)
        if action_ok:
            postcheck = self.run_postcheck(
                hostname=hostname,
                health_url=health_url,
                runner=runner,
            )
            report["postcheck"] = postcheck
            report["postcheck_ok"] = postcheck["ok"]
            # PR 3: auto-rollback if postcheck fails
            if not postcheck["ok"] and auto_rollback and pre_deploy_sha:
                rollback = self.run_rollback(
                    strategy=strategy,
                    pre_deploy_sha=pre_deploy_sha,
                    service_name=service_name,
                    runner=runner,
                    host_cfg=host_cfg,
                )
                report["rollback"] = rollback
                report["deployed"] = False
                report["abort_reason"] = "postcheck failed; auto-rollback executed"
        else:
            report["postcheck"] = None
            report["postcheck_ok"] = False

        return report

    def _run_deploy_strategy(
        self,
        strategy: str,
        service_name: str = "igris",
        compose_file: str = "docker-compose.yml",
        nginx_webroot: str = "/var/www/html",
        runner: Optional[CommandRunner] = None,
        host_cfg: Optional[HostConfig] = None,
    ) -> Dict[str, Any]:
        """Execute the deploy action for the given strategy.

        Returns a dict of step_name → {ok, output} pairs.
        """
        action: Dict[str, Any] = {}
        cwd = str(self.project_root)
        effective_runner = runner or self._runner

        def _blocked(msg: str) -> Dict[str, Any]:
            return {"policy_blocked": {"ok": False, "output": msg[:300]}}

        if host_cfg is not None:
            if not self._path_allowed(host_cfg, cwd):
                return _blocked(f"project root not allowed by host policy: {cwd}")
            if strategy == "static_nginx" and not self._path_allowed(host_cfg, nginx_webroot):
                return _blocked(f"nginx_webroot not allowed by host policy: {nginx_webroot}")
            if strategy == "docker_compose" and not self._service_allowed(host_cfg, "docker"):
                return _blocked("service docker is not allowed by host policy")
            if strategy == "static_nginx" and not self._service_allowed(host_cfg, "nginx"):
                return _blocked("service nginx is not allowed by host policy")
            if strategy in ("git_pull_restart", "systemd_app") and not self._service_allowed(host_cfg, service_name):
                return _blocked(f"service {service_name!r} is not allowed by host policy")

        if strategy in ("git_pull_restart", "systemd_app"):
            # Step 1: git pull
            r_pull = effective_runner.run(["git", "pull", "--ff-only"], cwd=cwd, timeout=60)
            action["git_pull"] = {
                "ok": r_pull.ok,
                "output": (r_pull.stdout + r_pull.stderr)[:500],
            }
            if not r_pull.ok:
                return action

            # Step 2: restart service
            svc = service_name if strategy == "systemd_app" else "igris"
            r_restart = effective_runner.run(
                ["systemctl", "restart", svc], timeout=30
            )
            action["restart"] = {
                "ok": r_restart.ok,
                "service": svc,
                "output": r_restart.stderr[:300],
            }

        elif strategy == "docker_compose":
            # Step 1: git pull
            r_pull = effective_runner.run(["git", "pull", "--ff-only"], cwd=cwd, timeout=60)
            action["git_pull"] = {
                "ok": r_pull.ok,
                "output": (r_pull.stdout + r_pull.stderr)[:500],
            }
            if not r_pull.ok:
                return action

            # Step 2: docker-compose up
            compose_cmd = ["docker-compose", "-f", compose_file, "up", "-d", "--build"]
            r_compose = effective_runner.run(compose_cmd, cwd=cwd, timeout=120)
            action["docker_compose_up"] = {
                "ok": r_compose.ok,
                "output": (r_compose.stdout + r_compose.stderr)[:500],
            }

        elif strategy == "static_nginx":
            # Step 1: git pull
            r_pull = effective_runner.run(["git", "pull", "--ff-only"], cwd=cwd, timeout=60)
            action["git_pull"] = {
                "ok": r_pull.ok,
                "output": (r_pull.stdout + r_pull.stderr)[:500],
            }
            if not r_pull.ok:
                return action

            # Step 2: copy files to webroot (rsync)
            r_sync = effective_runner.run(
                ["rsync", "-a", "--delete", "dist/", nginx_webroot + "/"],
                cwd=cwd,
                timeout=30,
            )
            action["rsync"] = {
                "ok": r_sync.ok,
                "output": (r_sync.stdout + r_sync.stderr)[:300],
            }
            if not r_sync.ok:
                return action

            # Step 3: nginx reload
            r_nginx = effective_runner.run(["nginx", "-s", "reload"], timeout=10)
            action["nginx_reload"] = {
                "ok": r_nginx.ok,
                "output": r_nginx.stderr[:200],
            }

        return action

    def run_rollback(
        self,
        strategy: str = "git_pull_restart",
        pre_deploy_sha: str = "",
        service_name: str = "igris",
        compose_file: str = "docker-compose.yml",
        runner: Optional[CommandRunner] = None,
        host_cfg: Optional[HostConfig] = None,
    ) -> Dict[str, Any]:
        """Roll back a deploy by resetting to pre_deploy_sha and restarting.

        PR 3: structured rollback tied to deploy strategy.
        Returns a dict with rollback steps and overall ok flag.
        """
        result: Dict[str, Any] = {
            "strategy": strategy,
            "pre_deploy_sha": pre_deploy_sha,
            "timestamp": time.time(),
        }
        cwd = str(self.project_root)
        effective_runner = runner or self._runner
        steps: Dict[str, Any] = {}

        if not pre_deploy_sha:
            result["ok"] = False
            result["error"] = "no pre_deploy_sha provided; cannot rollback"
            return result

        # Git reset to pre-deploy SHA
        r_reset = effective_runner.run(
            ["git", "reset", "--hard", pre_deploy_sha],
            cwd=cwd,
            timeout=15,
        )
        steps["git_reset"] = {
            "ok": r_reset.ok,
            "sha": pre_deploy_sha,
            "output": (r_reset.stdout + r_reset.stderr)[:300],
        }

        if not r_reset.ok:
            result["steps"] = steps
            result["ok"] = False
            result["error"] = "git reset failed; manual intervention required"
            return result

        # Restart service (strategy-specific)
        if strategy in ("git_pull_restart", "systemd_app"):
            if host_cfg is not None and not self._service_allowed(host_cfg, service_name):
                steps["restart"] = {"ok": False, "service": service_name, "output": "policy blocked"}
                result["steps"] = steps
                result["ok"] = False
                return result
            r_restart = effective_runner.run(["systemctl", "restart", service_name], timeout=30)
            steps["restart"] = {
                "ok": r_restart.ok,
                "service": service_name,
                "output": r_restart.stderr[:200],
            }
        elif strategy == "docker_compose":
            if host_cfg is not None and not self._service_allowed(host_cfg, "docker"):
                steps["docker_compose_up"] = {"ok": False, "output": "policy blocked"}
                result["steps"] = steps
                result["ok"] = False
                return result
            r_compose = effective_runner.run(
                ["docker-compose", "-f", compose_file, "up", "-d"],
                cwd=cwd,
                timeout=120,
            )
            steps["docker_compose_up"] = {
                "ok": r_compose.ok,
                "output": (r_compose.stdout + r_compose.stderr)[:300],
            }
        elif strategy == "static_nginx":
            if host_cfg is not None and not self._service_allowed(host_cfg, "nginx"):
                steps["nginx_reload"] = {"ok": False, "output": "policy blocked"}
                result["steps"] = steps
                result["ok"] = False
                return result
            r_nginx = effective_runner.run(["nginx", "-s", "reload"], timeout=10)
            steps["nginx_reload"] = {"ok": r_nginx.ok, "output": r_nginx.stderr[:200]}

        result["steps"] = steps
        result["ok"] = all(v.get("ok", False) for v in steps.values())
        return result

    def _effective_runner(self, host_cfg: Optional[HostConfig]) -> CommandRunner:
        if host_cfg is None:
            return self._runner
        host = str(host_cfg.hostname or "").strip().lower()
        if host in {"", "localhost", "127.0.0.1"}:
            return self._runner
        return SSHCommandRunner(
            hostname=host_cfg.hostname,
            user=host_cfg.ssh_user,
            port=host_cfg.ssh_port,
        )

    @staticmethod
    def _service_allowed(host_cfg: HostConfig, service: str) -> bool:
        allowed = {str(s).strip().lower() for s in host_cfg.allowed_services or [] if str(s).strip()}
        if not allowed:
            return True
        return str(service or "").strip().lower() in allowed

    @staticmethod
    def _path_allowed(host_cfg: HostConfig, path: str) -> bool:
        norm = str(path or "").strip()
        if not norm:
            return False
        allowed = [str(p).strip() for p in host_cfg.allowed_paths or [] if str(p).strip()]
        if not allowed:
            return True
        return any(norm.startswith(prefix) for prefix in allowed)

    def _build_dry_run_evidence(
        self,
        *,
        strategy: str,
        hostname: Optional[str],
        health_url: str,
        host_cfg: Optional[HostConfig],
        runner: CommandRunner,
    ) -> Dict[str, Any]:
        target = hostname or "localhost"
        planned: List[str] = []
        if strategy in ("git_pull_restart", "systemd_app"):
            planned = ["git pull --ff-only", "systemctl restart igris"]
        elif strategy == "docker_compose":
            planned = ["git pull --ff-only", "docker-compose -f docker-compose.yml up -d --build"]
        elif strategy == "static_nginx":
            planned = ["git pull --ff-only", "rsync dist/ ...", "nginx -s reload"]

        nginx = runner.run(["nginx", "-t"], timeout=8)
        docker = runner.run(["docker", "ps", "--format", "{{.Names}}"], timeout=8)
        ssl_probe: Dict[str, Any] = {"available": False}
        if health_url.startswith("https://"):
            ssl_probe["available"] = True
            ssl_probe["target"] = health_url
        browser_url = health_url or "http://localhost:7778/api/ping"
        browser = self.run_smoke_test(url=browser_url)

        return {
            "target_host": target,
            "planned_commands": planned,
            "policy_enforced": bool(host_cfg is not None),
            "allowed_paths": list(host_cfg.allowed_paths) if host_cfg else [],
            "allowed_services": list(host_cfg.allowed_services) if host_cfg else [],
            "nginx": nginx.to_dict(),
            "docker": docker.to_dict(),
            "ssl": ssl_probe,
            "browser": browser,
        }

    # ------------------------------------------------------------------
    # Smoke test
    # ------------------------------------------------------------------

    def run_smoke_test(self, url: str = "") -> Dict[str, Any]:
        """HTTP smoke test: GET *url* and return evidence.

        Falls back to ``http://localhost:7778/api/ping`` if no URL is given.
        Never raises — all failures are captured in the result dict.
        """
        target = url.strip() or "http://localhost:7778/api/ping"
        start = time.time()
        result: Dict[str, Any] = {
            "url": target,
            "ok": False,
            "status_code": None,
            "response_time_ms": None,
            "body_preview": "",
            "timestamp": start,
        }
        try:
            req = urllib.request.Request(
                target,
                headers={"User-Agent": "IGRIS-DevOps-Smoke/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
                elapsed_ms = int((time.time() - start) * 1000)
                result.update(
                    ok=200 <= resp.status < 400,
                    status_code=resp.status,
                    response_time_ms=elapsed_ms,
                    body_preview=body[:500],
                )
        except urllib.error.HTTPError as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            result.update(
                ok=False,
                status_code=exc.code,
                response_time_ms=elapsed_ms,
                error=str(exc)[:200],
            )
        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            result.update(
                ok=False,
                response_time_ms=elapsed_ms,
                error=str(exc)[:200],
            )
        return result
