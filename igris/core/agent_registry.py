"""Agent role registry and contracts for IGRIS assignment routing."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ROLES: Dict[str, Dict[str, Any]] = {
    "planner": {
        "description": "Decomposes large missions and plans execution.",
        "default_task_type": "planning",
        "risk_tolerance": "low",
    },
    "backend_coder": {
        "description": "Implements backend/API changes.",
        "default_task_type": "backend_endpoint",
        "risk_tolerance": "medium",
    },
    "tester": {
        "description": "Writes and repairs tests.",
        "default_task_type": "test_only",
        "risk_tolerance": "low",
    },
    "test_debugger": {
        "description": "Diagnoses pytest failures.",
        "default_task_type": "pytest_failure",
        "risk_tolerance": "low",
    },
    "devops": {
        "description": "Handles runtime, CI, deploy, smoke.",
        "default_task_type": "devops_runtime",
        "risk_tolerance": "high",
    },
    "security_reviewer": {
        "description": "Reviews secrets, destructive diffs and safety gates.",
        "default_task_type": "security_review",
        "risk_tolerance": "very_high",
    },
    "memory_architect": {
        "description": "Works on memory/synapse systems.",
        "default_task_type": "memory_system",
        "risk_tolerance": "medium",
    },
    "cost_guardian": {
        "description": "Optimizes routing and budget decisions.",
        "default_task_type": "cost_control",
        "risk_tolerance": "low",
    },
    "coordinator": {
        "description": "Validates contracts and coordinates escalations.",
        "default_task_type": "coordination",
        "risk_tolerance": "low",
    },
}

TOOL_PERMISSIONS: Dict[str, List[str]] = {
    "planner": ["read_file", "search_code", "find_files", "list_directory", "run_command", "memory_record", "finish", "blocked", "request_approval", "memory_graph_read"],
    "backend_coder": ["read_file", "edit_file", "write_file", "search_code", "find_files", "list_directory", "run_command", "run_tests", "memory_record", "finish", "blocked", "request_approval"],
    "tester": ["read_file", "edit_file", "write_file", "search_code", "find_files", "list_directory", "run_tests", "memory_record", "finish", "blocked"],
    "test_debugger": ["read_file", "search_code", "find_files", "list_directory", "run_tests", "run_command", "memory_record", "finish", "blocked"],
    "devops": ["read_file", "edit_file", "write_file", "search_code", "find_files", "list_directory", "run_command", "run_tests", "memory_record", "finish", "blocked", "request_approval"],
    "security_reviewer": ["read_file", "search_code", "find_files", "list_directory", "run_command", "memory_record", "finish", "blocked", "request_approval"],
    "memory_architect": ["read_file", "edit_file", "write_file", "search_code", "find_files", "list_directory", "run_command", "run_tests", "memory_record", "finish", "blocked", "memory_graph_read", "memory_graph_write"],
    "cost_guardian": ["read_file", "search_code", "find_files", "list_directory", "memory_record", "finish", "blocked"],
    "coordinator": ["memory_record", "finish", "blocked", "request_approval", "memory_graph_read"],
}

OUTPUT_SCHEMA: Dict[str, List[str]] = {
    "planner": ["plan", "summary"], "backend_coder": ["files_modified", "summary"],
    "tester": ["test_files", "summary"], "test_debugger": ["root_cause", "fix_applied", "summary"],
    "devops": ["commands_run", "summary"], "security_reviewer": ["risk_level", "concerns", "summary"],
    "memory_architect": ["nodes_created", "summary"], "cost_guardian": ["recommendation", "summary"],
    "coordinator": ["summary"],
}

ESCALATION_PATH: Dict[str, str] = {
    "planner": "coordinator", "backend_coder": "planner", "tester": "planner", "test_debugger": "planner",
    "devops": "coordinator", "security_reviewer": "coordinator", "memory_architect": "coordinator",
    "cost_guardian": "coordinator", "coordinator": "",
}

PROFILE_RELATIVE_COST: Dict[str, float] = {
    "local_light": 0.0, "local_coder": 0.0, "cheap_cloud_reasoning": 1.0,
    "mini_execution": 2.1, "endpoint_implementation": 2.1, "risk_reviewer": 1.0,
    "strong_cloud_reasoning": 3.1, "strong_execution": 3.1,
}

def get_role(name: str) -> Optional[Dict[str, Any]]:
    return ROLES.get(name)

def get_default_task_type(role_name: str) -> str:
    role = ROLES.get(role_name, {})
    return str(role.get("default_task_type", "code_reasoning"))

def list_roles() -> Dict[str, Dict[str, Any]]:
    return dict(ROLES)
