from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from hexcrawler.content.schema import validate_save_payload, validate_world_payload
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import save_hash, world_hash
from hexcrawler.sim.world import WorldState

SCHEMA_VERSION = 1
CANONICAL_JSON_INDENT = 2
CANONICAL_JSON_SEPARATORS = (",", ": ")


def _build_world_payload(world: WorldState) -> dict[str, Any]:
    world_payload = world.to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "world_hash": world_hash(world),
        **world_payload,
    }


def _simulation_state_payload(simulation: Simulation) -> dict[str, Any]:
    payload = simulation.simulation_payload()
    payload.pop("world", None)
    payload.pop("input_log", None)
    return payload


def _build_game_payload(world: WorldState, simulation: Simulation) -> dict[str, Any]:
    metadata = simulation.save_metadata if isinstance(simulation.save_metadata, dict) else {}
    world_state = world.to_dict()
    simulation_state = _simulation_state_payload(simulation)
    input_log = [command.to_dict() for command in simulation.input_log]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "world_state": world_state,
        "simulation_state": simulation_state,
        "input_log": input_log,
        "metadata": metadata,
    }
    payload["save_hash"] = save_hash(payload)
    return payload


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        indent=CANONICAL_JSON_INDENT,
        separators=CANONICAL_JSON_SEPARATORS,
        sort_keys=True,
    )


def _write_atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = _canonical_json(payload)

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            delete=False,
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(serialized)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _load_legacy_world_payload(payload: dict[str, Any]) -> WorldState:
    validate_world_payload(payload)
    world = WorldState.from_dict(payload)
    expected_hash = payload["world_hash"]
    actual_hash = world_hash(world)
    if expected_hash != actual_hash:
        raise ValueError(
            f"world_hash mismatch while loading save (stored={expected_hash}, recomputed={actual_hash})"
        )
    return world


def _load_canonical_game_payload(payload: dict[str, Any]) -> tuple[WorldState, Simulation]:
    validate_save_payload(payload)

    expected_hash = payload["save_hash"]
    actual_hash = save_hash(payload)
    if expected_hash != actual_hash:
        raise ValueError(
            f"save_hash mismatch while loading save (stored={expected_hash}, recomputed={actual_hash})"
        )

    world = WorldState.from_dict(payload["world_state"])
    simulation_payload = {
        **payload["simulation_state"],
        "world": payload["world_state"],
        "input_log": payload["input_log"],
    }
    simulation = Simulation.from_simulation_payload(simulation_payload)
    metadata = payload.get("metadata", {})
    simulation.save_metadata = metadata if isinstance(metadata, dict) else {}
    return world, simulation


def load_world_json(path: str | Path) -> WorldState:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "world_state" in payload and "save_hash" in payload:
        world, _ = _load_canonical_game_payload(payload)
        return world
    return _load_legacy_world_payload(payload)


def save_world_json(path: str | Path, world: WorldState) -> None:
    payload = _build_world_payload(world)
    validate_world_payload(payload)
    _write_atomic_json(path, payload)


def save_game_json(path: str | Path, world: WorldState, simulation: Simulation) -> None:
    payload = _build_game_payload(world, simulation)
    validate_save_payload(payload)
    _write_atomic_json(path, payload)


def load_game_json(path: str | Path) -> tuple[WorldState, Simulation]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _load_canonical_game_payload(payload)


def load_simulation_json(path: str | Path) -> Simulation:
    _, simulation = load_game_json(path)
    return simulation


def save_simulation_json(path: str | Path, simulation: Simulation) -> None:
    save_game_json(path, simulation.state.world, simulation)
