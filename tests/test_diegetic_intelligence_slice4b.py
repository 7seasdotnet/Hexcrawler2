from __future__ import annotations

from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    FACTION_BEHAVIOR_ACTION_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
    FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
    MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK,
    FactionBehaviorPlannerModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_slice4b_request_emits_single_behavior_action_stub_payload() -> None:
    subject = {"kind": "player", "id": "scout"}
    sim = Simulation(world=WorldState(), seed=201)
    sim.register_rule_module(FactionBehaviorPlannerModule())

    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
        params={
            "faction_id": "wolves",
            "belief_id": "belief-raid",
            "request_type": "investigate_contested",
            "base_key": "raid",
            "subject": subject,
            "tick": 0,
        },
    )

    sim.advance_ticks(2)
    stubs = _events(sim, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)
    assert len(stubs) == 1
    assert stubs[0]["params"] == {
        "tick": 0,
        "source_request_event_id": "evt-00000001",
        "faction_id": "wolves",
        "request_type": "investigate_contested",
        "belief_id": "belief-raid",
        "base_key": "raid",
        "subject": subject,
        "actions": [
            {
                "action_type": "investigate_belief",
                "template_id": "belief_investigation",
                "params": {
                    "belief_id": "belief-raid",
                    "request_type": "investigate_contested",
                    "reason": "contested_belief",
                    "priority": 2,
                },
            }
        ],
    }


def test_slice4b_ordering_is_lexical_and_independent_of_arrival_order() -> None:
    subject = {"kind": "unknown_actor", "id": "unknown"}
    sim = Simulation(world=WorldState(), seed=202)
    sim.register_rule_module(FactionBehaviorPlannerModule())

    scrambled = [
        ("f03", "b03", "investigate_unknown_actor"),
        ("f01", "b03", "investigate_contested"),
        ("f02", "b02", "investigate_unknown_actor"),
        ("f01", "b01", "investigate_unknown_actor"),
    ]
    for faction_id, belief_id, request_type in scrambled:
        sim.schedule_event_at(
            tick=0,
            event_type=FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
            params={
                "faction_id": faction_id,
                "belief_id": belief_id,
                "request_type": request_type,
                "base_key": belief_id,
                "subject": subject,
                "tick": 0,
            },
        )

    sim.advance_ticks(2)
    stubs = _events(sim, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)
    tuples = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["request_type"],
            row["params"]["source_request_event_id"],
        )
        for row in stubs
    ]
    assert tuples == sorted(tuples)


def test_slice4b_budget_cap_emits_single_exhausted_forensic_and_caps_stubs() -> None:
    subject = {"kind": "player", "id": "scout"}
    sim = Simulation(world=WorldState(), seed=203)
    sim.register_rule_module(FactionBehaviorPlannerModule())

    for index in range(MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK + 3):
        sim.schedule_event_at(
            tick=0,
            event_type=FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
            params={
                "faction_id": f"f{index:02d}",
                "belief_id": f"b{index:02d}",
                "request_type": "investigate_contested",
                "base_key": f"base{index}",
                "subject": subject,
                "tick": 0,
            },
        )

    sim.advance_ticks(2)
    stubs = _events(sim, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)
    assert len(stubs) == MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK
    assert [row["params"]["faction_id"] for row in stubs] == [f"f{idx:02d}" for idx in range(MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK)]
    exhausted = _events(sim, FACTION_BEHAVIOR_ACTION_BUDGET_EXHAUSTED_EVENT_TYPE)
    assert len(exhausted) == 1


def test_slice4b_idempotence_blocks_duplicate_source_request_event_id() -> None:
    subject = {"kind": "player", "id": "scout"}
    sim = Simulation(world=WorldState(), seed=204)
    module = FactionBehaviorPlannerModule()
    sim.register_rule_module(module)

    event = SimEvent(
        tick=0,
        event_id="evt-dup-request",
        event_type=FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
        params={
            "faction_id": "wolves",
            "belief_id": "belief-1",
            "request_type": "investigate_unknown_actor",
            "base_key": "mystery",
            "subject": subject,
            "tick": 0,
        },
    )

    module.on_event_executed(sim, event)
    state_after_first = sim.get_rules_state("faction_behavior_planner")
    assert len(state_after_first.get("pending_action_stubs", [])) == 1

    module.on_event_executed(sim, event)
    state_after_second = sim.get_rules_state("faction_behavior_planner")
    assert len(state_after_second.get("pending_action_stubs", [])) == 1

    sim.advance_ticks(2)
    assert len(_events(sim, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)) == 1




def test_slice4b_single_emission_boundary_staged_once_and_save_load_safe() -> None:
    subject = {"kind": "player", "id": "scout"}

    def _sim(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorPlannerModule())
        sim.schedule_event_at(
            tick=0,
            event_type=FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
            params={
                "faction_id": "wolves",
                "belief_id": "belief-boundary",
                "request_type": "investigate_unknown_actor",
                "base_key": "mystery",
                "subject": subject,
                "tick": 0,
            },
        )
        return sim

    direct = _sim(seed=206)
    direct.advance_ticks(1)

    # Boundary proof: request consumed at tick 0; action stub is scheduled for tick 1 only.
    assert len(_events(direct, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)) == 0
    direct_state = direct.get_rules_state("faction_behavior_planner")
    assert direct_state.get("pending_action_stubs", []) == []
    assert direct_state.get("applied_request_event_ids", []) == ["evt-00000001"]

    loaded = Simulation.from_simulation_payload(direct.simulation_payload())
    loaded.register_rule_module(FactionBehaviorPlannerModule())

    direct.advance_ticks(1)
    loaded.advance_ticks(1)

    assert len(_events(direct, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)) == 1
    assert len(_events(loaded, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)) == 1
    assert simulation_hash(direct) == simulation_hash(loaded)

def test_slice4b_save_load_hash_stability_and_pending_flush_after_load() -> None:
    subject = {"kind": "player", "id": "scout"}

    def _sim_with_pending(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorPlannerModule())
        sim.set_rules_state(
            "faction_behavior_planner",
            {
                "applied_request_event_ids": ["evt-existing"],
                "pending_action_stubs": [
                    {
                        "tick": 0,
                        "source_request_event_id": "evt-b",
                        "faction_id": "f03",
                        "request_type": "investigate_unknown_actor",
                        "belief_id": "b03",
                        "base_key": "bk3",
                        "subject": subject,
                        "priority": 1,
                        "reason": "unknown_actor",
                    },
                    {
                        "tick": 0,
                        "source_request_event_id": "evt-a",
                        "faction_id": "f01",
                        "request_type": "investigate_contested",
                        "belief_id": "b01",
                        "base_key": "bk1",
                        "subject": subject,
                        "priority": 2,
                        "reason": "contested_belief",
                    },
                ],
            },
        )
        return sim

    direct = _sim_with_pending(seed=205)
    loaded = Simulation.from_simulation_payload(_sim_with_pending(seed=205).simulation_payload())
    loaded.register_rule_module(FactionBehaviorPlannerModule())

    direct.advance_ticks(2)
    loaded.advance_ticks(2)

    direct_stubs = _events(direct, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)
    loaded_stubs = _events(loaded, FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE)
    assert [row["params"] for row in direct_stubs] == [row["params"] for row in loaded_stubs]
    assert simulation_hash(direct) == simulation_hash(loaded)
