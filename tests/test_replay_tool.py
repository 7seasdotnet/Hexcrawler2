from pathlib import Path

from hexcrawler.cli.replay_tool import _build_parser, main
from hexcrawler.content.io import load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.world import HexCoord


def _build_save(path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    simulation = Simulation(world=world, seed=77)
    simulation.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))
    simulation.append_command(
        SimCommand(tick=0, entity_id="runner", command_type="set_move_vector", params={"x": 1.0, "y": 0.0})
    )
    save_game_json(path, simulation.state.world, simulation)


def test_replay_tool_parser_accepts_print_artifacts_flag() -> None:
    parser = _build_parser()
    args = parser.parse_args(["save.json", "--print-artifacts"])

    assert args.print_artifacts is True


def test_replay_tool_main_outputs_hashes(tmp_path: Path, capsys) -> None:
    save_path = tmp_path / "game_save.json"
    dumped_path = tmp_path / "replayed_save.json"
    _build_save(save_path)

    exit_code = main(
        [
            str(save_path),
            "--ticks",
            "2",
            "--print-input-summary",
            "--print-artifacts",
            "--dump-final-save",
            str(dumped_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "start_hash=" in output
    assert "end_hash=" in output
    assert "integrity=OK" in output
    assert "artifacts.signals.limit=10" in output
    assert "artifacts.tracks.limit=10" in output
    assert "artifacts.spawns.limit=10" in output
    assert "artifacts.entities.limit=20" in output
    assert "artifacts.outcomes.limit=20" in output
    assert "artifacts.selection owner_entity_id=scout selected_entity_id=none" in output
    assert dumped_path.exists()
