from __future__ import annotations

import pytest

from hexcrawler.sim.beliefs import (
    BASE_TRANSMISSION_DELAY_TICKS,
    BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import WorldState


def _claim_payload(*, confidence: int = 25) -> dict[str, object]:
    return {
        "subject": {"kind": "player", "id": "player"},
        "claim_key": "violence",
        "confidence": confidence,
    }


def test_slice1d_base_delay_applies_deterministically_without_context() -> None:
    sim = Simulation(world=WorldState(), seed=3)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": _claim_payload()},
    )
    sim.advance_ticks(1)

    queued = sim.state.world.faction_beliefs["wolves"]["transmission_queue"][0]
    assert queued["created_tick"] == 0
    assert queued["not_before_tick"] == BASE_TRANSMISSION_DELAY_TICKS


def test_slice1d_site_template_modifier_has_precedence_over_region() -> None:
    world = WorldState(
        belief_enqueue_config={
            "delay_mod_by_site_template": {"town_a": 4},
            "delay_mod_by_region": {"north": 99},
            "confidence_mod_by_site_template": {"town_a": 7},
            "confidence_mod_by_region": {"north": 50},
        }
    )
    sim = Simulation(world=world, seed=5)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(
        tick=2,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={
            "faction_id": "wolves",
            "site_template_id": "town_a",
            "region_id": "north",
            "claim": _claim_payload(confidence=20),
        },
    )
    sim.advance_ticks(3)

    queued = sim.state.world.faction_beliefs["wolves"]["transmission_queue"][0]
    assert queued["not_before_tick"] == 2 + BASE_TRANSMISSION_DELAY_TICKS + 4
    assert queued["claim"]["confidence"] == 27


def test_slice1d_region_modifier_applies_when_site_template_absent() -> None:
    world = WorldState(
        belief_enqueue_config={
            "delay_mod_by_region": {"north": -5},
            "confidence_mod_by_region": {"north": -30},
        }
    )
    sim = Simulation(world=world, seed=7)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(
        tick=4,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={
            "faction_id": "wolves",
            "region_id": "north",
            "claim": _claim_payload(confidence=25),
        },
    )
    sim.advance_ticks(5)

    queued = sim.state.world.faction_beliefs["wolves"]["transmission_queue"][0]
    assert queued["not_before_tick"] == 4 + BASE_TRANSMISSION_DELAY_TICKS - 5
    assert queued["claim"]["confidence"] == 0


def test_slice1d_canonicalization_rejects_duplicate_modifier_keys() -> None:
    payload = WorldState().to_dict()
    payload["belief_enqueue_config"] = {
        "delay_mod_by_region": {
            "North ": 1,
            " north": 2,
        }
    }

    with pytest.raises(ValueError, match="unique after normalization"):
        WorldState.from_dict(payload)


def test_slice1d_save_load_and_hash_stability_for_modifier_config() -> None:
    default_world = WorldState()
    default_payload = default_world.to_dict()
    assert "belief_enqueue_config" not in default_payload

    default_loaded = WorldState.from_dict(default_payload)
    assert default_loaded.to_dict() == default_payload
    assert world_hash(default_loaded) == world_hash(default_world)

    configured_world = WorldState(
        belief_enqueue_config={
            "delay_mod_by_site_template": {"town_a": 3},
            "confidence_mod_by_region": {"north": 5},
        }
    )
    configured_payload = configured_world.to_dict()
    assert "belief_enqueue_config" in configured_payload

    configured_loaded = WorldState.from_dict(configured_payload)
    assert configured_loaded.to_dict() == configured_payload
    assert world_hash(configured_loaded) == world_hash(configured_world)
    assert world_hash(configured_world) != world_hash(default_world)

    sim_a = Simulation(world=configured_world, seed=19)
    sim_b = Simulation.from_simulation_payload(sim_a.simulation_payload())
    assert simulation_hash(sim_a) == simulation_hash(sim_b)
