from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.faction_behavior import (
    FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE,
    FACTION_BEHAVIOR_EXECUTION_BRIDGE_APPLIED_EVENT_TYPE,
    FACTION_BEHAVIOR_EXECUTION_BRIDGE_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_BEHAVIOR_EXECUTION_BRIDGE_IGNORED_EVENT_TYPE,
    MAX_FACTION_BEHAVIOR_BRIDGES_PER_TICK,
    FactionBehaviorExecutionBridgeModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import WorldState


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]


def _schedule_execute_request(
    sim: Simulation,
    *,
    tick: int,
    event_id: str,
    action_uid: str,
    faction_id: str,
    belief_id: str,
    action_type: str = "investigate_belief",
    template_id: str = "belief_investigation",
) -> None:
    sim.schedule_event(
        SimEvent(
            tick=tick,
            event_id=event_id,
            event_type=FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE,
            params={
                "tick": tick,
                "action_uid": action_uid,
                "faction_id": faction_id,
                "action_type": action_type,
                "template_id": template_id,
                "belief_id": belief_id,
            },
        )
    )


def test_slice4d_supported_bridge_reuses_existing_investigation_enqueue_event() -> None:
    sim = Simulation(world=WorldState(), seed=401)
    sim.register_rule_module(FactionBehaviorExecutionBridgeModule())

    _schedule_execute_request(
        sim,
        tick=0,
        event_id="evt-exec-1",
        action_uid="evt-exec-1:0",
        faction_id="wolves",
        belief_id="belief-raid",
    )

    sim.advance_ticks(2)
    bridged = _events(sim, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)
    assert len(bridged) == 1
    assert bridged[0]["params"] == {
        "faction_id": "wolves",
        "subject": {"kind": "unknown_actor"},
        "claim_key": "belief-raid",
        "confidence": 50,
        "site_template_id": None,
        "region_id": None,
        "claim": {
            "subject": {"kind": "unknown_actor"},
            "claim_key": "belief-raid",
            "confidence": 50,
        },
    }

    applied = _events(sim, FACTION_BEHAVIOR_EXECUTION_BRIDGE_APPLIED_EVENT_TYPE)
    assert len(applied) == 1
    assert applied[0]["params"] == {
        "tick": 0,
        "action_uid": "evt-exec-1:0",
        "faction_id": "wolves",
        "action_type": "investigate_belief",
        "template_id": "belief_investigation",
        "bridged_event_type": BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE,
        "belief_id": "belief-raid",
    }


def test_slice4d_unsupported_action_emits_ignored_and_does_not_enqueue_job() -> None:
    sim = Simulation(world=WorldState(), seed=402)
    sim.register_rule_module(FactionBehaviorExecutionBridgeModule())

    _schedule_execute_request(
        sim,
        tick=0,
        event_id="evt-exec-2",
        action_uid="evt-exec-2:0",
        faction_id="wolves",
        belief_id="belief-raid",
        action_type="unsupported",
        template_id="other",
    )

    sim.advance_ticks(2)
    assert len(_events(sim, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)) == 0
    ignored = _events(sim, FACTION_BEHAVIOR_EXECUTION_BRIDGE_IGNORED_EVENT_TYPE)
    assert len(ignored) == 1
    assert ignored[0]["params"] == {
        "tick": 0,
        "action_uid": "evt-exec-2:0",
        "faction_id": "wolves",
        "action_type": "unsupported",
        "template_id": "other",
        "reason": "unsupported_action",
    }


def test_slice4d_ordering_independent_of_arrival() -> None:
    sim = Simulation(world=WorldState(), seed=403)
    sim.register_rule_module(FactionBehaviorExecutionBridgeModule())

    scrambled = [
        ("evt-d", "f03", "b03"),
        ("evt-b", "f01", "b03"),
        ("evt-c", "f02", "b02"),
        ("evt-a", "f01", "b01"),
    ]
    for event_id, faction_id, belief_id in scrambled:
        _schedule_execute_request(
            sim,
            tick=0,
            event_id=event_id,
            action_uid=f"{event_id}:0",
            faction_id=faction_id,
            belief_id=belief_id,
        )

    sim.advance_ticks(2)
    applied = _events(sim, FACTION_BEHAVIOR_EXECUTION_BRIDGE_APPLIED_EVENT_TYPE)
    keys = [
        (
            row["params"]["faction_id"],
            row["params"]["belief_id"],
            row["params"]["action_type"],
            row["params"]["action_uid"],
        )
        for row in applied
    ]
    assert keys == sorted(keys)


def test_slice4d_budget_cap_emits_single_exhausted_event_and_stops_processing() -> None:
    sim = Simulation(world=WorldState(), seed=404)
    sim.register_rule_module(FactionBehaviorExecutionBridgeModule())

    for index in range(MAX_FACTION_BEHAVIOR_BRIDGES_PER_TICK + 3):
        _schedule_execute_request(
            sim,
            tick=0,
            event_id=f"evt-{index:03d}",
            action_uid=f"evt-{index:03d}:0",
            faction_id=f"f{index:02d}",
            belief_id=f"b{index:02d}",
        )

    sim.advance_ticks(2)
    assert len(_events(sim, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)) == MAX_FACTION_BEHAVIOR_BRIDGES_PER_TICK
    exhausted = _events(sim, FACTION_BEHAVIOR_EXECUTION_BRIDGE_BUDGET_EXHAUSTED_EVENT_TYPE)
    assert len(exhausted) == 1


def test_slice4d_idempotence_action_uid_prevents_duplicate_staging_or_enqueue() -> None:
    sim = Simulation(world=WorldState(), seed=405)
    module = FactionBehaviorExecutionBridgeModule()
    sim.register_rule_module(module)

    event = SimEvent(
        tick=0,
        event_id="evt-dup",
        event_type=FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE,
        params={
            "tick": 0,
            "action_uid": "evt-dup:0",
            "faction_id": "wolves",
            "action_type": "investigate_belief",
            "template_id": "belief_investigation",
            "belief_id": "belief-dup",
        },
    )

    module.on_event_executed(sim, event)
    module.on_event_executed(sim, event)
    assert len(sim.get_rules_state("faction_behavior_bridge").get("pending_bridge_requests", [])) == 1

    sim.advance_ticks(2)
    assert len(_events(sim, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)) == 1


def test_slice4d_single_emission_boundary_save_load_exactly_once() -> None:
    def _sim(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorExecutionBridgeModule())
        _schedule_execute_request(
            sim,
            tick=0,
            event_id="evt-boundary",
            action_uid="evt-boundary:0",
            faction_id="wolves",
            belief_id="belief-boundary",
        )
        return sim

    direct = _sim(seed=406)
    direct.advance_ticks(1)

    assert len(_events(direct, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)) == 0
    state = direct.get_rules_state("faction_behavior_bridge")
    assert state.get("pending_bridge_requests", []) == []
    assert state.get("applied_action_uids", []) == ["evt-boundary:0"]

    loaded = Simulation.from_simulation_payload(direct.simulation_payload())
    loaded.register_rule_module(FactionBehaviorExecutionBridgeModule())

    direct.advance_ticks(1)
    loaded.advance_ticks(1)

    assert len(_events(direct, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)) == 1
    assert len(_events(loaded, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)) == 1
    assert simulation_hash(direct) == simulation_hash(loaded)


def test_slice4d_save_load_hash_stability_with_forensics_and_bridged_artifacts() -> None:
    def _sim(seed: int) -> Simulation:
        sim = Simulation(world=WorldState(), seed=seed)
        sim.register_rule_module(FactionBehaviorExecutionBridgeModule())
        sim.set_rules_state(
            "faction_behavior_bridge",
            {
                "applied_action_uids": ["evt-existing:0"],
                "pending_bridge_requests": [
                    {
                        "tick": 0,
                        "action_uid": "evt-b:0",
                        "faction_id": "f03",
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "belief_id": "b03",
                    },
                    {
                        "tick": 0,
                        "action_uid": "evt-a:0",
                        "faction_id": "f01",
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "belief_id": "b01",
                    },
                ],
            },
        )
        return sim

    direct = _sim(seed=407)
    loaded = Simulation.from_simulation_payload(_sim(seed=407).simulation_payload())
    loaded.register_rule_module(FactionBehaviorExecutionBridgeModule())

    direct.advance_ticks(2)
    loaded.advance_ticks(2)

    assert [row["params"] for row in _events(direct, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)] == [
        row["params"] for row in _events(loaded, BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE)
    ]
    assert [row["params"] for row in _events(direct, FACTION_BEHAVIOR_EXECUTION_BRIDGE_APPLIED_EVENT_TYPE)] == [
        row["params"] for row in _events(loaded, FACTION_BEHAVIOR_EXECUTION_BRIDGE_APPLIED_EVENT_TYPE)
    ]
    assert simulation_hash(direct) == simulation_hash(loaded)


def test_slice4d_bridge_reuses_existing_investigation_queue_substrate() -> None:
    sim = Simulation(world=WorldState(), seed=408)
    sim.register_rule_module(FactionBehaviorExecutionBridgeModule())
    sim.register_rule_module(BeliefJobQueueModule())

    _schedule_execute_request(
        sim,
        tick=0,
        event_id="evt-queue",
        action_uid="evt-queue:0",
        faction_id="wolves",
        belief_id="belief-queue",
    )

    sim.advance_ticks(3)
    queue = sim.state.world.faction_beliefs.get("wolves", {}).get("investigation_queue", [])
    assert len(queue) == 1
    assert queue[0]["claim"]["claim_key"] == "belief-queue"
    assert queue[0]["claim"]["confidence"] == 50
    assert queue[0]["claim"]["subject"]["kind"] == "unknown_actor"
