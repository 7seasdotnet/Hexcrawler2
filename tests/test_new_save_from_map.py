import json
from pathlib import Path

from hexcrawler.cli.new_save_from_map import main
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash


def test_new_save_from_map_builds_canonical_save(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "sample_save.json"

    exit_code = main(
        [
            "content/examples/basic_map.json",
            str(out_path),
            "--seed",
            "123",
            "--print-summary",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert out_path.exists()
    assert "summary " in output
    assert "save_hash=" in output

    world, simulation = load_game_json(out_path)
    assert world_hash(world) == world_hash(load_world_json("content/examples/basic_map.json"))
    assert simulation.seed == 123

    hash_before = simulation_hash(simulation)
    reloaded_world, reloaded_sim = load_game_json(out_path)
    assert world_hash(reloaded_world) == world_hash(world)
    assert simulation_hash(reloaded_sim) == hash_before


def test_new_save_from_map_refuses_canonical_input(tmp_path: Path, capsys) -> None:
    canonical_input = tmp_path / "canonical_input.json"
    world = load_world_json("content/examples/basic_map.json")
    simulation = Simulation(world=world, seed=5)
    save_game_json(canonical_input, world, simulation)

    out_path = tmp_path / "out.json"
    exit_code = main([str(canonical_input), str(out_path), "--seed", "7"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "already canonical save" in output
    assert not out_path.exists()


def test_new_save_from_map_requires_force_to_overwrite(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "existing_save.json"
    out_path.write_text(json.dumps({"existing": True}), encoding="utf-8")

    exit_code = main(["content/examples/basic_map.json", str(out_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "use --force" in output

    overwrite_exit_code = main(["content/examples/basic_map.json", str(out_path), "--force"])
    assert overwrite_exit_code == 0
