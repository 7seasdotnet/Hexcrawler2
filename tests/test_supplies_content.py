from __future__ import annotations

import json
from pathlib import Path

import pytest

from hexcrawler.content.supplies import DEFAULT_SUPPLY_PROFILES_PATH, load_supply_profiles_json


def test_load_supply_profiles_default_registry() -> None:
    registry = load_supply_profiles_json(DEFAULT_SUPPLY_PROFILES_PATH)

    assert registry.schema_version == 1
    assert [profile.profile_id for profile in registry.profiles] == sorted(
        profile.profile_id for profile in registry.profiles
    )
    assert "player_default" in registry.by_id()


def test_load_supply_profiles_rejects_duplicate_item_consumes(tmp_path: Path) -> None:
    path = tmp_path / "supply_profiles.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "profile_id": "dup",
                        "consumes": [
                            {"item_id": "rations", "quantity": 1, "interval_ticks": 2},
                            {"item_id": "rations", "quantity": 1, "interval_ticks": 3},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate consumes.item_id"):
        load_supply_profiles_json(path)
