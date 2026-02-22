import re

import pytest

from hexcrawler.content.local_arenas import validate_local_arena_templates_payload



def _base_payload() -> dict:
    return {
        "schema_version": 1,
        "default_template_id": "template_alpha",
        "templates": [
            {
                "template_id": "template_alpha",
                "topology_type": "square_grid",
                "topology_params": {"width": 4, "height": 4},
                "role": "local",
                "anchors": [
                    {
                        "anchor_id": "spawn",
                        "coord": {"x": 1, "y": 1},
                    }
                ],
                "doors": [
                    {
                        "door_id": "door_a",
                        "anchor_id": "spawn",
                    }
                ],
                "interactables": [
                    {
                        "interactable_id": "interactable_a",
                        "anchor_id": "spawn",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("templates", 0, "metadata", "foo"), 1.5, "templates[0].metadata must not contain float values"),
        (
            ("templates", 0, "doors", 0, "metadata", "weight"),
            2.25,
            "templates[0].doors[0] must not contain float values",
        ),
        (
            ("templates", 0, "interactables", 0, "metadata", "durability"),
            3.75,
            "templates[0].interactables[0] must not contain float values",
        ),
    ],
)
def test_validate_local_arena_templates_rejects_float_values(path: tuple, value: float, expected: str) -> None:
    payload = _base_payload()
    cursor = payload
    for key in path[:-1]:
        if isinstance(cursor, dict) and key not in cursor:
            cursor[key] = {}
        cursor = cursor[key]
    cursor[path[-1]] = value

    with pytest.raises(ValueError, match=re.escape(expected)):
        validate_local_arena_templates_payload(payload)




def test_validate_local_arena_templates_rejects_float_in_topology_params() -> None:
    payload = _base_payload()
    payload["templates"][0]["topology_params"]["noise"] = 0.125

    with pytest.raises(ValueError, match=re.escape("templates[0].topology_params must not contain float values")):
        validate_local_arena_templates_payload(payload)

def test_validate_local_arena_templates_requires_door_id() -> None:
    payload = _base_payload()
    del payload["templates"][0]["doors"][0]["door_id"]

    with pytest.raises(
        ValueError,
        match=r"templates\[0\]\.doors\[0\]\.door_id must be non-empty string",
    ):
        validate_local_arena_templates_payload(payload)


def test_validate_local_arena_templates_rejects_duplicate_door_id() -> None:
    payload = _base_payload()
    payload["templates"][0]["doors"].append(
        {
            "door_id": "door_a",
            "anchor_id": "spawn",
        }
    )

    with pytest.raises(ValueError, match=r"templates\[0\] duplicate door_id: door_a"):
        validate_local_arena_templates_payload(payload)


def test_validate_local_arena_templates_requires_interactable_id() -> None:
    payload = _base_payload()
    del payload["templates"][0]["interactables"][0]["interactable_id"]

    with pytest.raises(
        ValueError,
        match=r"templates\[0\]\.interactables\[0\]\.interactable_id must be non-empty string",
    ):
        validate_local_arena_templates_payload(payload)


def test_validate_local_arena_templates_rejects_duplicate_interactable_id() -> None:
    payload = _base_payload()
    payload["templates"][0]["interactables"].append(
        {
            "interactable_id": "interactable_a",
            "anchor_id": "spawn",
        }
    )

    with pytest.raises(ValueError, match=r"templates\[0\] duplicate interactable_id: interactable_a"):
        validate_local_arena_templates_payload(payload)


def test_validate_local_arena_templates_rejects_bool_door_id() -> None:
    payload = _base_payload()
    payload["templates"][0]["doors"][0]["door_id"] = True

    with pytest.raises(ValueError, match=r"templates\[0\]\.doors\[0\]\.door_id must be non-empty string"):
        validate_local_arena_templates_payload(payload)


def test_validate_local_arena_templates_rejects_bool_interactable_id() -> None:
    payload = _base_payload()
    payload["templates"][0]["interactables"][0]["interactable_id"] = False

    with pytest.raises(ValueError, match=r"templates\[0\]\.interactables\[0\]\.interactable_id must be non-empty string"):
        validate_local_arena_templates_payload(payload)
