# Safe System Info — Sprint 35

**v0.6 Human-Usable Console**

## Overview

IGRIS can now answer basic machine/resource questions without free shell access. The `/api/system/info` endpoint provides safe, read-only system information with no secrets, no environment variable dumps, and no private IP exposure.

## Endpoint

### GET /api/system/info

Returns a JSON object with sections:

| Section | Contents |
|---------|----------|
| `os` | System, release, version, machine, platform |
| `python` | Version, implementation, executable path |
| `process` | PID |
| `cpu` | CPU count |
| `memory` | Total/available MB, used percent (Linux; graceful fallback elsewhere) |
| `disk` | Total/free/used GB, used percent for project root |
| `uptime` | Process uptime in seconds and formatted string |
| `container` | Whether running in Docker/Kubernetes (best-effort) |
| `ollama` | Reachable, model configured, model available |
| `igris` | Host, port, project root |
| `network` | Server bind address, external access flag |

### Example Response

```json
{
  "os": {"system": "Linux", "release": "5.15.0", ...},
  "python": {"version": "3.12.8", ...},
  "process": {"pid": 12345},
  "cpu": {"count": 4},
  "memory": {"total_mb": 8192, "available_mb": 5120, "used_percent": 37.5},
  "disk": {"total_gb": 50.0, "free_gb": 30.2, "used_gb": 19.8, "used_percent": 39.6},
  "uptime": {"process_uptime_seconds": 3600, "formatted": "1h 0m 0s"},
  "container": {"likely_container": false},
  "ollama": {"reachable": false, "model_configured": "phi4-mini", "model_available": false},
  "igris": {"host": "127.0.0.1", "port": 8000, "project_root": "/home/user/project"},
  "network": {"server_bind": "127.0.0.1:8000", "external_access_possible": false}
}
```

## Command ID

`system_info` is registered in the safe commands allowlist and can be executed via the terminal tab.

## Safety

**Never exposed:**
- Environment variables
- Private/public IP addresses
- API keys, tokens, or secrets
- Full network interface list
- Home directory contents
- Process environment

**Conservative defaults:**
- Network section only shows bind address and external access flag
- Container detection uses best-effort (/.dockerenv, cgroup, env hints)
- Memory/disk gracefully fall back to a note if unavailable
- Ollama check uses 2-second timeout, non-blocking

## Chat Integration

The `machine_info` intent now includes `/api/system/info` as the primary action:
- Grounded response lists it first
- Suggested actions include "System Info" button
- No free shell suggested

The `network_info` intent also references `/api/system/info` for bind address info.
