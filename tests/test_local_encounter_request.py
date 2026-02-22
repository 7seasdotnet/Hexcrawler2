from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, SpaceState


CAMPAIGN_SPACE_ID = "campaign_plane_alpha"


def _build_sim(*, role: str, seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[CAMPAIGN_SPACE_ID] = SpaceState(
        space_id=CAMPAIGN_SPACE_ID,
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=role,
        topology_params={"width": 3, "height": 3, "origin": {"x": 0, "y": 0}},
    )
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(LocalEncounterRequestModule())
    return sim


def _schedule_encounter_resolve_request(sim: Simulation) -> None:
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
                "coord": {"x": 1, "y": 2},
            },
            "roll": 33,
            "category": "hostile",
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
            "suggested_local_template_id": "local_template_forest",
            "tags": ["night", "rain"],
        },
    )


def _local_encounter_request_trace(sim: Simulation) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE]


def test_campaign_space_emits_local_encounter_request() -> None:
    sim = _build_sim(role=CAMPAIGN_SPACE_ROLE)
    _schedule_encounter_resolve_request(sim)

    sim.advance_ticks(2)

    requests = _local_encounter_request_trace(sim)
    assert len(requests) == 1

    params = requests[0]["params"]
    assert params == {
        "tick": 0,
        "from_space_id": CAMPAIGN_SPACE_ID,
        "from_location": {
            "space_id": CAMPAIGN_SPACE_ID,
            "topology_type": SQUARE_GRID_TOPOLOGY,
            "coord": {"x": 1, "y": 2},
        },
        "context": "global",
        "trigger": "travel",
        "location": {
            "space_id": CAMPAIGN_SPACE_ID,
            "topology_type": SQUARE_GRID_TOPOLOGY,
            "coord": {"x": 1, "y": 2},
        },
        "roll": 33,
        "category": "hostile",
        "table_id": "enc_table_primary",
        "entry_id": "wolves_1",
        "encounter": {
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
            "category": "hostile",
            "roll": 33,
        },
        "suggested_local_template_id": "local_template_forest",
        "tags": ["night", "rain"],
    }


def test_local_space_does_not_emit_local_encounter_request() -> None:
    sim = _build_sim(role=LOCAL_SPACE_ROLE)
    _schedule_encounter_resolve_request(sim)

    sim.advance_ticks(2)

    assert _local_encounter_request_trace(sim) == []


def test_local_encounter_request_emission_is_deterministic() -> None:
    sim_a = _build_sim(role=CAMPAIGN_SPACE_ROLE, seed=777)
    sim_b = _build_sim(role=CAMPAIGN_SPACE_ROLE, seed=777)

    _schedule_encounter_resolve_request(sim_a)
    _schedule_encounter_resolve_request(sim_b)

    sim_a.advance_ticks(2)
    sim_b.advance_ticks(2)

    assert _local_encounter_request_trace(sim_a) == _local_encounter_request_trace(sim_b)


def test_local_encounter_request_emits_once_and_does_not_duplicate_after_save_load() -> None:
    sim = _build_sim(role=CAMPAIGN_SPACE_ROLE, seed=991)
    _schedule_encounter_resolve_request(sim)

    sim.advance_ticks(2)
    requests_before_save = _local_encounter_request_trace(sim)
    assert len(requests_before_save) == 1

    payload = sim.simulation_payload()
    reloaded = Simulation.from_simulation_payload(payload)
    reloaded.register_rule_module(LocalEncounterRequestModule())

    reloaded.advance_ticks(10)
    requests_after_load = _local_encounter_request_trace(reloaded)
    assert len(requests_after_load) == 1


def test_local_encounter_request_save_load_replay_deterministic_trace_identity() -> None:
    def _run(seed: int) -> list[dict]:
        sim = _build_sim(role=CAMPAIGN_SPACE_ROLE, seed=seed)
        _schedule_encounter_resolve_request(sim)
        sim.advance_ticks(2)
        payload = sim.simulation_payload()
        loaded = Simulation.from_simulation_payload(payload)
        loaded.register_rule_module(LocalEncounterRequestModule())
        loaded.advance_ticks(10)
        return _local_encounter_request_trace(loaded)

    trace_a = _run(seed=404)
    trace_b = _run(seed=404)
    assert trace_a == trace_b
