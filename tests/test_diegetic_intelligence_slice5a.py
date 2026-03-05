from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
    FACTION_INVESTIGATOR_SPAWN_REJECTED_EVENT_TYPE,
    FACTION_INVESTIGATOR_SPAWNED_EVENT_TYPE,
    FactionInvestigationActorModule,
    MAX_INVESTIGATORS_SPAWNED_PER_TICK,
)
from hexcrawler.sim.hash import simulation_hash


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def _build_sim(seed: int = 1) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(FactionInvestigationActorModule())
    return sim


def _enqueue_job(
    sim: Simulation,
    *,
    event_id: str,
    action_uid: str,
    faction_id: str,
    belief_id: str,
    location: dict[str, object] | None = None,
) -> None:
    claim: dict[str, object] = {"subject": {"kind": "unknown_actor"}, "claim_key": belief_id, "confidence": 50}
    if location is not None:
        claim["location"] = location
    sim.schedule_event(
        SimEvent(
            tick=0,
            event_id=event_id,
            event_type=BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
            params={
                "faction_id": faction_id,
                "belief_id": belief_id,
                "source_action_uid": action_uid,
                "claim": claim,
            },
        )
    )


def test_slice5a_basic_investigator_spawn() -> None:
    sim = _build_sim(seed=501)
    _enqueue_job(sim, event_id="evt-1", action_uid="act-1", faction_id="wolves", belief_id="belief-1")

    sim.advance_ticks(2)

    entity = sim.state.entities["investigator:act-1:0"]
    assert entity.template_id == "faction_investigator"
    assert entity.stats["faction_id"] == "wolves"
    assert entity.stats["role"] == "investigator"
    assert entity.stats["source_belief_id"] == "belief-1"
    assert entity.stats["source_action_uid"] == "act-1"

    spawned = _events(sim, FACTION_INVESTIGATOR_SPAWNED_EVENT_TYPE)
    assert len(spawned) == 1
    assert spawned[0]["params"]["entity_id"] == "investigator:act-1:0"


def test_slice5a_deterministic_identity_same_seed_and_inputs() -> None:
    sim_a = _build_sim(seed=502)
    sim_b = _build_sim(seed=502)
    for sim in (sim_a, sim_b):
        _enqueue_job(sim, event_id="evt-1", action_uid="act-1", faction_id="wolves", belief_id="belief-1")
        _enqueue_job(sim, event_id="evt-2", action_uid="act-2", faction_id="wolves", belief_id="belief-2")

    sim_a.advance_ticks(2)
    sim_b.advance_ticks(2)

    assert sorted(sim_a.state.entities) == sorted(sim_b.state.entities)
    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_slice5a_cap_enforcement_emits_rejection_event() -> None:
    sim = _build_sim(seed=503)
    for index in range(MAX_INVESTIGATORS_SPAWNED_PER_TICK + 2):
        _enqueue_job(
            sim,
            event_id=f"evt-{index}",
            action_uid=f"act-{index}",
            faction_id="wolves",
            belief_id=f"belief-{index}",
        )

    sim.advance_ticks(2)

    spawned = _events(sim, FACTION_INVESTIGATOR_SPAWNED_EVENT_TYPE)
    rejected = _events(sim, FACTION_INVESTIGATOR_SPAWN_REJECTED_EVENT_TYPE)
    assert len(spawned) == MAX_INVESTIGATORS_SPAWNED_PER_TICK
    assert len(rejected) == 2
    assert {row["params"]["reason"] for row in rejected} == {"cap_exceeded"}


def test_slice5a_idempotence_duplicate_enqueue_action_uid_spawns_once() -> None:
    sim = _build_sim(seed=504)
    _enqueue_job(sim, event_id="evt-1", action_uid="act-dup", faction_id="wolves", belief_id="belief-1")
    _enqueue_job(sim, event_id="evt-2", action_uid="act-dup", faction_id="wolves", belief_id="belief-1")

    sim.advance_ticks(2)

    assert [entity_id for entity_id in sim.state.entities if entity_id.startswith("investigator:")] == [
        "investigator:act-dup:0"
    ]
    assert len(_events(sim, FACTION_INVESTIGATOR_SPAWNED_EVENT_TYPE)) == 1


def test_slice5a_save_load_stability_keeps_hash_and_ids() -> None:
    base = _build_sim(seed=505)
    _enqueue_job(base, event_id="evt-1", action_uid="act-1", faction_id="wolves", belief_id="belief-1")
    base.advance_ticks(2)

    loaded = Simulation.from_simulation_payload(base.simulation_payload())
    loaded.register_rule_module(FactionInvestigationActorModule())

    assert sorted(base.state.entities) == sorted(loaded.state.entities)
    assert simulation_hash(base) == simulation_hash(loaded)


def test_slice5a_ordering_independent_of_enqueue_arrival_order() -> None:
    sim = _build_sim(seed=506)
    jobs = [
        ("evt-c", "act-c", "f02", "b01"),
        ("evt-a", "act-a", "f01", "b02"),
        ("evt-d", "act-d", "f03", "b01"),
        ("evt-b", "act-b", "f01", "b01"),
    ]
    for event_id, action_uid, faction_id, belief_id in jobs:
        _enqueue_job(
            sim,
            event_id=event_id,
            action_uid=action_uid,
            faction_id=faction_id,
            belief_id=belief_id,
        )

    sim.advance_ticks(2)

    keys = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["source_action_uid"],
        )
        for row in _events(sim, FACTION_INVESTIGATOR_SPAWNED_EVENT_TYPE)
    ]
    assert keys == sorted(keys)
