import json
from pathlib import Path

import pytest

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json, save_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import save_hash, world_hash
from hexcrawler.sim.world import HexCoord


def _build_simulation(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    simulation = Simulation(world=world, seed=seed)
    simulation.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))
    simulation.append_command(
        SimCommand(tick=0, entity_id="runner", command_type="set_move_vector", params={"x": 1.0, "y": 0.0})
    )
    simulation.append_command(SimCommand(tick=4, entity_id="runner", command_type="stop", params={}))
    simulation.advance_ticks(7)
    return simulation


def test_save_then_load_round_trip_matches_world_hash(tmp_path: Path) -> None:
    source_world = load_world_json("content/examples/basic_map.json")
    before = world_hash(source_world)

    out_path = tmp_path / "world_export.json"
    save_world_json(out_path, source_world)
    loaded_world = load_world_json(out_path)
    after = world_hash(loaded_world)

    assert before == after
    assert loaded_world.topology_type == source_world.topology_type
    assert loaded_world.topology_params == source_world.topology_params


def test_save_includes_schema_version_world_hash_and_topology(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    out_path = tmp_path / "world_export.json"

    save_world_json(out_path, world)
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["world_hash"] == world_hash(world)
    assert payload["topology_type"] == world.topology_type
    assert payload["topology_params"] == world.topology_params


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


def test_game_save_json_stable_across_save_load_cycles(tmp_path: Path) -> None:
    simulation = _build_simulation()
    first_path = tmp_path / "first_game.json"
    second_path = tmp_path / "second_game.json"

    save_game_json(first_path, simulation.state.world, simulation)
    loaded_world, loaded_simulation = load_game_json(first_path)
    save_game_json(second_path, loaded_world, loaded_simulation)

    assert first_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")


def test_game_loader_fails_when_save_hash_is_tampered(tmp_path: Path) -> None:
    simulation = _build_simulation()
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["simulation_state"]["tick"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="save_hash mismatch"):
        load_game_json(path)


def test_game_save_preserves_unknown_metadata_fields(tmp_path: Path) -> None:
    simulation = _build_simulation()
    simulation.save_metadata = {
        "engine": {"build": "dev", "flags": ["x", "y"]},
        "editor_notes": {"author": "qa"},
    }

    first_path = tmp_path / "game_save.json"
    second_path = tmp_path / "game_save_2.json"

    save_game_json(first_path, simulation.state.world, simulation)
    loaded_world, loaded_sim = load_game_json(first_path)
    save_game_json(second_path, loaded_world, loaded_sim)

    round_tripped_payload = json.loads(second_path.read_text(encoding="utf-8"))
    assert round_tripped_payload["metadata"] == simulation.save_metadata


def test_load_world_json_accepts_canonical_game_payload(tmp_path: Path) -> None:
    simulation = _build_simulation()
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    loaded_world = load_world_json(path)

    assert world_hash(loaded_world) == world_hash(simulation.state.world)


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


def test_save_hash_matches_payload_parts(tmp_path: Path) -> None:
    simulation = _build_simulation()
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["save_hash"] == save_hash(payload)


def test_game_loader_rejects_malformed_world_state_signals_shape(tmp_path: Path) -> None:
    simulation = _build_simulation()
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["world_state"]["signals"] = {"not": "a list"}
    payload["save_hash"] = save_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="world_state.signals"):
        load_game_json(path)


def test_game_save_load_round_trip_preserves_spawn_descriptors_exactly(tmp_path: Path) -> None:
    simulation = _build_simulation(seed=212)
    simulation.state.world.spawn_descriptors = [
        {
            "created_tick": 5,
            "location": {"topology_type": "overworld_hex", "coord": {"q": 1, "r": 2}},
            "template_id": "bandit_scouts",
            "quantity": 2,
            "expires_tick": None,
            "source_event_id": "evt-src",
            "action_uid": "evt-src:0",
            "extra": {"note": "forward-compatible"},
        }
    ]
    path = tmp_path / "game_save.json"

    save_game_json(path, simulation.state.world, simulation)
    _, loaded = load_game_json(path)

    assert loaded.state.world.spawn_descriptors == simulation.state.world.spawn_descriptors


def test_game_loader_rejects_malformed_world_state_spawn_descriptors_shape(tmp_path: Path) -> None:
    simulation = _build_simulation(seed=313)
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["world_state"]["spawn_descriptors"] = {"not": "a list"}
    payload["save_hash"] = save_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="world_state.spawn_descriptors"):
        load_game_json(path)


def test_game_loader_rejects_invalid_spawn_descriptor_quantity_type(tmp_path: Path) -> None:
    simulation = _build_simulation(seed=314)
    simulation.state.world.spawn_descriptors = [
        {
            "created_tick": 3,
            "location": {"topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "template_id": "bandit_scouts",
            "quantity": 1,
            "expires_tick": None,
            "source_event_id": "evt",
            "action_uid": "evt:0",
        }
    ]
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["world_state"]["spawn_descriptors"][0]["quantity"] = "many"
    payload["save_hash"] = save_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"spawn_descriptors\[0\]\.quantity"):
        load_game_json(path)


def test_game_loader_rejects_malformed_simulation_state_tick_type(tmp_path: Path) -> None:
    simulation = _build_simulation()
    path = tmp_path / "game_save.json"
    save_game_json(path, simulation.state.world, simulation)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["simulation_state"]["tick"] = "bad"
    payload["save_hash"] = save_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="simulation_state.tick"):
        load_game_json(path)

def test_game_save_load_round_trip_preserves_rumors_exactly(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    simulation = Simulation(world=world, seed=77)
    simulation.state.world.rumors = [
        {
            "rumor_id": "rumor-abc",
            "created_tick": 4,
            "location": {"topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "template_id": "rumor.signal_intent",
            "source_action_uid": "evt-source:0",
            "confidence": 0.75,
            "hop": 1,
            "expires_tick": 200,
            "payload": {"note": "test"},
        }
    ]

    path = tmp_path / "rumors_save.json"
    save_game_json(path, simulation.state.world, simulation)
    _, loaded = load_game_json(path)

    assert loaded.state.world.rumors == simulation.state.world.rumors
