import json

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import MAX_SITE_EVIDENCE_RECORDS, SiteRecord, WorldState

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

def test_add_site_evidence_appends_record() -> None:
    world = _world_with_site()

    world.add_site_evidence(
        "camp_01",
        evidence_type="blood_trace",
        strength=3,
        source_event_id="evt_11",
        faction_id="faction_red",
        tick=9,
    )

    records = world.sites["camp_01"].site_state.evidence_records
    assert len(records) == 1
    assert records[0].to_dict() == {
        "evidence_type": "blood_trace",
        "strength": 3,
        "tick": 9,
        "source_event_id": "evt_11",
        "faction_id": "faction_red",
    }

def test_add_site_evidence_fifo_eviction_is_deterministic() -> None:
    world = _world_with_site()

    for i in range(MAX_SITE_EVIDENCE_RECORDS + 5):
        world.add_site_evidence(
            "camp_01",
            evidence_type=f"track_{i % 2}",
            strength=i,
            tick=i,
        )

    records = world.sites["camp_01"].site_state.evidence_records
    assert len(records) == MAX_SITE_EVIDENCE_RECORDS
    assert records[0].tick == 5
    assert records[-1].tick == MAX_SITE_EVIDENCE_RECORDS + 4

def test_site_evidence_defaults_for_legacy_load() -> None:
    payload = {
        "topology_type": "custom",
        "topology_params": {},
        "hexes": [
            {"coord": {"q": 0, "r": 0}, "record": {"terrain_type": "plains", "site_type": "none", "metadata": {}}}
        ],
        "sites": {
            "legacy_site": {
                "site_id": "legacy_site",
                "site_type": "ruin",
                "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                "site_state": {
                    "pressure_records": [],
                    "condition_markers": [],
                },
            }
        },
    }

    loaded = WorldState.from_dict(payload)
    assert loaded.sites["legacy_site"].site_state.evidence_records == []

def test_site_state_evidence_changes_simulation_hash_deterministically() -> None:
    sim_a = Simulation(world=_world_with_site(), seed=33)
    sim_b = Simulation(world=_world_with_site(), seed=33)

    before = simulation_hash(sim_a)
    sim_a.state.world.add_site_evidence("camp_01", evidence_type="debris", strength=2, tick=7)
    sim_b.state.world.add_site_evidence("camp_01", evidence_type="debris", strength=2, tick=7)

    assert simulation_hash(sim_a) != before
    assert simulation_hash(sim_a) == simulation_hash(sim_b)

def test_site_state_save_load_and_hash_round_trip_with_evidence(tmp_path) -> None:
    world = _world_with_site()
    sim = Simulation(world=world, seed=101)
    world.add_site_evidence("camp_01", evidence_type="corpse", strength=2, tick=5)
    world_before = world_hash(sim.state.world)

    save_path = tmp_path / "site_evidence_state_save.json"
    save_game_json(save_path, sim.state.world, sim)
    payload_before = json.loads(save_path.read_text(encoding="utf-8"))

    loaded_world, loaded_sim = load_game_json(save_path)
    save_game_json(save_path, loaded_world, loaded_sim)
    payload_after = json.loads(save_path.read_text(encoding="utf-8"))

    assert payload_before["world_state"]["sites"] == payload_after["world_state"]["sites"]
    assert world_before == world_hash(loaded_world)
