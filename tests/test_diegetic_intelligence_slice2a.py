from __future__ import annotations

import pytest

from hexcrawler.sim.beliefs import (
    BELIEF_FANOUT_GATED_EVENT_TYPE,
    BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
    BELIEF_JOB_ENQUEUE_GATED_EVENT_TYPE,
    BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
    BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
    BeliefJobQueueModule,
    is_fanout_allowed,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import WorldState


def _claim() -> dict[str, object]:
    return {
        "subject": {"kind": "player", "id": "player"},
        "claim_key": "violence",
        "confidence": 20,
    }


def _seed(sim: Simulation) -> None:
    sim.state.world.faction_registry = ["alpha", "source"]
    sim.state.world.activated_factions = ["alpha", "source"]
    sim.state.world.faction_beliefs = {
        "source": {"belief_records": {}},
        "alpha": {"belief_records": {}},
    }


def test_slice2a_default_behavior_unchanged_without_geo_config() -> None:
    sim = Simulation(world=WorldState(), seed=41)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed(sim)

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params={
            "source_faction_id": "source",
            "subject": {"kind": "player", "id": "player"},
            "claim_key": "violence",
            "confidence": 25,
        },
    )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "alpha", "claim": _claim()},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "alpha", "claim": _claim()},
    )
    sim.advance_ticks(1)

    assert len(sim.state.world.faction_beliefs["alpha"].get("transmission_queue", [])) == 2
    assert len(sim.state.world.faction_beliefs["alpha"].get("investigation_queue", [])) == 1
    assert not [row for row in sim.get_event_trace() if row["event_type"] == BELIEF_FANOUT_GATED_EVENT_TYPE]
    assert not [row for row in sim.get_event_trace() if row["event_type"] == BELIEF_JOB_ENQUEUE_GATED_EVENT_TYPE]


def test_slice2a_fanout_require_context_denies_without_ids() -> None:
    world = WorldState(belief_geo_gating_config={"require_context": True})
    sim = Simulation(world=world, seed=42)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed(sim)

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params={
            "source_faction_id": "source",
            "subject": {"kind": "player", "id": "player"},
            "claim_key": "violence",
            "confidence": 25,
        },
    )
    sim.advance_ticks(1)

    assert "transmission_queue" not in sim.state.world.faction_beliefs["alpha"]
    gated = [row for row in sim.get_event_trace() if row["event_type"] == BELIEF_FANOUT_GATED_EVENT_TYPE]
    assert len(gated) == 1
    assert gated[0]["params"]["reason"] == "missing_context"


def test_slice2a_allowlist_and_denylist_precedence() -> None:
    allowed, reason = is_fanout_allowed(
        context={"region_id": "north", "site_template_id": None},
        config={"allow_regions": ["north"], "deny_regions": ["north"]},
    )
    assert not allowed
    assert reason == "in_denylist"

    allowed_missing, reason_missing = is_fanout_allowed(
        context={"region_id": "south", "site_template_id": None},
        config={"allow_regions": ["north"]},
    )
    assert not allowed_missing
    assert reason_missing == "not_in_allowlist"


def test_slice2a_combined_region_and_site_context_uses_conservative_deny() -> None:
    allowed, reason = is_fanout_allowed(
        context={"region_id": "north", "site_template_id": "town_a"},
        config={"allow_regions": ["north"], "deny_site_templates": ["town_a"]},
    )
    assert not allowed
    assert reason == "in_denylist"


def test_slice2a_enqueue_gating_denies_when_enabled_and_context_matches_denylist() -> None:
    world = WorldState(
        belief_geo_gating_config={
            "gate_enqueue_by_region": True,
            "enqueue_deny_regions": ["north"],
        }
    )
    sim = Simulation(world=world, seed=43)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={
            "faction_id": "alpha",
            "region_id": "north",
            "claim": _claim(),
        },
    )
    sim.advance_ticks(1)

    assert "transmission_queue" not in sim.state.world.faction_beliefs.get("alpha", {})
    gated = [row for row in sim.get_event_trace() if row["event_type"] == BELIEF_JOB_ENQUEUE_GATED_EVENT_TYPE]
    assert len(gated) == 1
    assert gated[0]["params"]["reason"] == "in_denylist"


def test_slice2a_canonicalization_rejects_duplicate_geo_gating_ids() -> None:
    payload = WorldState().to_dict()
    payload["belief_geo_gating_config"] = {"allow_regions": [" Foo ", "foo"]}

    with pytest.raises(ValueError, match="unique after normalization"):
        WorldState.from_dict(payload)


def test_slice2a_save_load_and_hash_stability_for_geo_gating_config() -> None:
    default_world = WorldState()
    default_payload = default_world.to_dict()
    assert "belief_geo_gating_config" not in default_payload

    default_loaded = WorldState.from_dict(default_payload)
    assert default_loaded.to_dict() == default_payload
    assert world_hash(default_loaded) == world_hash(default_world)

    configured_world = WorldState(
        belief_geo_gating_config={
            "require_context": True,
            "allow_regions": [" north ", "South"],
            "gate_enqueue_by_region": True,
            "enqueue_deny_regions": [" swamps "],
        }
    )
    configured_payload = configured_world.to_dict()
    assert configured_payload["belief_geo_gating_config"]["allow_regions"] == ["north", "south"]

    configured_loaded = WorldState.from_dict(configured_payload)
    assert configured_loaded.to_dict() == configured_payload
    assert world_hash(configured_loaded) == world_hash(configured_world)
    assert world_hash(configured_world) != world_hash(default_world)

    sim_a = Simulation(world=configured_world, seed=54)
    sim_b = Simulation.from_simulation_payload(sim_a.simulation_payload())
    assert simulation_hash(sim_a) == simulation_hash(sim_b)
