from __future__ import annotations

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import SiteRecord, SitePressureSummary, WorldState


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


def test_site_pressure_summary_defaults_for_empty_site() -> None:
    world = _world_with_site()

    assert world.get_site_pressure_summary("camp_01") == SitePressureSummary(
        total_pressure=0,
        by_faction={},
        by_pressure_type={},
        dominant_faction_id=None,
        dominant_strength=0,
        record_count=0,
    )


def test_site_pressure_summary_aggregates_by_faction_and_type() -> None:
    world = _world_with_site()

    world.add_site_pressure("camp_01", "faction:zeta", "presence", 3, tick=1)
    world.add_site_pressure("camp_01", "faction:alpha", "claim_activity", 2, tick=2)
    world.add_site_pressure("camp_01", "faction:zeta", "claim_activity", 4, tick=3)

    summary = world.get_site_pressure_summary("camp_01")

    assert summary.total_pressure == 9
    assert summary.by_faction == {"faction:alpha": 2, "faction:zeta": 7}
    assert summary.by_pressure_type == {"claim_activity": 6, "presence": 3}
    assert summary.dominant_faction_id == "faction:zeta"
    assert summary.dominant_strength == 7
    assert summary.record_count == 3


def test_site_pressure_summary_dominant_tiebreak_is_lexical() -> None:
    world = _world_with_site()

    world.add_site_pressure("camp_01", "faction:omega", "probe", 5, tick=1)
    world.add_site_pressure("camp_01", "faction:alpha", "probe", 5, tick=2)

    summary = world.get_site_pressure_summary("camp_01")

    assert summary.by_faction == {"faction:alpha": 5, "faction:omega": 5}
    assert summary.dominant_faction_id == "faction:alpha"
    assert summary.dominant_strength == 5


def test_site_pressure_summary_is_stable_across_save_load(tmp_path) -> None:
    sim = Simulation(world=_world_with_site(), seed=404)
    sim.state.world.add_site_pressure("camp_01", "faction:red", "presence", 2, tick=7)
    sim.state.world.add_site_pressure("camp_01", "faction:blue", "presence", 4, tick=8)

    summary_before = sim.state.world.get_site_pressure_summary("camp_01")
    save_path = tmp_path / "site_pressure_interpretation_a5.json"
    save_game_json(save_path, sim.state.world, sim)

    loaded_world, _ = load_game_json(save_path)
    summary_after = loaded_world.get_site_pressure_summary("camp_01")

    assert summary_after == summary_before


def test_site_pressure_summary_does_not_mutate_state_or_hash() -> None:
    sim = Simulation(world=_world_with_site(), seed=121)
    sim.state.world.add_site_pressure("camp_01", "faction:red", "threat", 3, tick=5)
    before_hash = simulation_hash(sim)
    before_records = [record.to_dict() for record in sim.state.world.sites["camp_01"].site_state.pressure_records]

    summary = sim.state.world.get_site_pressure_summary("camp_01")

    assert summary.total_pressure == 3
    assert summary.record_count == 1
    assert [record.to_dict() for record in sim.state.world.sites["camp_01"].site_state.pressure_records] == before_records
    assert simulation_hash(sim) == before_hash
