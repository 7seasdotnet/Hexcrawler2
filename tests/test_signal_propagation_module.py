from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.signals import (
    EMIT_SIGNAL_INTENT_COMMAND_TYPE,
    PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
    SIGNAL_EMIT_OUTCOME_EVENT_TYPE,
    SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE,
    SignalPropagationModule,
    SignalRecord,
    compute_signal_strength,
    distance_between_locations,
)
from hexcrawler.sim.world import HexCoord, MAX_SIGNALS


def _make_sim(seed: int = 17) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0)))
    sim.register_rule_module(SignalPropagationModule())
    return sim


def _outcomes(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_signal_emit_record_creation_and_deterministic_outcome() -> None:
    sim_a = _make_sim(seed=50)
    sim_b = _make_sim(seed=50)

    command = SimCommand(
        tick=0,
        entity_id="scout",
        command_type=EMIT_SIGNAL_INTENT_COMMAND_TYPE,
        params={"channel": "sound", "base_intensity": 5, "max_radius": 6, "ttl_ticks": 4, "duration_ticks": 2},
    )
    sim_a.append_command(command)
    sim_b.append_command(command)

    sim_a.advance_ticks(4)
    sim_b.advance_ticks(4)

    assert sim_a.state.world.signals == sim_b.state.world.signals
    assert sim_a.state.world.signals[0]["signal_id"] == "0:0"
    assert _outcomes(sim_a, SIGNAL_EMIT_OUTCOME_EVENT_TYPE)[0]["params"]["outcome"] == "applied"


def test_signal_bounded_fifo_eviction_is_deterministic() -> None:
    sim = _make_sim()

    for i in range(MAX_SIGNALS + 3):
        sim.state.world.append_signal_record(
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
        )

    assert len(sim.state.world.signals) == MAX_SIGNALS
    assert sim.state.world.signals[0]["signal_id"] == "sig-3"
    assert sim.state.world.signals[-1]["signal_id"] == f"sig-{MAX_SIGNALS + 2}"


def test_signal_save_load_mid_delay_idempotence_for_emit_and_perceive() -> None:
    sim = _make_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type=EMIT_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "base_intensity": 5, "max_radius": 5, "ttl_ticks": 10, "duration_ticks": 3},
        )
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "radius": 5, "duration_ticks": 4},
        )
    )

    sim.advance_ticks(1)
    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(SignalPropagationModule())

    loaded.advance_ticks(6)
    emit_outcomes = _outcomes(loaded, SIGNAL_EMIT_OUTCOME_EVENT_TYPE)
    perceive_outcomes = _outcomes(loaded, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE)
    assert len([x for x in emit_outcomes if x["params"]["action_uid"] == "0:0" and x["params"]["outcome"] == "applied"]) == 1
    assert len([x for x in perceive_outcomes if x["params"]["action_uid"] == "0:1" and x["params"]["outcome"] == "completed"]) == 1

    loaded.schedule_event_at(
        tick=loaded.state.tick,
        event_type="signal_emit_execute",
        params={
            "action_uid": "0:0",
            "entity_id": "scout",
            "channel": "sound",
            "base_intensity": 5,
            "max_radius": 5,
            "ttl_ticks": 10,
            "origin": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "metadata": {},
            "falloff_model": "linear",
        },
    )
    loaded.advance_ticks(1)
    emit_outcomes = _outcomes(loaded, SIGNAL_EMIT_OUTCOME_EVENT_TYPE)
    assert any(x["params"]["action_uid"] == "0:0" and x["params"]["outcome"] == "already_applied" for x in emit_outcomes)


def test_signal_distance_and_strength_math_hex_and_square() -> None:
    a_hex = LocationRef(space_id="overworld", topology_type=OVERWORLD_HEX_TOPOLOGY, coord={"q": 0, "r": 0})
    b_hex = LocationRef(space_id="overworld", topology_type=OVERWORLD_HEX_TOPOLOGY, coord={"q": 2, "r": -1})
    assert distance_between_locations(a_hex, b_hex) == 2

    a_sq = LocationRef(space_id="d1", topology_type=SQUARE_GRID_TOPOLOGY, coord={"x": 1, "y": 2})
    b_sq = LocationRef(space_id="d1", topology_type=SQUARE_GRID_TOPOLOGY, coord={"x": 4, "y": 6})
    assert distance_between_locations(a_sq, b_sq) == 7

    signal = SignalRecord(
        signal_id="sig",
        tick_emitted=5,
        space_id="d1",
        origin=a_sq,
        channel="sound",
        base_intensity=9,
        falloff_model="linear",
        max_radius=10,
        ttl_ticks=4,
        metadata={},
    )
    assert compute_signal_strength(signal, b_sq, current_tick=8) == 2


def test_signal_expiry_filtering_in_perception() -> None:
    sim = _make_sim()
    sim.state.world.append_signal_record(
        {
            "signal_id": "expired",
            "tick_emitted": 0,
            "space_id": "overworld",
            "origin": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "channel": "sound",
            "base_intensity": 10,
            "falloff_model": "linear",
            "max_radius": 3,
            "ttl_ticks": 0,
            "metadata": {},
        }
    )
    sim.append_command(
        SimCommand(
            tick=2,
            entity_id="scout",
            command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "radius": 4, "duration_ticks": 0},
        )
    )

    sim.advance_ticks(4)
    outcome = _outcomes(sim, SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE)[0]["params"]
    assert outcome["outcome"] == "completed"
    assert outcome["hits"] == []


def test_signal_replay_hash_identity() -> None:
    sim_a = _make_sim(seed=909)
    sim_b = _make_sim(seed=909)

    commands = [
        SimCommand(
            tick=1,
            entity_id="scout",
            command_type=EMIT_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "base_intensity": 6, "max_radius": 5, "ttl_ticks": 6, "duration_ticks": 1},
        ),
        SimCommand(
            tick=3,
            entity_id="scout",
            command_type=PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE,
            params={"channel": "sound", "radius": 5, "duration_ticks": 1},
        ),
    ]
    for command in commands:
        sim_a.append_command(command)
        sim_b.append_command(command)

    sim_a.advance_ticks(8)
    sim_b.advance_ticks(8)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
