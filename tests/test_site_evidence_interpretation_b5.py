from __future__ import annotations

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import SiteEvidenceSummary, SiteRecord, WorldState


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


def test_site_evidence_summary_defaults_for_empty_site() -> None:
    world = _world_with_site()

    assert world.get_site_evidence_summary("camp_01") == SiteEvidenceSummary(
        total_strength=0,
        by_evidence_type={},
        by_faction={},
        dominant_evidence_type=None,
        dominant_strength=0,
        record_count=0,
    )


def test_site_evidence_summary_aggregates_by_type_and_faction() -> None:
    world = _world_with_site()

    world.add_site_evidence("camp_01", evidence_type="tracks", strength=3, faction_id="faction:zeta", tick=1)
    world.add_site_evidence("camp_01", evidence_type="burns", strength=2, faction_id="faction:alpha", tick=2)
    world.add_site_evidence("camp_01", evidence_type="tracks", strength=4, faction_id="faction:zeta", tick=3)
    world.add_site_evidence("camp_01", evidence_type="corpses", strength=1, tick=4)

    summary = world.get_site_evidence_summary("camp_01")

    assert summary.total_strength == 10
    assert summary.by_evidence_type == {"burns": 2, "corpses": 1, "tracks": 7}
    assert summary.by_faction == {"faction:alpha": 2, "faction:zeta": 7}
    assert summary.dominant_evidence_type == "tracks"
    assert summary.dominant_strength == 7
    assert summary.record_count == 4


def test_site_evidence_summary_dominant_tiebreak_is_lexical() -> None:
    world = _world_with_site()

    world.add_site_evidence("camp_01", evidence_type="tracks", strength=5, tick=1)
    world.add_site_evidence("camp_01", evidence_type="burns", strength=5, tick=2)

    summary = world.get_site_evidence_summary("camp_01")

    assert summary.by_evidence_type == {"burns": 5, "tracks": 5}
    assert summary.dominant_evidence_type == "burns"
    assert summary.dominant_strength == 5


def test_site_evidence_summary_is_stable_across_save_load(tmp_path) -> None:
    sim = Simulation(world=_world_with_site(), seed=909)
    sim.state.world.add_site_evidence("camp_01", evidence_type="tracks", strength=2, faction_id="faction:red", tick=7)
    sim.state.world.add_site_evidence("camp_01", evidence_type="burns", strength=4, faction_id="faction:blue", tick=8)

    summary_before = sim.state.world.get_site_evidence_summary("camp_01")
    save_path = tmp_path / "site_evidence_interpretation_b5.json"
    save_game_json(save_path, sim.state.world, sim)

    loaded_world, _ = load_game_json(save_path)
    summary_after = loaded_world.get_site_evidence_summary("camp_01")

    assert summary_after == summary_before


def test_site_evidence_summary_does_not_mutate_state_or_hash() -> None:
    sim = Simulation(world=_world_with_site(), seed=707)
    sim.state.world.add_site_evidence("camp_01", evidence_type="debris", strength=3, faction_id="faction:red", tick=5)
    before_hash = simulation_hash(sim)
    before_records = [record.to_dict() for record in sim.state.world.sites["camp_01"].site_state.evidence_records]

    summary = sim.state.world.get_site_evidence_summary("camp_01")

    assert summary.total_strength == 3
    assert summary.record_count == 1
    assert [record.to_dict() for record in sim.state.world.sites["camp_01"].site_state.evidence_records] == before_records
    assert simulation_hash(sim) == before_hash
