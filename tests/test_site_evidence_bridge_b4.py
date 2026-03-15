from __future__ import annotations

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.site_evidence import (
    SITE_EVIDENCE_APPLY_EVENT_TYPE,
    SITE_EVIDENCE_BRIDGE_OUTCOME_EVENT_TYPE,
    SiteEvidenceBridgeModule,
    SiteEvidenceMutationModule,
)
from hexcrawler.sim.world import SiteRecord, WorldState


def _world_with_sites() -> WorldState:
    world = load_world_json("content/examples/basic_map.json")
    world.sites = {
        "camp_01": SiteRecord(
            site_id="camp_01",
            site_type="camp",
            location={"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        ),
        "camp_02": SiteRecord(
            site_id="camp_02",
            site_type="camp",
            location={"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 1, "r": 0}},
        ),
    }
    return world


def _sim(seed: int = 123) -> Simulation:
    sim = Simulation(world=_world_with_sites(), seed=seed)
    sim.register_rule_module(SiteEvidenceBridgeModule())
    sim.register_rule_module(SiteEvidenceMutationModule())
    return sim


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_b4_claim_opportunity_consumed_bridges_into_site_evidence_apply() -> None:
    sim = _sim()
    sim.schedule_event_at(
        tick=0,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 0, "r": 0},
                "template_id": "site:camp_01",
            },
        },
    )

    sim.advance_ticks(1)

    bridge_outcome = _events(sim, SITE_EVIDENCE_BRIDGE_OUTCOME_EVENT_TYPE)[-1]
    assert bridge_outcome["params"]["outcome"] == "emitted"

    apply_events = _events(sim, SITE_EVIDENCE_APPLY_EVENT_TYPE)
    assert len(apply_events) == 1
    assert apply_events[0]["params"] == {
        "site_id": "camp_01",
        "evidence_type": "claim_marker",
        "strength": 1,
        "faction_id": "group:caravan",
        "source_event_id": apply_events[0]["params"]["source_event_id"],
        "tick": 0,
    }

    records = sim.state.world.sites["camp_01"].site_state.evidence_records
    assert len(records) == 1
    assert records[0].to_dict() == {
        "evidence_type": "claim_marker",
        "strength": 1,
        "source_event_id": apply_events[0]["params"]["source_event_id"],
        "faction_id": "group:caravan",
        "tick": 0,
    }


def test_b4_missing_context_skips_without_mutation() -> None:
    sim = _sim()
    sim.schedule_event_at(
        tick=0,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "",
            "site_key": {"template_id": "site:camp_01"},
        },
    )

    sim.advance_ticks(1)

    bridge_outcome = _events(sim, SITE_EVIDENCE_BRIDGE_OUTCOME_EVENT_TYPE)[-1]
    assert bridge_outcome["params"]["outcome"] == "skipped_invalid_context"
    assert _events(sim, SITE_EVIDENCE_APPLY_EVENT_TYPE) == []
    assert sim.state.world.sites["camp_01"].site_state.evidence_records == []


def test_b4_multiple_source_events_preserve_stable_order() -> None:
    sim = _sim()
    sim.schedule_event_at(
        tick=0,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "alpha",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 0, "r": 0},
                "template_id": "site:camp_01",
            },
        },
    )
    sim.schedule_event_at(
        tick=0,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "beta",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 0, "r": 0},
                "template_id": "site:camp_01",
            },
        },
    )

    sim.advance_ticks(1)

    records = sim.state.world.sites["camp_01"].site_state.evidence_records
    assert [record.faction_id for record in records] == ["group:alpha", "group:beta"]


def test_b4_bridge_path_save_load_and_hash_stability(tmp_path) -> None:
    contiguous = _sim(seed=404)
    contiguous.schedule_event_at(
        tick=2,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 0, "r": 0},
                "template_id": "site:camp_01",
            },
        },
    )
    contiguous.advance_ticks(5)

    split = _sim(seed=404)
    split.schedule_event_at(
        tick=2,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 0, "r": 0},
                "template_id": "site:camp_01",
            },
        },
    )
    split.advance_ticks(1)

    save_path = tmp_path / "site_evidence_bridge_b4.json"
    save_game_json(save_path, split.state.world, split)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(SiteEvidenceBridgeModule())
    loaded.register_rule_module(SiteEvidenceMutationModule())
    loaded.advance_ticks(4)

    assert simulation_hash(loaded) == simulation_hash(contiguous)
    assert loaded.state.world.sites["camp_01"].site_state.to_dict() == contiguous.state.world.sites["camp_01"].site_state.to_dict()
