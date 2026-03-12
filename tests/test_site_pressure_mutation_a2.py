from __future__ import annotations

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.site_pressure import (
    SITE_PRESSURE_APPLY_EVENT_TYPE,
    SITE_PRESSURE_OUTCOME_EVENT_TYPE,
    SitePressureMutationModule,
)
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


def _sim_with_module(seed: int = 77) -> Simulation:
    sim = Simulation(world=_world_with_site(), seed=seed)
    sim.register_rule_module(SitePressureMutationModule())
    return sim


def _outcomes(sim: Simulation) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == SITE_PRESSURE_OUTCOME_EVENT_TYPE]


def test_site_pressure_apply_event_mutates_world_state() -> None:
    sim = _sim_with_module()

    sim.schedule_event_at(
        tick=0,
        event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
        params={
            "site_id": "camp_01",
            "faction_id": "faction_red",
            "pressure_type": "presence",
            "strength": 4,
            "source_event_id": "raid_01",
        },
    )

    sim.advance_ticks(1)

    records = sim.state.world.sites["camp_01"].site_state.pressure_records
    assert len(records) == 1
    assert records[0].to_dict() == {
        "faction_id": "faction_red",
        "pressure_type": "presence",
        "strength": 4,
        "source_event_id": "raid_01",
        "tick": 0,
    }
    assert _outcomes(sim)[-1]["params"]["outcome"] == "applied"


def test_site_pressure_apply_unknown_site_rejects_without_mutation() -> None:
    sim = _sim_with_module()

    sim.schedule_event_at(
        tick=0,
        event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
        params={
            "site_id": "missing_site",
            "faction_id": "faction_red",
            "pressure_type": "presence",
            "strength": 3,
        },
    )
    sim.advance_ticks(1)

    assert sim.state.world.sites["camp_01"].site_state.pressure_records == []
    assert _outcomes(sim)[-1]["params"]["outcome"] == "unknown_site"


def test_site_pressure_apply_invalid_strength_rejects_without_mutation() -> None:
    sim = _sim_with_module()

    sim.schedule_event_at(
        tick=0,
        event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
        params={
            "site_id": "camp_01",
            "faction_id": "faction_red",
            "pressure_type": "presence",
            "strength": 0,
        },
    )
    sim.advance_ticks(1)

    assert sim.state.world.sites["camp_01"].site_state.pressure_records == []
    assert _outcomes(sim)[-1]["params"]["outcome"] == "invalid_strength"


def test_repeated_site_pressure_apply_events_preserve_order() -> None:
    sim = _sim_with_module()

    for i in range(5):
        sim.schedule_event_at(
            tick=0,
            event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
            params={
                "site_id": "camp_01",
                "faction_id": "faction_red",
                "pressure_type": "probe",
                "strength": i + 1,
            },
        )

    sim.advance_ticks(1)

    records = sim.state.world.sites["camp_01"].site_state.pressure_records
    assert [record.strength for record in records] == [1, 2, 3, 4, 5]


def test_site_pressure_fifo_eviction_holds_through_event_seam() -> None:
    sim = _sim_with_module()

    for i in range(MAX_SITE_PRESSURE_RECORDS + 4):
        sim.schedule_event_at(
            tick=0,
            event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
            params={
                "site_id": "camp_01",
                "faction_id": "faction_red",
                "pressure_type": "probe",
                "strength": i + 1,
            },
        )

    sim.advance_ticks(1)

    records = sim.state.world.sites["camp_01"].site_state.pressure_records
    assert len(records) == MAX_SITE_PRESSURE_RECORDS
    assert records[0].strength == 5
    assert records[-1].strength == MAX_SITE_PRESSURE_RECORDS + 4


def test_site_pressure_apply_save_load_and_hash_stability(tmp_path) -> None:
    sim = _sim_with_module(seed=99)
    sim.schedule_event_at(
        tick=2,
        event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
        params={
            "site_id": "camp_01",
            "faction_id": "faction_red",
            "pressure_type": "presence",
            "strength": 2,
            "tick": 2,
        },
    )

    sim.advance_ticks(1)
    save_path = tmp_path / "site_pressure_a2_save.json"
    save_game_json(save_path, sim.state.world, sim)

    loaded_world, loaded_sim = load_game_json(save_path)
    loaded_sim.register_rule_module(SitePressureMutationModule())
    loaded_sim.advance_ticks(2)

    fresh = _sim_with_module(seed=99)
    fresh.schedule_event_at(
        tick=2,
        event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
        params={
            "site_id": "camp_01",
            "faction_id": "faction_red",
            "pressure_type": "presence",
            "strength": 2,
            "tick": 2,
        },
    )
    fresh.advance_ticks(3)

    assert loaded_world.sites["camp_01"].site_state.pressure_records == []
    assert simulation_hash(loaded_sim) == simulation_hash(fresh)
    assert loaded_sim.state.world.sites["camp_01"].site_state.to_dict() == fresh.state.world.sites["camp_01"].site_state.to_dict()

