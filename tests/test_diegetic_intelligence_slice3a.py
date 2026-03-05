from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_CLAIM_EMITTED_EVENT_TYPE,
    BELIEF_CONTRADICTION_DETECTED_EVENT_TYPE,
    BELIEF_CONTRADICTION_RESOLVED_EVENT_TYPE,
    BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
    BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE,
    BELIEF_UPDATED_FROM_TRANSMISSION_EVENT_TYPE,
    BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
    INVESTIGATION_CONFIDENCE_DELTA,
    INVESTIGATION_DEFAULT_CONFIDENCE,
    INVESTIGATION_RESOLVE_DELTA,
    BeliefClaimIngestionModule,
    BeliefJobQueueModule,
    compute_belief_id,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_slice3a_contradiction_detected_on_ingestion() -> None:
    sim = Simulation(world=WorldState(), seed=1)
    sim.register_rule_module(BeliefClaimIngestionModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_CLAIM_EMITTED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim_key": "wanted:affirm", "confidence_delta": 20, "evidence_increment": 1},
    )
    sim.schedule_event_at(
        tick=1,
        event_type=BELIEF_CLAIM_EMITTED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim_key": "wanted:deny", "confidence_delta": 25, "evidence_increment": 1},
    )

    sim.advance_ticks(3)

    affirm_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="wanted:affirm",
    )
    deny_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="wanted:deny",
    )
    records = sim.state.world.faction_beliefs["wolves"]["belief_records"]

    assert records[affirm_id]["base_key"] == "wanted"
    assert records[affirm_id]["stance"] == "affirm"
    assert records[affirm_id]["opposed_belief_id"] == deny_id
    assert records[deny_id]["opposed_belief_id"] == affirm_id

    forensic = _events(sim, BELIEF_CONTRADICTION_DETECTED_EVENT_TYPE)
    assert len(forensic) == 1


def test_slice3a_investigation_resolves_contested_beliefs_deterministically() -> None:
    sim = Simulation(world=WorldState(), seed=2)
    sim.register_rule_module(BeliefJobQueueModule())
    claim_affirm = {"subject": {"kind": "player", "id": "player"}, "claim_key": "raider:affirm", "confidence": 40}
    claim_deny = {"subject": {"kind": "player", "id": "player"}, "claim_key": "raider:deny", "confidence": 5}

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:a", "claim": claim_affirm, "tick": 0},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:b", "claim": claim_deny, "tick": 0},
    )
    sim.advance_ticks(1)

    sim.schedule_event_at(
        tick=1,
        event_type=BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:c", "claim": claim_affirm, "tick": 1},
    )
    sim.advance_ticks(1)

    affirm_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="raider:affirm",
    )
    deny_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="raider:deny",
    )
    records = sim.state.world.faction_beliefs["wolves"]["belief_records"]

    assert records[affirm_id]["confidence"] == 40 + INVESTIGATION_RESOLVE_DELTA
    assert records[deny_id]["confidence"] == 0
    assert "opposed_belief_id" not in records[affirm_id]
    assert "opposed_belief_id" not in records[deny_id]

    resolved = _events(sim, BELIEF_CONTRADICTION_RESOLVED_EVENT_TYPE)
    assert len(resolved) == 1


def test_slice3a_non_contested_investigation_behavior_is_bounded() -> None:
    sim = Simulation(world=WorldState(), seed=3)
    sim.register_rule_module(BeliefJobQueueModule())
    claim = {"subject": {"kind": "player", "id": "player"}, "claim_key": "aid:affirm", "confidence": 20}

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:z", "claim": claim, "tick": 0},
    )
    sim.advance_ticks(1)

    belief_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="aid:affirm",
    )
    belief = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]

    assert belief["confidence"] == INVESTIGATION_DEFAULT_CONFIDENCE + INVESTIGATION_CONFIDENCE_DELTA
    assert belief["base_key"] == "aid"
    assert belief["stance"] == "affirm"
    assert "opposed_belief_id" not in belief
    assert len(_events(sim, BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE)) == 1


def test_slice3a_save_load_and_hash_stability_for_contested_and_resolved_states() -> None:
    sim = Simulation(world=WorldState(), seed=4)
    sim.register_rule_module(BeliefJobQueueModule())
    claim_affirm = {"subject": {"kind": "player", "id": "player"}, "claim_key": "thief:affirm", "confidence": 35}
    claim_deny = {"subject": {"kind": "player", "id": "player"}, "claim_key": "thief:deny", "confidence": 35}

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:1", "claim": claim_affirm, "tick": 0},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:2", "claim": claim_deny, "tick": 0},
    )
    sim.advance_ticks(1)

    loaded_contested = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded_contested.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded_contested) == simulation_hash(sim)

    sim.schedule_event_at(
        tick=1,
        event_type=BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
        params={"faction_id": "wolves", "job_id": "job:3", "claim": claim_affirm, "tick": 1},
    )
    sim.advance_ticks(1)

    loaded_after_resolution_attempt = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded_after_resolution_attempt.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded_after_resolution_attempt) == simulation_hash(sim)


def test_slice3a_backward_compat_pre_3a_belief_records_load_with_defaults() -> None:
    payload = {
        "faction_beliefs": {
            "wolves": {
                "belief_records": {
                    "belief:legacy": {
                        "belief_id": "belief:legacy",
                        "subject": {"kind": "player", "id": "player"},
                        "claim_key": "legacy_claim",
                        "confidence": 10,
                        "first_seen_tick": 1,
                        "last_updated_tick": 1,
                        "evidence_count": 1,
                    }
                }
            }
        }
    }

    world = WorldState.from_dict(payload)
    record = world.faction_beliefs["wolves"]["belief_records"]["belief:legacy"]
    assert record["base_key"] == "legacy_claim"
    assert record["stance"] == "affirm"
    assert "opposed_belief_id" not in record
