from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
    BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
    BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE,
    BELIEF_UPDATED_FROM_TRANSMISSION_EVENT_TYPE,
    INVESTIGATION_CONFIDENCE_DELTA,
    INVESTIGATION_DEFAULT_CONFIDENCE,
    BeliefJobQueueModule,
    compute_belief_id,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import WorldState


def _claim_payload(*, claim_key: str = "violence", confidence: int = 25) -> dict[str, object]:
    return {
        "subject": {"kind": "player", "id": "player"},
        "claim_key": claim_key,
        "confidence": confidence,
    }


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_slice1c_transmission_completion_mutates_beliefs_and_hash_stable_after_load() -> None:
    sim = Simulation(world=WorldState(), seed=7)
    sim.register_rule_module(BeliefJobQueueModule())
    claim = _claim_payload(claim_key="raid", confidence=30)
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )

    sim.advance_ticks(12)

    faction = sim.state.world.faction_beliefs["wolves"]
    assert faction.get("transmission_queue") is None
    belief_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="raid",
    )
    belief = faction["belief_records"][belief_id]
    assert belief["confidence"] == 30
    assert belief["evidence_count"] == 1
    assert belief["last_updated_tick"] == 11

    forensic = _events(sim, BELIEF_UPDATED_FROM_TRANSMISSION_EVENT_TYPE)
    assert len(forensic) == 1
    assert forensic[0]["params"]["belief_id"] == belief_id

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded) == simulation_hash(sim)


def test_slice1c_investigation_completion_mutates_beliefs_and_hash_stable_after_load() -> None:
    sim = Simulation(world=WorldState(), seed=9)
    sim.register_rule_module(BeliefJobQueueModule())
    claim = _claim_payload(claim_key="theft", confidence=5)
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )

    sim.advance_ticks(22)

    belief_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="theft",
    )
    belief = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert belief["confidence"] == INVESTIGATION_DEFAULT_CONFIDENCE + INVESTIGATION_CONFIDENCE_DELTA
    assert belief["evidence_count"] == 1
    assert belief["last_updated_tick"] == 21

    forensic = _events(sim, BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE)
    assert len(forensic) == 1
    assert forensic[0]["params"]["belief_id"] == belief_id

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded) == simulation_hash(sim)


def test_slice1c_completion_exactly_once_and_duplicate_job_entries_mutate_once() -> None:
    sim = Simulation(world=WorldState(), seed=33)
    sim.register_rule_module(BeliefJobQueueModule())
    claim = _claim_payload(claim_key="aid", confidence=20)

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )

    sim.advance_ticks(22)

    belief_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="aid",
    )
    belief = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert belief["confidence"] == 20
    assert belief["evidence_count"] == 1

    completed = sim.state.world.faction_beliefs["wolves"]["completed_job_ids"]
    assert len(completed) == 1

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="belief_transmission_job_completed",
        params={
            "faction_id": "wolves",
            "job_id": next(iter(completed)),
            "claim": claim,
            "tick": sim.state.tick,
        },
    )
    sim.advance_ticks(1)

    belief_after = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert belief_after["confidence"] == 20
    assert belief_after["evidence_count"] == 1


def test_slice1c_default_omission_empty_ledger_and_queue_hash_stable() -> None:
    world = WorldState()
    payload = world.to_dict()
    assert "faction_beliefs" not in payload

    loaded = WorldState.from_dict(payload)
    assert loaded.to_dict() == payload
    assert world_hash(loaded) == world_hash(world)


def test_slice1c_duplicate_completion_removes_matching_queued_job() -> None:
    sim = Simulation(world=WorldState(), seed=41)
    sim.register_rule_module(BeliefJobQueueModule())
    claim = _claim_payload(claim_key="betrayal", confidence=15)

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )
    sim.advance_ticks(1)

    faction_state = sim.state.world.faction_beliefs["wolves"]
    queued_job_id = faction_state["transmission_queue"][0]["job_id"]
    faction_state["completed_job_ids"] = {queued_job_id: sim.state.tick}

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="belief_transmission_job_completed",
        params={
            "faction_id": "wolves",
            "job_id": queued_job_id,
            "claim": claim,
            "tick": sim.state.tick,
        },
    )
    sim.advance_ticks(1)

    wolves = sim.state.world.faction_beliefs["wolves"]
    assert wolves.get("transmission_queue") is None


def test_slice1c_confidence_scale_is_fixed_point_0_to_100_with_clamp() -> None:
    sim = Simulation(world=WorldState(), seed=51)
    sim.register_rule_module(BeliefJobQueueModule())
    claim = _claim_payload(claim_key="alliance", confidence=100)

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )
    sim.advance_ticks(22)

    belief_id = compute_belief_id(
        faction_id="wolves",
        subject={"kind": "player", "id": "player"},
        claim_key="alliance",
    )
    belief = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert belief["confidence"] == 100

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": claim},
    )
    sim.advance_ticks(22)

    belief_after = sim.state.world.faction_beliefs["wolves"]["belief_records"][belief_id]
    assert belief_after["confidence"] == 100
