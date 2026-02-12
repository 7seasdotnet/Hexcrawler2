import json
from pathlib import Path

import pytest

from hexcrawler.content.io import load_world_json, save_world_json
from hexcrawler.sim.hash import world_hash
from hexcrawler.sim.world import HexCoord


def test_save_then_load_round_trip_matches_world_hash(tmp_path: Path) -> None:
    source_world = load_world_json("content/examples/basic_map.json")
    before = world_hash(source_world)

    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, source_world)
    loaded_world = load_world_json(out_path)
    after = world_hash(loaded_world)

    assert before == after


def test_save_includes_schema_version_and_world_hash(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    out_path = tmp_path / "world_export.json"

    save_world_json(out_path, world)
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["world_hash"] == world_hash(world)


def test_loader_fails_when_world_hash_does_not_match(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, world)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    payload["hexes"][0]["record"]["metadata"]["name"] = "Tampered"
    out_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="world_hash mismatch"):
        load_world_json(out_path)


def test_canonical_json_stable_across_save_load_cycles(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    save_world_json(first_path, world)
    world_reloaded = load_world_json(first_path)
    save_world_json(second_path, world_reloaded)

    assert first_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")


def test_atomic_save_writes_final_file(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    out_path = tmp_path / "nested" / "world_export.json"

    save_world_json(out_path, world)

    assert out_path.exists()
    assert list(out_path.parent.glob("*.tmp")) == []


def test_metadata_unknown_fields_are_preserved(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    record = world.get_hex_record(HexCoord(1, 0))
    assert record is not None
    record.metadata["forward_compat_flag"] = {"nested": [1, 2, 3]}

    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, world)
    loaded = load_world_json(out_path)
    loaded_record = loaded.get_hex_record(HexCoord(1, 0))

    assert loaded_record is not None
    assert loaded_record.metadata["forward_compat_flag"] == {"nested": [1, 2, 3]}


def test_loader_rejects_missing_schema_version(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, world)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    payload.pop("schema_version")
    out_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_world_json(out_path)


def test_loader_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, world)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 999
    out_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema_version"):
        load_world_json(out_path)
