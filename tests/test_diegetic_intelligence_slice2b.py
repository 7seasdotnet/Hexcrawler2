from __future__ import annotations

import pytest

from hexcrawler.sim.beliefs import (
    BELIEF_FANOUT_CONTACT_GATED_EVENT_TYPE,
    BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
    MAX_FANOUT_RECIPIENTS,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import MAX_CONTACTS_PER_FACTION, WorldState


def _claim_subject() -> dict[str, str]:
    return {"kind": "player", "id": "player"}


def _seed_factions(sim: Simulation, faction_ids: list[str], *, activated: list[str] | None = None) -> None:
    sim.state.world.faction_beliefs = {
        faction_id: {"belief_records": {}}
        for faction_id in faction_ids
    }
    sim.state.world.faction_registry = sorted(faction_ids)
    sim.state.world.activated_factions = sorted(activated if activated is not None else faction_ids)


def _schedule_outbound(sim: Simulation, *, source_faction_id: str) -> None:
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params={
            "source_faction_id": source_faction_id,
            "subject": _claim_subject(),
            "claim_key": "violence",
            "confidence": 25,
        },
    )


def test_slice2b_default_behavior_unchanged_without_contacts_configured() -> None:
    sim = Simulation(world=WorldState(), seed=61)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed_factions(sim, ["delta", "gamma", "alpha", "beta", "source"])

    _schedule_outbound(sim, source_faction_id="source")
    sim.advance_ticks(1)

    expected_recipients = ["alpha", "beta", "delta"][:MAX_FANOUT_RECIPIENTS]
    for faction_id in expected_recipients:
        assert len(sim.state.world.faction_beliefs[faction_id]["transmission_queue"]) == 1
    assert "transmission_queue" not in sim.state.world.faction_beliefs["gamma"]


def test_slice2b_contact_gating_restricts_universe_deterministically() -> None:
    sim = Simulation(
        world=WorldState(
            faction_registry=["source", "alpha", "beta", "delta", "gamma", "zeta"],
            activated_factions=["source", "alpha", "beta", "delta", "gamma", "zeta"],
            faction_contacts={"source": ["zeta", "delta", "beta"]},
        ),
        seed=62,
    )
    sim.register_rule_module(BeliefJobQueueModule())
    sim.state.world.faction_beliefs = {
        faction_id: {"belief_records": {}}
        for faction_id in ["source", "alpha", "beta", "delta", "gamma", "zeta"]
    }

    _schedule_outbound(sim, source_faction_id="source")
    sim.advance_ticks(1)

    for faction_id in ["beta", "delta", "zeta"]:
        assert len(sim.state.world.faction_beliefs[faction_id]["transmission_queue"]) == 1
    assert "transmission_queue" not in sim.state.world.faction_beliefs["alpha"]
    assert "transmission_queue" not in sim.state.world.faction_beliefs["gamma"]

    forensic = [
        row for row in sim.get_event_trace() if row["event_type"] == BELIEF_FANOUT_CONTACT_GATED_EVENT_TYPE
    ]
    assert len(forensic) == 1
    assert forensic[0]["params"]["universe_before"] == 6
    assert forensic[0]["params"]["universe_after"] == 3


def test_slice2b_validation_rejects_unknown_factions_in_contacts() -> None:
    payload = WorldState().to_dict()
    payload["faction_registry"] = ["source", "alpha"]
    payload["faction_contacts"] = {"source": ["alpha", "unknown"]}

    with pytest.raises(ValueError, match="recipient ids must exist"):
        WorldState.from_dict(payload)


def test_slice2b_validation_rejects_self_contact() -> None:
    with pytest.raises(ValueError, match="must not include self-contact"):
        WorldState(
            faction_registry=["source", "alpha"],
            faction_contacts={"source": ["alpha", "source"]},
        )


def test_slice2b_bounds_enforced_for_contact_list() -> None:
    recipients = [f"f{index:03d}" for index in range(MAX_CONTACTS_PER_FACTION + 1)]
    with pytest.raises(ValueError, match="exceeds maximum"):
        WorldState(
            faction_registry=["source", *recipients],
            faction_contacts={"source": recipients},
        )


def test_slice2b_save_load_and_hash_stability_for_contacts() -> None:
    default_world = WorldState(faction_registry=["source", "alpha"])
    default_payload = default_world.to_dict()
    assert "faction_contacts" not in default_payload

    loaded_default = WorldState.from_dict(default_payload)
    assert loaded_default.to_dict() == default_payload
    assert world_hash(loaded_default) == world_hash(default_world)

    configured_world = WorldState(
        faction_registry=["source", "alpha", "beta", "gamma"],
        faction_contacts={" source ": [" gamma ", "alpha", "beta"]},
    )
    configured_payload = configured_world.to_dict()
    assert configured_payload["faction_contacts"] == {"source": ["alpha", "beta", "gamma"]}

    loaded_configured = WorldState.from_dict(configured_payload)
    assert loaded_configured.to_dict() == configured_payload
    assert world_hash(loaded_configured) == world_hash(configured_world)
    assert world_hash(configured_world) != world_hash(default_world)

    sim_a = Simulation(world=configured_world, seed=63)
    sim_b = Simulation.from_simulation_payload(sim_a.simulation_payload())
    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_slice2b_contact_gate_intersects_with_activation_gate() -> None:
    sim = Simulation(
        world=WorldState(
            faction_registry=["source", "alpha", "beta", "gamma", "delta"],
            activated_factions=["source", "alpha", "delta"],
            faction_contacts={"source": ["alpha", "beta", "gamma"]},
        ),
        seed=64,
    )
    sim.register_rule_module(BeliefJobQueueModule())
    sim.state.world.faction_beliefs = {
        faction_id: {"belief_records": {}}
        for faction_id in ["source", "alpha", "beta", "gamma", "delta"]
    }

    _schedule_outbound(sim, source_faction_id="source")
    sim.advance_ticks(1)

    assert len(sim.state.world.faction_beliefs["alpha"]["transmission_queue"]) == 1
    assert "transmission_queue" not in sim.state.world.faction_beliefs["beta"]
    assert "transmission_queue" not in sim.state.world.faction_beliefs["gamma"]
    assert "transmission_queue" not in sim.state.world.faction_beliefs["delta"]
