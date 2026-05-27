from igris.agent.mission import Mission, understand_and_plan


def test_understand_and_plan_simple_request():
    mission = understand_and_plan(
        user_input="Verifica i test del modulo missione",
        project="igrisgpt",
    )
    assert mission.status == "understand_planned"
    assert mission.requirements
    assert mission.checklist
    assert len(mission.checklist) == 1
    decomp = mission.context_snapshot["intent_decomposition"]
    assert decomp["request_shape"] == "simple"
    assert decomp["what"] != "unknown"
    assert "why" in decomp


def test_understand_and_plan_multi_step_request():
    mission = understand_and_plan(
        user_input=(
            "Modifica il planner, aggiungi test di regressione e aggiorna il report finale "
            "con evidenze verificabili."
        ),
        project="igrisgpt",
        repo_view={"changed_files": ["igris/core/mission_planner.py"]},
    )
    assert mission.status == "understand_planned"
    assert len(mission.requirements) >= 3
    assert len(mission.plan) >= 3
    assert all(item.linked_requirement for item in mission.checklist)
    decomp = mission.context_snapshot["intent_decomposition"]
    assert decomp["request_shape"] == "multi_step"
    assert decomp["where"] != ["unknown"]


def test_understand_and_plan_architecture_request_updates_existing_mission():
    base = Mission(project="igrisgpt", user_input="old")
    mission = understand_and_plan(
        user_input="Progetta l'architettura mission brain per evitare loop di recovery",
        project="igrisgpt",
        mission=base,
    )
    assert mission is base
    assert "[architecture|architectural]" in mission.intent_summary
    assert all(req.verification_method for req in mission.requirements)
    assert not any("pulito" in item.description.lower() for item in mission.checklist)
    assert mission.context_snapshot["intent_decomposition"]["why"] in {
        "improve_system_design",
        "unknown",
        "per evitare loop di recovery",
    }


def test_understand_and_plan_ambiguous_request_marks_unknowns():
    mission = understand_and_plan(
        user_input="Sistema tutto quello che non va",
        project="igrisgpt",
    )
    decomp = mission.context_snapshot["intent_decomposition"]
    assert decomp["request_shape"] == "ambiguous"
    assert "where" in decomp["unknowns"]
    assert any(req.verification_method == "unknowns_explicitly_marked_check" for req in mission.requirements)


def test_understand_and_plan_diagnosis_and_constraints():
    mission = understand_and_plan(
        user_input="Diagnostica il bug in igris/core/mission_planner.py senza cambiare API pubbliche",
        project="igrisgpt",
    )
    decomp = mission.context_snapshot["intent_decomposition"]
    assert decomp["intent_type"] == "diagnosis"
    assert "igris/core/mission_planner.py" in decomp["where"]
    assert "contains_without_constraint" in decomp["constraints"]
