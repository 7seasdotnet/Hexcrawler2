from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    END_LOCAL_ENCOUNTER_INTENT,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
    EncounterActionExecutionModule,
    LocalEncounterInstanceModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.world import HexCoord


def _build_phase6d_contract_sim(seed: int = 606) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(EncounterActionExecutionModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    x, y = axial_to_world_xy(HexCoord(q=0, r=0))
    sim.add_entity(EntityState(entity_id=DEFAULT_PLAYER_ENTITY_ID, position_x=x, position_y=y, space_id="overworld"))
    return sim


def _local_encounter_execute_params(source_event_id: str) -> dict[str, object]:
    return {
        "source_event_id": source_event_id,
        "tick": 7,
        "context": "global",
        "trigger": "travel",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        "roll": 22,
        "category": "hostile",
        "table_id": "basic_encounters",
        "entry_id": "scavenger_patrol",
        "entry_tags": ["patrol"],
        "actions": [
            {
                "action_type": "local_encounter_intent",
                "template_id": "default_arena_v1",
                "params": {"suggested_local_template_id": "default_arena_v1"},
            }
        ],
    }


def _trace_by_type(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_phase6d_encounter_to_arena_binding_contract_roundtrip() -> None:
    sim = _build_phase6d_contract_sim(seed=606)

    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
        params=_local_encounter_execute_params(source_event_id="evt-phase6d-enter"),
    )
    sim.advance_ticks(5)

    begin_events = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    assert len(begin_events) == 1
    begin = begin_events[0]["params"]
    local_space_id = begin["to_space_id"]
    assert isinstance(local_space_id, str) and local_space_id.startswith("local_encounter:")
    assert sim.state.entities[DEFAULT_PLAYER_ENTITY_ID].space_id == local_space_id
    assert sim.state.world.spaces[local_space_id].role == "local"
    assert begin["template_id"] == "default_arena_v1"

    request_events_before_nested = _trace_by_type(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE)
    assert len(request_events_before_nested) == 1

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
        params=_local_encounter_execute_params(source_event_id="evt-phase6d-nested"),
    )
    sim.advance_ticks(4)

    request_events_after_nested = _trace_by_type(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE)
    assert len(request_events_after_nested) == 1

    rejection_outcomes = [
        entry["params"]
        for entry in _trace_by_type(sim, ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE)
        if entry.get("params", {}).get("reason") == "local_encounter_not_allowed_from_local_space"
    ]
    assert len(rejection_outcomes) == 1
    rejection = rejection_outcomes[0]
    assert rejection["applied"] is False
    assert rejection["reason"] == "local_encounter_not_allowed_from_local_space"
    assert rejection["entity_id"] == DEFAULT_PLAYER_ENTITY_ID
    assert rejection["space_id"] == local_space_id
    assert isinstance(rejection.get("tick"), int)
    assert isinstance(rejection.get("action_uid"), str) and rejection["action_uid"]

    hash_before_load = simulation_hash(sim)
    trace_before_load = sim.get_event_trace()

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    assert loaded.get_event_trace() == trace_before_load
    assert simulation_hash(loaded) == hash_before_load

    loaded.append_command(
        SimCommand(
            tick=loaded.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": DEFAULT_PLAYER_ENTITY_ID, "tags": []},
        )
    )
    loaded.advance_ticks(4)

    assert loaded.state.entities[DEFAULT_PLAYER_ENTITY_ID].space_id == "overworld"

    return_events = _trace_by_type(loaded, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)
    assert len(return_events) == 1
    final_return = return_events[-1]["params"]
    assert final_return["applied"] is True
    assert final_return["to_space_id"] == "overworld"
    assert all(
        not str(entry["params"].get("to_space_id", "")).startswith("local_encounter:") for entry in return_events
    )

    rules_state = loaded.get_rules_state(LocalEncounterInstanceModule.name)
    assert local_space_id not in rules_state["return_in_progress_by_local_space"]
