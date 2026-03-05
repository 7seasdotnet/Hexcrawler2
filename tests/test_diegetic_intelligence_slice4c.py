from __future__ import annotations

from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    FACTION_BEHAVIOR_ACTION_EXECUTE_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_BEHAVIOR_ACTION_EXECUTE_IGNORED_EVENT_TYPE,
    FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE,
    FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
    MAX_FACTION_BEHAVIOR_EXECUTE_REQUESTS_PER_TICK,
    FactionBehaviorExecutionSeamModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def test_slice4c_supported_stub_action_emits_execute_request_payload() -> None:
    sim = Simulation(world=WorldState(), seed=301)
    sim.register_rule_module(FactionBehaviorExecutionSeamModule())

    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
        params={
            "tick": 0,
            "source_request_event_id": "evt-request",
            "faction_id": "wolves",
            "belief_id": "belief-raid",
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
        },
    )

    sim.advance_ticks(2)
    execute_requests = _events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)
    assert len(execute_requests) == 1
    assert execute_requests[0]["params"] == {
        "tick": 0,
        "source_action_stub_event_id": "evt-00000001",
        "action_uid": "evt-00000001:0",
        "faction_id": "wolves",
        "action_type": "investigate_belief",
        "template_id": "belief_investigation",
        "belief_id": "belief-raid",
        "request_type": "investigate_contested",
        "reason": "contested_belief",
        "priority": 2,
    }


def test_slice4c_unsupported_action_emits_single_ignored_forensic() -> None:
    sim = Simulation(world=WorldState(), seed=302)
    sim.register_rule_module(FactionBehaviorExecutionSeamModule())

    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
        params={
            "tick": 0,
            "faction_id": "wolves",
            "belief_id": "belief-raid",
            "actions": [
                {
                    "action_type": "unknown_action",
                    "template_id": "unknown_template",
                    "params": {
                        "belief_id": "belief-raid",
                    },
                }
            ],
        },
    )

    sim.advance_ticks(2)
    assert len(_events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)) == 0
    ignored = _events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_IGNORED_EVENT_TYPE)
    assert len(ignored) == 1
    assert ignored[0]["params"] == {
        "tick": 0,
        "action_uid": "evt-00000001:0",
        "faction_id": "wolves",
        "action_type": "unknown_action",
        "template_id": "unknown_template",
        "reason": "unsupported_action",
    }


def test_slice4c_ordering_is_lexical_and_independent_of_arrival() -> None:
    sim = Simulation(world=WorldState(), seed=303)
    sim.register_rule_module(FactionBehaviorExecutionSeamModule())

    scrambled = [
        ("f03", "b03"),
        ("f01", "b03"),
        ("f02", "b02"),
        ("f01", "b01"),
    ]
    for faction_id, belief_id in scrambled:
        sim.schedule_event_at(
            tick=0,
            event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
            params={
                "tick": 0,
                "faction_id": faction_id,
                "belief_id": belief_id,
                "actions": [
                    {
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "params": {
                            "belief_id": belief_id,
                            "request_type": "investigate_unknown_actor",
                            "reason": "unknown_actor",
                            "priority": 1,
                        },
                    }
                ],
            },
        )

    sim.advance_ticks(2)
    execute_requests = _events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)
    keys = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["action_type"],
            row["params"]["action_uid"],
        )
        for row in execute_requests
    ]
    assert keys == sorted(keys)


def test_slice4c_budget_cap_emits_single_exhausted_forensic_and_stops_tick() -> None:
    sim = Simulation(world=WorldState(), seed=304)
    sim.register_rule_module(FactionBehaviorExecutionSeamModule())

    for index in range(MAX_FACTION_BEHAVIOR_EXECUTE_REQUESTS_PER_TICK + 4):
        sim.schedule_event_at(
            tick=0,
            event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
            params={
                "tick": 0,
                "faction_id": f"f{index:02d}",
                "belief_id": f"b{index:02d}",
                "actions": [
                    {
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "params": {
                            "belief_id": f"b{index:02d}",
                            "request_type": "investigate_unknown_actor",
                            "reason": "unknown_actor",
                            "priority": 1,
                        },
                    }
                ],
            },
        )

    sim.advance_ticks(2)
    execute_requests = _events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)
    assert len(execute_requests) == MAX_FACTION_BEHAVIOR_EXECUTE_REQUESTS_PER_TICK
    exhausted = _events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_BUDGET_EXHAUSTED_EVENT_TYPE)
    assert len(exhausted) == 1


def test_slice4c_idempotence_blocks_duplicate_action_uid() -> None:
    sim = Simulation(world=WorldState(), seed=305)
    module = FactionBehaviorExecutionSeamModule()
    sim.register_rule_module(module)

    event = SimEvent(
        tick=0,
        event_id="evt-stub-dup",
        event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
        params={
            "tick": 0,
            "faction_id": "wolves",
            "belief_id": "belief-dup",
            "actions": [
                {
                    "action_type": "investigate_belief",
                    "template_id": "belief_investigation",
                    "params": {
                        "belief_id": "belief-dup",
                        "request_type": "investigate_unknown_actor",
                        "reason": "unknown_actor",
                        "priority": 1,
                    },
                }
            ],
        },
    )

    module.on_event_executed(sim, event)
    module.on_event_executed(sim, event)
    state = sim.get_rules_state("faction_behavior_execution")
    assert len(state.get("pending_execute_requests", [])) == 1

    sim.advance_ticks(2)
    assert len(_events(sim, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)) == 1


def test_slice4c_single_emission_boundary_and_save_load_exactly_once() -> None:
    def _sim(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorExecutionSeamModule())
        sim.schedule_event_at(
            tick=0,
            event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
            params={
                "tick": 0,
                "faction_id": "wolves",
                "belief_id": "belief-boundary",
                "actions": [
                    {
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "params": {
                            "belief_id": "belief-boundary",
                            "request_type": "investigate_unknown_actor",
                            "reason": "unknown_actor",
                            "priority": 1,
                        },
                    }
                ],
            },
        )
        return sim

    direct = _sim(seed=306)
    direct.advance_ticks(1)

    assert len(_events(direct, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)) == 0
    direct_state = direct.get_rules_state("faction_behavior_execution")
    assert direct_state.get("pending_execute_requests", []) == []
    assert direct_state.get("applied_action_uids", []) == ["evt-00000001:0"]

    loaded = Simulation.from_simulation_payload(direct.simulation_payload())
    loaded.register_rule_module(FactionBehaviorExecutionSeamModule())

    direct.advance_ticks(1)
    loaded.advance_ticks(1)

    assert len(_events(direct, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)) == 1
    assert len(_events(loaded, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)) == 1
    assert simulation_hash(direct) == simulation_hash(loaded)


def test_slice4c_save_load_hash_stability_with_execution_ledger() -> None:
    def _sim_with_state(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorExecutionSeamModule())
        sim.set_rules_state(
            "faction_behavior_execution",
            {
                "applied_action_uids": ["evt-existing:0"],
                "pending_execute_requests": [
                    {
                        "tick": 0,
                        "source_action_stub_event_id": "evt-b",
                        "action_uid": "evt-b:0",
                        "faction_id": "f03",
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "belief_id": "b03",
                        "request_type": "investigate_unknown_actor",
                        "reason": "unknown_actor",
                        "priority": 1,
                    },
                    {
                        "tick": 0,
                        "source_action_stub_event_id": "evt-a",
                        "action_uid": "evt-a:0",
                        "faction_id": "f01",
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "belief_id": "b01",
                        "request_type": "investigate_contested",
                        "reason": "contested_belief",
                        "priority": 2,
                    },
                ],
            },
        )
        return sim

    direct = _sim_with_state(seed=307)
    loaded = Simulation.from_simulation_payload(_sim_with_state(seed=307).simulation_payload())
    loaded.register_rule_module(FactionBehaviorExecutionSeamModule())

    direct.advance_ticks(2)
    loaded.advance_ticks(2)

    direct_rows = _events(direct, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)
    loaded_rows = _events(loaded, FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE)
    assert [row["params"] for row in direct_rows] == [row["params"] for row in loaded_rows]
    assert simulation_hash(direct) == simulation_hash(loaded)
