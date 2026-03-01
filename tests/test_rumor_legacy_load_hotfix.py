from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.hash import world_hash
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
