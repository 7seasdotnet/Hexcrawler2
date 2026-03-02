from __future__ import annotations

import json
from pathlib import Path

import pytest

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import save_hash, world_hash
from hexcrawler.sim.world import WorldState


LEGACY_RUMOR_WITH_REPORTED_FIELDS = {
    "confidence": 0.75,
    "expires_tick": 123,
    "hop": 2,
    "location": {"q": 1, "r": 2},
    "payload": {"x": 1},
    "source_action_uid": "evt-42",
    "template_id": "group_arrival",
}


def _base_payload() -> dict:
    world = load_world_json("content/examples/basic_map.json")
    return world.to_dict()


def test_legacy_rumor_fields_load_and_migrate_without_unknowns() -> None:
    payload = _base_payload()
    payload["rumors"] = [dict(LEGACY_RUMOR_WITH_REPORTED_FIELDS)]

    loaded = WorldState.from_dict(payload)

    assert len(loaded.rumors) == 1
    rumor = loaded.rumors[0]
    assert rumor["kind"] == "group_arrival"
    assert rumor["created_tick"] == 0
    assert rumor["consumed"] is False
    assert set(rumor.keys()) <= {"rumor_id", "kind", "created_tick", "site_key", "group_id", "consumed"}


def test_legacy_rumor_canonicalization_produces_stable_rumor_id() -> None:
    payload = _base_payload()
    first = {
        "template_id": "site_claim",
        "payload": {"a": 1, "b": 2},
        "location": {"r": 3, "q": 4},
    }
    second = {
        "location": {"q": 4, "r": 3},
        "payload": {"b": 2, "a": 1},
        "template_id": "site_claim",
    }
    payload["rumors"] = [first, second]

    loaded = WorldState.from_dict(payload)

    assert len(loaded.rumors) == 2
    assert loaded.rumors[0]["rumor_id"] == loaded.rumors[1]["rumor_id"].split("~")[0]
    assert loaded.rumors[1]["rumor_id"].startswith(f"{loaded.rumors[0]['rumor_id']}~")


def test_modern_rumor_entry_remains_unchanged() -> None:
    payload = _base_payload()
    modern = {
        "rumor_id": "modern-1",
        "kind": "claim_opportunity",
        "created_tick": 44,
        "group_id": "g-1",
        "consumed": True,
    }
    payload["rumors"] = [modern]

    loaded = WorldState.from_dict(payload)

    assert loaded.rumors == [modern]


def test_legacy_load_hash_is_stable_across_reloads() -> None:
    payload = _base_payload()
    payload["rumors"] = [
        dict(LEGACY_RUMOR_WITH_REPORTED_FIELDS),
        {
            "template_id": "unknown_template",
            "payload": {"ignored": True},
        },
    ]

    world_a = WorldState.from_dict(payload)
    world_b = WorldState.from_dict(payload)

    assert world_a.to_dict() == world_b.to_dict()
    assert world_hash(world_a) == world_hash(world_b)


def test_legacy_rumor_fields_do_not_preblock_canonical_save_load_path(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=123)

    save_path = tmp_path / "legacy_rumor_hotfix_save.json"
    save_game_json(save_path, world, sim)

    payload = json.loads(save_path.read_text(encoding="utf-8"))
    payload["world_state"]["rumors"] = [
        {
            "rumor_id": "legacy1",
            "template_id": "group_arrival",
            "payload": {},
            "location": {},
            "expires_tick": 123,
            "confidence": 0.5,
            "hop": 1,
            "source_action_uid": "a:1",
            "created_tick": 0,
        }
    ]
    payload["save_hash"] = save_hash(payload)
    save_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ": "), indent=2), encoding="utf-8")

    loaded_world, _ = load_game_json(save_path)

    assert len(loaded_world.rumors) == 1
    rumor = loaded_world.rumors[0]
    assert rumor["kind"] == "group_arrival"
    assert set(rumor.keys()) <= {"rumor_id", "kind", "site_key", "group_id", "created_tick", "consumed"}


def test_modern_malformed_rumor_entry_still_rejected_after_load_unblock(tmp_path: Path) -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=321)

    save_path = tmp_path / "modern_malformed_rumor_save.json"
    save_game_json(save_path, world, sim)

    payload = json.loads(save_path.read_text(encoding="utf-8"))
    payload["world_state"]["rumors"] = [
        {
            "rumor_id": "modern-bad",
            "kind": "group_arrival",
            "created_tick": 0,
            "consumed": 1,
        }
    ]
    payload["save_hash"] = save_hash(payload)
    save_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ": "), indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="consumed must be a boolean"):
        load_game_json(save_path)
