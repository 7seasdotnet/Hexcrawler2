from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.beliefs import (
    BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
    BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import EntityState, SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
    FACTION_INVESTIGATION_COMPLETION_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_INVESTIGATION_OUTCOME_HOOK_APPLIED_EVENT_TYPE,
    FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE,
    FactionInvestigationActorModule,
    FactionInvestigationOutcomeHooksModule,
    MAX_FACTION_INVESTIGATION_COMPLETIONS_PER_TICK,
)
from hexcrawler.sim.groups import GroupMovementModule
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def _build_sim(seed: int = 1) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.register_rule_module(GroupMovementModule())
    sim.register_rule_module(FactionInvestigationActorModule())
    sim.register_rule_module(FactionInvestigationOutcomeHooksModule())
    return sim


def _enqueue_job(
    sim: Simulation,
    *,
    event_id: str,
    action_uid: str,
    faction_id: str,
    belief_id: str,
    target_location: dict[str, object] | None = None,
) -> None:
    claim: dict[str, object] = {"subject": {"kind": "unknown_actor", "id": "unknown"}, "claim_key": belief_id, "confidence": 50}
    if target_location is not None:
        claim["location"] = target_location
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
                "target_location": target_location,
            },
        )
    )


def test_slice5b_basic_completion_hook_exactly_once() -> None:
    sim = _build_sim(seed=601)
    _enqueue_job(sim, event_id="evt-1", action_uid="act-1", faction_id="wolves", belief_id="belief-1")

    sim.advance_ticks(4)

    completed = _events(sim, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)
    assert len(completed) == 1
    assert completed[0]["params"]["source_action_uid"] == "act-1"


def test_slice5b_bridge_back_reuses_belief_investigation_completion_seam() -> None:
    sim = _build_sim(seed=602)
    _enqueue_job(sim, event_id="evt-1", action_uid="act-bridge", faction_id="wolves", belief_id="belief-bridge")

    sim.advance_ticks(4)

    applied = _events(sim, FACTION_INVESTIGATION_OUTCOME_HOOK_APPLIED_EVENT_TYPE)
    assert len(applied) == 1
    assert applied[0]["params"]["bridged_event_type"] == BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE

    completed = _events(sim, BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE)
    updated = _events(sim, BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE)
    assert len(completed) == 1
    assert len(updated) == 1


def test_slice5b_idempotence_duplicate_completion_trigger_is_ignored() -> None:
    sim = _build_sim(seed=603)
    _enqueue_job(sim, event_id="evt-1", action_uid="act-dup", faction_id="wolves", belief_id="belief-dup")

    sim.advance_ticks(2)
    sim.advance_ticks(3)

    assert len(_events(sim, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)) == 1
    assert len(_events(sim, FACTION_INVESTIGATION_OUTCOME_HOOK_APPLIED_EVENT_TYPE)) == 1
    assert len(_events(sim, BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE)) == 1


def test_slice5b_ordering_is_lexical_not_arrival_order() -> None:
    sim = _build_sim(seed=604)
    jobs = [
        ("evt-c", "act-c", "f02", "b01"),
        ("evt-a", "act-a", "f01", "b02"),
        ("evt-d", "act-d", "f03", "b01"),
        ("evt-b", "act-b", "f01", "b01"),
    ]
    for event_id, action_uid, faction_id, belief_id in jobs:
        _enqueue_job(sim, event_id=event_id, action_uid=action_uid, faction_id=faction_id, belief_id=belief_id)

    sim.advance_ticks(4)

    keys = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["source_action_uid"],
            row["params"]["entity_id"],
        )
        for row in _events(sim, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)
    ]
    assert keys == sorted(keys)


def test_slice5b_budget_cap_emits_single_budget_event_and_halts_processing() -> None:
    sim = _build_sim(seed=605)
    total_jobs = MAX_FACTION_INVESTIGATION_COMPLETIONS_PER_TICK + 3
    for i in range(total_jobs):
        entity_id = f"investigator:budget-{i}:0"
        entity = EntityState.from_hex(entity_id=entity_id, hex_coord=HexCoord(q=i, r=0))
        entity.template_id = "faction_investigator"
        entity.source_action_uid = f"budget-{i}"
        entity.stats = {
            "role": "investigator",
            "faction_id": "wolves",
            "source_belief_id": f"belief-{i}",
            "source_action_uid": f"budget-{i}",
            "location": {"space_id": "overworld", "coord": {"q": i, "r": 0}},
            "target_location": None,
        }
        sim.add_entity(entity)

    sim.advance_ticks(2)

    completions = _events(sim, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)
    exhausted = _events(sim, FACTION_INVESTIGATION_COMPLETION_BUDGET_EXHAUSTED_EVENT_TYPE)
    assert len(completions) == MAX_FACTION_INVESTIGATION_COMPLETIONS_PER_TICK
    assert len(exhausted) == 1


def test_slice5b_save_load_stability_for_outcome_ledger_and_hash() -> None:
    base = _build_sim(seed=606)
    _enqueue_job(base, event_id="evt-1", action_uid="act-save", faction_id="wolves", belief_id="belief-save")
    base.advance_ticks(4)

    loaded = Simulation.from_simulation_payload(base.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    loaded.register_rule_module(GroupMovementModule())
    loaded.register_rule_module(FactionInvestigationActorModule())
    loaded.register_rule_module(FactionInvestigationOutcomeHooksModule())

    loaded.advance_ticks(2)

    assert len(_events(loaded, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)) == 1
    assert simulation_hash(base) == simulation_hash(Simulation.from_simulation_payload(base.simulation_payload()))


def test_slice5b_single_emission_boundary_with_save_load() -> None:
    sim = _build_sim(seed=607)
    _enqueue_job(sim, event_id="evt-1", action_uid="act-boundary", faction_id="wolves", belief_id="belief-boundary")

    # Tick 0 executes staging and tick-end processing; forensic completion event is scheduled for tick+1.
    sim.advance_ticks(1)
    assert len(_events(sim, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)) == 0

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    loaded.register_rule_module(GroupMovementModule())
    loaded.register_rule_module(FactionInvestigationActorModule())
    loaded.register_rule_module(FactionInvestigationOutcomeHooksModule())

    loaded.advance_ticks(3)

    assert len(_events(loaded, FACTION_INVESTIGATOR_COMPLETED_EVENT_TYPE)) == 1
    assert len(_events(loaded, FACTION_INVESTIGATION_OUTCOME_HOOK_APPLIED_EVENT_TYPE)) == 1
    assert len(_events(loaded, BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE)) == 1
