from igris.core.agent_reasoning_loop import AgentReasoningLoop, LoopResult


def test_ltm_hydration_adds_memory_items(tmp_path):
    loop = AgentReasoningLoop(project_root=str(tmp_path), task_type="code_reasoning")
    loop._init_long_term_memory()
    assert loop._ltm is not None
    loop._ltm.store(domain="code_reasoning", content="pytest failure fixed", tags=["pytest"])

    loop._hydrate_long_term_memory_context("fix pytest failure")
    assert loop._world_state.get("ltm_hydrated") is True
    assert any(item.get("event_type") == "long_term_memory" for item in loop._ltm_context_items)


def test_ltm_persist_outcome(tmp_path):
    loop = AgentReasoningLoop(project_root=str(tmp_path), task_type="code_reasoning")
    loop._init_long_term_memory()
    result = LoopResult(goal="add tests", status="finished", stop_reason="finish", total_steps=3, successful_steps=3)

    loop._persist_long_term_memory_outcome(goal="add tests", result=result)
    entries = loop._ltm.get_entries("code_reasoning", limit=5)
    assert len(entries) >= 1
    assert any("add tests" in str(e.content) for e in entries)
