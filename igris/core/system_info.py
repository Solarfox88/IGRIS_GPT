"""Safe, read-only system information for IGRIS.

Exposes OS, Python, CPU, memory, disk, Ollama status, and IGRIS config
without revealing environment variables, private IPs, or secrets.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


def get_system_info(
    project_root: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> Dict[str, Any]:
    """Collect safe system information.

    Never exposes:
    - Environment variables
    - Private/public IP addresses
    - Secrets, tokens, or API keys
    - Full network interface dump
    """
    info: Dict[str, Any] = {}

    # OS / platform
    info["os"] = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
    }

    # Python
    info["python"] = {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
    }

    # Process
    info["process"] = {
        "pid": os.getpid(),
    }

    # CPU
    cpu_count = os.cpu_count()
    info["cpu"] = {
        "count": cpu_count if cpu_count else "unknown",
    }

    # Memory (best-effort, no psutil required)
    info["memory"] = _get_memory_info()

    # Disk usage for project root
    info["disk"] = _get_disk_info(project_root)

    # Uptime (process uptime, not system)
    info["uptime"] = _get_uptime()

    # Container detection
    info["container"] = {
        "likely_container": _detect_container(),
    }

    # Ollama status
    info["ollama"] = _get_ollama_status()

    # IGRIS config (safe subset)
    info["igris"] = {
        "host": host,
        "port": port,
        "project_root": str(project_root) if project_root else None,
    }

    # Network summary (conservative)
    info["network"] = {
        "server_bind": f"{host}:{port}",
        "external_access_possible": host in ("0.0.0.0", "::"),
    }

    return info


def _get_memory_info() -> Dict[str, Any]:
    """Get memory info without psutil."""
    mem: Dict[str, Any] = {}
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            for line in lines:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    mem["total_mb"] = round(kb / 1024)
                elif line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    mem["available_mb"] = round(kb / 1024)
            if "total_mb" in mem and "available_mb" in mem:
                mem["used_percent"] = round(
                    (1 - mem["available_mb"] / mem["total_mb"]) * 100, 1
                )
        else:
            mem["note"] = "Memory details available on Linux only"
    except Exception:
        mem["note"] = "Could not read memory info"
    return mem


def _get_disk_info(project_root: Optional[str] = None) -> Dict[str, Any]:
    """Get disk usage for project root."""
    disk: Dict[str, Any] = {}
    try:
        path = project_root or "."
        usage = os.statvfs(path) if hasattr(os, "statvfs") else None
        if usage:
            total = usage.f_frsize * usage.f_blocks
            free = usage.f_frsize * usage.f_bavail
            used = total - free
            disk["total_gb"] = round(total / (1024 ** 3), 1)
            disk["free_gb"] = round(free / (1024 ** 3), 1)
            disk["used_gb"] = round(used / (1024 ** 3), 1)
            disk["used_percent"] = round((used / total) * 100, 1) if total > 0 else 0
            disk["path"] = str(path)
        else:
            disk["note"] = "Disk info not available on this platform"
    except Exception:
        disk["note"] = "Could not read disk info"
    return disk


_process_start_time = time.time()


def _get_uptime() -> Dict[str, Any]:
    """Process uptime."""
    elapsed = time.time() - _process_start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    return {
        "process_uptime_seconds": round(elapsed),
        "formatted": f"{hours}h {minutes}m {seconds}s",
    }


def _detect_container() -> bool:
    """Best-effort container detection."""
    # Check /.dockerenv
    if Path("/.dockerenv").exists():
        return True
    # Check cgroup
    try:
        with open("/proc/1/cgroup") as f:
            content = f.read()
        if "docker" in content or "kubepods" in content or "containerd" in content:
            return True
    except Exception:
        pass
    # Check container env hint (safe — only checks existence, not value)
    if os.environ.get("container") or os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    return False


def _get_ollama_status() -> Dict[str, Any]:
    """Check Ollama availability without making real LLM calls."""
    status: Dict[str, Any] = {
        "reachable": False,
        "model_configured": None,
        "model_available": False,
    }
    try:
        from igris.models.config import CONFIG
        status["model_configured"] = getattr(CONFIG, "local_llm_model", None)
    except Exception:
        pass

    try:
        import socket
        import urllib.request
        base = os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434")
        # Quick TCP check before HTTP to avoid long hangs
        host_part = base.replace("http://", "").replace("https://", "")
        sock_host, sock_port = host_part.split(":") if ":" in host_part else (host_part, "11434")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((sock_host, int(sock_port)))
        sock.close()
        if result != 0:
            raise ConnectionError("Ollama not reachable")
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        req.add_header("User-Agent", "IGRIS_GPT/system_info")
        with urllib.request.urlopen(req, timeout=1) as resp:
            if resp.status == 200:
                status["reachable"] = True
                import json
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                configured = status.get("model_configured")
                if configured:
                    status["model_available"] = any(
                        configured in m or configured.replace("-", "") in m
                        for m in models
                    )
    except Exception:
        pass

    return status


def get_safe_system_summary() -> str:
    """One-line safe summary for chat responses."""
    info = get_system_info()
    os_info = info.get("os", {})
    cpu = info.get("cpu", {})
    mem = info.get("memory", {})
    parts = [
        f"{os_info.get('system', '?')} {os_info.get('release', '')}",
        f"Python {info.get('python', {}).get('version', '?')}",
        f"{cpu.get('count', '?')} CPUs",
    ]
    if "total_mb" in mem:
        parts.append(f"{mem['total_mb']}MB RAM")
    return " | ".join(parts)
