import copy
import re

import pytest

from hexcrawler.content.local_arenas import (
    load_local_arena_templates_payload,
    validate_local_arena_templates_payload,
)


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
        (
            ("templates", 0, "metadata", "a", "b", "c"),
            1.234,
            "templates[0].metadata must not contain float values",
        ),
        (
            ("templates", 0, "topology_params", "scale"),
            1.5,
            "templates[0].topology_params must not contain float values",
        ),
        (
            ("templates", 0, "doors", 0, "metadata", "opacity"),
            0.5,
            "templates[0].doors[0] must not contain float values",
        ),
        (
            ("templates", 0, "interactables", 0, "metadata", "opacity"),
            0.5,
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


@pytest.mark.parametrize("bool_id", [True, False])
def test_validate_local_arena_templates_rejects_bool_door_id(bool_id: bool) -> None:
    payload = _base_payload()
    payload["templates"][0]["doors"][0]["door_id"] = bool_id

    with pytest.raises(ValueError, match=r"templates\[0\]\.doors\[0\]\.door_id must be non-empty string"):
        validate_local_arena_templates_payload(payload)


@pytest.mark.parametrize("bool_id", [True, False])
def test_validate_local_arena_templates_rejects_bool_interactable_id(bool_id: bool) -> None:
    payload = _base_payload()
    payload["templates"][0]["interactables"][0]["interactable_id"] = bool_id

    with pytest.raises(ValueError, match=r"templates\[0\]\.interactables\[0\]\.interactable_id must be non-empty string"):
        validate_local_arena_templates_payload(payload)


def test_validate_local_arena_templates_accepts_numeric_string_ids() -> None:
    payload = _base_payload()
    payload["templates"][0]["doors"][0]["door_id"] = "1"
    payload["templates"][0]["interactables"][0]["interactable_id"] = "0"

    validate_local_arena_templates_payload(payload)


def test_local_arena_registry_deterministic_ordering_on_repeated_loads() -> None:
    payload = _base_payload()
    payload["templates"].append(
        {
            "template_id": "template_beta",
            "topology_type": "square_grid",
            "topology_params": {"width": 5, "height": 5},
            "role": "local",
            "anchors": [
                {"anchor_id": "z_anchor", "coord": {"x": 1, "y": 1}},
                {"anchor_id": "a_anchor", "coord": {"x": 2, "y": 2}},
            ],
            "doors": [
                {"door_id": "door_2", "anchor_id": "z_anchor"},
                {"door_id": "door_1", "anchor_id": "a_anchor"},
            ],
            "interactables": [
                {"interactable_id": "interactable_2", "anchor_id": "z_anchor"},
                {"interactable_id": "interactable_1", "anchor_id": "a_anchor"},
            ],
        }
    )

    first_registry = load_local_arena_templates_payload(copy.deepcopy(payload))
    second_registry = load_local_arena_templates_payload(copy.deepcopy(payload))

    assert [template.template_id for template in first_registry.templates] == [
        template.template_id for template in second_registry.templates
    ]

    first_beta = first_registry.by_id()["template_beta"]
    second_beta = second_registry.by_id()["template_beta"]

    assert [anchor["anchor_id"] for anchor in first_beta.anchors] == [anchor["anchor_id"] for anchor in second_beta.anchors]
    assert [door["door_id"] for door in first_beta.doors] == [door["door_id"] for door in second_beta.doors]
    assert [item["interactable_id"] for item in first_beta.interactables] == [
        item["interactable_id"] for item in second_beta.interactables
    ]
