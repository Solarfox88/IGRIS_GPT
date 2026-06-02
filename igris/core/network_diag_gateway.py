"""Safe, gated network diagnostics gateway (#950).

Design goals:
- allow only explicitly scoped hosts/domains by default;
- provide read-only DNS/TCP/HTTP/port/latency/traceroute diagnostics;
- degrade cleanly when traceroute is unavailable;
- redact tokens/secrets from audit payloads;
- keep tests fake-only.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


@runtime_checkable
class NetworkDiagRunner(Protocol):
    def dns_lookup(self, host: str) -> List[str]: ...
    def tcp_connect(self, host: str, port: int, timeout: float) -> Dict[str, Any]: ...
    def http_latency(self, url: str, timeout: float) -> Dict[str, Any]: ...
    def traceroute(self, host: str, max_hops: int, timeout: float) -> Dict[str, Any]: ...


class LocalNetworkDiagRunner:
    """Best-effort local runner using stdlib only."""

    def dns_lookup(self, host: str) -> List[str]:
        infos = socket.getaddrinfo(host, None)
        addrs = []
        for info in infos:
            addr = info[4][0]
            if addr not in addrs:
                addrs.append(addr)
        return addrs

    def tcp_connect(self, host: str, port: int, timeout: float) -> Dict[str, Any]:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {"reachable": True, "latency_ms": latency_ms, "port": port, "host": host}

    def http_latency(self, url: str, timeout: float) -> Dict[str, Any]:
        t0 = time.monotonic()
        req = Request(url, method="GET")
        req.add_header("User-Agent", "IGRIS_NetworkDiagGateway/1.0")
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read(1024)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {
                "status_code": resp.status,
                "latency_ms": latency_ms,
                "body_bytes": len(body),
                "url": url,
            }

    def traceroute(self, host: str, max_hops: int, timeout: float) -> Dict[str, Any]:
        for cmd in (["traceroute", "-m", str(max_hops), host], ["tracepath", host]):
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                if proc.returncode == 0 or proc.stdout:
                    return {
                        "available": True,
                        "command": cmd[0],
                        "returncode": proc.returncode,
                        "output": proc.stdout.strip(),
                    }
            except FileNotFoundError:
                continue
            except Exception as exc:  # noqa: BLE001
                return {"available": False, "status": "degraded", "reason": str(exc)}
        return {"available": False, "status": "degraded", "reason": "traceroute unavailable"}


@dataclass
class NetworkDiagGateway:
    """Safe network diagnostics gateway."""

    dry_run: bool = False
    runner: Optional[NetworkDiagRunner] = None
    default_allowed_hosts: List[str] = field(default_factory=lambda: ["127.0.0.1", "localhost", "::1"])
    default_allowed_domains: List[str] = field(default_factory=list)
    audit_log: List[Dict[str, Any]] = field(default_factory=list)
    audit_path: str = ".igris/network_diag_audit.jsonl"

    def _runner(self) -> NetworkDiagRunner:
        return self.runner or LocalNetworkDiagRunner()

    @staticmethod
    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for key, raw in value.items():
                key_str = str(key).lower()
                if any(token in key_str for token in ("token", "secret", "password", "key", "auth")):
                    out[str(key)] = "[REDACTED]"
                else:
                    out[str(key)] = NetworkDiagGateway._redact(raw)
            return out
        if isinstance(value, list):
            return [NetworkDiagGateway._redact(item) for item in value]
        if isinstance(value, str) and "://" in value:
            parsed = urlparse(value)
            if parsed.query:
                query_parts = []
                for chunk in parsed.query.split("&"):
                    if "=" in chunk:
                        key, _ = chunk.split("=", 1)
                        key_norm = key.lower()
                        if any(token in key_norm for token in ("token", "secret", "password", "key", "auth")):
                            query_parts.append(f"{key}=[REDACTED]")
                        else:
                            query_parts.append(chunk)
                    else:
                        query_parts.append(chunk)
                parsed = parsed._replace(query="&".join(query_parts))
            return urlunparse(parsed)
        return value

    @staticmethod
    def _normalize_list(values: Optional[Iterable[str]], fallback: List[str]) -> List[str]:
        items = [str(v).strip().lower() for v in (values or fallback) if str(v).strip()]
        return sorted(dict.fromkeys(items))

    def _audit(self, action: str, target: str, status: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = {
            "id": f"net-{len(self.audit_log) + 1:04d}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "target": self._redact(target),
            "status": status,
            "details": self._redact(details or {}),
            "dry_run": self.dry_run,
        }
        self.audit_log.append(entry)
        try:
            path = Path(self.audit_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            logger.warning("NetworkDiagGateway audit write failed for %s", action)
        logger.info("NetworkDiagGateway audit: %s", entry)
        return entry

    def _target_host(self, host_or_url: str) -> str:
        if "://" in host_or_url:
            parsed = urlparse(host_or_url)
            return parsed.hostname or host_or_url
        return host_or_url.split(":", 1)[0]

    def _target_allowed(
        self,
        host_or_url: str,
        *,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> bool:
        host = self._target_host(host_or_url).strip().lower()
        host_list = self._normalize_list(allowed_hosts, self.default_allowed_hosts)
        domain_list = self._normalize_list(allowed_domains, self.default_allowed_domains)
        if host in host_list:
            return True
        return any(host == domain or host.endswith("." + domain) for domain in domain_list)

    def _blocked(self, action: str, target: str, reason: str) -> Dict[str, Any]:
        self._audit(action, target, "BLOCKED", {"reason": reason})
        return {"success": False, "status": "blocked", "reason": reason, "target": target}

    def dns_lookup(
        self,
        host: str,
        *,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        action = "dns.lookup"
        if not self._target_allowed(host, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains):
            return self._blocked(action, host, "host_not_allowed")
        if self.dry_run:
            self._audit(action, host, "DRY_RUN")
            return {"success": True, "dry_run": True, "status": "dry_run", "result": {"host": host, "addresses": []}}
        try:
            addresses = self._runner().dns_lookup(host)
            result = {"host": host, "addresses": addresses}
            self._audit(action, host, "OK", result)
            return {"success": True, "dry_run": False, "status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001
            self._audit(action, host, "FAILED", {"error": str(exc)})
            return {"success": False, "dry_run": False, "status": "failed", "reason": str(exc)}

    def tcp_connect(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 5.0,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        action = "tcp.connect"
        if port < 1 or port > 65535:
            return self._blocked(action, f"{host}:{port}", "port_out_of_range")
        if not self._target_allowed(host, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains):
            return self._blocked(action, f"{host}:{port}", "host_not_allowed")
        if self.dry_run:
            self._audit(action, f"{host}:{port}", "DRY_RUN", {"timeout": timeout})
            return {"success": True, "dry_run": True, "status": "dry_run", "result": {"host": host, "port": port}}
        try:
            result = self._runner().tcp_connect(host, port, timeout)
            self._audit(action, f"{host}:{port}", "OK", result)
            return {"success": True, "dry_run": False, "status": "ok", "result": self._redact(result)}
        except Exception as exc:  # noqa: BLE001
            self._audit(action, f"{host}:{port}", "FAILED", {"error": str(exc)})
            return {"success": False, "dry_run": False, "status": "failed", "reason": str(exc)}

    def http_latency(
        self,
        url: str,
        *,
        timeout: float = 5.0,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        action = "http.latency"
        host = self._target_host(url)
        if not self._target_allowed(host, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains):
            return self._blocked(action, url, "host_not_allowed")
        if self.dry_run:
            self._audit(action, url, "DRY_RUN", {"timeout": timeout})
            return {"success": True, "dry_run": True, "status": "dry_run", "result": {"url": self._redact(url)}}
        try:
            result = self._runner().http_latency(url, timeout)
            self._audit(action, url, "OK", result)
            return {"success": True, "dry_run": False, "status": "ok", "result": self._redact(result)}
        except Exception as exc:  # noqa: BLE001
            self._audit(action, url, "FAILED", {"error": str(exc)})
            return {"success": False, "dry_run": False, "status": "failed", "reason": str(exc)}

    def port_check(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 5.0,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        action = "port.check"
        if port < 1 or port > 65535:
            return self._blocked(action, f"{host}:{port}", "port_out_of_range")
        return self.tcp_connect(host, port, timeout=timeout, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)

    def traceroute(
        self,
        host: str,
        *,
        max_hops: int = 12,
        timeout: float = 10.0,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        action = "traceroute"
        if not self._target_allowed(host, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains):
            return self._blocked(action, host, "host_not_allowed")
        if self.dry_run:
            self._audit(action, host, "DRY_RUN", {"max_hops": max_hops, "timeout": timeout})
            return {"success": True, "dry_run": True, "status": "dry_run", "result": {"host": host, "hops": []}}
        try:
            result = self._runner().traceroute(host, max_hops, timeout)
            if result.get("available") is False or result.get("status") == "degraded":
                self._audit(action, host, "DEGRADED", result)
                return {"success": True, "dry_run": False, "status": "degraded", "result": self._redact(result)}
            self._audit(action, host, "OK", result)
            return {"success": True, "dry_run": False, "status": "ok", "result": self._redact(result)}
        except Exception as exc:  # noqa: BLE001
            self._audit(action, host, "FAILED", {"error": str(exc)})
            return {"success": False, "dry_run": False, "status": "failed", "reason": str(exc)}

    def diagnose(
        self,
        host: str,
        *,
        port: Optional[int] = None,
        url: Optional[str] = None,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        report: Dict[str, Any] = {"host": host, "results": {}}
        report["results"]["dns"] = self.dns_lookup(host, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        if port is not None:
            report["results"]["tcp"] = self.tcp_connect(host, port, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
            report["results"]["port_check"] = self.port_check(host, port, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        if url is not None:
            report["results"]["http_latency"] = self.http_latency(url, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        report["results"]["traceroute"] = self.traceroute(host, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        report["status"] = "dry_run" if self.dry_run else "ok"
        self._audit("diagnose", host, report["status"], report)
        return report

    def inventory(
        self,
        host: str,
        *,
        port: Optional[int] = None,
        url: Optional[str] = None,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Return a scoped inventory of safe diagnostics available for the target."""
        allowed = self._target_allowed(host or url or "", allowed_hosts=allowed_hosts, allowed_domains=allowed_domains)
        inventory = {
            "target": self._redact(host or url or ""),
            "allowed": allowed,
            "allowed_hosts": self._normalize_list(allowed_hosts, self.default_allowed_hosts),
            "allowed_domains": self._normalize_list(allowed_domains, self.default_allowed_domains),
            "checks": {
                "dns": bool(allowed),
                "tcp": bool(allowed and port is not None),
                "http_latency": bool(allowed and url is not None),
                "port_check": bool(allowed and port is not None),
                "traceroute": bool(allowed),
            },
            "provisioning_hooks": {
                "status": "dry_run",
                "available": False,
                "reason": "explicit approval required; backend not configured",
            },
        }
        self._audit("inventory", host or url or "", "OK" if allowed else "BLOCKED", inventory)
        return inventory

    def propose_provisioning_hook(
        self,
        target: str,
        hook: str,
        *,
        approval: bool = False,
        dry_run: bool = True,
        allowed_hosts: Optional[Iterable[str]] = None,
        allowed_domains: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Plan a controlled provisioning hook without executing provisioning."""
        action = "provisioning.hook.propose"
        if not self._target_allowed(target, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains):
            return self._blocked(action, target, "host_not_allowed")
        proposal = {
            "target": self._redact(target),
            "hook": self._redact(hook),
            "dry_run": dry_run,
            "approval_required": True,
            "approved": bool(approval),
            "status": "dry_run" if dry_run or not approval else "blocked",
        }
        if dry_run or not approval:
            self._audit(action, target, "DRY_RUN", proposal)
            return {"success": True, "dry_run": True, "status": "dry_run", "proposal": proposal}
        self._audit(action, target, "BLOCKED", {"reason": "provisioning backend not configured", "proposal": proposal})
        return {
            "success": False,
            "dry_run": False,
            "status": "blocked",
            "reason": "provisioning backend not configured",
            "approval_required": True,
            "proposal": proposal,
        }

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return list(self.audit_log)
