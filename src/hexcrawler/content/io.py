from __future__ import annotations

import json
from pathlib import Path

from hexcrawler.content.schema import validate_world_payload
from hexcrawler.sim.world import WorldState


def load_world_json(path: str | Path) -> WorldState:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_world_payload(payload)
    return WorldState.from_dict(payload)


def save_world_json(path: str | Path, world: WorldState) -> None:
    payload = world.to_dict()
    validate_world_payload(payload)
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
