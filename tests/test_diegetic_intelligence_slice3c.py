from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_REACTION_BUDGET_EXHAUSTED_EVENT_TYPE,
    BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
    BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE,
    REACTION_COOLDOWN_TICKS,
    BeliefJobQueueModule,
    compute_belief_id,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def _contested_pair(*, faction_id: str, base_key: str, confidence_a: int, confidence_b: int, contested_since_tick: int, last_updated_tick: int) -> dict[str, dict[str, object]]:
    subject = {"kind": "player", "id": "player"}
    affirm_claim = f"{base_key}:affirm"
    deny_claim = f"{base_key}:deny"
    affirm_id = compute_belief_id(faction_id=faction_id, subject=subject, claim_key=affirm_claim)
    deny_id = compute_belief_id(faction_id=faction_id, subject=subject, claim_key=deny_claim)
    return {
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
            "last_updated_tick": last_updated_tick,
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
            "last_updated_tick": last_updated_tick,
            "evidence_count": 1,
        },
    }


def test_slice3c_disabled_config_no_effect() -> None:
    world = WorldState.from_dict(
        {
            "faction_beliefs": {
                "wolves": {
                    "belief_records": _contested_pair(
                        faction_id="wolves",
                        base_key="raid",
                        confidence_a=90,
                        confidence_b=50,
                        contested_since_tick=0,
                        last_updated_tick=100,
                    )
                }
            }
        }
    )
    sim = Simulation(world=world, seed=11)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(2)

    assert not _events(sim, BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE)
    faction_state = sim.state.world.faction_beliefs["wolves"]
    assert "investigation_queue" not in faction_state
    for record in faction_state["belief_records"].values():
        assert "last_contested_investigation_reaction_tick" not in record


def test_slice3c_contested_reaction_triggers_and_cooldown_blocks_next_tick() -> None:
    world = WorldState.from_dict(
        {
            "belief_reaction_config": {
                "enabled": True,
                "contested_investigation_threshold": 60,
                "contested_min_age_ticks": 0,
                "unknown_actor_investigation_threshold": 70,
            },
            "faction_beliefs": {
                "wolves": {
                    "belief_records": _contested_pair(
                        faction_id="wolves",
                        base_key="raid",
                        confidence_a=60,
                        confidence_b=85,
                        contested_since_tick=0,
                        last_updated_tick=100,
                    )
                }
            },
        }
    )
    sim = Simulation(world=world, seed=12)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.advance_ticks(2)
    forensic = _events(sim, BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE)
    assert len(forensic) == 1

    faction_state = sim.state.world.faction_beliefs["wolves"]
    assert len(faction_state["investigation_queue"]) == 1
    for record in faction_state["belief_records"].values():
        assert "last_contested_investigation_reaction_tick" in record

    sim.advance_ticks(1)
    assert len(_events(sim, BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE)) == 1


def test_slice3c_unknown_actor_reaction_triggers_deterministically() -> None:
    subject = {"kind": "unknown_actor", "id": "unknown"}
    claim_key = "raid:affirm"
    belief_id = compute_belief_id(faction_id="wolves", subject=subject, claim_key=claim_key)
    world = WorldState.from_dict(
        {
            "belief_reaction_config": {
                "enabled": True,
                "unknown_actor_investigation_threshold": 70,
            },
            "faction_beliefs": {
                "wolves": {
                    "belief_records": {
                        belief_id: {
                            "belief_id": belief_id,
                            "subject": subject,
                            "claim_key": claim_key,
                            "confidence": 80,
                            "first_seen_tick": 0,
                            "last_updated_tick": 100,
                            "evidence_count": 1,
                        }
                    }
                }
            },
        }
    )
    sim = Simulation(world=world, seed=13)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.advance_ticks(2)
    assert len(_events(sim, BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE)) == 1
    record = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert "last_unknown_actor_investigation_reaction_tick" in record
    assert len(sim.state.world.faction_beliefs["wolves"]["investigation_queue"]) == 1


def test_slice3c_budget_caps_enforced_in_lexical_order() -> None:
    world = WorldState.from_dict(
        {
            "belief_reaction_config": {
                "enabled": True,
                "max_reactions_per_tick": 2,
                "max_investigation_jobs_enqueued_per_tick": 1,
                "contested_investigation_threshold": 50,
                "contested_min_age_ticks": 0,
                "unknown_actor_investigation_threshold": 50,
            },
            "faction_beliefs": {
                "f01": {"belief_records": _contested_pair(faction_id="f01", base_key="r1", confidence_a=90, confidence_b=1, contested_since_tick=0, last_updated_tick=10)},
                "f02": {"belief_records": _contested_pair(faction_id="f02", base_key="r2", confidence_a=90, confidence_b=1, contested_since_tick=0, last_updated_tick=10)},
                "f03": {"belief_records": _contested_pair(faction_id="f03", base_key="r3", confidence_a=90, confidence_b=1, contested_since_tick=0, last_updated_tick=10)},
            },
        }
    )
    sim = Simulation(world=world, seed=14)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(2)

    forensic = _events(sim, BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE)
    assert len(forensic) == 2
    assert [row["params"]["faction_id"] for row in forensic] == ["f01", "f02"]
    assert len(_events(sim, BELIEF_REACTION_BUDGET_EXHAUSTED_EVENT_TYPE)) == 1

    assert len(sim.state.world.faction_beliefs["f01"].get("investigation_queue", [])) == 1
    assert "investigation_queue" not in sim.state.world.faction_beliefs["f02"]


def test_slice3c_save_load_hash_stability_and_marker_default_omission() -> None:
    world = WorldState.from_dict(
        {
            "belief_reaction_config": {
                "enabled": True,
                "contested_investigation_threshold": 50,
                "contested_min_age_ticks": 0,
            },
            "faction_beliefs": {
                "wolves": {
                    "belief_records": _contested_pair(
                        faction_id="wolves",
                        base_key="raid",
                        confidence_a=90,
                        confidence_b=20,
                        contested_since_tick=0,
                        last_updated_tick=100,
                    )
                }
            },
        }
    )
    sim = Simulation(world=world, seed=15)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(2)

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded) == simulation_hash(sim)

    empty = WorldState.from_dict(
        {
            "faction_beliefs": {
                "wolves": {
                    "belief_records": {
                        "b1": {
                            "belief_id": "b1",
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
    legacy_record = empty.to_dict()["faction_beliefs"]["wolves"]["belief_records"]["b1"]
    assert "last_contested_investigation_reaction_tick" not in legacy_record
    assert "last_unknown_actor_investigation_reaction_tick" not in legacy_record


def test_slice3c_backward_compat_pre3c_beliefs_default_markers() -> None:
    subject = {"kind": "unknown_actor", "id": "unknown"}
    claim_key = "legacy:affirm"
    belief_id = compute_belief_id(faction_id="wolves", subject=subject, claim_key=claim_key)
    world = WorldState.from_dict(
        {
            "belief_reaction_config": {"enabled": True, "unknown_actor_investigation_threshold": 40},
            "faction_beliefs": {
                "wolves": {
                    "belief_records": {
                        belief_id: {
                            "belief_id": belief_id,
                            "subject": subject,
                            "claim_key": claim_key,
                            "confidence": 40,
                            "first_seen_tick": 2,
                            "last_updated_tick": 2,
                            "evidence_count": 1,
                        }
                    }
                }
            },
        }
    )

    record = world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert "last_unknown_actor_investigation_reaction_tick" not in record

    sim = Simulation(world=world, seed=16)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.advance_ticks(2)
    assert len(_events(sim, BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE)) == 1

    sim.advance_ticks(REACTION_COOLDOWN_TICKS)
    assert len(_events(sim, BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE)) == 2
