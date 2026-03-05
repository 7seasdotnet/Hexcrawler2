from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.beliefs import BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE, BeliefJobQueueModule
from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    FACTION_HOSTILITY_ESCALATED_EVENT_TYPE,
    FACTION_POLITICAL_ACTION_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_RAID_INTENT_DECLARED_EVENT_TYPE,
    FACTION_WARNING_ISSUED_EVENT_TYPE,
    FactionPoliticalActionModule,
    HOSTILITY_THRESHOLD,
    MAX_FACTION_POLITICAL_ACTIONS_PER_TICK,
    RAID_THRESHOLD,
    WARNING_THRESHOLD,
)
from hexcrawler.sim.hash import simulation_hash


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def _build_sim(seed: int = 1) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(BeliefJobQueueModule())
    sim.register_rule_module(FactionPoliticalActionModule())
    return sim


def _set_belief(
    sim: Simulation,
    *,
    faction_id: str,
    belief_id: str,
    base_key: str,
    confidence: int,
    recollection_tier: str | None = None,
) -> None:
    faction_state = sim.state.world.faction_beliefs.setdefault(faction_id, {"belief_records": {}})
    records = faction_state.setdefault("belief_records", {})
    payload = {
        "belief_id": belief_id,
        "subject": {"kind": "unknown_actor", "id": "unknown"},
        "claim_key": f"{base_key}:affirm",
        "base_key": base_key,
        "stance": "affirm",
        "confidence": confidence,
        "first_seen_tick": 0,
        "last_updated_tick": 0,
        "evidence_count": 1,
    }
    if recollection_tier is not None:
        payload["recollection_tier"] = recollection_tier
    records[belief_id] = payload


def _emit_belief_outcome(sim: Simulation, *, event_id: str, faction_id: str, belief_id: str) -> None:
    sim.schedule_event(
        SimEvent(
            tick=0,
            event_id=event_id,
            event_type=BELIEF_UPDATED_FROM_INVESTIGATION_EVENT_TYPE,
            params={
                "tick": 0,
                "faction_id": faction_id,
                "belief_id": belief_id,
                "claim_key": f"{belief_id}:affirm",
                "job_id": f"job-{belief_id}",
            },
        )
    )


def test_slice5c_warning_trigger_emits_warning_event() -> None:
    sim = _build_sim(seed=701)
    _set_belief(sim, faction_id="wolves", belief_id="b-warning", base_key="raiders_nearby", confidence=WARNING_THRESHOLD)
    _emit_belief_outcome(sim, event_id="evt-warning", faction_id="wolves", belief_id="b-warning")

    sim.advance_ticks(2)

    warnings = _events(sim, FACTION_WARNING_ISSUED_EVENT_TYPE)
    assert len(warnings) == 1
    assert warnings[0]["params"]["belief_id"] == "b-warning"


def test_slice5c_hostility_trigger_emits_hostility_event() -> None:
    sim = _build_sim(seed=702)
    _set_belief(sim, faction_id="wolves", belief_id="b-hostile", base_key="trade_dispute", confidence=HOSTILITY_THRESHOLD)
    _emit_belief_outcome(sim, event_id="evt-hostile", faction_id="wolves", belief_id="b-hostile")

    sim.advance_ticks(2)

    hostile = _events(sim, FACTION_HOSTILITY_ESCALATED_EVENT_TYPE)
    assert len(hostile) == 1
    assert hostile[0]["params"]["escalation_level"] == 1


def test_slice5c_raid_trigger_emits_raid_intent_event() -> None:
    sim = _build_sim(seed=703)
    _set_belief(sim, faction_id="wolves", belief_id="b-raid", base_key="blood_debt", confidence=RAID_THRESHOLD)
    _emit_belief_outcome(sim, event_id="evt-raid", faction_id="wolves", belief_id="b-raid")

    sim.advance_ticks(2)

    raids = _events(sim, FACTION_RAID_INTENT_DECLARED_EVENT_TYPE)
    assert len(raids) == 1
    assert raids[0]["params"]["reason"] == "confidence_at_or_above_raid_threshold"


def test_slice5c_ordering_is_lexical_not_event_arrival_order() -> None:
    sim = _build_sim(seed=704)
    beliefs = [
        ("f02", "b03", "k03"),
        ("f01", "b02", "k02"),
        ("f02", "b01", "k01"),
        ("f01", "b01", "k00"),
    ]
    for i, (faction_id, belief_id, base_key) in enumerate(beliefs):
        _set_belief(sim, faction_id=faction_id, belief_id=belief_id, base_key=base_key, confidence=WARNING_THRESHOLD)
        _emit_belief_outcome(sim, event_id=f"evt-{i}", faction_id=faction_id, belief_id=belief_id)

    sim.advance_ticks(2)

    keys = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["base_key"],
        )
        for row in _events(sim, FACTION_WARNING_ISSUED_EVENT_TYPE)
    ]
    assert keys == sorted(keys)


def test_slice5c_idempotence_repeated_outcome_does_not_duplicate_action() -> None:
    sim = _build_sim(seed=705)
    _set_belief(sim, faction_id="wolves", belief_id="b-idem", base_key="idem", confidence=RAID_THRESHOLD)

    _emit_belief_outcome(sim, event_id="evt-1", faction_id="wolves", belief_id="b-idem")
    _emit_belief_outcome(sim, event_id="evt-2", faction_id="wolves", belief_id="b-idem")

    sim.advance_ticks(2)

    raids = _events(sim, FACTION_RAID_INTENT_DECLARED_EVENT_TYPE)
    assert len(raids) == 1


def test_slice5c_budget_cap_emits_budget_event_and_halts_further_actions() -> None:
    sim = _build_sim(seed=706)
    total = MAX_FACTION_POLITICAL_ACTIONS_PER_TICK + 3
    for i in range(total):
        belief_id = f"b-{i:03d}"
        _set_belief(sim, faction_id="wolves", belief_id=belief_id, base_key=belief_id, confidence=WARNING_THRESHOLD)
        _emit_belief_outcome(sim, event_id=f"evt-{i}", faction_id="wolves", belief_id=belief_id)

    sim.advance_ticks(2)

    warnings = _events(sim, FACTION_WARNING_ISSUED_EVENT_TYPE)
    exhausted = _events(sim, FACTION_POLITICAL_ACTION_BUDGET_EXHAUSTED_EVENT_TYPE)
    assert len(warnings) == MAX_FACTION_POLITICAL_ACTIONS_PER_TICK
    assert len(exhausted) == 1


def test_slice5c_save_load_stability_with_populated_political_action_ledger() -> None:
    sim = _build_sim(seed=707)
    _set_belief(sim, faction_id="wolves", belief_id="b-save", base_key="save_key", confidence=RAID_THRESHOLD)
    _emit_belief_outcome(sim, event_id="evt-save", faction_id="wolves", belief_id="b-save")

    sim.advance_ticks(2)

    before_hash = simulation_hash(sim)

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(BeliefJobQueueModule())
    loaded.register_rule_module(FactionPoliticalActionModule())

    loaded_hash = simulation_hash(loaded)

    assert before_hash == loaded_hash
