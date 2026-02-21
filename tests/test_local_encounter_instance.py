from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import square_grid_cell_to_world_xy
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, SpaceState


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
    scout2_x, scout2_y = square_grid_cell_to_world_xy(11, 21)
    sim.add_entity(EntityState(entity_id="a_hireling", position_x=scout2_x, position_y=scout2_y, space_id=CAMPAIGN_SPACE_ID))
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


def test_local_encounter_instance_exactly_once() -> None:
    sim = _build_sim()
    _schedule_request(sim)

    sim.advance_ticks(3)

    requests = _trace_by_type(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE)
    begin_events = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    assert len(requests) == 1
    assert len(begin_events) == 1

    expected_space_id = begin_events[0]["params"]["to_space_id"]
    assert expected_space_id in sim.state.world.spaces
    local_space = sim.state.world.spaces[expected_space_id]
    assert local_space.role == "local"
    assert local_space.topology_type == SQUARE_GRID_TOPOLOGY

    begin_params = begin_events[0]["params"]
    assert begin_params["to_space_id"] == expected_space_id
    assert begin_params["entity_id"] == "scout"
    assert begin_params["from_space_id"] == CAMPAIGN_SPACE_ID
    assert begin_params["to_spawn_coord"] == {"x": 0, "y": 0}
    assert begin_params["transition_applied"] is True
    assert sim.state.entities["scout"].space_id == expected_space_id


def test_local_encounter_instance_save_load_idempotent() -> None:
    sim = _build_sim(seed=9)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin_before = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    assert len(begin_before) == 1
    expected_space_id = begin_before[0]["params"]["to_space_id"]

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    loaded.advance_ticks(10)

    begin_after = _trace_by_type(loaded, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    assert len(begin_after) == 1
    assert loaded.state.entities["scout"].space_id == expected_space_id
    assert expected_space_id in loaded.state.world.spaces


def test_local_encounter_instance_deterministic_hash_stable() -> None:
    sim_a = _build_sim(seed=77)
    sim_b = _build_sim(seed=77)
    _schedule_request(sim_a)
    _schedule_request(sim_b)

    sim_a.advance_ticks(5)
    sim_b.advance_ticks(5)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_local_encounter_instancing_uses_non_overworld_campaign_space() -> None:
    sim = _build_sim(seed=12)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin_event = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    assert begin_event["params"]["from_space_id"] == CAMPAIGN_SPACE_ID
    assert begin_event["params"]["from_location"]["space_id"] == CAMPAIGN_SPACE_ID
