from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash


def test_calendar_derivation_boundaries_default_epoch() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=11)
    sim.state.time.ticks_per_day = 240
    sim.state.time.epoch_tick = 0

    sim.state.tick = 0
    assert sim.get_day_index() == 0
    assert sim.get_tick_in_day() == 0

    sim.state.tick = 239
    assert sim.get_day_index() == 0
    assert sim.get_tick_in_day() == 239

    sim.state.tick = 240
    assert sim.get_day_index() == 1
    assert sim.get_tick_in_day() == 0


def test_calendar_derivation_with_epoch_offset() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=12)
    sim.state.time.ticks_per_day = 240
    sim.state.time.epoch_tick = 10

    sim.state.tick = 10
    assert sim.get_day_index() == 0
    assert sim.get_tick_in_day() == 0

    sim.state.tick = 249
    assert sim.get_day_index() == 0
    assert sim.get_tick_in_day() == 239

    sim.state.tick = 250
    assert sim.get_day_index() == 1
    assert sim.get_tick_in_day() == 0


def test_calendar_save_load_round_trip_preserves_time_derivation(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=13)
    sim.state.time.ticks_per_day = 120
    sim.state.time.epoch_tick = 10
    sim.state.tick = 155

    save_path = tmp_path / "calendar_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(save_path)

    assert loaded.get_ticks_per_day() == 120
    assert loaded.state.time.epoch_tick == 10
    assert loaded.state.tick == 155
    assert loaded.get_day_index() == sim.get_day_index()
    assert loaded.get_tick_in_day() == sim.get_tick_in_day()


def test_calendar_back_compat_load_defaults_time_state() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=14)
    payload = sim.simulation_payload()
    payload.pop("time")

    restored = Simulation.from_simulation_payload(payload)
    assert restored.get_ticks_per_day() == 240
    assert restored.state.time.epoch_tick == 0


def test_calendar_contributes_to_deterministic_simulation_hash() -> None:
    world_a = load_world_json("content/examples/basic_map.json")
    world_b = load_world_json("content/examples/basic_map.json")

    sim_a = Simulation(world=world_a, seed=21)
    sim_b = Simulation(world=world_b, seed=21)

    sim_a.state.tick = 330
    sim_b.state.tick = 330
    sim_a.state.time.ticks_per_day = 120
    sim_b.state.time.ticks_per_day = 120
    sim_a.state.time.epoch_tick = 7
    sim_b.state.time.epoch_tick = 7

    assert simulation_hash(sim_a) == simulation_hash(sim_b)

    sim_b.state.time.epoch_tick = 8
    assert simulation_hash(sim_a) != simulation_hash(sim_b)
