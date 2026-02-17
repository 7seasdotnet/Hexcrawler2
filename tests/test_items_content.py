from __future__ import annotations

import json
from pathlib import Path

import pytest

from hexcrawler.content.items import DEFAULT_ITEMS_PATH, load_items_json


def test_load_items_json_default_registry() -> None:
    registry = load_items_json(DEFAULT_ITEMS_PATH)
    assert registry.schema_version == 1
    assert [item.item_id for item in registry.items] == sorted(item.item_id for item in registry.items)
    assert all(item.stackable for item in registry.items)


def test_load_items_json_rejects_non_stackable(tmp_path: Path) -> None:
    path = tmp_path / "items.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "item_id": "bad",
                        "name": "Bad",
                        "stackable": False,
                        "unit_mass": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stackable must be true"):
        load_items_json(path)
