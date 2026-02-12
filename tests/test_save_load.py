from pathlib import Path

from hexcrawler.content.io import load_world_json, save_world_json
from hexcrawler.sim.hash import world_hash


def test_save_then_load_round_trip_matches_world_hash(tmp_path: Path) -> None:
    source_world = load_world_json("content/examples/basic_map.json")
    before = world_hash(source_world)

    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, source_world)
    loaded_world = load_world_json(out_path)
    after = world_hash(loaded_world)

    assert before == after
