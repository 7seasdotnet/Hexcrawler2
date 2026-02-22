from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    END_LOCAL_ENCOUNTER_INTENT,
    END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE,
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_END_EVENT_TYPE,
    LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import square_grid_cell_to_world_xy, world_xy_to_square_grid_cell
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, SpaceState


CAMPAIGN_SPACE_ID = "campaign_plane_beta"


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[CAMPAIGN_SPACE_ID] = SpaceState(
        space_id=CAMPAIGN_SPACE_ID,
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=CAMPAIGN_SPACE_ROLE,
        topology_params={"width": 6, "height": 6, "origin": {"x": 10, "y": 20}},
    )
    sim = Simulation(world=world, seed=seed)
    scout_x, scout_y = square_grid_cell_to_world_xy(12, 21)
    sim.add_entity(EntityState(entity_id="scout", position_x=scout_x, position_y=scout_y, space_id=CAMPAIGN_SPACE_ID))
    sim.register_rule_module(LocalEncounterRequestModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    return sim


def _schedule_request(sim: Simulation) -> None:
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params={
            "tick": 0,
            "context": "global",
            "trigger": "travel",
            "location": {
                "space_id": CAMPAIGN_SPACE_ID,
                "topology_type": SQUARE_GRID_TOPOLOGY,
                "coord": {"x": 12, "y": 21},
            },
            "roll": 48,
            "category": "hostile",
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
        },
    )


def _trace_by_type(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def _issue_end_intent(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": "scout", "tags": []},
        )
    )


def test_local_encounter_return_happy_path() -> None:
    sim = _build_sim(seed=20)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]
    assert sim.state.entities["scout"].space_id == local_space_id

    _issue_end_intent(sim)
    sim.advance_ticks(3)

    return_events = _trace_by_type(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)
    assert len(return_events) == 1
    assert return_events[0]["params"]["applied"] is True
    assert return_events[0]["params"]["to_space_id"] == CAMPAIGN_SPACE_ID
    assert sim.state.entities["scout"].space_id == CAMPAIGN_SPACE_ID
    assert world_xy_to_square_grid_cell(sim.state.entities["scout"].position_x, sim.state.entities["scout"].position_y) == {
        "x": 12,
        "y": 21,
    }

    rules_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    assert local_space_id not in rules_state["active_by_local_space"]


def test_local_encounter_return_idempotent_across_save_load() -> None:
    sim = _build_sim(seed=9)
    _schedule_request(sim)
    sim.advance_ticks(3)

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    _issue_end_intent(loaded)
    loaded.advance_ticks(3)
    assert len(_trace_by_type(loaded, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)) == 1

    payload_after_end = loaded.simulation_payload()
    loaded_after_end = Simulation.from_simulation_payload(payload_after_end)
    loaded_after_end.register_rule_module(LocalEncounterRequestModule())
    loaded_after_end.register_rule_module(LocalEncounterInstanceModule())
    loaded_after_end.advance_ticks(5)

    assert len(_trace_by_type(loaded_after_end, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)) == 1


def test_end_local_encounter_role_gating_and_missing_context() -> None:
    sim_campaign = _build_sim(seed=31)
    _issue_end_intent(sim_campaign)
    sim_campaign.advance_ticks(1)
    campaign_outcome = _trace_by_type(sim_campaign, END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE)[0]
    assert campaign_outcome["params"]["applied"] is False
    assert campaign_outcome["params"]["reason"] == "not_in_local_space"

    sim_local_no_context = _build_sim(seed=32)
    local_space_id = "local_no_context"
    sim_local_no_context.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 4, "height": 4, "origin": {"x": 0, "y": 0}},
    )
    x, y = square_grid_cell_to_world_xy(0, 0)
    sim_local_no_context.state.entities["scout"].space_id = local_space_id
    sim_local_no_context.state.entities["scout"].position_x = x
    sim_local_no_context.state.entities["scout"].position_y = y

    _issue_end_intent(sim_local_no_context)
    sim_local_no_context.advance_ticks(1)
    local_outcome = _trace_by_type(sim_local_no_context, END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE)[0]
    assert local_outcome["params"]["applied"] is False
    assert local_outcome["params"]["reason"] == "no_active_local_encounter"


def test_local_encounter_return_uses_origin_campaign_plane() -> None:
    sim = _build_sim(seed=44)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    return_event = _trace_by_type(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)[0]
    assert return_event["params"]["to_space_id"] == CAMPAIGN_SPACE_ID


def test_local_encounter_return_deterministic_trace_and_hash() -> None:
    sim_a = _build_sim(seed=77)
    sim_b = _build_sim(seed=77)
    _schedule_request(sim_a)
    _schedule_request(sim_b)

    sim_a.advance_ticks(3)
    sim_b.advance_ticks(3)
    _issue_end_intent(sim_a)
    _issue_end_intent(sim_b)
    sim_a.advance_ticks(3)
    sim_b.advance_ticks(3)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)

    traced = {
        LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
        LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
        END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE,
        LOCAL_ENCOUNTER_END_EVENT_TYPE,
        LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
    }
    filtered_a = [entry for entry in sim_a.get_event_trace() if entry["event_type"] in traced]
    filtered_b = [entry for entry in sim_b.get_event_trace() if entry["event_type"] in traced]
    assert filtered_a == filtered_b


def test_local_encounter_return_rejects_invalid_origin_location_shape() -> None:
    sim = _build_sim(seed=52)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]
    rules_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    active = rules_state["active_by_local_space"][local_space_id]
    active["origin_space_id"] = "overworld"
    active["origin_location"] = {
        "space_id": "overworld",
        "topology_type": OVERWORLD_HEX_TOPOLOGY,
        "coord": {"x": 2, "y": 3},
    }
    rules_state["active_by_local_space"][local_space_id] = active
    sim.set_rules_state(LocalEncounterInstanceModule.name, rules_state)

    scout_before = sim.state.entities["scout"].space_id
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    return_event = _trace_by_type(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)[0]
    assert return_event["params"]["applied"] is False
    assert return_event["params"]["reason"] == "invalid_origin_location_for_space"
    assert sim.state.entities["scout"].space_id == scout_before


def test_local_encounter_return_migrates_legacy_origin_coord_shape() -> None:
    sim = _build_sim(seed=62)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]
    rules_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    active = rules_state["active_by_local_space"][local_space_id]
    active["origin_space_id"] = "overworld"
    active["origin_location"] = {"space_id": "overworld", "coord": {"q": 0, "r": 0}}
    rules_state["active_by_local_space"][local_space_id] = active
    sim.set_rules_state(LocalEncounterInstanceModule.name, rules_state)

    _issue_end_intent(sim)
    sim.advance_ticks(3)

    return_event = _trace_by_type(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)[0]
    assert return_event["params"]["applied"] is True
    assert return_event["params"]["to_space_id"] == "overworld"


def test_local_encounter_return_save_load_hash_stable_with_legacy_context() -> None:
    sim_a = _build_sim(seed=71)
    sim_b = _build_sim(seed=71)
    _schedule_request(sim_a)
    _schedule_request(sim_b)
    sim_a.advance_ticks(3)
    sim_b.advance_ticks(3)

    for sim in (sim_a, sim_b):
        begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
        local_space_id = begin["params"]["to_space_id"]
        rules_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        active = rules_state["active_by_local_space"][local_space_id]
        active.pop("origin_location", None)
        active.pop("origin_space_id", None)
        active["from_space_id"] = "overworld"
        active["return_spawn_coord"] = {"q": 0, "r": 0}
        rules_state["active_by_local_space"][local_space_id] = active
        sim.set_rules_state(LocalEncounterInstanceModule.name, rules_state)

        payload = sim.simulation_payload()
        loaded = Simulation.from_simulation_payload(payload)
        loaded.register_rule_module(LocalEncounterRequestModule())
        loaded.register_rule_module(LocalEncounterInstanceModule())

        _issue_end_intent(loaded)
        loaded.advance_ticks(3)
        assert _trace_by_type(loaded, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)[0]["params"]["applied"] is True

        if sim is sim_a:
            sim_a = loaded
        else:
            sim_b = loaded

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_end_local_encounter_intent_is_gated_per_local_space() -> None:
    sim = _build_sim(seed=81)
    _schedule_request(sim)
    sim.advance_ticks(3)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": "scout", "tags": []},
        )
    )
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": "scout", "tags": []},
        )
    )
    sim.advance_ticks(3)

    outcomes = _trace_by_type(sim, END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE)
    assert len(outcomes) == 2
    assert outcomes[0]["params"]["reason"] == "resolved"
    assert outcomes[1]["params"]["reason"] == "already_returning"
    assert len(_trace_by_type(sim, LOCAL_ENCOUNTER_END_EVENT_TYPE)) == 1
    assert len(_trace_by_type(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)) == 1


def test_return_in_progress_state_survives_save_load_and_clears_on_return() -> None:
    sim = _build_sim(seed=82)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]

    _issue_end_intent(sim)
    sim.advance_ticks(1)

    rules_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    assert rules_state["return_in_progress_by_local_space"].get(local_space_id) is True

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    loaded_rules_state = loaded.get_rules_state(LocalEncounterInstanceModule.name)
    assert loaded_rules_state["return_in_progress_by_local_space"].get(local_space_id) is True

    loaded.advance_ticks(2)
    assert len(_trace_by_type(loaded, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)) == 1
    loaded_rules_state_after = loaded.get_rules_state(LocalEncounterInstanceModule.name)
    assert local_space_id not in loaded_rules_state_after["return_in_progress_by_local_space"]


def test_local_encounter_return_forensics_include_actor_space_before_after_with_save_load() -> None:
    sim = _build_sim(seed=93)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]
    assert sim.state.entities["scout"].space_id == local_space_id

    _issue_end_intent(sim)
    sim.advance_ticks(1)
    rules_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    assert rules_state["return_in_progress_by_local_space"].get(local_space_id) is True

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    loaded.advance_ticks(2)
    assert loaded.state.entities["scout"].space_id == CAMPAIGN_SPACE_ID
    loaded_rules_state = loaded.get_rules_state(LocalEncounterInstanceModule.name)
    assert local_space_id not in loaded_rules_state["return_in_progress_by_local_space"]

    return_event = _trace_by_type(loaded, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)[0]
    assert return_event["params"]["applied"] is True
    assert return_event["params"]["actor_id"] == "scout"
    assert return_event["params"]["local_space_id"] == local_space_id
    assert return_event["params"]["origin_space_id"] == CAMPAIGN_SPACE_ID
    assert return_event["params"]["actor_space_id_before"] == local_space_id
    assert return_event["params"]["actor_space_id_after"] == CAMPAIGN_SPACE_ID
