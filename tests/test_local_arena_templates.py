import json

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import square_grid_cell_to_world_xy
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, SpaceState

CAMPAIGN_SPACE_ID = "campaign_plane_beta"


def _build_sim(seed: int = 123, *, module: LocalEncounterInstanceModule | None = None) -> Simulation:
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
    sim.register_rule_module(module or LocalEncounterInstanceModule())
    return sim


def _schedule_request(sim: Simulation, *, suggested_template_id: str | None = None) -> None:
    payload = {
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
        "tags": ["night"],
    }
    if suggested_template_id is not None:
        payload["suggested_local_template_id"] = suggested_template_id
    sim.schedule_event_at(tick=0, event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE, params=payload)


def _trace_by_type(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_local_arena_template_selection_suggested_and_default() -> None:
    sim_suggested = _build_sim(seed=5)
    _schedule_request(sim_suggested, suggested_template_id="default_arena_v1")
    sim_suggested.advance_ticks(3)
    applied_suggested = _trace_by_type(sim_suggested, LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE)[0]["params"]
    assert applied_suggested["template_id"] == "default_arena_v1"
    assert applied_suggested["reason"] == "applied"

    sim_default = _build_sim(seed=6)
    _schedule_request(sim_default)
    sim_default.advance_ticks(3)
    begin_default = _trace_by_type(sim_default, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    assert begin_default["template_id"] == "default_arena_v1"
    assert begin_default["encounter_context_passthrough"]["table_id"] == "enc_table_primary"


def test_local_arena_template_save_load_idempotent_hash_stable() -> None:
    sim_a = _build_sim(seed=9)
    sim_b = _build_sim(seed=9)
    _schedule_request(sim_a)
    _schedule_request(sim_b)
    sim_a.advance_ticks(3)
    sim_b.advance_ticks(3)

    payload = sim_b.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    sim_a.advance_ticks(5)
    loaded.advance_ticks(5)
    assert simulation_hash(sim_a) == simulation_hash(loaded)

    template_events = _trace_by_type(loaded, LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE)
    assert len(template_events) == 1
    assert template_events[0]["params"]["reason"] == "applied"


def test_local_arena_template_unknown_suggested_uses_default() -> None:
    sim = _build_sim(seed=21)
    _schedule_request(sim, suggested_template_id="unknown_template")
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    applied = _trace_by_type(sim, LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE)[0]["params"]
    assert begin["template_selection_reason"] == "unknown_template"
    assert begin["template_id"] == "default_arena_v1"
    assert applied["template_id"] == "default_arena_v1"


def test_local_arena_template_missing_default_falls_back_deterministically(tmp_path) -> None:
    bad_payload = {
        "schema_version": 1,
        "templates": [
            {
                "template_id": "template_a",
                "topology_type": "square_grid",
                "topology_params": {"width": 10, "height": 10},
                "role": "local",
                "anchors": [{"anchor_id": "entry", "coord": {"x": 1, "y": 1}, "tags": ["entry"]}],
            }
        ],
    }
    bad_path = tmp_path / "bad_local_arenas.json"
    bad_path.write_text(json.dumps(bad_payload), encoding="utf-8")

    sim_a = _build_sim(seed=33, module=LocalEncounterInstanceModule(local_arenas_path=str(bad_path)))
    sim_b = _build_sim(seed=33, module=LocalEncounterInstanceModule(local_arenas_path=str(bad_path)))
    _schedule_request(sim_a)
    _schedule_request(sim_b)
    sim_a.advance_ticks(3)
    sim_b.advance_ticks(3)

    applied = _trace_by_type(sim_a, LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE)[0]["params"]
    begin = _trace_by_type(sim_a, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    assert applied["template_id"] == "__fallback_minimal__"
    assert applied["reason"] == "invalid_template_payload"
    assert begin["to_spawn_coord"] == {"x": 0, "y": 0}
    assert simulation_hash(sim_a) == simulation_hash(sim_b)
