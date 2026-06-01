from pathlib import Path

from fastapi.testclient import TestClient

from igris.core.long_term_memory import LongTermMemory
from igris.models.config import CONFIG
from igris.web.server import create_app


def _seed_ltm(project_root: Path) -> None:
    ltm_dir = project_root / ".igris" / "memory" / "long_term"
    ltm = LongTermMemory(storage_dir=str(ltm_dir))
    ltm.store(domain="code_reasoning", content="fixed flaky pytest failure", tags=["pytest", "fix"])
    ltm.store(domain="code_reasoning", content="added endpoint /api/ping", tags=["api"])


def test_long_term_search_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "project_root", tmp_path)
    _seed_ltm(tmp_path)
    c = TestClient(create_app())

    r = c.get("/api/memory/long-term/search", params={"q": "pytest", "domain": "code_reasoning"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert body["domain"] == "code_reasoning"


def test_long_term_summarize_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "project_root", tmp_path)
    _seed_ltm(tmp_path)
    c = TestClient(create_app())

    r = c.get("/api/memory/long-term/summarize", params={"domain": "code_reasoning", "force": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == "code_reasoning"
    assert isinstance(body["summary"], str)
