from igris.core.failure_memory import FailureMemory


def test_record_with_files_updates_file_patterns(tmp_path):
    fm = FailureMemory(store_path=tmp_path / "failure_patterns.json")
    fm.record("goal", "blocked", files_touched=["igris/core/self_repair_supervisor.py"])
    assert "igris/core/self_repair_supervisor.py" in fm._file_patterns


def test_check_returns_file_risks(tmp_path):
    fm = FailureMemory(store_path=tmp_path / "failure_patterns.json")
    for _ in range(3):
        fm.record("goal", "blocked", files_touched=["a.py"])
    risk = fm.check("goal")
    assert risk.file_risks.get("a.py") == "high"
