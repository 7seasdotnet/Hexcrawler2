from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_UNKNOWN_ACTOR_ATTRIBUTED_EVENT_TYPE,
    MAX_UNKNOWN_ATTRIBUTIONS_PER_TICK,
    UNKNOWN_ACTOR_ATTRIBUTION_CONFIDENCE,
    UNKNOWN_ACTOR_MAX_CONF_THRESHOLD,
    UNKNOWN_ACTOR_MIN_CONTESTED_AGE_TICKS,
    BeliefJobQueueModule,
    compute_belief_id,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def _contested_world(*, faction_id: str, base_key: str, confidence_a: int, confidence_b: int, contested_since_tick: int, tick: int) -> WorldState:
    subject = {"kind": "player", "id": "player"}
    affirm_claim = f"{base_key}:affirm"
    deny_claim = f"{base_key}:deny"
    affirm_id = compute_belief_id(faction_id=faction_id, subject=subject, claim_key=affirm_claim)
    deny_id = compute_belief_id(faction_id=faction_id, subject=subject, claim_key=deny_claim)
    payload = {
        "faction_beliefs": {
            faction_id: {
                "belief_records": {
                    affirm_id: {
                        "belief_id": affirm_id,
                        "subject": subject,
                        "claim_key": affirm_claim,
                        "base_key": base_key,
                        "stance": "affirm",
                        "opposed_belief_id": deny_id,
                        "contested_since_tick": contested_since_tick,
                        "confidence": confidence_a,
                        "first_seen_tick": 0,
                        "last_updated_tick": tick,
                        "evidence_count": 1,
                    },
                    deny_id: {
                        "belief_id": deny_id,
                        "subject": subject,
                        "claim_key": deny_claim,
                        "base_key": base_key,
                        "stance": "deny",
                        "opposed_belief_id": affirm_id,
                        "contested_since_tick": contested_since_tick,
                        "confidence": confidence_b,
                        "first_seen_tick": 0,
                        "last_updated_tick": tick,
                        "evidence_count": 1,
                    },
                }
            }
        }
    }
    return WorldState.from_dict(payload)


def test_slice3b_attribution_triggers_deterministically_once() -> None:
    tick = 0
    world = _contested_world(
        faction_id="wolves",
        base_key="raid",
        confidence_a=UNKNOWN_ACTOR_MAX_CONF_THRESHOLD,
        confidence_b=20,
        contested_since_tick=0,
        tick=tick,
    )
    sim = Simulation(world=world, seed=1)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.advance_ticks(UNKNOWN_ACTOR_MIN_CONTESTED_AGE_TICKS + 11)

    unknown_subject = {"kind": "unknown_actor", "id": "unknown"}
    unknown_id = compute_belief_id(faction_id="wolves", subject=unknown_subject, claim_key="raid:affirm")
    records = sim.state.world.faction_beliefs["wolves"]["belief_records"]
    assert records[unknown_id]["confidence"] == UNKNOWN_ACTOR_ATTRIBUTION_CONFIDENCE

    affirm_id = compute_belief_id(faction_id="wolves", subject={"kind": "player", "id": "player"}, claim_key="raid:affirm")
    deny_id = compute_belief_id(faction_id="wolves", subject={"kind": "player", "id": "player"}, claim_key="raid:deny")
    attribution_tick = int(_events(sim, BELIEF_UNKNOWN_ACTOR_ATTRIBUTED_EVENT_TYPE)[0]["tick"])
    assert records[affirm_id]["last_unknown_actor_attribution_tick"] == attribution_tick - 1
    assert records[deny_id]["last_unknown_actor_attribution_tick"] == attribution_tick - 1

    sim.advance_ticks(1)
    assert records[unknown_id]["evidence_count"] == 1
    assert len(_events(sim, BELIEF_UNKNOWN_ACTOR_ATTRIBUTED_EVENT_TYPE)) == 1


def test_slice3b_no_attribution_when_confidence_too_high() -> None:
    tick = 80
    world = _contested_world(
        faction_id="wolves",
        base_key="raid",
        confidence_a=UNKNOWN_ACTOR_MAX_CONF_THRESHOLD + 1,
        confidence_b=1,
        contested_since_tick=0,
        tick=tick,
    )
    sim = Simulation(world=world, seed=2)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.advance_ticks(1)
    unknown_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "unknown_actor", "id": "unknown"},
        claim_key="raid:affirm",
    )
    assert unknown_id not in sim.state.world.faction_beliefs["wolves"]["belief_records"]


def test_slice3b_no_attribution_when_contested_age_too_small() -> None:
    tick = 20
    world = _contested_world(
        faction_id="wolves",
        base_key="raid",
        confidence_a=10,
        confidence_b=10,
        contested_since_tick=tick,
        tick=tick,
    )
    sim = Simulation(world=world, seed=3)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.advance_ticks(1)
    unknown_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "unknown_actor", "id": "unknown"},
        claim_key="raid:affirm",
    )
    assert unknown_id not in sim.state.world.faction_beliefs["wolves"]["belief_records"]


def test_slice3b_respects_bounded_cap_and_deterministic_ordering() -> None:
    tick = 0
    world = WorldState()
    for index in range(MAX_UNKNOWN_ATTRIBUTIONS_PER_TICK + 2):
        faction_id = f"f{index:02d}"
        world.faction_beliefs[faction_id] = _contested_world(
            faction_id=faction_id,
            base_key="raid",
            confidence_a=5,
            confidence_b=5,
            contested_since_tick=0,
            tick=tick,
        ).faction_beliefs[faction_id]

    sim = Simulation(world=world, seed=4)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(UNKNOWN_ACTOR_MIN_CONTESTED_AGE_TICKS + 2)

    forensic = _events(sim, BELIEF_UNKNOWN_ACTOR_ATTRIBUTED_EVENT_TYPE)
    assert len(forensic) == MAX_UNKNOWN_ATTRIBUTIONS_PER_TICK
    assert [row["params"]["faction_id"] for row in forensic] == [f"f{idx:02d}" for idx in range(MAX_UNKNOWN_ATTRIBUTIONS_PER_TICK)]


def test_slice3b_save_load_hash_stability_and_default_omission() -> None:
    tick = 120
    world = _contested_world(
        faction_id="wolves",
        base_key="raid",
        confidence_a=10,
        confidence_b=10,
        contested_since_tick=tick - UNKNOWN_ACTOR_MIN_CONTESTED_AGE_TICKS,
        tick=tick,
    )
    sim = Simulation(world=world, seed=5)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(1)

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded) == simulation_hash(sim)

    world_no_contested = WorldState.from_dict(
        {
            "faction_beliefs": {
                "wolves": {
                    "belief_records": {
                        "belief:legacy": {
                            "belief_id": "belief:legacy",
                            "subject": {"kind": "player", "id": "player"},
                            "claim_key": "legacy:affirm",
                            "confidence": 1,
                            "first_seen_tick": 1,
                            "last_updated_tick": 1,
                            "evidence_count": 1,
                        }
                    }
                }
            }
        }
    )
    record = world_no_contested.to_dict()["faction_beliefs"]["wolves"]["belief_records"]["belief:legacy"]
    assert "contested_since_tick" not in record
    assert "last_unknown_actor_attribution_tick" not in record


def test_slice3b_backward_compat_contested_defaults_deterministically() -> None:
    faction_id = "wolves"
    subject = {"kind": "player", "id": "player"}
    affirm_id = compute_belief_id(faction_id=faction_id, subject=subject, claim_key="raid:affirm")
    deny_id = compute_belief_id(faction_id=faction_id, subject=subject, claim_key="raid:deny")

    payload = {
        "faction_beliefs": {
            faction_id: {
                "belief_records": {
                    affirm_id: {
                        "belief_id": affirm_id,
                        "subject": subject,
                        "claim_key": "raid:affirm",
                        "base_key": "raid",
                        "stance": "affirm",
                        "opposed_belief_id": deny_id,
                        "confidence": 10,
                        "first_seen_tick": 1,
                        "last_updated_tick": 10,
                        "evidence_count": 1,
                    },
                    deny_id: {
                        "belief_id": deny_id,
                        "subject": subject,
                        "claim_key": "raid:deny",
                        "base_key": "raid",
                        "stance": "deny",
                        "opposed_belief_id": affirm_id,
                        "confidence": 10,
                        "first_seen_tick": 1,
                        "last_updated_tick": 10,
                        "evidence_count": 1,
                    },
                }
            }
        }
    }

    world = WorldState.from_dict(payload)
    records = world.faction_beliefs[faction_id]["belief_records"]
    assert records[affirm_id]["contested_since_tick"] == 10
    assert "last_unknown_actor_attribution_tick" not in records[affirm_id]

    sim = Simulation(world=world, seed=6)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(UNKNOWN_ACTOR_MIN_CONTESTED_AGE_TICKS + 12)

    forensic = _events(sim, BELIEF_UNKNOWN_ACTOR_ATTRIBUTED_EVENT_TYPE)
    assert len(forensic) == 1
