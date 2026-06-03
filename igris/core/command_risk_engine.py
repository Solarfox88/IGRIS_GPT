"""Command Risk Engine v2 — Epic #63.

Governs shell access with multi-level risk classification:
    1. Structured Tool preferred
    2. Template parametrized as second option
    3. Raw shell proposal only as escape hatch, gated

Pipeline for raw shell proposals:
    parse_command → deterministic_classify → contextual_policy →
    llm_risk_review (via Model Orchestrator) → decision

Risk classes: LOW, MEDIUM, HIGH, CRITICAL, UNKNOWN

The LLM Risk Reviewer is advisory only — final decision is always
made by IGRIS Policy Engine, never by the LLM.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from igris.core.safety import redact_secrets


# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------

RISK_LEVELS = ("low", "medium", "high", "critical", "unknown")


# Structured tool registry: explicit, auditable, and extensible.
STRUCTURED_TOOL_REGISTRY: Dict[str, Dict[str, str]] = {
    "service_control": {
        "tool": "structured_service_control",
        "operation": "service_restart",
        "fallback_rationale": "structured service control exists, so raw shell is blocked",
    },
    "service_observability": {
        "tool": "structured_service_observability",
        "operation": "service_logs",
        "fallback_rationale": "structured service observability exists, so raw shell is blocked",
    },
    "container_control": {
        "tool": "structured_container_control",
        "operation": "container_management",
        "fallback_rationale": "structured container control exists, so raw shell is blocked",
    },
    "webserver_control": {
        "tool": "structured_webserver_control",
        "operation": "webserver_management",
        "fallback_rationale": "structured webserver control exists, so raw shell is blocked",
    },
    "filesystem_ops": {
        "tool": "structured_filesystem_ops",
        "operation": "filesystem_inspection",
        "fallback_rationale": "structured filesystem ops exist, so raw shell is blocked",
    },
    "network_ops": {
        "tool": "structured_network_ops",
        "operation": "network_diagnostics",
        "fallback_rationale": "structured network ops exist, so raw shell is blocked",
    },
    "git_ops": {
        "tool": "structured_git_ops",
        "operation": "git_inspection",
        "fallback_rationale": "structured git ops exist, so raw shell is blocked",
    },
    "database_ops": {
        "tool": "structured_database_ops",
        "operation": "database_maintenance",
        "fallback_rationale": "structured database ops exist, so raw shell is blocked",
    },
}


# ---------------------------------------------------------------------------
# Shell parser — recognize command structure and dangerous patterns
# ---------------------------------------------------------------------------

# Dangerous command patterns (deterministic blocklist)
_SUDO_RE = re.compile(r"\b(sudo|su)\b")
_RM_RE = re.compile(r"\brm\b.*(-r|-f|-rf|--recursive|--force)")
_DELETE_RE = re.compile(r"\b(unlink|rmdir|shred)\b")
_CHMOD_RE = re.compile(r"\b(chmod|chown)\b")
_SYSTEMCTL_RE = re.compile(r"\b(systemctl|service|journalctl)\b")
_DOCKER_RE = re.compile(r"\b(docker|docker-compose|docker compose)\b")
_NGINX_RE = re.compile(r"\b(nginx|apache2?|httpd|certbot)\b")
_PKG_RE = re.compile(r"\b(apt|apt-get|dpkg|pip|pip3|npm|pnpm|yarn|cargo)\b")
_GIT_DANGER_RE = re.compile(r"\bgit\b.*\b(push|reset|clean|force)\b")
_FORCE_PUSH_RE = re.compile(r"\bgit\b.*\bpush\b.*(-f|--force|--force-with-lease)")
_CURL_PIPE_RE = re.compile(r"\b(curl|wget)\b.*\|\s*(bash|sh|zsh|python|perl)")
_PIPE_RE = re.compile(r"\|")
_REDIRECT_RE = re.compile(r"[>]{1,2}")
_SUBSHELL_RE = re.compile(r"[\$]\(|`")
_CHAIN_RE = re.compile(r"&&|\|\|")
_ABS_PATH_RE = re.compile(r"(?:^|\s)/(?:etc|usr|var|root|boot|proc|sys|dev)/")
_WILDCARD_RE = re.compile(r"\*")
_NETWORK_RE = re.compile(r"\b(curl|wget|nc|ncat|netcat|ssh|scp|rsync|telnet|ftp)\b")
_DB_RE = re.compile(r"\b(mysql|psql|mongo|redis-cli|sqlite3)\b.*\b(DROP|DELETE|TRUNCATE|ALTER|MIGRATE)\b", re.IGNORECASE)
_DB_CMD_RE = re.compile(r"\b(mysql|psql|mongo|redis-cli|sqlite3)\b")
_FIREWALL_RE = re.compile(r"\b(iptables|ufw|firewalld|firewall-cmd|nftables)\b")
_DNS_RE = re.compile(r"\b(dig|nslookup|host|resolvectl)\b.*\b(update|set|add|delete)\b", re.IGNORECASE)
_ENV_RE = re.compile(r"(\.env|\.secrets|\.pem|\.key|id_rsa|credentials|token|password|api[._]key)", re.IGNORECASE)
_SECRET_ACCESS_RE = re.compile(r"\b(cat|less|more|head|tail|grep|awk|sed)\b.*\.(env|secret|pem|key)", re.IGNORECASE)

# PR 2 additions — patterns previously missing
# Inline code execution: bash -c "...", bash -lc "...", sh -c "...", python -c "..."
_INLINE_EXEC_RE = re.compile(r"\b(bash|sh|zsh|fish|dash|python[23]?|py)\s+-[a-z]*c[a-z]*\b")
# xargs feeding rm (equivalent to rm but bypasses _RM_RE)
_XARGS_RM_RE = re.compile(r"\bxargs\b.*\brm\b|\brm\b.*\bxargs\b")
# find with -delete flag or -exec rm
_FIND_DELETE_RE = re.compile(r"\bfind\b.*(-delete|-exec\s+rm|-exec\s+unlink)")
# Shell metacharacters unsafe in template parameters
_UNSAFE_PARAM_CHARS_RE = re.compile(r'[;&|`$<>(){}\[\]\\!#~\n\r]')


@dataclass
class ParsedCommand:
    """Parsed representation of a shell command."""
    raw: str = ""
    executable: str = ""
    args: List[str] = field(default_factory=list)
    has_sudo: bool = False
    has_rm: bool = False
    has_delete: bool = False
    has_chmod: bool = False
    has_systemctl: bool = False
    has_docker: bool = False
    has_nginx: bool = False
    has_package_manager: bool = False
    has_git_danger: bool = False
    has_force_push: bool = False
    has_curl_pipe: bool = False
    has_pipe: bool = False
    has_redirect: bool = False
    has_subshell: bool = False
    has_chain: bool = False
    has_abs_path: bool = False
    has_wildcard: bool = False
    has_network: bool = False
    has_db: bool = False
    has_db_destructive: bool = False
    has_firewall: bool = False
    has_dns_modify: bool = False
    has_env_access: bool = False
    has_secret_access: bool = False
    # PR 2 additions
    has_inline_exec: bool = False    # bash -c / python -c / sh -c
    has_xargs_rm: bool = False       # xargs rm (equivalent to rm)
    has_find_delete: bool = False    # find -delete / find -exec rm
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": redact_secrets(self.raw),
            "executable": self.executable,
            "has_sudo": self.has_sudo,
            "has_rm": self.has_rm,
            "has_chmod": self.has_chmod,
            "has_systemctl": self.has_systemctl,
            "has_docker": self.has_docker,
            "has_nginx": self.has_nginx,
            "has_package_manager": self.has_package_manager,
            "has_git_danger": self.has_git_danger,
            "has_force_push": self.has_force_push,
            "has_curl_pipe": self.has_curl_pipe,
            "has_pipe": self.has_pipe,
            "has_redirect": self.has_redirect,
            "has_subshell": self.has_subshell,
            "has_chain": self.has_chain,
            "has_abs_path": self.has_abs_path,
            "has_wildcard": self.has_wildcard,
            "has_network": self.has_network,
            "has_db": self.has_db,
            "has_db_destructive": self.has_db_destructive,
            "has_firewall": self.has_firewall,
            "has_dns_modify": self.has_dns_modify,
            "has_env_access": self.has_env_access,
            "has_secret_access": self.has_secret_access,
            "flags": self.flags,
        }


def parse_command(raw: str) -> ParsedCommand:
    """Parse a shell command string into structured representation.

    Epic #1072 fix: uses shlex.split() instead of .split() so quoted arguments
    (e.g. 'git commit -m "fix: my message"') are parsed correctly.  Falls back
    to simple whitespace split on shlex.ValueError (e.g. unterminated quotes).
    """
    import shlex as _shlex
    cmd = ParsedCommand(raw=raw)
    if not raw or not raw.strip():
        return cmd

    try:
        parts = _shlex.split(raw)
    except ValueError:
        # Unterminated quote or other shell syntax error — use naive split
        parts = raw.strip().split()
    cmd.executable = parts[0] if parts else ""
    cmd.args = parts[1:] if len(parts) > 1 else []

    cmd.has_sudo = bool(_SUDO_RE.search(raw))
    cmd.has_rm = bool(_RM_RE.search(raw))
    cmd.has_delete = bool(_DELETE_RE.search(raw))
    cmd.has_chmod = bool(_CHMOD_RE.search(raw))
    cmd.has_systemctl = bool(_SYSTEMCTL_RE.search(raw))
    cmd.has_docker = bool(_DOCKER_RE.search(raw))
    cmd.has_nginx = bool(_NGINX_RE.search(raw))
    cmd.has_package_manager = bool(_PKG_RE.search(raw))
    cmd.has_git_danger = bool(_GIT_DANGER_RE.search(raw))
    cmd.has_force_push = bool(_FORCE_PUSH_RE.search(raw))
    cmd.has_curl_pipe = bool(_CURL_PIPE_RE.search(raw))
    cmd.has_pipe = bool(_PIPE_RE.search(raw))
    cmd.has_redirect = bool(_REDIRECT_RE.search(raw))
    cmd.has_subshell = bool(_SUBSHELL_RE.search(raw))
    cmd.has_chain = bool(_CHAIN_RE.search(raw))
    cmd.has_abs_path = bool(_ABS_PATH_RE.search(raw))
    cmd.has_wildcard = bool(_WILDCARD_RE.search(raw))
    cmd.has_network = bool(_NETWORK_RE.search(raw))
    cmd.has_db = bool(_DB_CMD_RE.search(raw))
    cmd.has_db_destructive = bool(_DB_RE.search(raw))
    cmd.has_firewall = bool(_FIREWALL_RE.search(raw))
    cmd.has_dns_modify = bool(_DNS_RE.search(raw))
    cmd.has_env_access = bool(_ENV_RE.search(raw))
    cmd.has_secret_access = bool(_SECRET_ACCESS_RE.search(raw))
    # PR 2 additions
    cmd.has_inline_exec = bool(_INLINE_EXEC_RE.search(raw))
    cmd.has_xargs_rm = bool(_XARGS_RM_RE.search(raw))
    cmd.has_find_delete = bool(_FIND_DELETE_RE.search(raw))

    # Collect flags
    for p in cmd.flags_list():
        cmd.flags.append(p)

    return cmd


def _flags_list(self) -> List[str]:
    """List all detected flags."""
    flags = []
    for attr in dir(self):
        if attr.startswith("has_") and getattr(self, attr, False):
            flags.append(attr.replace("has_", ""))
    return flags


ParsedCommand.flags_list = _flags_list


# ---------------------------------------------------------------------------
# Deterministic risk classifier
# ---------------------------------------------------------------------------

def classify_command_risk(parsed: ParsedCommand) -> str:
    """Classify risk level deterministically from parsed command.

    Returns: low | medium | high | critical | unknown
    """
    # CRITICAL — always blocked or requires explicit confirmation
    if parsed.has_force_push:
        return "critical"
    if parsed.has_curl_pipe:
        return "critical"
    if parsed.has_rm and parsed.has_sudo:
        return "critical"
    if parsed.has_rm and parsed.has_wildcard:
        return "critical"
    if parsed.has_db_destructive:
        return "critical"
    if parsed.has_firewall:
        return "critical"
    if parsed.has_dns_modify:
        return "critical"
    if parsed.has_secret_access:
        return "critical"
    # PR 2 — inline code execution is always CRITICAL (arbitrary code)
    if parsed.has_inline_exec:
        return "critical"
    # PR 2 — xargs rm with wildcard or sudo is CRITICAL
    if parsed.has_xargs_rm and (parsed.has_wildcard or parsed.has_sudo):
        return "critical"
    # PR 2 — find -delete with sudo or abs path is CRITICAL
    if parsed.has_find_delete and (parsed.has_sudo or parsed.has_abs_path):
        return "critical"

    # HIGH — requires rollback/policy
    if parsed.has_sudo:
        return "high"
    if parsed.has_rm:
        return "high"
    if parsed.has_delete:
        return "high"
    # PR 2 — xargs rm and find -delete are HIGH (equivalent to rm)
    if parsed.has_xargs_rm:
        return "high"
    if parsed.has_find_delete:
        return "high"
    if parsed.has_systemctl:
        return "high"
    if parsed.has_docker:
        return "high"
    if parsed.has_nginx:
        return "high"
    if parsed.has_git_danger:
        return "high"
    if parsed.has_abs_path:
        return "high"
    if parsed.has_env_access:
        return "high"

    # MEDIUM — review recommended
    if parsed.has_package_manager:
        return "medium"
    if parsed.has_network:
        return "medium"
    if parsed.has_redirect:
        return "medium"
    if parsed.has_subshell:
        return "medium"
    if parsed.has_chmod:
        return "medium"
    if parsed.has_db:
        return "medium"
    if parsed.has_chain and parsed.has_pipe:
        return "medium"

    # LOW — safe read-only operations
    safe_executables = {
        "ls", "cat", "head", "tail", "wc", "echo", "pwd", "whoami",
        "date", "uname", "hostname", "env", "printenv",
        "grep", "rg", "find", "which", "type", "file",
        "git", "python", "python3", "node", "ruby",
        "pytest", "jest", "mocha", "cargo",
    }
    if parsed.executable in safe_executables and not parsed.has_pipe and not parsed.has_redirect:
        return "low"

    # UNKNOWN — needs LLM review
    return "unknown"


# ---------------------------------------------------------------------------
# LLM Risk Reviewer output
# ---------------------------------------------------------------------------

@dataclass
class RiskReviewResult:
    """Output of the LLM Risk Reviewer."""
    risk_assessment: str = "unknown"  # low | medium | high | critical | unknown
    reasons: List[str] = field(default_factory=list)
    affected_paths: List[str] = field(default_factory=list)
    affected_services: List[str] = field(default_factory=list)
    requires_rollback: bool = False
    recommended_prechecks: List[str] = field(default_factory=list)
    recommended_postchecks: List[str] = field(default_factory=list)
    safer_alternative: Optional[str] = None
    should_execute: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_assessment": self.risk_assessment,
            "reasons": self.reasons,
            "affected_paths": self.affected_paths,
            "affected_services": self.affected_services,
            "requires_rollback": self.requires_rollback,
            "recommended_prechecks": self.recommended_prechecks,
            "recommended_postchecks": self.recommended_postchecks,
            "safer_alternative": self.safer_alternative,
            "should_execute": self.should_execute,
        }


# ---------------------------------------------------------------------------
# Safety Event Log
# ---------------------------------------------------------------------------

@dataclass
class SafetyEvent:
    """Record of a risk engine evaluation."""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    command: str = ""
    parsed_flags: List[str] = field(default_factory=list)
    deterministic_risk: str = "unknown"
    llm_risk: str = ""
    final_risk: str = "unknown"
    decision: str = "blocked"  # allowed | blocked | needs_approval
    reason: str = ""
    review_result: Optional[Dict[str, Any]] = None
    decision_explanation: Dict[str, Any] = field(default_factory=dict)
    mission_id: str = ""
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "command": redact_secrets(self.command),
            "parsed_flags": self.parsed_flags,
            "deterministic_risk": self.deterministic_risk,
            "llm_risk": self.llm_risk,
            "final_risk": self.final_risk,
            "decision": self.decision,
            "reason": redact_secrets(self.reason),
            "review_result": self.review_result,
            "decision_explanation": self.decision_explanation,
            "mission_id": self.mission_id,
            "trace_id": self.trace_id,
        }


# ---------------------------------------------------------------------------
# Rollback Plan — structured, not just text
# ---------------------------------------------------------------------------

@dataclass
class RollbackPlan:
    """Structured rollback plan for HIGH/CRITICAL commands.

    PR 2: replaces the text-only get_rollback_suggestion() with a typed
    dataclass that callers (DevOpsManager, DeliveryWorkflow) can act on.
    """
    command: str = ""
    risk_level: str = "unknown"
    backup_cmd: str = ""       # Run BEFORE to snapshot state
    restore_cmd: str = ""      # Run AFTER to undo
    steps: List[str] = field(default_factory=list)
    automated: bool = False    # Can IGRIS execute rollback without approval?
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "risk_level": self.risk_level,
            "backup_cmd": self.backup_cmd,
            "restore_cmd": self.restore_cmd,
            "steps": self.steps,
            "automated": self.automated,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Host-aware policy
# ---------------------------------------------------------------------------

class HostAwarePolicy:
    """Infer environment from hostname and apply host-aware risk rules.

    PR 2: production/staging hosts should automatically escalate risk
    thresholds without manual environment= parameter.

    Usage:
        env = HostAwarePolicy.infer_environment()  # reads socket.gethostname()
        engine = CommandRiskEngine(environment=env)
    """

    _PRODUCTION_PATTERNS = [r"prod", r"production", r"live", r"prd", r"-prd-", r"\.prod\."]
    _STAGING_PATTERNS = [r"stag", r"staging", r"stage", r"stg", r"-stg-"]

    @classmethod
    def infer_environment(cls, hostname: Optional[str] = None) -> str:
        """Return 'production' | 'staging' | 'dev' based on hostname.

        If hostname is None, reads from socket.gethostname().
        """
        import socket
        h = (hostname or socket.gethostname()).lower()
        if any(re.search(p, h) for p in cls._PRODUCTION_PATTERNS):
            return "production"
        if any(re.search(p, h) for p in cls._STAGING_PATTERNS):
            return "staging"
        return "dev"

    @classmethod
    def from_hostname(cls, hostname: Optional[str] = None) -> "CommandRiskEngine":
        """Create a CommandRiskEngine with environment inferred from hostname.

        Usage:
            engine = HostAwarePolicy.from_hostname()
        """
        env = cls.infer_environment(hostname)
        return CommandRiskEngine(environment=env)


# ---------------------------------------------------------------------------
# Command Risk Engine
# ---------------------------------------------------------------------------

class CommandRiskEngine:
    """Multi-level risk classification and governance for shell commands.

    Policy hierarchy:
        1. Structured Tool → always prefer
        2. Template parametrized → safer than raw
        3. Raw shell proposal → escape hatch, fully gated

    For raw shell proposals:
        parse → deterministic classify → LLM review (MEDIUM+) → policy decision

    Epic #1072 improvements:
        - Contextual policy: higher risk threshold in production environments
        - Destructive pre-check: explicit check before any destructive command
        - Dry-run mode: evaluate without executing; return would-execute result
    """

    #: Known destructive command patterns
    DESTRUCTIVE_PATTERNS = re.compile(
        r"\b(rm\b.*(-r|-f|-rf)|DROP\s+TABLE|TRUNCATE\s+TABLE|git\s+clean|"
        r"git\s+reset\s+--hard|mkfs|dd\s+if=|shred|wipefs)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        project_root: Optional[str] = None,
        use_llm_reviewer: bool = True,
        environment: str = "dev",  # Epic #1072: "dev" | "staging" | "production"
        dry_run: bool = False,      # Epic #1072: if True, never executes
    ):
        import os
        self.project_root = project_root or os.environ.get("PROJECT_ROOT", ".")
        self.use_llm_reviewer = use_llm_reviewer
        self.environment = environment
        self.dry_run = dry_run
        self._event_log: List[SafetyEvent] = []
        # Epic #1072 — Precheck/postcheck hook registries
        # Each hook is callable(command: str) -> Optional[str]
        # Returning a non-None string means "block with this reason"
        self._prechecks: List[Any] = []
        self._postchecks: List[Any] = []

    @staticmethod
    def _normalize_host_context(host_context: Any) -> Dict[str, Any]:
        """Normalize host metadata from dict-like or object-like inputs."""
        if not host_context:
            return {}
        if isinstance(host_context, dict):
            raw = dict(host_context)
        else:
            raw = {
                key: getattr(host_context, key, None)
                for key in (
                    "hostname",
                    "alias",
                    "policy",
                    "allowed_paths",
                    "allowed_services",
                    "requires_backup",
                    "approval_mode",
                    "authorized_hosts",
                    "structured_tool_available",
                )
            }

        allowed_paths = [
            str(path).strip()
            for path in (raw.get("allowed_paths") or [])
            if str(path).strip()
        ]
        allowed_services = [
            str(service).strip().lower()
            for service in (raw.get("allowed_services") or [])
            if str(service).strip()
        ]
        authorized_hosts = [
            str(host).strip()
            for host in (raw.get("authorized_hosts") or [])
            if str(host).strip()
        ]

        return {
            "hostname": str(raw.get("hostname") or raw.get("host") or "").strip(),
            "alias": str(raw.get("alias") or "").strip(),
            "policy": str(raw.get("policy") or "safe").strip().lower() or "safe",
            "allowed_paths": allowed_paths,
            "allowed_services": allowed_services,
            "requires_backup": bool(raw.get("requires_backup", True)),
            "approval_mode": str(raw.get("approval_mode") or "").strip().lower(),
            "authorized_hosts": authorized_hosts,
            "structured_tool_available": bool(raw.get("structured_tool_available", False)),
        }

    @staticmethod
    def _extract_host_service(parsed: ParsedCommand) -> str:
        """Best-effort service name for host policy checks."""
        if parsed.has_inline_exec:
            raw = parsed.raw or ""
            if "journalctl" in raw:
                match = re.search(r"journalctl\s+-u\s+([^\s'\"`]+)", raw)
                if match:
                    return match.group(1)
                return "journalctl"
            if "systemctl" in raw or "service " in raw:
                match = re.search(
                    r"(?:systemctl|service)\s+(?:restart|start|stop|reload|status)\s+([^\s'\"`]+)",
                    raw,
                )
                if match:
                    return match.group(1)
                return "service"
            if "docker compose" in raw or "docker-compose" in raw or " docker " in raw:
                return "docker"
        if parsed.has_systemctl:
            skip = {
                "restart",
                "start",
                "stop",
                "status",
                "reload",
                "enable",
                "disable",
                "is-active",
                "daemon-reload",
                "--user",
                "--now",
                "-q",
                "--no-pager",
            }
            for arg in parsed.args:
                if arg.startswith("-") or arg in skip:
                    continue
                return arg
        if parsed.has_nginx:
            return "nginx"
        if parsed.has_docker:
            return "docker"
        return ""

    @staticmethod
    def _extract_absolute_paths(command: str) -> List[str]:
        """Return absolute paths mentioned in a shell command string."""
        paths = []
        for match in re.finditer(r"(?<![\w.-])/(?:[^\s'\"|&;<>`$]+)", command):
            path = match.group(0).rstrip(").,")
            if path:
                paths.append(path)
        return paths

    @staticmethod
    def _structured_tool_recommendation(
        parsed: ParsedCommand,
        host_context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Return a structured-tool recommendation when the host supports it.

        This is intentionally conservative: only command families with a clear
        structured operator replacement are flagged here.
        """
        if not host_context.get("structured_tool_available"):
            return None

        family = CommandRiskEngine._structured_tool_family(parsed)
        if not family:
            return None
        registry_entry = STRUCTURED_TOOL_REGISTRY.get(family)
        if not registry_entry:
            return None
        target = parsed.executable or family
        if family == "service_control":
            target = CommandRiskEngine._extract_host_service(parsed) or "service"
        elif family == "service_observability":
            target = parsed.executable or "journalctl"
        elif family == "container_control":
            target = "docker"
        elif family == "webserver_control":
            target = "nginx"
        elif family == "filesystem_ops":
            target = (parsed.args[0] if parsed.args else parsed.executable) or "filesystem"
        elif family == "network_ops":
            target = parsed.executable or "network"
        elif family == "git_ops":
            target = parsed.executable or "git"
        elif family == "database_ops":
            target = parsed.executable or "database"
        return {
            "tool": registry_entry["tool"],
            "operation": registry_entry["operation"],
            "target": target,
            "reason": f"use structured {registry_entry['tool']} instead of raw shelling",
            "fallback_rationale": registry_entry["fallback_rationale"],
        }

        return None

    @staticmethod
    def _structured_tool_family(parsed: ParsedCommand) -> Optional[str]:
        """Map a parsed command to a structured-tool family when available."""
        executable = (parsed.executable or "").lower()
        raw = (parsed.raw or "").lower()
        if parsed.has_inline_exec:
            if "journalctl" in raw:
                return "service_observability"
            if "systemctl" in raw or "service " in raw:
                return "service_control"
            if "docker compose" in raw or "docker-compose" in raw or " docker " in raw:
                return "container_control"
            if "nginx" in raw:
                return "webserver_control"
        if executable in {"cat", "ls", "find", "grep", "head", "tail", "awk", "sed"}:
            return "filesystem_ops"
        if executable in {"curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "rsync", "telnet", "ftp"}:
            return "network_ops"
        if executable == "git" or parsed.has_git_danger:
            return "git_ops"
        if executable in {"mysql", "psql", "mongo", "redis-cli", "sqlite3"} or parsed.has_db:
            return "database_ops"
        if executable in {"systemctl", "service"}:
            return "service_control"
        if executable == "journalctl":
            return "service_observability"
        if executable in {"docker", "docker-compose"} or "docker compose" in raw:
            return "container_control"
        if executable == "nginx" or "nginx " in raw or raw.startswith("nginx\t"):
            return "webserver_control"
        return None

    @staticmethod
    def _path_allowed(target: str, allowed_paths: List[str]) -> bool:
        """Return True if target is under one of the allowed paths."""
        target_path = Path(target)
        for allowed in allowed_paths:
            try:
                allowed_path = Path(allowed)
                if str(target_path).startswith(str(allowed_path)):
                    return True
            except Exception:
                continue
        return False

    def _host_policy_reason(
        self,
        command: str,
        parsed: ParsedCommand,
        host_context: Dict[str, Any],
    ) -> Optional[str]:
        """Return a host-policy block reason, or None if allowed."""
        if not host_context:
            return None

        hostname = host_context.get("hostname") or "unknown-host"
        policy = host_context.get("policy") or "safe"
        allowed_paths = host_context.get("allowed_paths") or []
        allowed_services = host_context.get("allowed_services") or []

        if parsed.has_systemctl or parsed.has_nginx or parsed.has_docker:
            service = self._extract_host_service(parsed)
            if allowed_services and service and service not in allowed_services:
                return (
                    f"host policy blocks service {service!r} on {hostname!r} "
                    f"(allowed: {allowed_services})"
                )

        if allowed_paths:
            for abs_path in self._extract_absolute_paths(command):
                if not self._path_allowed(abs_path, allowed_paths):
                    return (
                        f"host policy blocks path {abs_path!r} on {hostname!r} "
                        f"(allowed paths: {allowed_paths})"
                    )

        if policy == "production" and parsed.has_systemctl:
            return f"host policy blocks systemctl command on production host {hostname!r}"

        return None

    def _build_decision_explanation(
        self,
        event: SafetyEvent,
        review: RiskReviewResult,
        host_context: Optional[Any] = None,
        contextual_reasons: Optional[List[str]] = None,
        rollback_plan: Optional[RollbackPlan] = None,
        structured_tool_recommendation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the structured decision explanation for audit/reporting."""
        host = self._normalize_host_context(host_context)
        tool_first_recommended = bool(structured_tool_recommendation)
        if structured_tool_recommendation:
            fallback_rationale = structured_tool_recommendation.get(
                "fallback_rationale",
                "use the structured tool instead of shelling out",
            )
        elif host.get("structured_tool_available"):
            fallback_rationale = "structured tool available; raw shell should remain an exception"
        else:
            fallback_rationale = "structured tool unavailable; raw shell policy applies"
        explanation = {
            "decision": event.decision,
            "final_risk": event.final_risk,
            "deterministic_risk": event.deterministic_risk,
            "llm_review_used": bool(event.llm_risk),
            "deterministic_reasons": [event.reason] if event.reason else [],
            "contextual_reasons": contextual_reasons or [],
            "required_prechecks": list(review.recommended_prechecks or []),
            "required_postchecks": list(review.recommended_postchecks or []),
            "rollback_plan": rollback_plan.to_dict() if rollback_plan else None,
            "safer_alternative": review.safer_alternative,
            "structured_tool_available": host.get("structured_tool_available", False),
            "tool_first_recommended": tool_first_recommended,
            "structured_tool_recommendation": structured_tool_recommendation,
            "structured_tool_registry": list(STRUCTURED_TOOL_REGISTRY.keys()),
            "fallback_rationale": fallback_rationale,
            "host_context": {
                k: host.get(k)
                for k in ("hostname", "policy", "allowed_paths", "allowed_services")
                if host.get(k)
            },
        }
        return explanation

    @staticmethod
    def structured_tool_registry() -> Dict[str, Dict[str, str]]:
        """Return a copy of the structured tool registry for audit/tests."""
        return {key: dict(value) for key, value in STRUCTURED_TOOL_REGISTRY.items()}

    def register_precheck(self, fn: Any) -> None:
        """Register a precheck hook called before command evaluation.

        Epic #1072 — Precheck hooks run before the deterministic classifier.
        A hook returns a string (block reason) or None (allow to proceed).
        Hooks are called in registration order; first block wins.

        Example:
            engine.register_precheck(lambda cmd: "blocked" if "sudo" in cmd else None)
        """
        self._prechecks.append(fn)

    def register_postcheck(self, fn: Any) -> None:
        """Register a postcheck hook called after evaluation, before returning.

        Epic #1072 — Postcheck hooks can veto an 'allowed' decision. They
        receive the command and the SafetyEvent produced so far and return
        a block reason string or None.

        Example:
            engine.register_postcheck(lambda cmd, evt: "no prod writes" if evt.final_risk == "high" else None)
        """
        self._postchecks.append(fn)

    def _run_prechecks(self, command: str, event: "SafetyEvent") -> Optional[str]:
        """Run all registered precheck hooks. Return first block reason or None."""
        for hook in self._prechecks:
            try:
                reason = hook(command)
                if reason is not None:
                    return str(reason)
            except Exception as exc:
                import logging as _logging
                _logging.getLogger("igris.risk.precheck").warning(
                    "precheck hook %r raised: %s", hook, exc
                )
        return None

    def _run_postchecks(self, command: str, event: "SafetyEvent") -> Optional[str]:
        """Run all registered postcheck hooks. Return first block reason or None."""
        for hook in self._postchecks:
            try:
                reason = hook(command, event)
                if reason is not None:
                    return str(reason)
            except Exception as exc:
                import logging as _logging
                _logging.getLogger("igris.risk.postcheck").warning(
                    "postcheck hook %r raised: %s", hook, exc
                )
        return None

    def get_rollback_suggestion(self, command: str, event: "SafetyEvent") -> str:
        """Return a human-readable rollback suggestion for a CRITICAL/HIGH command.

        Epic #1072 — Binding rollback hints let operators know how to undo
        a command if it runs and causes problems.

        Deprecated: use build_rollback_plan() for structured output.
        """
        plan = self.build_rollback_plan(command, event)
        if plan.steps:
            return " | ".join(plan.steps)
        return plan.notes

    def build_rollback_plan(self, command: str, event: "SafetyEvent") -> RollbackPlan:
        """Return a structured RollbackPlan for a CRITICAL/HIGH command.

        PR 2: replaces text-only get_rollback_suggestion() with a typed
        RollbackPlan that DevOpsManager and DeliveryWorkflow can act on.
        """
        cmd_lower = command.lower()
        plan = RollbackPlan(command=command, risk_level=event.final_risk)

        # Check inline exec FIRST — it's more dangerous than rm
        if ("bash -c" in cmd_lower or "sh -c" in cmd_lower
                or re.search(r"\bpython[23]?\s+-c\b", cmd_lower)):
            plan.backup_cmd = "git stash && git add -A && git stash"
            plan.restore_cmd = "git checkout -- ."
            plan.steps = [
                "Inline code execution: snapshot all changed files before running.",
                "Restore any modified files from git: `git checkout -- .`",
            ]
            plan.automated = False
            plan.notes = "Inline exec arbitrary code — manual review required before execution."

        elif "rm " in cmd_lower or "rmdir" in cmd_lower or "xargs" in cmd_lower:
            plan.backup_cmd = "git stash && git add -A && git stash"
            plan.restore_cmd = "git checkout -- ."
            plan.steps = [
                "Before running: commit or stash any staged changes.",
                "Restore deleted files: `git checkout -- .`",
                "If not tracked by git: restore from the last filesystem backup.",
            ]
            plan.automated = True
            plan.notes = "Deleted files can be recovered from git history if previously tracked."

        elif "drop table" in cmd_lower or "truncate table" in cmd_lower:
            plan.backup_cmd = "pg_dump $DATABASE_URL > backup_$(date +%s).sql"
            plan.restore_cmd = "psql $DATABASE_URL < backup_<timestamp>.sql"
            plan.steps = [
                "Before running: create a full DB dump with pg_dump.",
                "Restore: psql $DATABASE_URL < backup_<timestamp>.sql",
            ]
            plan.automated = False
            plan.notes = "Database destructive operation — manual snapshot required."

        elif "git reset --hard" in cmd_lower:
            plan.backup_cmd = "git log --oneline -5  # note the current SHA"
            plan.restore_cmd = "git reset --hard <pre-reset-SHA>"
            plan.steps = [
                "Note current HEAD SHA: `git rev-parse HEAD`",
                "After reset: use `git reflog` to find the pre-reset SHA.",
                "Restore: `git reset --hard <pre-reset-SHA>`",
            ]
            plan.automated = True
            plan.notes = "Git reflog retains commits for 90 days by default."

        elif "git clean" in cmd_lower:
            plan.backup_cmd = "git stash -u  # stash untracked files"
            plan.restore_cmd = "git stash pop"
            plan.steps = [
                "Before running: `git stash -u` to save untracked files.",
                "Restore: `git stash pop`",
                "Permanently deleted untracked files cannot be recovered without a backup.",
            ]
            plan.automated = False
            plan.notes = "Untracked files cannot be recovered after git clean -f without stash."

        elif "dd if=" in cmd_lower or "mkfs" in cmd_lower or "wipefs" in cmd_lower:
            plan.backup_cmd = "dd if=<device> of=<backup_file> bs=4M"
            plan.restore_cmd = "dd if=<backup_file> of=<device> bs=4M"
            plan.steps = [
                "Before running: create a full disk image backup with `dd`.",
                "Restore: `dd if=<backup_file> of=<device> bs=4M`",
                "This operation is IRREVERSIBLE without a prior disk image.",
            ]
            plan.automated = False
            plan.notes = "Disk write is irreversible without a full disk image backup."

        elif event.final_risk in ("critical", "high"):
            plan.backup_cmd = "git add -A && git stash"
            plan.restore_cmd = "git stash pop"
            plan.steps = [
                f"Command classified as {event.final_risk} — take a snapshot before running.",
                "Restore from the most recent backup of affected resources.",
            ]
            plan.automated = False
            plan.notes = f"Risk level {event.final_risk} — manual rollback required."

        return plan

    def is_destructive(self, command: str) -> bool:
        """Epic #1072 — Pre-check: return True if command matches destructive patterns.

        This is a fast, deterministic check run before full evaluation.
        Destructive commands always get at least 'high' risk in production.
        """
        return bool(self.DESTRUCTIVE_PATTERNS.search(command))

    def evaluate_command(
        self,
        command: str,
        context: str = "",
        mission_id: str = "",
        trace_id: str = "",
        cwd: Optional[str] = None,
        host_context: Optional[Any] = None,
    ) -> Tuple[SafetyEvent, RiskReviewResult]:
        """Evaluate a raw shell command through the full risk pipeline.

        Returns (SafetyEvent, RiskReviewResult).

        Epic #1072:
        - If dry_run=True, returns a would-execute event with decision="dry_run"
        - If environment="production" and command is destructive → escalate to critical
        - Destructive pre-check always fires before LLM review
        """
        event = SafetyEvent(
            command=command,
            mission_id=mission_id,
            trace_id=trace_id,
        )
        host = self._normalize_host_context(host_context)

        # Epic #1072 — run precheck hooks before any evaluation
        precheck_block = self._run_prechecks(command, event)
        if precheck_block:
            event.decision = "blocked"
            event.reason = f"precheck: {precheck_block}"
            event.final_risk = "high"
            event.deterministic_risk = "high"
            event.decision_explanation = self._build_decision_explanation(
                event, RiskReviewResult(), host_context=host,
                contextual_reasons=[f"precheck:{precheck_block}"],
            )
            self._event_log.append(event)
            return event, RiskReviewResult()

        # Epic #1072 — dry-run mode: classify but never gate execution
        if self.dry_run:
            parsed = parse_command(command)
            det_risk = classify_command_risk(parsed)
            event.parsed_flags = parsed.flags_list()
            event.deterministic_risk = det_risk
            event.final_risk = det_risk
            event.decision = "dry_run"
            event.reason = f"dry_run mode: would classify as {det_risk}"
            event.decision_explanation = self._build_decision_explanation(
                event, RiskReviewResult(), host_context=host,
                contextual_reasons=["dry_run mode"],
            )
            self._event_log.append(event)
            return event, RiskReviewResult()

        # Epic #1072 — Contextual policy: cwd-based escalation.
        # Commands run outside the project root (e.g. /etc, /var, /home/other)
        # are escalated to at least 'medium' to flag unexpected scope.
        # Commands run in system directories are escalated to 'high'.
        if cwd:
            import os as _os
            _cwd_resolved = _os.path.realpath(str(cwd))
            _proj_resolved = _os.path.realpath(str(self.project_root))
            _in_project = _cwd_resolved.startswith(_proj_resolved)
            _system_dirs = ("/etc", "/usr", "/var", "/bin", "/sbin", "/lib", "/boot", "/sys", "/proc")
            _in_system = any(_cwd_resolved.startswith(d) for d in _system_dirs)
            if _in_system:
                event.reason = (
                    f"Command cwd is a system directory ({_cwd_resolved!r}); escalating risk."
                )
                event.decision = "blocked"
                event.deterministic_risk = "high"
                event.final_risk = "high"
                event.decision_explanation = self._build_decision_explanation(
                    event, RiskReviewResult(), host_context=host,
                    contextual_reasons=[f"cwd:{_cwd_resolved}"],
                )
                self._event_log.append(event)
                return event, RiskReviewResult()
            if not _in_project:
                # Outside project root — log warning but don't block by default
                context = context + f" [cwd={_cwd_resolved!r} is outside project root]"

        # 1. Parse command
        parsed = parse_command(command)
        event.parsed_flags = parsed.flags_list()

        # 2. Deterministic classification
        det_risk = classify_command_risk(parsed)
        event.deterministic_risk = det_risk

        host_block = self._host_policy_reason(command, parsed, host)
        if host_block:
            event.decision = "blocked"
            event.reason = f"host policy: {host_block}"
            event.deterministic_risk = "high"
            event.final_risk = "high"
            event.decision_explanation = self._build_decision_explanation(
                event,
                RiskReviewResult(),
                host_context=host,
                contextual_reasons=[host_block],
            )
            self._event_log.append(event)
            return event, RiskReviewResult()

        structured_tool_recommendation = self._structured_tool_recommendation(parsed, host)
        if structured_tool_recommendation:
            event.decision = "blocked"
            event.reason = f"tool-first policy: {structured_tool_recommendation['reason']}"
            event.final_risk = det_risk if det_risk != "unknown" else "high"
            event.deterministic_risk = event.final_risk
            rollback_plan = (
                self.build_rollback_plan(command, event)
                if event.final_risk in ("high", "critical")
                else None
            )
            event.decision_explanation = self._build_decision_explanation(
                event,
                RiskReviewResult(),
                host_context=host,
                contextual_reasons=[structured_tool_recommendation["reason"]],
                rollback_plan=rollback_plan,
                structured_tool_recommendation=structured_tool_recommendation,
            )
            self._event_log.append(event)
            return event, RiskReviewResult()

        # Epic #1072 — Destructive pre-check: escalate in production
        if self.is_destructive(command):
            if self.environment == "production":
                det_risk = "critical"
                event.deterministic_risk = "critical"
                event.reason = (
                    f"Destructive command blocked in production environment: {command[:100]}"
                )
                event.decision = "blocked"
                event.final_risk = "critical"
                event.decision_explanation = self._build_decision_explanation(
                    event, RiskReviewResult(), host_context=host,
                    contextual_reasons=["production destructive block"],
                )
                self._event_log.append(event)
                return event, RiskReviewResult()
            elif self.environment == "staging" and det_risk not in ("high", "critical"):
                # Escalate destructive commands in staging to at least high
                det_risk = "high"
                event.deterministic_risk = "high"

        # 3. LLM review for MEDIUM, HIGH, UNKNOWN
        review = RiskReviewResult()
        if det_risk in ("medium", "high", "unknown") and self.use_llm_reviewer:
            review = self._llm_review(command, parsed, context, det_risk)
            event.llm_risk = review.risk_assessment

        # 4. Final risk = max(deterministic, llm) for safety
        event.final_risk = self._resolve_final_risk(det_risk, event.llm_risk)

        # Epic #1072 — Contextual policy: production blocks HIGH (not just CRITICAL)
        if self.environment == "production" and event.final_risk in ("high", "critical"):
            event.decision = "blocked"
            event.reason = (
                f"Blocked in production environment (risk={event.final_risk}): "
                + (", ".join(review.reasons) or "policy")
            )
            rollback_plan = self.build_rollback_plan(command, event) if event.final_risk in ("high", "critical") else None
            event.decision_explanation = self._build_decision_explanation(
                event,
                review,
                host_context=host,
                contextual_reasons=["production risk block"],
                rollback_plan=rollback_plan,
            )
            self._event_log.append(event)
            return event, review

        # 5. Standard policy decision
        event.decision, event.reason = self._apply_policy(
            event.final_risk, parsed, review,
        )
        event.review_result = review.to_dict()

        # Epic #1072 — run postcheck hooks (can veto 'allowed' or 'needs_approval')
        if event.decision in ("allowed", "needs_approval"):
            postcheck_block = self._run_postchecks(command, event)
            if postcheck_block:
                event.decision = "blocked"
                event.reason = f"postcheck: {postcheck_block}"
        rollback_plan = self.build_rollback_plan(command, event) if event.final_risk in ("high", "critical") else None
        event.decision_explanation = self._build_decision_explanation(
            event,
            review,
            host_context=host,
            contextual_reasons=[reason for reason in [event.reason] if reason],
            rollback_plan=rollback_plan,
            structured_tool_recommendation=None,
        )

        # 6. Log event
        self._event_log.append(event)

        return event, review

    def evaluate_template(
        self,
        template_id: str,
        parameters: Dict[str, str],
        mission_id: str = "",
        trace_id: str = "",
        host_context: Optional[Any] = None,
    ) -> Tuple[SafetyEvent, RiskReviewResult]:
        """Evaluate a parametrized shell template.

        Templates are safer than raw commands — validated parameters only.
        PR 2: parameter values are validated for shell metacharacters before
        rendering to prevent template injection attacks.
        """
        # PR 2 — validate params before rendering
        param_error = self._validate_template_params(parameters)
        if param_error:
            event = SafetyEvent(
                command=f"template:{template_id}",
                mission_id=mission_id,
                trace_id=trace_id,
                decision="blocked",
                reason=f"template param injection: {param_error}",
                final_risk="critical",
                deterministic_risk="critical",
            )
            self._event_log.append(event)
            return event, RiskReviewResult(
                risk_assessment="critical",
                reasons=[param_error],
                should_execute=False,
            )

        rendered = self._render_template(template_id, parameters)
        event, review = self.evaluate_command(
            command=rendered,
            context=f"Template: {template_id}",
            mission_id=mission_id,
            trace_id=trace_id,
            host_context=host_context,
        )
        # Templates get a risk reduction (one level down from raw)
        if event.final_risk == "high":
            event.final_risk = "medium"
            event.reason = f"Template risk reduced: {event.reason}"
        elif event.final_risk == "medium":
            event.final_risk = "low"
            event.reason = f"Template risk reduced: {event.reason}"
        # Re-evaluate policy with reduced risk
        event.decision, policy_reason = self._apply_policy(
            event.final_risk, parse_command(rendered), review,
        )
        if "Template" not in event.reason:
            event.reason = f"Template risk reduced: {policy_reason}"
        self._event_log.append(event)
        return event, review

    def get_event_log(self) -> List[Dict[str, Any]]:
        """Get safety event log."""
        return [e.to_dict() for e in self._event_log]

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent safety events."""
        return [e.to_dict() for e in self._event_log[-limit:]]

    # -- Internal --

    def _llm_review(
        self,
        command: str,
        parsed: ParsedCommand,
        context: str,
        det_risk: str,
    ) -> RiskReviewResult:
        """Request LLM risk review via Model Orchestrator.

        The LLM reviewer is advisory only. IGRIS Policy Engine makes
        the final decision.
        """
        try:
            from igris.core.model_orchestrator import ModelOrchestrator
            orch = ModelOrchestrator()

            prompt = (
                f"You are a security reviewer. Evaluate this shell command:\n"
                f"Command: {redact_secrets(command)}\n"
                f"Deterministic risk: {det_risk}\n"
                f"Detected flags: {', '.join(parsed.flags_list())}\n"
                f"Context: {context}\n\n"
                f"Respond with JSON:\n"
                f'{{"risk_assessment": "medium|high|critical|unknown", '
                f'"reasons": [], "affected_paths": [], "affected_services": [], '
                f'"requires_rollback": true/false, '
                f'"recommended_prechecks": [], "recommended_postchecks": [], '
                f'"safer_alternative": null, "should_execute": false}}'
            )

            result = orch.complete(
                task_type="risk_review",
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You are a security-focused command risk reviewer.",
                json_mode=True,
                preferred_profile="risk_reviewer",
            )

            if result.success and result.text:
                return self._parse_review_response(result.text)

        except Exception:
            pass

        # Fallback: conservative review
        return RiskReviewResult(
            risk_assessment=det_risk,
            reasons=[f"LLM review unavailable, using deterministic: {det_risk}"],
            requires_rollback=det_risk in ("high", "critical"),
            should_execute=det_risk == "low",
        )

    def _parse_review_response(self, text: str) -> RiskReviewResult:
        """Parse LLM risk review JSON response."""
        import json
        try:
            data = json.loads(text)
            return RiskReviewResult(
                risk_assessment=data.get("risk_assessment", "unknown"),
                reasons=data.get("reasons", []),
                affected_paths=data.get("affected_paths", []),
                affected_services=data.get("affected_services", []),
                requires_rollback=data.get("requires_rollback", False),
                recommended_prechecks=data.get("recommended_prechecks", []),
                recommended_postchecks=data.get("recommended_postchecks", []),
                safer_alternative=data.get("safer_alternative"),
                should_execute=data.get("should_execute", False),
            )
        except (json.JSONDecodeError, TypeError):
            return RiskReviewResult(
                risk_assessment="unknown",
                reasons=["Failed to parse LLM review response"],
                should_execute=False,
            )

    @staticmethod
    def _resolve_final_risk(deterministic: str, llm: str) -> str:
        """Resolve final risk level — always take the higher one.

        If LLM review was not performed (llm is empty), use deterministic only.
        """
        if not llm:
            return deterministic
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3, "unknown": 2}
        d_score = order.get(deterministic, 2)
        l_score = order.get(llm, -1)
        if l_score > d_score:
            return llm
        return deterministic

    @staticmethod
    def _apply_policy(
        risk: str,
        parsed: ParsedCommand,
        review: RiskReviewResult,
    ) -> Tuple[str, str]:
        """Apply policy engine to determine final decision.

        Returns (decision, reason).
        Decision: allowed | blocked | needs_approval
        """
        # CRITICAL — always blocked
        if risk == "critical":
            return "blocked", f"Critical risk: {', '.join(review.reasons) or 'deterministic block'}"

        # HIGH — needs approval + rollback
        if risk == "high":
            if review.requires_rollback:
                return "needs_approval", f"High risk, requires rollback: {', '.join(review.reasons) or 'high risk'}"
            return "needs_approval", f"High risk: {', '.join(review.reasons) or 'high risk command'}"

        # MEDIUM — allowed with logging
        if risk == "medium":
            return "allowed", f"Medium risk, logged: {', '.join(review.reasons) or 'standard medium'}"

        # LOW — always allowed
        if risk == "low":
            return "allowed", "Low risk: safe command"

        # UNKNOWN — needs approval
        return "needs_approval", f"Unknown risk: {', '.join(review.reasons) or 'unrecognized command'}"

    @staticmethod
    def _validate_template_params(parameters: Dict[str, str]) -> Optional[str]:
        """Validate template parameters — block shell metacharacters.

        PR 2: prevents template injection by rejecting values containing
        shell operators (;, |, &, $, backtick, <, >, {, }, etc.).

        Returns error message string if invalid, None if all params are safe.
        """
        for key, value in parameters.items():
            if _UNSAFE_PARAM_CHARS_RE.search(str(value)):
                # Find the offending character for clear error message
                m = _UNSAFE_PARAM_CHARS_RE.search(str(value))
                char = m.group(0) if m else "?"
                return (
                    f"param {key!r} contains unsafe shell character {char!r} "
                    f"in value {str(value)[:40]!r}"
                )
        return None

    @staticmethod
    def _render_template(template_id: str, parameters: Dict[str, str]) -> str:
        """Render a shell template with safe parameters."""
        templates = {
            "pip_install": "pip install {package}",
            "npm_install": "npm install {package}",
            "pytest_run": "python -m pytest {path} -v",
            "git_status": "git status",
            "git_diff": "git diff {path}",
            "cat_file": "cat {path}",
            "ls_dir": "ls -la {path}",
            "docker_ps": "docker ps",
            "systemctl_status": "systemctl status {service}",
        }
        template = templates.get(template_id, template_id)
        try:
            return template.format(**parameters)
        except (KeyError, IndexError):
            return template
