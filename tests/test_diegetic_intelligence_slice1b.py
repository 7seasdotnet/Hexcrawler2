from __future__ import annotations

import pytest
from hexcrawler.sim.beliefs import (
    BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
    BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
    BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
    BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
    MAX_JOBS_PER_TICK,
    BeliefJobQueueModule,
    compute_belief_job_id,
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


def _completion_events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_slice1b_world_defaults_omit_belief_queues_and_hash_stable() -> None:
    world = WorldState()
    payload = world.to_dict()

    assert "faction_beliefs" not in payload

    loaded = WorldState.from_dict(payload)
    assert loaded.to_dict() == payload
    assert world_hash(loaded) == world_hash(world)


def test_slice1b_world_with_transmission_job_serializes_and_changes_hash() -> None:
    default_world = WorldState()
    sim = Simulation(world=WorldState(), seed=7)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "not_before_tick": 10, "claim": _claim_payload()},
    )
    sim.advance_ticks(1)

    payload = sim.state.world.to_dict()
    assert "faction_beliefs" in payload

    loaded = WorldState.from_dict(payload)
    assert loaded.to_dict() == payload
    assert world_hash(loaded) == world_hash(sim.state.world)
    assert world_hash(sim.state.world) != world_hash(default_world)


def test_slice1b_processing_order_is_deterministic_across_factions() -> None:
    sim = Simulation(world=WorldState(), seed=11)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim": _claim_payload(claim_key="wolf_claim"), "not_before_tick": 0},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "bears", "claim": _claim_payload(claim_key="bear_claim"), "not_before_tick": 0},
    )

    sim.advance_ticks(2)

    completions = _completion_events(sim, BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE)
    assert len(completions) == 2
    assert completions[0]["params"]["faction_id"] == "bears"
    assert completions[1]["params"]["faction_id"] == "wolves"


def test_slice1b_processing_is_bounded_by_max_jobs_per_tick() -> None:
    sim = Simulation(world=WorldState(), seed=42)
    sim.register_rule_module(BeliefJobQueueModule())

    total_jobs = MAX_JOBS_PER_TICK + 3
    for index in range(total_jobs):
        sim.schedule_event_at(
            tick=0,
            event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
            params={
                "faction_id": "wolves",
                "not_before_tick": 0,
                "claim": _claim_payload(claim_key=f"claim_{index}"),
            },
        )

    sim.advance_ticks(1)
    faction_state = sim.state.world.faction_beliefs["wolves"]
    remaining = faction_state["transmission_queue"]
    assert len(remaining) == total_jobs - MAX_JOBS_PER_TICK
    assert remaining[0]["claim"]["claim_key"] == f"claim_{MAX_JOBS_PER_TICK}"


def test_slice1b_not_before_tick_delay_is_deterministic() -> None:
    sim = Simulation(world=WorldState(), seed=9)
    sim.register_rule_module(BeliefJobQueueModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "not_before_tick": 5, "claim": _claim_payload()},
    )

    sim.advance_ticks(5)
    assert _completion_events(sim, BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE) == []
    assert len(sim.state.world.faction_beliefs["wolves"]["investigation_queue"]) == 1

    sim.advance_ticks(2)
    completions = _completion_events(sim, BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE)
    assert len(completions) == 1
    assert completions[0]["tick"] == 6


def test_slice1b_save_load_hash_stability_for_enqueued_jobs() -> None:
    sim_a = Simulation(world=WorldState(), seed=123)
    sim_b = Simulation(world=WorldState(), seed=123)
    for sim in (sim_a, sim_b):
        sim.register_rule_module(BeliefJobQueueModule())
        sim.schedule_event_at(
            tick=0,
            event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
            params={"faction_id": "wolves", "not_before_tick": 3, "claim": _claim_payload()},
        )
        sim.advance_ticks(2)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)

    loaded = Simulation.from_simulation_payload(sim_a.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    assert simulation_hash(loaded) == simulation_hash(sim_a)


def test_slice1b_max_jobs_per_tick_is_per_faction_total_transmission_first() -> None:
    sim = Simulation(world=WorldState(), seed=99)
    sim.register_rule_module(BeliefJobQueueModule())

    for index in range(MAX_JOBS_PER_TICK):
        sim.schedule_event_at(
            tick=0,
            event_type=BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE,
            params={
                "faction_id": "wolves",
                "not_before_tick": 0,
                "claim": _claim_payload(claim_key=f"t_{index}"),
            },
        )
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "not_before_tick": 0, "claim": _claim_payload(claim_key="i_0")},
    )

    sim.advance_ticks(2)

    transmission_completed = _completion_events(sim, BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE)
    investigation_completed = _completion_events(sim, BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE)

    assert len(transmission_completed) == MAX_JOBS_PER_TICK
    assert investigation_completed == []
    assert "wolves" not in sim.state.world.faction_beliefs


def test_slice1b_load_rejects_invalid_job_payload_instead_of_dropping() -> None:
    invalid_job = {
        "job_id": compute_belief_job_id(
            queue_kind="transmission",
            faction_id="wolves",
            subject={"kind": "player", "id": "player"},
            claim_key="violence",
            created_tick=1,
            not_before_tick=1,
        ),
        "created_tick": 1,
        "not_before_tick": 1,
        "faction_id": "wolves",
        "claim": _claim_payload(),
    }
    invalid_job["job_id"] = "belief_job:tampered"

    payload = WorldState().to_dict()
    payload["faction_beliefs"] = {
        "wolves": {
            "belief_records": {},
            "transmission_queue": [invalid_job],
        }
    }

    with pytest.raises(ValueError, match="job_id mismatch"):
        WorldState.from_dict(payload)


def test_slice1b_non_empty_queue_is_never_omitted_during_normalization() -> None:
    sim = Simulation(world=WorldState(), seed=5)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        params={"faction_id": "wolves", "not_before_tick": 20, "claim": _claim_payload()},
    )
    sim.advance_ticks(1)

    payload = sim.state.world.to_dict()
    assert payload["faction_beliefs"]["wolves"]["investigation_queue"]

    loaded = WorldState.from_dict(payload)
    assert loaded.to_dict() == payload
