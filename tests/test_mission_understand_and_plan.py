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


def test_understand_and_plan_architecture_request_updates_existing_mission():
    base = Mission(project="igrisgpt", user_input="old")
    mission = understand_and_plan(
        user_input="Progetta l'architettura mission brain per evitare loop di recovery",
        project="igrisgpt",
        mission=base,
    )
    assert mission is base
    assert "[architecture]" in mission.intent_summary
    assert all(req.verification_method for req in mission.requirements)
    assert not any("pulito" in item.description.lower() for item in mission.checklist)

