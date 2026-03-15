import json

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import MAX_SITE_PRESSURE_RECORDS, SiteRecord, WorldState

def _world_with_site() -> WorldState:
    world = load_world_json("content/examples/basic_map.json")
    world.sites = {
        "camp_01": SiteRecord(
            site_id="camp_01",
            site_type="camp",
            location={"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            tags=["test"],
        )
    }
    return world

def test_site_state_initializes_for_legacy_site_payload() -> None:
    world = WorldState.from_dict(
        {
            "topology_type": "custom",
            "topology_params": {},
            "hexes": [{"coord": {"q": 0, "r": 0}, "record": {"terrain_type": "plains", "site_type": "none", "metadata": {}}}],
            "sites": {
                "legacy_site": {
                    "site_id": "legacy_site",
                    "site_type": "ruin",
                    "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                }
            },
        }
    )

    site_state = world.sites["legacy_site"].site_state
    assert site_state.owner_faction_id is None
    assert site_state.pressure_records == []
    assert site_state.condition_markers == []

def test_add_site_pressure_appends_record() -> None:
    world = _world_with_site()

    world.add_site_pressure(
        "camp_01",
        faction_id="faction_red",
        pressure_type="presence",
        strength=3,
        source_event_id="evt_01",
        tick=12,
    )

    records = world.sites["camp_01"].site_state.pressure_records
    assert len(records) == 1
    assert records[0].to_dict() == {
        "faction_id": "faction_red",
        "pressure_type": "presence",
        "strength": 3,
        "source_event_id": "evt_01",
        "tick": 12,
    }

def test_add_site_pressure_fifo_eviction_is_deterministic() -> None:
    world = _world_with_site()

    for i in range(MAX_SITE_PRESSURE_RECORDS + 5):
        world.add_site_pressure(
            "camp_01",
            faction_id=f"faction_{i % 2}",
            pressure_type="probe",
            strength=i,
            tick=i,
        )

    records = world.sites["camp_01"].site_state.pressure_records
    assert len(records) == MAX_SITE_PRESSURE_RECORDS
    assert records[0].tick == 5
    assert records[-1].tick == MAX_SITE_PRESSURE_RECORDS + 4

def test_site_state_save_load_and_hash_round_trip(tmp_path) -> None:
    world = _world_with_site()
    sim = Simulation(world=world, seed=101)
    world.add_site_pressure("camp_01", faction_id="faction_red", pressure_type="presence", strength=9, tick=4)
    world_before = world_hash(sim.state.world)

    save_path = tmp_path / "site_state_save.json"
    save_game_json(save_path, sim.state.world, sim)
    payload_before = json.loads(save_path.read_text(encoding="utf-8"))

    loaded_world, loaded_sim = load_game_json(save_path)
    save_game_json(save_path, loaded_world, loaded_sim)
    payload_after = json.loads(save_path.read_text(encoding="utf-8"))

    assert payload_before["world_state"]["sites"] == payload_after["world_state"]["sites"]
    assert world_before == world_hash(loaded_world)
