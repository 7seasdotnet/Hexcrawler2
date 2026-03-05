from __future__ import annotations

import pytest

from hexcrawler.sim.beliefs import (
    BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
    FACTION_ACTIVATED_EVENT_TYPE,
    FACTION_ACTIVATION_CHANGED_EVENT_TYPE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import WorldState, normalize_activated_factions


def _claim_subject() -> dict[str, str]:
    return {"kind": "player", "id": "player"}


def test_slice1f_registry_normalization_rejects_duplicates_after_canonicalization() -> None:
    with pytest.raises(ValueError, match="faction_registry ids must be unique"):
        WorldState(faction_registry=["wolves", " wolves "])


def test_slice1f_activated_factions_must_be_subset_of_registry() -> None:
    with pytest.raises(ValueError, match="activated_factions must be a subset"):
        WorldState(faction_registry=["wolves"], activated_factions=["hawks"])


def test_slice1f_activation_event_is_idempotent_and_hash_stable_across_save_load() -> None:
    sim = Simulation(world=WorldState(faction_registry=["wolves"]), seed=21)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(tick=0, event_type=FACTION_ACTIVATED_EVENT_TYPE, params={"faction_id": "wolves"})
    sim.schedule_event_at(tick=0, event_type=FACTION_ACTIVATED_EVENT_TYPE, params={"faction_id": "wolves"})
    sim.advance_ticks(1)

    assert sim.state.world.activated_factions == ["wolves"]
    forensic = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_ACTIVATION_CHANGED_EVENT_TYPE]
    assert [row["params"]["did_change"] for row in forensic] == [True, False]

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded) == simulation_hash(sim)


def test_slice1f_fanout_recipients_come_from_activated_set_not_belief_keys() -> None:
    sim = Simulation(
        world=WorldState(
            faction_registry=["source", "alpha", "beta", "delta", "gamma"],
            activated_factions=["alpha", "delta", "source"],
        ),
        seed=34,
    )
    sim.register_rule_module(BeliefJobQueueModule())
    sim.state.world.faction_beliefs = {
        "source": {"belief_records": {}},
        "beta": {"belief_records": {}},
        "gamma": {"belief_records": {}},
    }

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params={
            "source_faction_id": "source",
            "subject": _claim_subject(),
            "claim_key": "violence",
            "confidence": 25,
        },
    )
    sim.advance_ticks(1)

    assert "transmission_queue" in sim.state.world.faction_beliefs["alpha"]
    assert "transmission_queue" in sim.state.world.faction_beliefs["delta"]
    assert "beta" in sim.state.world.faction_beliefs
    assert "transmission_queue" not in sim.state.world.faction_beliefs["beta"]
    assert "gamma" in sim.state.world.faction_beliefs
    assert "transmission_queue" not in sim.state.world.faction_beliefs["gamma"]


def test_slice1f_backward_compat_defaults_registry_from_belief_keys() -> None:
    payload = WorldState().to_dict()
    payload["faction_beliefs"] = {
        "wolves": {
            "belief_records": {
                "belief:w": {
                    "belief_id": "belief:w",
                    "subject": {"kind": "player", "id": "player"},
                    "claim_key": "violence",
                    "confidence": 20,
                    "first_seen_tick": 0,
                    "last_updated_tick": 0,
                    "evidence_count": 1,
                }
            }
        },
        "hawks": {
            "belief_records": {
                "belief:h": {
                    "belief_id": "belief:h",
                    "subject": {"kind": "player", "id": "player"},
                    "claim_key": "aid",
                    "confidence": 10,
                    "first_seen_tick": 0,
                    "last_updated_tick": 0,
                    "evidence_count": 1,
                }
            }
        },
    }

    loaded = WorldState.from_dict(payload)

    assert loaded.faction_registry == ["hawks", "wolves"]
    assert loaded.activated_factions == []


def test_slice1f_backward_compat_registry_derivation_does_not_grow_canonical_payload() -> None:
    payload = WorldState().to_dict()
    payload["faction_beliefs"] = {
        "wolves": {
            "belief_records": {
                "belief:w": {
                    "belief_id": "belief:w",
                    "subject": {"kind": "player", "id": "player"},
                    "claim_key": "violence",
                    "confidence": 20,
                    "first_seen_tick": 0,
                    "last_updated_tick": 0,
                    "evidence_count": 1,
                }
            }
        },
        "hawks": {
            "belief_records": {
                "belief:h": {
                    "belief_id": "belief:h",
                    "subject": {"kind": "player", "id": "player"},
                    "claim_key": "aid",
                    "confidence": 10,
                    "first_seen_tick": 0,
                    "last_updated_tick": 0,
                    "evidence_count": 1,
                }
            }
        },
    }

    loaded_a = WorldState.from_dict(payload)
    serialized_a = loaded_a.to_dict()
    loaded_b = WorldState.from_dict(serialized_a)
    serialized_b = loaded_b.to_dict()

    assert loaded_a.faction_registry == ["hawks", "wolves"]
    assert "faction_registry" not in serialized_a
    assert "faction_registry" not in serialized_b
    assert world_hash(loaded_a) == world_hash(loaded_b)


def test_slice1f_explicit_registry_persists_when_present_in_input() -> None:
    payload = WorldState().to_dict()
    payload["faction_beliefs"] = {
        "wolves": {
            "belief_records": {
                "belief:w": {
                    "belief_id": "belief:w",
                    "subject": {"kind": "player", "id": "player"},
                    "claim_key": "violence",
                    "confidence": 20,
                    "first_seen_tick": 0,
                    "last_updated_tick": 0,
                    "evidence_count": 1,
                }
            }
        },
    }
    payload["faction_registry"] = ["wolves"]

    loaded = WorldState.from_dict(payload)

    assert loaded.to_dict()["faction_registry"] == ["wolves"]


def test_slice1f_backward_compat_derived_runtime_registry_gates_activation_validation() -> None:
    payload = WorldState().to_dict()
    payload["faction_beliefs"] = {
        "wolves": {
            "belief_records": {
                "belief:w": {
                    "belief_id": "belief:w",
                    "subject": {"kind": "player", "id": "player"},
                    "claim_key": "violence",
                    "confidence": 20,
                    "first_seen_tick": 0,
                    "last_updated_tick": 0,
                    "evidence_count": 1,
                }
            }
        },
    }

    loaded = WorldState.from_dict(payload)

    assert normalize_activated_factions(["wolves"], faction_registry=loaded.faction_registry) == ["wolves"]
    with pytest.raises(ValueError, match="activated_factions must be a subset"):
        normalize_activated_factions(["hawks"], faction_registry=loaded.faction_registry)


def test_slice1f_registry_activation_save_load_and_hash_stability() -> None:
    world_default = WorldState()
    world_with_gate = WorldState(faction_registry=["wolves", "hawks"], activated_factions=["wolves"])

    payload = world_with_gate.to_dict()
    loaded = WorldState.from_dict(payload)

    assert loaded.to_dict() == payload
    assert world_hash(loaded) == world_hash(world_with_gate)
    assert world_hash(world_with_gate) != world_hash(world_default)

