from __future__ import annotations

import copy

import pytest

from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.entity_stats import ENTITY_STAT_OUTCOME_EVENT_TYPE, EntityStatsExecutionModule
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.interactions import INTERACTION_OUTCOME_EVENT_TYPE, InteractionExecutionModule
from hexcrawler.sim.signals import (
    EMIT_SIGNAL_INTENT_COMMAND_TYPE,
    MAX_EXECUTED_ACTION_UIDS as MAX_SIGNAL_EXECUTED_UIDS,
    PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
    SIGNAL_EMIT_OUTCOME_EVENT_TYPE,
    SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE,
    SignalPropagationModule,
    distance_between_locations,
)
from hexcrawler.sim.world import AnchorRecord, DoorRecord, HexCoord, HexRecord, InteractableRecord, MAX_OCCLUSION_EDGES, MAX_SIGNALS, SpaceState, WorldState


def _build_world() -> WorldState:
    overworld = SpaceState(
        space_id="overworld",
        topology_type="hex_rectangle",
        topology_params={"width": 2, "height": 2},
        hexes={
            HexCoord(0, 0): HexRecord(terrain_type="plains"),
            HexCoord(0, 1): HexRecord(terrain_type="plains"),
            HexCoord(1, 0): HexRecord(terrain_type="plains"),
            HexCoord(1, 1): HexRecord(terrain_type="plains"),
        },
    )
    dungeon = SpaceState(
        space_id="dungeon:test",
        topology_type="square_grid",
        topology_params={"width": 4, "height": 4, "origin": {"x": 0, "y": 0}},
        doors={
            "door:1": DoorRecord(
                door_id="door:1",
                space_id="dungeon:test",
                a={"x": 1, "y": 1},
                b={"x": 2, "y": 1},
                state="closed",
            )
        },
        anchors={
            "anchor:exit": AnchorRecord(
                anchor_id="anchor:exit",
                space_id="dungeon:test",
                coord={"x": 0, "y": 0},
                kind="exit",
                target={"type": "space", "space_id": "overworld"},
            )
        },
        interactables={
            "int:1": InteractableRecord(
                interactable_id="int:1",
                space_id="dungeon:test",
                coord={"x": 3, "y": 3},
                kind="urn",
                state={"used": False},
            )
        },
    )
    return WorldState(spaces={"overworld": overworld, "dungeon:test": dungeon})


def _make_sim(seed: int = 99) -> Simulation:
    sim = Simulation(world=_build_world(), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0)))
    return sim


def _events(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry.get("event_type") == event_type]


def test_stats_to_perception_mid_delay_save_load_is_exactly_once_and_hash_stable() -> None:
    def build_run() -> Simulation:
        sim = _make_sim(seed=121)
        sim.register_rule_module(EntityStatsExecutionModule())
        sim.register_rule_module(SignalPropagationModule())
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="scout",
                command_type="entity_stat_intent",
                params={"target_entity_id": "scout", "op": "set", "key": "hearing", "value": 30, "duration_ticks": 0},
            )
        )
        sim.append_command(
            SimCommand(
                tick=1,
                entity_id="scout",
                command_type=EMIT_SIGNAL_INTENT_COMMAND_TYPE,
                params={"channel": "sound", "base_intensity": 2, "max_radius": 6, "ttl_ticks": 8, "duration_ticks": 2},
            )
        )
        sim.append_command(
            SimCommand(
                tick=1,
                entity_id="scout",
                command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
                params={"channel": "sound", "radius": 6, "duration_ticks": 3},
            )
        )
        return sim

    full_run = build_run()
    full_run.advance_ticks(10)

    split_run = build_run()
    split_run.advance_ticks(3)
    restored = Simulation.from_simulation_payload(split_run.simulation_payload())
    restored.register_rule_module(EntityStatsExecutionModule())
    restored.register_rule_module(SignalPropagationModule())
    restored.advance_ticks(7)

    outcomes = [entry["params"] for entry in _events(restored, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE)]
    completed = [row for row in outcomes if row["action_uid"] == "1:1" and row["outcome"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["sensitivity"] == 30
    assert completed[0]["sensitivity_source"] == "hearing"
    assert completed[0]["bonus"] == 3
    assert completed[0]["hits"]
    assert simulation_hash(restored) == simulation_hash(full_run)


def test_interaction_and_signals_coexist_deterministically_in_non_overworld_space() -> None:
    sim_a = _make_sim(seed=133)
    sim_b = _make_sim(seed=133)
    for sim in (sim_a, sim_b):
        sim.register_rule_module(InteractionExecutionModule())
        sim.register_rule_module(SignalPropagationModule())
        scout = sim.state.entities["scout"]
        scout.space_id = "dungeon:test"
        scout.position_x = 1.0
        scout.position_y = 1.0
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="scout",
                command_type="interaction_intent",
                params={"interaction_type": "toggle", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 1},
            )
        )
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="scout",
                command_type=EMIT_SIGNAL_INTENT_COMMAND_TYPE,
                params={"channel": "sound", "base_intensity": 6, "max_radius": 4, "ttl_ticks": 4, "duration_ticks": 0},
            )
        )
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="scout",
                command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
                params={"channel": "sound", "radius": 4, "duration_ticks": 0},
            )
        )

    sim_a.advance_ticks(5)
    sim_b.advance_ticks(5)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert _events(sim_a, INTERACTION_OUTCOME_EVENT_TYPE) == _events(sim_b, INTERACTION_OUTCOME_EVENT_TYPE)
    assert _events(sim_a, SIGNAL_EMIT_OUTCOME_EVENT_TYPE) == _events(sim_b, SIGNAL_EMIT_OUTCOME_EVENT_TYPE)
    assert _events(sim_a, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE) == _events(sim_b, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE)


def test_invalid_intents_fail_deterministically_without_mutation_across_new_seams() -> None:
    sim = _make_sim(seed=211)
    sim.register_rule_module(EntityStatsExecutionModule())
    sim.register_rule_module(InteractionExecutionModule())
    sim.register_rule_module(SignalPropagationModule())
    scout = sim.state.entities["scout"]
    scout.space_id = "dungeon:test"
    scout.position_x = 1.0
    scout.position_y = 1.0
    before_door = sim.state.world.spaces["dungeon:test"].doors["door:1"].state

    sim.append_command(
        SimCommand(tick=0, entity_id="scout", command_type="entity_stat_intent", params={"op": "bad", "key": "hearing", "duration_ticks": 0})
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type=EMIT_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "base_intensity": -1, "max_radius": 2, "ttl_ticks": 1, "duration_ticks": 0},
        )
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "radius": -1, "duration_ticks": 0},
        )
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="interaction_intent",
            params={"interaction_type": "kick", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 0},
        )
    )

    sim.advance_ticks(2)

    assert sim.get_entity_stats("scout") == {}
    assert sim.state.world.signals == []
    assert sim.state.world.spaces["dungeon:test"].doors["door:1"].state == before_door
    assert all(row["params"]["outcome"] == "invalid_params" for row in _events(sim, ENTITY_STAT_OUTCOME_EVENT_TYPE))
    assert all(row["params"]["outcome"] == "invalid_params" for row in _events(sim, SIGNAL_EMIT_OUTCOME_EVENT_TYPE))
    assert all(row["params"]["outcome"] == "invalid_params" for row in _events(sim, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE))
    assert all(row["params"]["outcome"] == "invalid_params" for row in _events(sim, INTERACTION_OUTCOME_EVENT_TYPE))


def test_signal_distance_helper_handles_topology_mismatch_and_missing_coords_safely() -> None:
    hex_loc = {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}}
    square_loc = {"space_id": "overworld", "topology_type": "square_grid", "coord": {"x": 0, "y": 0}}
    from hexcrawler.sim.location import LocationRef

    valid_hex = LocationRef.from_dict(hex_loc)
    valid_square = LocationRef.from_dict(square_loc)
    malformed_hex = LocationRef.from_dict(hex_loc)
    object.__setattr__(malformed_hex, "coord", {"q": 0})

    assert distance_between_locations(valid_hex, valid_square) is None
    assert distance_between_locations(valid_hex, malformed_hex) is None


def test_signal_rules_state_executed_uid_ledger_is_bounded_fifo() -> None:
    sim = _make_sim(seed=377)
    sim.register_rule_module(SignalPropagationModule())

    existing = [f"uid-{i}" for i in range(MAX_SIGNAL_EXECUTED_UIDS + 3)]
    sim.set_rules_state(
        "signal_propagation",
        {"signal_emission": {"executed_action_uids": existing}, "signal_perception": {"executed_action_uids": []}},
    )

    sim.schedule_event_at(
        tick=0,
        event_type="signal_emit_execute",
        params={
            "action_uid": "uid-new",
            "entity_id": "scout",
            "channel": "sound",
            "base_intensity": 1,
            "max_radius": 1,
            "ttl_ticks": 1,
            "origin": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "metadata": {},
        },
    )
    sim.advance_ticks(1)

    state = sim.get_rules_state("signal_propagation")["signal_emission"]["executed_action_uids"]
    assert len(state) == MAX_SIGNAL_EXECUTED_UIDS
    assert state[0] == "uid-4"
    assert state[-1] == "uid-new"


def test_world_signal_payload_load_validation_and_fifo_truncation() -> None:
    world = _build_world()
    payload = world.to_dict()
    payload["signals"] = [
        {
            "signal_id": f"sig-{i}",
            "tick_emitted": i,
            "space_id": "overworld",
            "origin": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "channel": "sound",
            "base_intensity": 1,
            "falloff_model": "linear",
            "max_radius": 1,
            "ttl_ticks": 1,
            "metadata": {},
        }
        for i in range(MAX_SIGNALS + 2)
    ]

    restored = WorldState.from_dict(payload)
    assert len(restored.signals) == MAX_SIGNALS
    assert restored.signals[0]["signal_id"] == "sig-2"

    invalid_payload = copy.deepcopy(payload)
    invalid_payload["signals"] = [
        {
            "signal_id": "bad",
            "tick_emitted": 0,
            "space_id": "overworld",
            "origin": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "channel": "sound",
            "base_intensity": -1,
            "falloff_model": "linear",
            "max_radius": 1,
            "ttl_ticks": 1,
            "metadata": {},
        }
    ]
    with pytest.raises(ValueError, match="signal.base_intensity"):
        WorldState.from_dict(invalid_payload)

    invalid_payload = copy.deepcopy(payload)
    invalid_payload["signals"] = [
        {
            "signal_id": "bad",
            "tick_emitted": 0,
            "space_id": "overworld",
            "origin": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "channel": "sound",
            "base_intensity": 1,
            "falloff_model": "linear",
            "max_radius": 1,
            "ttl_ticks": -1,
            "metadata": {},
        }
    ]
    with pytest.raises(ValueError, match="signal.ttl_ticks"):
        WorldState.from_dict(invalid_payload)


def test_world_structure_occlusion_payload_round_trip_and_fifo_bound() -> None:
    world = _build_world()
    for index in range(MAX_OCCLUSION_EDGES + 3):
        world.set_structure_occlusion_edge(
            space_id="dungeon:test",
            cell_a={"x": index, "y": 0},
            cell_b={"x": index + 1, "y": 0},
            occlusion_value=1,
        )
    payload = world.to_dict()
    restored = WorldState.from_dict(payload)
    assert len(restored.structure_occlusion) == MAX_OCCLUSION_EDGES


def test_world_hash_changes_when_structure_occlusion_changes() -> None:
    sim = _make_sim(seed=401)
    sim.register_rule_module(SignalPropagationModule())
    before = simulation_hash(sim)
    sim.state.world.set_structure_occlusion_edge(
        space_id="dungeon:test",
        cell_a={"x": 1, "y": 1},
        cell_b={"x": 2, "y": 1},
        occlusion_value=5,
    )
    after = simulation_hash(sim)
    assert before != after


def test_door_toggle_updates_structure_occlusion_deterministically() -> None:
    sim = _make_sim(seed=402)
    sim.register_rule_module(InteractionExecutionModule())
    scout = sim.state.entities["scout"]
    scout.space_id = "dungeon:test"
    scout.position_x = 1.0
    scout.position_y = 1.0

    initial = sim.state.world.get_structure_occlusion_value(
        space_id="dungeon:test",
        cell_a={"x": 1, "y": 1},
        cell_b={"x": 2, "y": 1},
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="interaction_intent",
            params={"interaction_type": "open", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 0},
        )
    )
    sim.advance_ticks(1)
    opened = sim.state.world.get_structure_occlusion_value(
        space_id="dungeon:test",
        cell_a={"x": 1, "y": 1},
        cell_b={"x": 2, "y": 1},
    )
    assert initial == 1
    assert opened == 0


def test_structure_occlusion_edge_rejects_topology_mismatch() -> None:
    world = _build_world()
    with pytest.raises(ValueError, match="same topology keys"):
        world.set_structure_occlusion_edge(
            space_id="dungeon:test",
            cell_a={"q": 0, "r": 0},
            cell_b={"x": 0, "y": 1},
            occlusion_value=1,
        )


def test_door_toggle_changes_signal_perception_strength_deterministically() -> None:
    def run(open_first: bool) -> int:
        sim = _make_sim(seed=403)
        sim.register_rule_module(InteractionExecutionModule())
        sim.register_rule_module(SignalPropagationModule())
        scout = sim.state.entities["scout"]
        scout.space_id = "dungeon:test"
        scout.position_x = 2.0
        scout.position_y = 1.0
        sim.state.world.append_signal_record(
            {
                "signal_id": "door-sig",
                "tick_emitted": 0,
                "space_id": "dungeon:test",
                "origin": {"space_id": "dungeon:test", "topology_type": "square_grid", "coord": {"x": 1, "y": 1}},
                "channel": "sound",
                "base_intensity": 6,
                "falloff_model": "linear",
                "max_radius": 4,
                "ttl_ticks": 10,
                "metadata": {},
            }
        )
        if open_first:
            sim.append_command(
                SimCommand(
                    tick=0,
                    entity_id="scout",
                    command_type="interaction_intent",
                    params={"interaction_type": "open", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 0},
                )
            )
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="scout",
                command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
                params={"channel": "sound", "radius": 4, "duration_ticks": 0},
            )
        )
        sim.advance_ticks(1)
        hits = _events(sim, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE)[0]["params"]["hits"]
        return int(hits[0]["computed_strength"]) if hits else 0

    closed_strength = run(open_first=False)
    open_strength = run(open_first=True)
    assert open_strength > closed_strength
