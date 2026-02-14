from pathlib import Path

import pytest

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation, run_replay
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))
    return sim


def _command_log() -> list[SimCommand]:
    return [
        SimCommand(tick=0, entity_id="runner", command_type="set_move_vector", params={"x": 1.0, "y": 0.0}),
        SimCommand(tick=3, entity_id="runner", command_type="stop", params={}),
        SimCommand(tick=4, entity_id="runner", command_type="set_target_position", params={"x": 1.5, "y": 0.86}),
    ]


def test_rules_state_round_trip(tmp_path: Path) -> None:
    sim = _build_sim()
    sim.set_rules_state("periodic_scheduler", {"tasks": ["check_a", "check_b"], "revision": 2})
    sim.set_rules_state("check_runner", {"last_run_tick": 7, "active": True})

    path = tmp_path / "save.json"
    save_game_json(path, sim.state.world, sim)
    _, loaded = load_game_json(path)

    assert loaded.get_rules_state("periodic_scheduler") == {"tasks": ["check_a", "check_b"], "revision": 2}
    assert loaded.get_rules_state("check_runner") == {"last_run_tick": 7, "active": True}


def test_rules_state_in_hash() -> None:
    sim_a = _build_sim(seed=77)
    sim_b = _build_sim(seed=77)

    baseline_hash = simulation_hash(sim_a)
    sim_b.set_rules_state("module_a", {"counter": 1, "nested": {"flag": True}})

    assert simulation_hash(sim_a) == baseline_hash
    assert simulation_hash(sim_b) != baseline_hash


def test_rules_state_replay_stability() -> None:
    seed = 99
    command_log = _command_log()

    sim_live = _build_sim(seed=seed)
    sim_live.set_rules_state("module_a", {"counter": 2, "tags": ["alpha", "beta"]})
    for command in command_log:
        sim_live.append_command(command)
    sim_live.advance_ticks(12)

    sim_base = _build_sim(seed=seed)
    sim_base.set_rules_state("module_a", {"counter": 2, "tags": ["alpha", "beta"]})
    replayed = run_replay(sim_base, command_log, ticks_to_run=12)

    assert simulation_hash(sim_live) == simulation_hash(replayed)


def test_rules_state_rejects_non_json_values() -> None:
    sim = _build_sim()

    with pytest.raises(ValueError, match="canonical JSON primitives"):
        sim.set_rules_state("bad_module", {"invalid": object()})


def test_rules_state_get_returns_copy() -> None:
    sim = _build_sim()
    sim.set_rules_state("module_a", {"counter": 1})

    state_copy = sim.get_rules_state("module_a")
    state_copy["counter"] = 999

    assert sim.get_rules_state("module_a") == {"counter": 1}
