"""Supervisor execution backends.

SupervisorBackend Protocol and LocalSupervisorBackend (governed local backend
using fixed argv commands only). Extracted from self_repair_supervisor.py for
modularity (Issue #1312).
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from igris.core.supervisor_models import (
    CommandResult,
    _command_detail,
    _safe_text,
)
from igris.core.supervisor_analysis import _smoke_output_is_valid


class SupervisorBackend(Protocol):
    def git_status(self) -> CommandResult: ...
    def git_log_head(self) -> CommandResult: ...
    def create_branch(self, branch: str) -> CommandResult: ...
    def run_reasoning(self, goal: str, max_steps: int, initial_context: Dict[str, Any], timeout: int = 300, task_type: str = "code_reasoning", preferred_profile: Optional[str] = None) -> Dict[str, Any]: ...
    def git_diff_stat(self) -> CommandResult: ...
    def git_diff(self) -> CommandResult: ...
    def run_tests(self, targets: Optional[List[str]] = None, timeout: int = 120, hard_cap: int = 3600) -> CommandResult: ...
    def run_test_diagnostics(self, timeout: int = 120) -> CommandResult: ...
    def smoke(self, endpoints: List[str], restart_command: str = "") -> CommandResult: ...
    def commit(self, message: str, files: Optional[List[str]] = None) -> CommandResult: ...
    def push_branch(self, branch: str) -> CommandResult: ...
    def open_pr(self, branch: str, title: str, body: str) -> CommandResult: ...
    def wait_ci(self) -> CommandResult: ...
    def merge_pr(self) -> CommandResult: ...
    def pull_main(self) -> CommandResult: ...
    def create_issue(self, title: str, body: str) -> CommandResult: ...
    def update_issue(self, issue_url: str, comment_body: str) -> CommandResult: ...
    def fetch_issue(self, issue_url: str) -> CommandResult: ...
    def restore_dangerous_diff(self) -> CommandResult: ...
    def restore_paths(self, paths: List[str]) -> CommandResult: ...
    def checkout_main(self) -> CommandResult: ...
    def delete_stale_rank_branches(self) -> CommandResult: ...
    def call_api_helper(self, packet: Dict[str, Any], model: str, max_tokens: int, timeout: int = 45) -> CommandResult: ...
    def api_helper_is_configured(self) -> bool: ...


class LocalSupervisorBackend:
    """Governed local backend using fixed argv commands only."""

    # LLM provider credentials forwarded to reasoning subprocesses when
    # forward_credentials=True — allows ModelOrchestrator inside the worker
    # to reach cloud providers instead of falling back to Ollama only.
    _REASONING_CREDENTIAL_ALLOWLIST: frozenset = frozenset({
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "IGRIS_API_HELPER_COMMAND",
        "IGRIS_API_HELPER_MODE",
        "IGRIS_API_HELPER_PROVIDER",
        "IGRIS_API_HELPER_MODEL",
        "IGRIS_EXECUTION_STRONG_MODEL",
        "IGRIS_EXECUTION_FALLBACK_MODEL",
        "IGRIS_ENABLE_CODEX_DIRECT_EXECUTION",
    })

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)

    def _subprocess_env(self, *, clean_for_tests: bool = False, forward_credentials: bool = False) -> Dict[str, str]:
        if not clean_for_tests:
            env = os.environ.copy()
            env["IGRIS_SUPERVISOR_CHILD"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            env.pop("PYTEST_CURRENT_TEST", None)
            return env
        allowlist: set = {
            "HOME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "LOGNAME",
            "PATH",
            "PYTHONPATH",
            "SHELL",
            "TERM",
            "TMPDIR",
            "TZ",
            "USER",
        }
        if forward_credentials:
            allowlist = allowlist | LocalSupervisorBackend._REASONING_CREDENTIAL_ALLOWLIST
        env = {
            key: value
            for key, value in os.environ.items()
            if key in allowlist and value
        }
        env.setdefault("PATH", os.defpath)
        env["IGRIS_SUPERVISOR_CHILD"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _run(
        self,
        cmd: List[str],
        timeout: int = 120,
        *,
        input_text: Optional[str] = None,
        clean_env: bool = False,
        forward_credentials: bool = False,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        try:
            env = self._subprocess_env(clean_for_tests=clean_env, forward_credentials=forward_credentials)
            if extra_env:
                env.update(extra_env)
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                env=env,
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                start_new_session=True,
                close_fds=True,
            )
            return CommandResult(
                success=proc.returncode == 0,
                output=proc.stdout,
                error=proc.stderr,
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            output = _safe_text(exc.stdout)
            error = _safe_text(exc.stderr) or "Command timed out"
            return CommandResult(False, output, error, 124)
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

    def _run_adaptive(
        self,
        cmd: List[str],
        *,
        idle_timeout: int = 120,
        hard_cap: int = 3600,
        clean_env: bool = False,
    ) -> CommandResult:
        """Run a command with activity-based dynamic timeout.

        The subprocess is killed only when:
        - no output (stdout OR stderr) has been produced for ``idle_timeout``
          seconds — the process is considered hung/stuck, OR
        - total wall-clock time exceeds ``hard_cap`` seconds — absolute
          safety net against infinite-loop tests.

        A healthy long-running command (e.g. pytest printing progress dots)
        continuously resets the idle timer and will never be killed by it.
        """
        env = self._subprocess_env(clean_for_tests=clean_env)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

        out_q: queue.Queue = queue.Queue()
        err_q: queue.Queue = queue.Queue()

        def _reader(pipe, q: queue.Queue) -> None:
            try:
                for line in pipe:
                    q.put(line)
            finally:
                q.put(None)  # sentinel — pipe closed

        threading.Thread(target=_reader, args=(proc.stdout, out_q), daemon=True).start()
        threading.Thread(target=_reader, args=(proc.stderr, err_q), daemon=True).start()

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []
        start = time.monotonic()
        last_active = start
        out_alive = err_alive = True
        kill_reason: Optional[str] = None

        while out_alive or err_alive:
            now = time.monotonic()
            if now - start >= hard_cap:
                kill_reason = f"hard cap {hard_cap}s exceeded"
                break
            if now - last_active >= idle_timeout:
                kill_reason = f"no output for {idle_timeout}s (idle timeout)"
                break

            drained = False
            for q_pipe, parts, name in (
                (out_q, stdout_parts, "out"),
                (err_q, stderr_parts, "err"),
            ):
                while True:
                    try:
                        chunk = q_pipe.get_nowait()
                    except queue.Empty:
                        break
                    if chunk is None:
                        if name == "out":
                            out_alive = False
                        else:
                            err_alive = False
                    else:
                        parts.append(chunk)
                        last_active = time.monotonic()
                        drained = True

            if not drained:
                time.sleep(0.05)

        if kill_reason:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
            proc.wait()
            return CommandResult(
                False,
                "".join(stdout_parts),
                f"Command killed: {kill_reason}",
                124,
            )

        proc.wait()
        return CommandResult(
            success=proc.returncode == 0,
            output="".join(stdout_parts),
            error="".join(stderr_parts),
            returncode=proc.returncode,
        )

    # Seconds without a heartbeat update before the worker is considered stale.
    # Workers write every 30s; 120s allows ~3 missed beats before we kill early.
    _HEARTBEAT_STALE_SECONDS = 120

    def _run_with_heartbeat_monitor(
        self,
        cmd: List[str],
        timeout: int,
        *,
        input_text: str,
        heartbeat_path: str,
        stale_threshold: int = _HEARTBEAT_STALE_SECONDS,
        forward_credentials: bool = False,
    ) -> CommandResult:
        """Run a subprocess, killing it early if its heartbeat file goes stale.

        Uses Popen so we can poll both process state and the heartbeat file
        simultaneously, rather than blocking on subprocess.run() for the full
        timeout when the worker silently hangs.
        """
        env = self._subprocess_env(forward_credentials=forward_credentials)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            return CommandResult(False, "", str(exc), 1)

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []

        def _read_pipe(pipe: Any, parts: List[str]) -> None:
            try:
                for line in pipe:
                    parts.append(line)
            except (OSError, ValueError):
                pass

        def _write_stdin() -> None:
            try:
                proc.stdin.write(input_text)  # type: ignore[union-attr]
            except OSError:
                pass
            finally:
                try:
                    proc.stdin.close()  # type: ignore[union-attr]
                except OSError:
                    pass

        threading.Thread(target=_write_stdin, daemon=True).start()
        out_thread = threading.Thread(target=_read_pipe, args=(proc.stdout, stdout_parts), daemon=True)
        err_thread = threading.Thread(target=_read_pipe, args=(proc.stderr, stderr_parts), daemon=True)
        out_thread.start()
        err_thread.start()

        start_mono = time.monotonic()
        last_hb_at: Optional[float] = None
        kill_reason = ""

        def _kill(reason: str) -> None:
            nonlocal kill_reason
            kill_reason = reason
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass

        _POLL = 5
        while True:
            time.sleep(_POLL)
            elapsed = time.monotonic() - start_mono

            if proc.poll() is not None:
                break

            if elapsed >= timeout:
                _kill("Reasoning timeout")
                break

            # Read heartbeat_at from the progress file.
            try:
                with open(heartbeat_path) as _f:
                    hb = json.load(_f)
                hb_at = float(hb.get("heartbeat_at", 0))
                if hb_at > 0:
                    last_hb_at = hb_at
            except (OSError, json.JSONDecodeError, ValueError, KeyError):
                pass

            now = time.time()
            if last_hb_at is not None and (now - last_hb_at) > stale_threshold:
                _kill(
                    f"Reasoning worker heartbeat stale "
                    f"({int(now - last_hb_at)}s since last update)"
                )
                break
            elif last_hb_at is None and elapsed > stale_threshold + 60:
                _kill("Reasoning worker never wrote a heartbeat; possible crash or startup failure")
                break

        proc.wait()
        out_thread.join(timeout=5)
        err_thread.join(timeout=5)

        try:
            os.unlink(heartbeat_path)
        except OSError:
            pass

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts) or kill_reason
        if kill_reason:
            return CommandResult(False, stdout, stderr, 124)
        return CommandResult(proc.returncode == 0, stdout, stderr, proc.returncode)

    def git_status(self) -> CommandResult:
        return self._run(["git", "status", "--short"], timeout=10)

    def git_log_head(self) -> CommandResult:
        return self._run(["git", "log", "-1", "--oneline"], timeout=10)

    def create_branch(self, branch: str) -> CommandResult:
        if branch in {"main", "master"} or branch.startswith("-"):
            return CommandResult(False, "", "Refusing unsafe branch name", 2)
        return self._run(["git", "checkout", "-b", branch], timeout=30)

    def run_reasoning(
        self,
        goal: str,
        max_steps: int,
        initial_context: Dict[str, Any],
        timeout: int = 300,
        task_type: str = "code_reasoning",
        preferred_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        import tempfile
        hb_fd, heartbeat_path = tempfile.mkstemp(prefix="igris_reasoning_hb_", suffix=".json")
        os.close(hb_fd)
        payload = json.dumps({
            "project_root": str(self.project_root),
            "goal": goal,
            "max_steps": max_steps,
            "initial_context": initial_context,
            "task_type": task_type,
            "preferred_profile": preferred_profile,
            "heartbeat_path": heartbeat_path,
        })
        result = self._run_with_heartbeat_monitor(
            [str(self.project_root / ".venv/bin/python"), "-m", "igris.core.supervisor_reasoning_worker"],
            timeout=timeout,
            input_text=payload,
            heartbeat_path=heartbeat_path,
            forward_credentials=True,
        )
        if result.success:
            try:
                return json.loads(result.output)
            except json.JSONDecodeError:
                return {
                    "status": "blocked",
                    "stop_reason": "invalid_reasoning_output",
                    "files_modified": [],
                    "final_summary": _command_detail(result) or "Reasoning worker returned invalid JSON",
                }
        return {
            "status": "blocked",
            "stop_reason": "reasoning_timeout" if result.returncode == 124 else "blocked",
            "files_modified": [],
            "final_summary": _command_detail(result) or "Reasoning worker failed",
        }

    def git_diff_stat(self) -> CommandResult:
        # Use `git diff HEAD --stat` instead of bare `git diff --stat` so that
        # newly-created files that have been staged (git add) are included.
        # Bare `git diff --stat` only shows unstaged changes to *tracked* files;
        # `git diff HEAD --stat` captures all changes vs HEAD (staged or unstaged).
        return self._run(["git", "diff", "HEAD", "--stat"], timeout=10)

    def git_diff(self) -> CommandResult:
        # Mirror the broader HEAD-relative view used by git_diff_stat.
        return self._run(["git", "diff", "HEAD"], timeout=10)

    def run_tests(
        self,
        targets: Optional[List[str]] = None,
        timeout: int = 120,
        hard_cap: int = 3600,
        exclude_slow: bool = False,
    ) -> CommandResult:
        cmd = [str(self.project_root / ".venv/bin/python"), "-m", "pytest", "-q"]
        if exclude_slow:
            cmd.extend(["-m", "not slow"])
        if targets:
            cmd.extend(targets)
        return self._run_adaptive(cmd, idle_timeout=timeout, hard_cap=hard_cap, clean_env=True)

    def run_test_diagnostics(self, timeout: int = 120) -> CommandResult:
        cmd = [
            str(self.project_root / ".venv/bin/python"),
            "-m",
            "pytest",
            "-x",
            "-vv",
        ]
        return self._run_adaptive(cmd, idle_timeout=timeout, hard_cap=timeout * 5, clean_env=True)

    def smoke(self, endpoints: List[str], restart_command: str = "") -> CommandResult:
        if restart_command:
            allowed = {"sudo -n systemctl restart igris"}
            if restart_command not in allowed:
                return CommandResult(False, "", "Restart command is not allowlisted", 126)
            restart = self._run(["sudo", "-n", "systemctl", "restart", "igris"], timeout=30)
            if not restart.success:
                return restart
        outputs: List[str] = []
        for endpoint in endpoints:
            result = self._run(["curl", "-fsS", endpoint], timeout=15)
            outputs.append(result.output or result.error)
            if not result.success:
                return CommandResult(False, "\n".join(outputs), result.error, result.returncode)
            if not _smoke_output_is_valid(endpoint, result.output):
                return CommandResult(
                    False,
                    "\n".join(outputs),
                    f"Invalid bootstrap response for {endpoint}",
                    1,
                )
        return CommandResult(True, "\n".join(outputs), "", 0)

    def commit(self, message: str, files: Optional[List[str]] = None) -> CommandResult:
        if files:
            add = self._run(["git", "add", *files], timeout=30)
            if not add.success:
                return add
        result = self._run(["git", "commit", "-m", message], timeout=60)
        combined = (result.output or "") + (result.error or "")
        if not result.success and (
            "nothing to commit" not in combined
            and "not staged" in combined
        ):
            # Stage all tracked modified files and retry once.
            self._run(["git", "add", "-u"], timeout=30)
            result = self._run(["git", "commit", "-m", message], timeout=60)
            combined = (result.output or "") + (result.error or "")
        if not result.success and "nothing to commit" in combined:
            # Last-resort: stage ALL changes (including untracked in allowed dirs)
            # in case the earlier file-specific add missed something.
            self._run(["git", "add", "-A", "--", "igris", "tests", "docs"], timeout=30)
            result = self._run(["git", "commit", "-m", message], timeout=60)
        return result

    def push_branch(self, branch: str) -> CommandResult:
        if branch in {"main", "master"} or branch.startswith("-"):
            return CommandResult(False, "", "Refusing push to protected/unsafe branch", 2)
        return self._run(["git", "push", "origin", branch], timeout=120)

    def open_pr(self, branch: str, title: str, body: str) -> CommandResult:
        return self._run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body], timeout=120)

    def wait_ci(self) -> CommandResult:
        return self._run(["gh", "pr", "checks", "--watch"], timeout=900)

    def merge_pr(self) -> CommandResult:
        return self._run(["gh", "pr", "merge", "--squash", "--delete-branch"], timeout=120)

    def pull_main(self) -> CommandResult:
        checkout = self._run(["git", "checkout", "main"], timeout=30)
        if not checkout.success:
            return checkout
        return self._run(["git", "pull", "--rebase", "origin", "main"], timeout=120)

    def update_issue(self, issue_url: str, comment_body: str) -> CommandResult:
        return self._run(
            ["gh", "issue", "comment", issue_url, "--body", comment_body],
            timeout=60,
        )

    def create_issue(self, title: str, body: str) -> CommandResult:
        listed = self._run(
            ["gh", "issue", "list", "--state", "open", "--limit", "200", "--json", "title,url"],
            timeout=120,
        )
        if listed.success:
            try:
                open_issues = json.loads(listed.output or "[]")
                for issue in open_issues:
                    if str(issue.get("title", "")) == title:
                        return CommandResult(True, str(issue.get("url", "")), "", 0)
            except json.JSONDecodeError:
                pass
        return self._run(["gh", "issue", "create", "--title", title, "--body", body], timeout=120)

    def fetch_issue(self, issue_url: str) -> CommandResult:
        return self._run(
            ["gh", "issue", "view", issue_url, "--json", "title,body,number"],
            timeout=60,
        )

    def restore_dangerous_diff(self) -> CommandResult:
        restore = self._run(["git", "restore", "--worktree", "--staged", "."], timeout=60)
        if not restore.success:
            return restore
        # Remove untracked files left by a failed supervised branch.
        # igris/ and tests/ are excluded so that implementation files written by the
        # reasoning worker but not yet committed survive to the next attempt. Untracked
        # files are NOT affected by git branch switches (checkout main / create branch),
        # so any files preserved here carry forward automatically to the new rank branch.
        # This prevents IGRIS's work from being silently discarded when the reasoning
        # loop signals no_diff_repair because new files were never staged/committed.
        clean = self._run(["git", "clean", "-fd", "-e", "igris", "-e", "tests", "."], timeout=60)
        if not clean.success:
            return clean
        return CommandResult(True, restore.output + clean.output, "", 0)

    def checkout_main(self) -> CommandResult:
        """Switch back to main branch after a blocked/cancelled run."""
        return self._run(["git", "checkout", "main"], timeout=30)

    def delete_stale_rank_branches(self) -> CommandResult:
        """Delete all local rank-* branches left by previous supervised runs."""
        list_result = self._run(
            ["git", "branch", "--list", "rank-*"],
            timeout=15,
        )
        if not list_result.success:
            return list_result
        branches = [b.strip().lstrip("* ") for b in list_result.output.splitlines() if b.strip()]
        if not branches:
            return CommandResult(True, "no rank branches to delete", "", 0)
        deleted, errors = [], []
        for branch in branches:
            r = self._run(["git", "branch", "-D", branch], timeout=15)
            if r.success:
                deleted.append(branch)
            else:
                errors.append(branch)
        msg = f"deleted={deleted} errors={errors}"
        return CommandResult(True, msg, "", 0)

    def restore_paths(self, paths: List[str]) -> CommandResult:
        selected = []
        for raw in paths:
            path = str(raw or "").strip()
            if not path:
                continue
            if path.startswith("-") or path.startswith("/") or ".." in path.split("/"):
                return CommandResult(False, "", f"Refusing unsafe restore path: {path}", 2)
            selected.append(path)
        if not selected:
            return CommandResult(True, "", "", 0)
        restore = self._run(["git", "restore", "--worktree", "--staged", "--", *selected], timeout=60)
        if not restore.success:
            return restore
        clean = self._run(["git", "clean", "-f", "--", *selected], timeout=60)
        if not clean.success:
            return clean
        return CommandResult(True, (restore.output or "") + (clean.output or ""), "", 0)

    def call_api_helper(
        self,
        packet: Dict[str, Any],
        model: str,
        max_tokens: int,
        timeout: int = 45,
        mode: str = "",
    ) -> CommandResult:
        helper_command = str(os.getenv("IGRIS_API_HELPER_COMMAND", "")).strip()
        if not helper_command:
            return CommandResult(False, "", "API helper command is not configured.", 2)
        cmd = shlex.split(helper_command)
        if not cmd:
            return CommandResult(False, "", "API helper command is empty after parsing.", 2)

        # Shadow mode A/B (Epic #445): always call primary; call shadow in parallel for scoring.
        # Primary result is always returned — shadow is never used for decisions.
        alt_model = str(os.getenv("IGRIS_API_HELPER_ALT_MODEL", "")).strip()
        ab_enabled = (
            bool(alt_model)
            and str(os.getenv("IGRIS_ENABLE_HELPER_AB_TEST", "false")).lower() == "true"
        )
        shadow_mode = str(os.getenv("IGRIS_HELPER_AB_SHADOW_MODE", "true")).lower() != "false"

        # Call primary
        import time as _time
        primary_env: Dict[str, str] = {}
        if mode:
            primary_env["IGRIS_API_HELPER_MODE"] = mode
        primary_payload = json.dumps({"model": model, "max_tokens": max_tokens, "packet": packet})
        t0 = _time.monotonic()
        result = self._run(cmd, timeout=timeout, input_text=primary_payload, extra_env=primary_env or None)
        result.helper_primary_latency_ms = int((_time.monotonic() - t0) * 1000)
        result.helper_model = model
        result.helper_ab_active = ab_enabled
        result.helper_ab_alt_model = alt_model if ab_enabled else ""

        # Launch shadow call if enabled
        if ab_enabled and shadow_mode and alt_model:
            self._run_shadow_helper(
                cmd=cmd,
                alt_model=alt_model,
                packet=packet,
                max_tokens=max_tokens,
                timeout=timeout,
                primary_result=result,
            )

        return result

    def _run_shadow_helper(
        self,
        *,
        cmd,
        alt_model: str,
        packet,
        max_tokens: int,
        timeout: int,
        primary_result: "CommandResult",
    ) -> None:
        """Call shadow helper and score both. Non-fatal — never changes primary output."""
        try:
            import time as _time
            import json as _json
            from igris.core.helper_ab_eval import (
                score_helper_response,
                make_ab_record,
                save_ab_result,
                is_safe_to_switch,
                load_ab_results,
            )
            alt_provider = str(os.getenv("IGRIS_API_HELPER_ALT_PROVIDER", "deepseek")).strip()
            shadow_env = {
                "IGRIS_API_HELPER_MODE": "auto",
                "IGRIS_API_HELPER_PROVIDER": alt_provider,
                # Override model so _resolve_model doesn't forward the Codex name to DeepSeek
                "IGRIS_API_HELPER_MODEL": alt_model,
                "IGRIS_HELPER_AB_ARM": "alt",
            }
            shadow_payload = _json.dumps({"model": alt_model, "max_tokens": max_tokens, "packet": packet})
            t0 = _time.monotonic()
            shadow_result = self._run(cmd, timeout=timeout, input_text=shadow_payload, extra_env=shadow_env)
            alt_latency_ms = int((_time.monotonic() - t0) * 1000)

            try:
                primary_parsed = _json.loads(primary_result.output) if primary_result.output else {}
            except _json.JSONDecodeError:
                primary_parsed = {}
            try:
                alt_parsed = _json.loads(shadow_result.output) if shadow_result.output else {}
            except _json.JSONDecodeError:
                alt_parsed = {}

            empty_case: Dict[str, Any] = {}
            primary_score_r = score_helper_response(primary_parsed, empty_case)
            alt_score_r = score_helper_response(alt_parsed, empty_case)
            primary_cost = float(primary_parsed.get("estimated_cost_usd", 0.0))
            alt_cost = float(alt_parsed.get("estimated_cost_usd", 0.0))

            record = make_ab_record(
                case_id=str(packet.get("failure_class", "unknown")),
                primary_model=primary_result.helper_model,
                alt_model=alt_model,
                primary_score=primary_score_r["total"],
                alt_score=alt_score_r["total"],
                primary_breakdown=primary_score_r["breakdown"],
                alt_breakdown=alt_score_r["breakdown"],
                primary_cost_usd=primary_cost,
                alt_cost_usd=alt_cost,
                primary_latency_ms=primary_result.helper_primary_latency_ms,
                alt_latency_ms=alt_latency_ms,
                source="organic_run",
                # Model identity from provider responses
                primary_requested_model=str(primary_parsed.get("api_helper_model_requested", "") or ""),
                primary_resolved_model=str(primary_parsed.get("api_helper_model_resolved", "") or ""),
                primary_provider_response_model=str(primary_parsed.get("model", "") or ""),
                primary_served_model=str(primary_parsed.get("model", "") or ""),
                primary_provider=str(primary_parsed.get("api_helper_provider", "") or ""),
                alt_requested_model=str(alt_parsed.get("api_helper_model_requested", alt_model) or ""),
                alt_resolved_model=str(alt_parsed.get("api_helper_model_resolved", "") or ""),
                alt_provider_response_model=str(alt_parsed.get("model", "") or ""),
                alt_served_model=str(alt_parsed.get("model", "") or ""),
                alt_provider=str(alt_parsed.get("api_helper_provider", alt_provider) or ""),
                api_helper_mode=str(primary_parsed.get("api_helper_mode", "") or ""),
            )
            ab_path = str(os.getenv("IGRIS_HELPER_AB_RESULTS_PATH", ".igris/helper_ab_results.json"))
            save_ab_result(record, ab_path)
            all_records = load_ab_results(ab_path)
            sw_report = is_safe_to_switch(all_records)
            safe = sw_report["safe_to_switch"]

            primary_result.helper_ab_shadow_mode = True
            primary_result.helper_primary_score = primary_score_r["total"]
            primary_result.helper_alt_score = alt_score_r["total"]
            primary_result.helper_primary_cost_usd = primary_cost
            primary_result.helper_alt_cost_usd = alt_cost
            primary_result.helper_alt_latency_ms = alt_latency_ms
            primary_result.helper_switch_recommendation = safe
        except Exception:
            pass  # shadow mode is non-fatal

    def api_helper_is_configured(self) -> bool:
        """Return True when IGRIS_API_HELPER_COMMAND env var is set and non-empty."""
        return bool(str(os.getenv("IGRIS_API_HELPER_COMMAND", "")).strip())


