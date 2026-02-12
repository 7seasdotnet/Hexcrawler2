from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from hexcrawler.content.schema import validate_world_payload
from hexcrawler.sim.hash import world_hash
from hexcrawler.sim.world import WorldState

SCHEMA_VERSION = 1
CANONICAL_JSON_INDENT = 2
CANONICAL_JSON_SEPARATORS = (",", ": ")


def _build_save_payload(world: WorldState) -> dict[str, Any]:
    world_payload = world.to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "world_hash": world_hash(world),
        **world_payload,
    }


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        indent=CANONICAL_JSON_INDENT,
        separators=CANONICAL_JSON_SEPARATORS,
        sort_keys=True,
    )


def load_world_json(path: str | Path) -> WorldState:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_world_payload(payload)
    world = WorldState.from_dict(payload)
    expected_hash = payload["world_hash"]
    actual_hash = world_hash(world)
    if expected_hash != actual_hash:
        raise ValueError(
            f"world_hash mismatch while loading save (stored={expected_hash}, recomputed={actual_hash})"
        )
    return world


def save_world_json(path: str | Path, world: WorldState) -> None:
    payload = _build_save_payload(world)
    validate_world_payload(payload)
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
