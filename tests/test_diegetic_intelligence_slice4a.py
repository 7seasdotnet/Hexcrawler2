from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
    BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE,
    compute_belief_id,
)
from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    FACTION_BEHAVIOR_REQUEST_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
    MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK,
    FactionBehaviorReactionIntegrationModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_slice4a_reaction_emits_single_behavior_request_payload() -> None:
    subject = {"kind": "player", "id": "scout"}
    claim_key = "raid:affirm"
    belief_id = compute_belief_id(faction_id="wolves", subject=subject, claim_key=claim_key)
    world = WorldState.from_dict(
        {
            "faction_beliefs": {
                "wolves": {
                    "belief_records": {
                        belief_id: {
                            "belief_id": belief_id,
                            "subject": subject,
                            "claim_key": claim_key,
                            "confidence": 90,
                            "first_seen_tick": 0,
                            "last_updated_tick": 0,
                            "evidence_count": 1,
                            "base_key": "raid",
                        }
                    }
                }
            }
        }
    )
    sim = Simulation(world=world, seed=101)
    sim.register_rule_module(FactionBehaviorReactionIntegrationModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
        params={
            "faction_id": "wolves",
            "belief_id": belief_id,
            "base_key": "raid",
            "subject": subject,
            "tick": 0,
        },
    )

    sim.advance_ticks(2)
    requests = _events(sim, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)
    assert len(requests) == 1
    params = requests[0]["params"]
    assert params == {
        "tick": 0,
        "source_event_id": "evt-00000001",
        "faction_id": "wolves",
        "request_type": "investigate_contested",
        "belief_id": belief_id,
        "base_key": "raid",
        "subject": subject,
        "priority": 2,
        "reason": "belief_reaction_hook",
    }


def test_slice4a_ordering_is_lexical_and_independent_of_arrival_order() -> None:
    subject = {"kind": "unknown_actor", "id": "unknown"}
    world = WorldState()
    sim = Simulation(world=world, seed=102)
    sim.register_rule_module(FactionBehaviorReactionIntegrationModule())

    scrambled = [
        ("f03", "b03", BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE),
        ("f01", "b03", BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE),
        ("f02", "b02", BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE),
        ("f01", "b01", BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE),
    ]
    for faction_id, belief_id, event_type in scrambled:
        sim.schedule_event_at(
            tick=0,
            event_type=event_type,
            params={
                "faction_id": faction_id,
                "belief_id": belief_id,
                "base_key": belief_id,
                "subject": subject,
                "tick": 0,
            },
        )

    sim.advance_ticks(2)
    requests = _events(sim, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)
    request_tuples = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["request_type"],
            row["params"]["source_event_id"],
        )
        for row in requests
    ]
    assert request_tuples == sorted(request_tuples)


def test_slice4a_budget_cap_emits_single_exhausted_forensic_and_caps_requests() -> None:
    subject = {"kind": "player", "id": "scout"}
    world = WorldState()
    sim = Simulation(world=world, seed=103)
    sim.register_rule_module(FactionBehaviorReactionIntegrationModule())

    for index in range(MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK + 3):
        sim.schedule_event_at(
            tick=0,
            event_type=BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
            params={
                "faction_id": f"f{index:02d}",
                "belief_id": f"b{index:02d}",
                "base_key": f"base{index}",
                "subject": subject,
                "tick": 0,
            },
        )

    sim.advance_ticks(2)
    requests = _events(sim, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)
    assert len(requests) == MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK
    assert [row["params"]["faction_id"] for row in requests] == [f"f{idx:02d}" for idx in range(MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK)]
    exhausted = _events(sim, FACTION_BEHAVIOR_REQUEST_BUDGET_EXHAUSTED_EVENT_TYPE)
    assert len(exhausted) == 1


def test_slice4a_idempotence_blocks_duplicate_source_event_id_across_replay_load() -> None:
    subject = {"kind": "player", "id": "scout"}
    world = WorldState()
    sim = Simulation(world=world, seed=104)
    sim.register_rule_module(FactionBehaviorReactionIntegrationModule())

    source_event_id = sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
        params={"faction_id": "wolves", "belief_id": "belief-1", "base_key": "raid", "subject": subject, "tick": 0},
    )
    sim.advance_ticks(2)
    assert len(_events(sim, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)) == 1

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(FactionBehaviorReactionIntegrationModule())
    loaded.schedule_event(
        SimEvent(
            tick=loaded.state.tick,
            event_id=source_event_id,
            event_type=BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
            params={"faction_id": "wolves", "belief_id": "belief-1", "base_key": "raid", "subject": subject, "tick": loaded.state.tick},
        )
    )
    loaded.advance_ticks(2)
    assert len(_events(loaded, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)) == 1


def test_slice4a_save_load_hash_stability_with_behavior_request_and_rules_state_ledger() -> None:
    world = WorldState()
    sim = Simulation(world=world, seed=105)
    sim.register_rule_module(FactionBehaviorReactionIntegrationModule())

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE,
        params={"faction_id": "wolves", "belief_id": "belief-ua", "base_key": "mystery", "tick": 0},
    )
    sim.advance_ticks(2)

    state = sim.get_rules_state("faction_behavior_integration")
    assert state.get("applied_source_event_ids") == ["evt-00000001"]
    assert len(_events(sim, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)) == 1

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(FactionBehaviorReactionIntegrationModule())
    assert simulation_hash(loaded) == simulation_hash(sim)


def test_slice4a_duplicate_source_event_id_does_not_duplicate_pending_or_emit() -> None:
    subject = {"kind": "player", "id": "scout"}
    sim = Simulation(world=WorldState(), seed=106)
    module = FactionBehaviorReactionIntegrationModule()
    sim.register_rule_module(module)

    event = SimEvent(
        tick=0,
        event_id="evt-duplicate",
        event_type=BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
        params={"faction_id": "wolves", "belief_id": "belief-1", "base_key": "raid", "subject": subject, "tick": 0},
    )

    module.on_event_executed(sim, event)
    state_after_first = sim.get_rules_state("faction_behavior_integration")
    assert len(state_after_first.get("pending_requests", [])) == 1

    module.on_event_executed(sim, event)
    state_after_second = sim.get_rules_state("faction_behavior_integration")
    assert len(state_after_second.get("pending_requests", [])) == 1

    sim.advance_ticks(2)
    assert len(_events(sim, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)) == 1


def test_slice4a_pending_requests_survive_load_and_flush_deterministically() -> None:
    subject = {"kind": "player", "id": "scout"}
    pending_requests = [
        {
            "tick": 0,
            "source_event_id": "evt-a",
            "faction_id": "f03",
            "request_type": "investigate_unknown_actor",
            "belief_id": "b03",
            "base_key": "bk3",
            "subject": subject,
            "priority": 1,
            "reason": "belief_reaction_hook",
        },
        {
            "tick": 0,
            "source_event_id": "evt-b",
            "faction_id": "f01",
            "request_type": "investigate_contested",
            "belief_id": "b01",
            "base_key": "bk1",
            "subject": subject,
            "priority": 2,
            "reason": "belief_reaction_hook",
        },
    ]

    def _sim_with_pending(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorReactionIntegrationModule())
        sim.set_rules_state(
            "faction_behavior_integration",
            {
                "applied_source_event_ids": [],
                "pending_requests": pending_requests,
            },
        )
        return sim

    direct = _sim_with_pending(seed=107)
    loaded = Simulation.from_simulation_payload(_sim_with_pending(seed=107).simulation_payload())
    loaded.register_rule_module(FactionBehaviorReactionIntegrationModule())

    direct.advance_ticks(2)
    loaded.advance_ticks(2)

    direct_requests = _events(direct, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)
    loaded_requests = _events(loaded, FACTION_BEHAVIOR_REQUEST_EVENT_TYPE)
    assert [row["params"] for row in direct_requests] == [row["params"] for row in loaded_requests]
    assert simulation_hash(direct) == simulation_hash(loaded)
