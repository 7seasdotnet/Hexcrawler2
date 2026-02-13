from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation, run_replay
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def _build_sim(seed: int = 11) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))
    return sim


def _command_log() -> list[SimCommand]:
    return [
        SimCommand(tick=0, entity_id="runner", command_type="set_move_vector", params={"x": 1.0, "y": 0.0}),
        SimCommand(tick=4, entity_id="runner", command_type="stop", params={}),
        SimCommand(
            tick=5,
            entity_id="runner",
            command_type="set_target_position",
            params={"x": 1.5, "y": 0.86},
        ),
    ]


def test_same_seed_and_input_log_produce_identical_hash() -> None:
    log = _command_log()
    sim_a = _build_sim(seed=99)
    sim_b = _build_sim(seed=99)

    for command in log:
        sim_a.append_command(command)
        sim_b.append_command(command.to_dict())

    sim_a.advance_ticks(20)
    sim_b.advance_ticks(20)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_run_replay_matches_live_runtime_commands() -> None:
    base_sim = _build_sim(seed=77)
    live_sim = _build_sim(seed=77)

    runtime_commands = [
        SimCommand(tick=0, entity_id="runner", command_type="set_move_vector", params={"x": 1.0, "y": 1.0}),
        SimCommand(tick=3, entity_id="runner", command_type="stop", params={}),
        SimCommand(tick=4, entity_id="runner", command_type="set_target_position", params={"x": 1.5, "y": -0.86}),
    ]

    for _ in range(12):
        for command in runtime_commands:
            if command.tick == live_sim.state.tick:
                live_sim.append_command(command)
        live_sim.advance_ticks(1)

    replayed = run_replay(base_sim, runtime_commands, ticks_to_run=12)

    assert simulation_hash(live_sim) == simulation_hash(replayed)


def test_save_load_preserves_input_log(tmp_path: Path) -> None:
    sim = _build_sim(seed=123)
    for command in _command_log():
        sim.append_command(command)

    path = tmp_path / "sim_save.json"
    save_game_json(path, sim.state.world, sim)
    _, loaded = load_game_json(path)

    assert [command.to_dict() for command in loaded.input_log] == [command.to_dict() for command in sim.input_log]
