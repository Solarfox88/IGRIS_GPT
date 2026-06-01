from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MemoryGCPolicy:
    max_age_days: int = 90
    min_importance: float = 0.4
    stale_only: bool = False
    include_contradictions: bool = True
    include_duplicates: bool = True
    dry_run: bool = True
    require_confirmation: bool = True
    archive_before_delete: bool = True


@dataclass
class MemoryGCCandidate:
    id: str
    domain: str
    reason: str
    risk: str
    age_days: float
    importance: float
    stale: bool
    contradiction: bool
    duplicate_of: Optional[str]
    action: str


@dataclass
class MemoryGCReport:
    dry_run: bool
    candidates: List[MemoryGCCandidate]
    kept_count: int
    archive_count: int
    delete_candidate_count: int
    warnings: List[str]
    audit_id: str
    created_at: float
    report_id: str
    policy_fingerprint: str


@dataclass
class MemoryGCApplyResult:
    applied: bool
    audit_id: str
    archived: int
    deleted: int
    skipped: int
    warnings: List[str] = field(default_factory=list)


class MemoryGarbageCollector:
    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root)
        self.memory_dir = self.project_root / ".igris" / "memory"
        self.db_path = self.memory_dir / "graph.db"
        self.audit_path = self.memory_dir / "gc_audit.jsonl"
        self.archive_path = self.memory_dir / "gc_archive.jsonl"
        self._issued_reports: Dict[str, Dict[str, Any]] = {}

    def _policy_fingerprint(self, policy: MemoryGCPolicy) -> str:
        payload = {
            "max_age_days": policy.max_age_days,
            "min_importance": policy.min_importance,
            "stale_only": policy.stale_only,
            "include_contradictions": policy.include_contradictions,
            "include_duplicates": policy.include_duplicates,
            "dry_run": policy.dry_run,
            "require_confirmation": policy.require_confirmation,
            "archive_before_delete": policy.archive_before_delete,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _append_jsonl(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _safe_importance(self, row: Dict[str, Any]) -> float:
        try:
            conf = float(row.get("confidence", 0.0) or 0.0)
        except Exception:
            conf = 0.0
        try:
            sr = float(row.get("success_rate", 0.0) or 0.0)
        except Exception:
            sr = 0.0
        content = row.get("content")
        if isinstance(content, dict):
            raw = content.get("importance")
            if raw is not None:
                try:
                    return max(0.0, min(1.0, float(raw)))
                except Exception:
                    pass
        score = (max(0.0, min(1.0, conf)) + max(0.0, min(1.0, sr))) / 2.0
        return max(0.0, min(1.0, score))

    def _is_recent(self, row: Dict[str, Any], now: float, max_age_days: int) -> bool:
        updated_at = row.get("updated_at")
        if updated_at is None:
            return True
        try:
            age_days = (now - float(updated_at)) / 86400.0
            return age_days < float(max_age_days)
        except Exception:
            return True

    def _age_days(self, row: Dict[str, Any], now: float) -> float:
        try:
            return max(0.0, (now - float(row.get("updated_at", now))) / 86400.0)
        except Exception:
            return 0.0

    def _safe_updated_at(self, row: Dict[str, Any], now: float) -> float:
        try:
            return float(row.get("updated_at", now) or now)
        except Exception:
            return now

    def _load_rows(self) -> tuple[List[Dict[str, Any]], List[str]]:
        import sqlite3

        warnings: List[str] = []
        if not self.db_path.exists():
            warnings.append("memory_db_missing")
            return [], warnings
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        rows: List[Dict[str, Any]] = []
        try:
            raw = conn.execute(
                "SELECT node_id,node_type,content,confidence,success_rate,created_at,updated_at,tags FROM memory_nodes"
            ).fetchall()
            for r in raw:
                item = dict(r)
                try:
                    item["content"] = json.loads(item.get("content") or "{}")
                except Exception:
                    warnings.append(f"corrupt_content:{item.get('node_id')}")
                    item["content"] = None
                try:
                    item["tags"] = json.loads(item.get("tags") or "[]")
                except Exception:
                    warnings.append(f"corrupt_tags:{item.get('node_id')}")
                    item["tags"] = []
                rows.append(item)
            return rows, warnings
        finally:
            conn.close()

    def scan(self, policy: MemoryGCPolicy) -> MemoryGCReport:
        now = time.time()
        rows, warnings = self._load_rows()
        candidates: List[MemoryGCCandidate] = []
        kept_count = 0
        duplicate_index: Dict[str, str] = {}

        for row in sorted(rows, key=lambda x: self._safe_updated_at(x, now), reverse=True):
            node_id = str(row.get("node_id", ""))
            node_type = str(row.get("node_type", "unknown"))
            content = row.get("content")
            tags = row.get("tags") if isinstance(row.get("tags"), list) else []
            if not node_id:
                kept_count += 1
                continue
            if not isinstance(content, dict):
                kept_count += 1
                continue

            importance = self._safe_importance(row)
            recent = self._is_recent(row, now, policy.max_age_days)
            stale = bool("stale" in tags) or not recent
            contradiction = bool("contradicted" in tags)
            dup_of: Optional[str] = None
            duplicate = False
            if policy.include_duplicates:
                key = hashlib.sha256(
                    json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                if key in duplicate_index:
                    duplicate = True
                    dup_of = duplicate_index[key]
                else:
                    duplicate_index[key] = node_id

            protected = recent or importance >= float(policy.min_importance)
            if protected:
                kept_count += 1
                continue
            if policy.stale_only and not stale:
                kept_count += 1
                continue

            reasons: List[str] = []
            if stale:
                reasons.append("stale")
            if contradiction and policy.include_contradictions:
                reasons.append("contradiction")
            if duplicate:
                reasons.append("duplicate")

            if not reasons:
                kept_count += 1
                continue

            candidates.append(
                MemoryGCCandidate(
                    id=node_id,
                    domain=node_type,
                    reason="+".join(reasons),
                    risk="low" if stale else "medium",
                    age_days=self._age_days(row, now),
                    importance=importance,
                    stale=stale,
                    contradiction=contradiction,
                    duplicate_of=dup_of,
                    action="delete_candidate",
                )
            )

        audit_id = f"gc_scan_{uuid.uuid4().hex[:12]}"
        report = MemoryGCReport(
            dry_run=bool(policy.dry_run),
            candidates=candidates,
            kept_count=kept_count,
            archive_count=len(candidates) if policy.archive_before_delete else 0,
            delete_candidate_count=len(candidates),
            warnings=warnings,
            audit_id=audit_id,
            created_at=now,
            report_id=uuid.uuid4().hex,
            policy_fingerprint=self._policy_fingerprint(policy),
        )
        self._issued_reports[report.report_id] = {
            "created_at": now,
            "policy_fp": report.policy_fingerprint,
            "consumed": False,
        }
        try:
            self._append_jsonl(
                self.audit_path,
                {
                    "ts": now,
                    "audit_id": audit_id,
                    "kind": "scan",
                    "dry_run": report.dry_run,
                    "candidate_count": len(candidates),
                    "warnings": list(warnings),
                    "report_id": report.report_id,
                },
            )
        except Exception:
            report.warnings.append("audit_write_failed")
        return report

    def _archive_candidates(self, candidates: List[MemoryGCCandidate]) -> bool:
        now = time.time()
        try:
            for c in candidates:
                self._append_jsonl(
                    self.archive_path,
                    {
                        "ts": now,
                        "node_id": c.id,
                        "domain": c.domain,
                        "reason": c.reason,
                        "risk": c.risk,
                        "age_days": c.age_days,
                        "importance": c.importance,
                        "stale": c.stale,
                        "contradiction": c.contradiction,
                        "duplicate_of": c.duplicate_of,
                    },
                )
            return True
        except Exception:
            return False

    def apply(self, report: MemoryGCReport, confirmation_token: str) -> MemoryGCApplyResult:
        if report.dry_run:
            return MemoryGCApplyResult(
                applied=False,
                audit_id=f"gc_apply_{uuid.uuid4().hex[:12]}",
                archived=0,
                deleted=0,
                skipped=len(report.candidates),
                warnings=["apply_blocked_dry_run_report"],
            )
        state = self._issued_reports.get(report.report_id)
        if not state:
            return MemoryGCApplyResult(False, f"gc_apply_{uuid.uuid4().hex[:12]}", 0, 0, len(report.candidates), ["unknown_report"])
        if state.get("consumed"):
            return MemoryGCApplyResult(False, f"gc_apply_{uuid.uuid4().hex[:12]}", 0, 0, len(report.candidates), ["report_already_used"])
        if time.time() - float(state.get("created_at", 0.0)) > 600:
            return MemoryGCApplyResult(False, f"gc_apply_{uuid.uuid4().hex[:12]}", 0, 0, len(report.candidates), ["stale_report"])
        if confirmation_token != "approved":
            return MemoryGCApplyResult(False, f"gc_apply_{uuid.uuid4().hex[:12]}", 0, 0, len(report.candidates), ["confirmation_required"])

        audit_id = f"gc_apply_{uuid.uuid4().hex[:12]}"
        archived = 0
        deleted = 0
        skipped = 0
        warnings: List[str] = []

        if report.archive_count > 0:
            if not self._archive_candidates(report.candidates):
                warnings.append("archive_failed_no_delete_performed")
                return MemoryGCApplyResult(False, audit_id, 0, 0, len(report.candidates), warnings)
            archived = len(report.candidates)

        import sqlite3

        if not self.db_path.exists():
            warnings.append("memory_db_missing")
            return MemoryGCApplyResult(False, audit_id, archived, 0, len(report.candidates), warnings)

        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                for c in report.candidates:
                    cur = conn.execute("DELETE FROM memory_nodes WHERE node_id=?", (c.id,))
                    if int(cur.rowcount or 0) > 0:
                        deleted += 1
                    else:
                        skipped += 1
            state["consumed"] = True
        except Exception:
            warnings.append("delete_failed")
        finally:
            conn.close()

        try:
            self._append_jsonl(
                self.audit_path,
                {
                    "ts": time.time(),
                    "audit_id": audit_id,
                    "kind": "apply",
                    "report_id": report.report_id,
                    "archived": archived,
                    "deleted": deleted,
                    "skipped": skipped,
                    "warnings": warnings,
                },
            )
        except Exception:
            warnings.append("audit_write_failed")

        return MemoryGCApplyResult(
            applied=(deleted > 0 or archived > 0),
            audit_id=audit_id,
            archived=archived,
            deleted=deleted,
            skipped=skipped,
            warnings=warnings,
        )
