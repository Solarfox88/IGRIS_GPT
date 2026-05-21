#!/usr/bin/env python3
"""
Evaluate whether a candidate helper model can replace the primary.

Usage:
    python scripts/evaluate_helper_replacement.py \
        --primary gpt-5.3-codex \
        --candidate deepseek-v4-pro \
        --fixtures tests/fixtures/helper_eval \
        --out .igris/helper_ab_results.json

Exit codes:
    0  — evaluation complete (candidate may win or lose — no auto-switch)
    2  — infrastructure error (helper misconfigured, fixtures missing, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from igris.core.helper_ab_eval import (
    score_helper_response,
    make_ab_record,
    save_ab_result,
    is_safe_to_switch,
    SCORE_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helper invocation
# ---------------------------------------------------------------------------

def _call_helper(
    cmd: List[str],
    model: str,
    provider: str,
    mode: str,
    packet: Dict[str, Any],
    max_tokens: int,
    timeout: int,
    extra_env: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], float, int, str]:
    """Call the helper subprocess and return (parsed_response, cost, latency_ms, error)."""
    env = {**os.environ, **extra_env}
    payload = json.dumps({"model": model, "max_tokens": max_tokens, "packet": packet})
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        if proc.returncode not in (0, 1):
            return None, 0.0, latency_ms, f"helper exit {proc.returncode}: {proc.stderr[:200]}"
        try:
            parsed = json.loads(proc.stdout)
            cost = float(parsed.get("estimated_cost_usd", 0.0))
            return parsed, cost, latency_ms, ""
        except json.JSONDecodeError as exc:
            return None, 0.0, latency_ms, f"invalid JSON: {exc}"
    except subprocess.TimeoutExpired:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return None, 0.0, latency_ms, f"timeout after {timeout}s"
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return None, 0.0, latency_ms, str(exc)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _fmt(v: float, digits: int = 3) -> str:
    return f"{v:.{digits}f}"


def _print_table(rows: List[Dict[str, Any]], primary: str, candidate: str) -> None:
    header = f"{'case_id':<45} {'p_score':>7} {'c_score':>7} {'p_cost':>9} {'c_cost':>9} {'winner':<8} {'valid'}"
    print()
    print(header)
    print("-" * len(header))
    for r in rows:
        validity = r.get("ab_validity", "valid")
        print(
            f"{r['case_id']:<45} "
            f"{_fmt(r['primary_score']):>7} "
            f"{_fmt(r['alt_score']):>7} "
            f"${_fmt(r['primary_cost_usd'], 6):>8} "
            f"${_fmt(r['alt_cost_usd'], 6):>8} "
            f"{r['winner']:<8} "
            f"{validity}"
        )
    print()

    if rows:
        valid_rows = [r for r in rows if r.get("ab_validity", "valid") != "model_mismatch"]
        mismatch_rows = [r for r in rows if r.get("ab_validity") == "model_mismatch"]
        avg_p = sum(r["primary_score"] for r in rows) / len(rows)
        avg_c = sum(r["alt_score"] for r in rows) / len(rows)
        tot_p = sum(r["primary_cost_usd"] for r in rows)
        tot_c = sum(r["alt_cost_usd"] for r in rows)
        wins_p = sum(1 for r in rows if r["winner"] == "primary")
        wins_c = sum(1 for r in rows if r["winner"] == "alt")
        ties = sum(1 for r in rows if r["winner"] == "tie")

        print(f"Summary: {len(rows)} cases ({len(valid_rows)} valid, {len(mismatch_rows)} model_mismatch)")
        print(f"  {primary:>30}: avg_score={_fmt(avg_p)}  total_cost=${_fmt(tot_p, 6)}  wins={wins_p}")
        print(f"  {candidate:>30}: avg_score={_fmt(avg_c)}  total_cost=${_fmt(tot_c, 6)}  wins={wins_c}")
        print(f"  ties={ties}")
        print()

        # Score breakdown averages per dimension
        bd_keys = list(SCORE_WEIGHTS.keys()) + ["anti_generic_penalty"]
        print(f"  {'dimension':<40} {'primary':>8} {'candidate':>10}")
        print(f"  {'-'*60}")
        for key in bd_keys:
            p_avg = sum(r.get("primary_breakdown", {}).get(key, 0.0) for r in rows) / len(rows)
            c_avg = sum(r.get("alt_breakdown", {}).get(key, 0.0) for r in rows) / len(rows)
            print(f"  {key:<40} {_fmt(p_avg):>8} {_fmt(c_avg):>10}")
        print()


def _print_switch_report(sw: Dict[str, Any], rows: List[Dict[str, Any]], primary: str, candidate: str) -> None:
    """Print detailed switch recommendation report."""
    print("=" * 70)
    print("SWITCH RECOMMENDATION REPORT")
    print("=" * 70)

    # Model identity summary
    p_models = {(r.get("primary_requested_model", ""), r.get("primary_resolved_model", ""),
                  r.get("primary_served_model", "")) for r in rows}
    a_models = {(r.get("alt_requested_model", ""), r.get("alt_resolved_model", ""),
                  r.get("alt_served_model", "")) for r in rows}
    print(f"\nModel identity:")
    print(f"  primary requested/resolved/served:")
    for req, res, srv in sorted(p_models):
        print(f"    requested={req or 'N/A'!r}  resolved={res or 'N/A'!r}  served={srv or 'N/A'!r}")
    print(f"  alt requested/resolved/served:")
    for req, res, srv in sorted(a_models):
        print(f"    requested={req or 'N/A'!r}  resolved={res or 'N/A'!r}  served={srv or 'N/A'!r}")

    # Record counts
    print(f"\nRecord counts:")
    print(f"  organic valid  : {sw['organic_count']}")
    print(f"  model_mismatch : {sw.get('model_mismatch_count', 0)}")
    print(f"  synthetic      : {sw['synthetic_count']}")
    print(f"  failure_classes: {sw['failure_classes_covered']}")

    # Downstream usefulness
    ds_known = [r for r in rows if r.get("downstream", {}).get("next_run_outcome", "unknown") != "unknown"]
    print(f"\nDownstream usefulness: {len(ds_known)}/{len(rows)} records with known outcome")
    if ds_known:
        outcomes: Dict[str, int] = {}
        for r in ds_known:
            o = r.get("downstream", {}).get("next_run_outcome", "unknown")
            outcomes[o] = outcomes.get(o, 0) + 1
        for outcome, count in sorted(outcomes.items()):
            print(f"  {outcome}: {count}")

    # Gate results
    print(f"\nGate evaluation:")
    for reason in sw["reasons"]:
        if reason.endswith("✓"):
            print(f"  ✓ {reason}")
        else:
            print(f"  ✗ {reason}")

    print(f"\n{'safe_to_switch = TRUE' if sw['safe_to_switch'] else 'safe_to_switch = FALSE'}")
    if not sw["safe_to_switch"] and sw.get("reason_if_not_safe"):
        print(f"Blockers: {sw['reason_if_not_safe']}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def evaluate(args: argparse.Namespace) -> int:
    fixture_dir = Path(args.fixtures)
    if not fixture_dir.is_dir():
        print(f"ERROR: fixtures directory not found: {fixture_dir}", file=sys.stderr)
        return 2

    fixture_files = sorted(fixture_dir.glob("*.json"))
    if not fixture_files:
        print(f"ERROR: no .json fixture files found in {fixture_dir}", file=sys.stderr)
        return 2

    helper_command = str(os.getenv("IGRIS_API_HELPER_COMMAND", "")).strip()
    if not helper_command:
        print("ERROR: IGRIS_API_HELPER_COMMAND is not set", file=sys.stderr)
        return 2

    cmd = shlex.split(helper_command)
    max_tokens = int(args.max_tokens)
    timeout = int(args.timeout)

    primary_env: Dict[str, str] = {}
    if args.primary_mode:
        primary_env["IGRIS_API_HELPER_MODE"] = args.primary_mode
    if args.primary_provider:
        primary_env["IGRIS_API_HELPER_PROVIDER"] = args.primary_provider

    candidate_env: Dict[str, str] = {
        "IGRIS_API_HELPER_MODE": "auto",
        "IGRIS_API_HELPER_PROVIDER": args.candidate_provider,
        "IGRIS_HELPER_AB_ARM": "alt",
    }

    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    print(f"\nEvaluating {len(fixture_files)} cases")
    print(f"  primary:   {args.primary} (provider={args.primary_provider or 'auto'})")
    print(f"  candidate: {args.candidate} (provider={args.candidate_provider})")

    for fixture_path in fixture_files:
        try:
            case = json.loads(fixture_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{fixture_path.name}: {exc}")
            continue

        case_id = case.get("case_id", fixture_path.stem)
        packet = {
            "failure_class": case.get("failure_class", ""),
            "goal": case.get("goal", ""),
            "repair_cycles_used": 1,
            "capability_signals": {},
            "events": case.get("recent_events", []),
        }

        print(f"  [{case_id}] calling primary... ", end="", flush=True)
        primary_resp, primary_cost, primary_latency, primary_err = _call_helper(
            cmd, args.primary, args.primary_provider or "", args.primary_mode or "",
            packet, max_tokens, timeout, primary_env,
        )
        if primary_err:
            print(f"ERROR: {primary_err}")
            errors.append(f"{case_id} primary: {primary_err}")
            primary_resp = {}
        else:
            print(f"ok ({primary_latency}ms, ${primary_cost:.6f})")

        print(f"  [{case_id}] calling candidate...", end="", flush=True)
        candidate_resp, candidate_cost, candidate_latency, candidate_err = _call_helper(
            cmd, args.candidate, args.candidate_provider, "auto",
            packet, max_tokens, timeout, candidate_env,
        )
        if candidate_err:
            print(f"ERROR: {candidate_err}")
            errors.append(f"{case_id} candidate: {candidate_err}")
            candidate_resp = {}
        else:
            print(f"ok ({candidate_latency}ms, ${candidate_cost:.6f})")

        primary_resp = primary_resp or {}
        candidate_resp = candidate_resp or {}

        primary_score_r = score_helper_response(primary_resp, case)
        candidate_score_r = score_helper_response(candidate_resp, case)

        record = make_ab_record(
            case_id=case_id,
            primary_model=args.primary,
            alt_model=args.candidate,
            primary_score=primary_score_r["total"],
            alt_score=candidate_score_r["total"],
            primary_breakdown=primary_score_r["breakdown"],
            alt_breakdown=candidate_score_r["breakdown"],
            primary_cost_usd=primary_cost,
            alt_cost_usd=candidate_cost,
            primary_latency_ms=primary_latency,
            alt_latency_ms=candidate_latency,
            source="synthetic_fixture",
            primary_requested_model=str(primary_resp.get("api_helper_model_requested", args.primary) or ""),
            primary_resolved_model=str(primary_resp.get("api_helper_model_resolved", "") or ""),
            primary_provider_response_model=str(primary_resp.get("model", "") or ""),
            primary_served_model=str(primary_resp.get("model", "") or ""),
            primary_provider=str(primary_resp.get("api_helper_provider", args.primary_provider) or ""),
            alt_requested_model=str(candidate_resp.get("api_helper_model_requested", args.candidate) or ""),
            alt_resolved_model=str(candidate_resp.get("api_helper_model_resolved", "") or ""),
            alt_provider_response_model=str(candidate_resp.get("model", "") or ""),
            alt_served_model=str(candidate_resp.get("model", "") or ""),
            alt_provider=str(candidate_resp.get("api_helper_provider", args.candidate_provider) or ""),
            api_helper_mode=args.primary_mode or "",
        )
        rows.append(record)

        try:
            save_ab_result(record, args.out)
        except Exception as exc:
            errors.append(f"{case_id} persist: {exc}")

    _print_table(rows, args.primary, args.candidate)

    sw = is_safe_to_switch(rows)
    _print_switch_report(sw, rows, args.primary, args.candidate)

    if errors:
        print(f"\nErrors ({len(errors)}):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        if len(errors) == len(fixture_files) * 2:
            return 2

    print(f"\nResults saved to: {args.out}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evaluate whether candidate helper can replace primary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--primary", default="gpt-5.3-codex", help="Primary model name")
    p.add_argument("--candidate", default="deepseek-v4-pro", help="Candidate model name")
    p.add_argument("--primary-provider", default="", dest="primary_provider",
                   help="Primary provider (openai/anthropic/deepseek). Default: auto")
    p.add_argument("--primary-mode", default="codex_only", dest="primary_mode",
                   help="Primary helper mode. Default: codex_only")
    p.add_argument("--candidate-provider", default="deepseek", dest="candidate_provider",
                   help="Candidate provider. Default: deepseek")
    p.add_argument("--fixtures", default="tests/fixtures/helper_eval",
                   help="Directory of fixture JSON files")
    p.add_argument("--out", default=".igris/helper_ab_results.json",
                   help="Output file for AB results")
    p.add_argument("--max-tokens", default=800, type=int, dest="max_tokens",
                   help="Max tokens per call. Default: 800")
    p.add_argument("--timeout", default=60, type=int,
                   help="Timeout per call in seconds. Default: 60")
    return p


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(evaluate(args))
