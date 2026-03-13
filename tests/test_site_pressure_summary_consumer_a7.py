from __future__ import annotations

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.site_pressure import (
    SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
    SITE_PRESSURE_SUMMARY_OUTCOME_EVENT_TYPE,
    SitePressureSummaryConsumerModule,
)
from hexcrawler.sim.world import SiteRecord, WorldState


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


def _sim(seed: int = 808) -> Simulation:
    sim = Simulation(world=_world_with_site(), seed=seed)
    sim.register_rule_module(SitePressureSummaryConsumerModule())
    return sim


def _outcomes(sim: Simulation) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == SITE_PRESSURE_SUMMARY_OUTCOME_EVENT_TYPE]


def test_a7_site_pressure_summary_consumer_threshold_met() -> None:
    sim = _sim()
    sim.state.world.add_site_pressure("camp_01", "faction:zeta", "claim_activity", 3, tick=1)
    sim.state.world.add_site_pressure("camp_01", "faction:alpha", "presence", 2, tick=2)

    before_hash = simulation_hash(sim)
    before_state = sim.state.world.sites["camp_01"].site_state.to_dict()

    sim.schedule_event_at(
        tick=0,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": "camp_01"},
    )
    sim.advance_ticks(1)

    outcome = _outcomes(sim)[-1]["params"]
    assert outcome["status"] == "threshold_met"
    assert outcome["summary"] == {
        "site_id": "camp_01",
        "threshold": 5,
        "total_pressure": 5,
        "dominant_faction_id": "faction:zeta",
        "dominant_strength": 3,
        "record_count": 2,
    }
    assert sim.state.world.sites["camp_01"].site_state.to_dict() == before_state
    assert simulation_hash(sim) != before_hash


def test_a7_site_pressure_summary_consumer_below_threshold() -> None:
    sim = _sim()
    sim.state.world.add_site_pressure("camp_01", "faction:red", "probe", 4, tick=7)

    sim.schedule_event_at(
        tick=3,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": "camp_01"},
    )
    sim.advance_ticks(4)

    outcome = _outcomes(sim)[-1]["params"]
    assert outcome["status"] == "below_threshold"
    assert outcome["summary"]["site_id"] == "camp_01"
    assert outcome["summary"]["total_pressure"] == 4
    assert outcome["summary"]["dominant_faction_id"] == "faction:red"
    assert outcome["summary"]["dominant_strength"] == 4
    assert outcome["summary"]["record_count"] == 1


def test_a7_site_pressure_summary_consumer_passes_deterministic_tiebreak() -> None:
    sim = _sim()
    sim.state.world.add_site_pressure("camp_01", "faction:omega", "probe", 3, tick=1)
    sim.state.world.add_site_pressure("camp_01", "faction:alpha", "probe", 3, tick=2)

    sim.schedule_event_at(
        tick=1,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": "camp_01"},
    )
    sim.advance_ticks(2)

    summary = _outcomes(sim)[-1]["params"]["summary"]
    assert summary["dominant_faction_id"] == "faction:alpha"
    assert summary["dominant_strength"] == 3


def test_a7_site_pressure_summary_consumer_save_load_replay_hash_stability(tmp_path) -> None:
    sim = _sim(seed=919)
    sim.state.world.add_site_pressure("camp_01", "faction:a", "presence", 2, tick=1)
    sim.state.world.add_site_pressure("camp_01", "faction:b", "presence", 4, tick=2)
    sim.schedule_event_at(
        tick=4,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": "camp_01"},
    )

    sim.advance_ticks(2)
    save_path = tmp_path / "site_pressure_summary_a7.json"
    save_game_json(save_path, sim.state.world, sim)

    loaded_world, loaded = load_game_json(save_path)
    loaded.register_rule_module(SitePressureSummaryConsumerModule())
    loaded.advance_ticks(4)

    contiguous = _sim(seed=919)
    contiguous.state.world.add_site_pressure("camp_01", "faction:a", "presence", 2, tick=1)
    contiguous.state.world.add_site_pressure("camp_01", "faction:b", "presence", 4, tick=2)
    contiguous.schedule_event_at(
        tick=4,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": "camp_01"},
    )
    contiguous.advance_ticks(6)

    assert loaded_world.sites["camp_01"].site_state.pressure_records == contiguous.state.world.sites["camp_01"].site_state.pressure_records
    assert simulation_hash(loaded) == simulation_hash(contiguous)
    assert _outcomes(loaded) == _outcomes(contiguous)


def test_a7_site_pressure_summary_check_invalid_context_is_forensic_only() -> None:
    sim = _sim()
    before_state = sim.state.world.sites["camp_01"].site_state.to_dict()

    sim.schedule_event_at(
        tick=0,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": ""},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE,
        params={"site_id": "missing"},
    )
    sim.advance_ticks(1)

    outcomes = [row["params"] for row in _outcomes(sim)]
    assert outcomes[0]["status"] == "invalid_site_id"
    assert outcomes[1]["status"] == "unknown_site"
    assert sim.state.world.sites["camp_01"].site_state.to_dict() == before_state
