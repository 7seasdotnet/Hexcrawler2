from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCAL_ARENAS_SCHEMA_VERSION = 1
DEFAULT_LOCAL_ARENAS_PATH = "content/local_arenas/local_arenas.json"
SUPPORTED_LOCAL_ARENA_TOPOLOGIES = {"square_grid"}


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, str))


def _normalize_json_value(value: Any, *, field_name: str) -> Any:
    if isinstance(value, float):
        raise ValueError(f"{field_name} must not contain float values")
    if _is_json_primitive(value):
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, field_name=field_name) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError(f"{field_name} keys must be strings")
            normalized[key] = _normalize_json_value(value[key], field_name=field_name)
        return normalized
    raise ValueError(f"{field_name} must contain only JSON-serializable values")


@dataclass(frozen=True)
class LocalArenaTemplate:
    template_id: str
    topology_type: str
    topology_params: dict[str, Any]
    role: str
    anchors: tuple[dict[str, Any], ...]
    doors: tuple[dict[str, Any], ...]
    interactables: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class LocalArenaTemplateRegistry:
    schema_version: int
    templates: tuple[LocalArenaTemplate, ...]
    default_template_id: str

    def by_id(self) -> dict[str, LocalArenaTemplate]:
        return {template.template_id: template for template in self.templates}


def validate_local_arena_templates_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("local arena templates payload must be an object")
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("local arena templates must contain integer field: schema_version")
    if schema_version != LOCAL_ARENAS_SCHEMA_VERSION:
        raise ValueError(f"unsupported local arena templates schema_version: {schema_version}")

    templates = payload.get("templates")
    if not isinstance(templates, list) or not templates:
        raise ValueError("local arena templates must contain non-empty list field: templates")

    seen: set[str] = set()
    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            raise ValueError(f"templates[{index}] must be an object")
        template_id = template.get("template_id")
        if not isinstance(template_id, str) or not template_id:
            raise ValueError(f"templates[{index}] must contain non-empty string field: template_id")
        if template_id in seen:
            raise ValueError(f"duplicate local arena template_id: {template_id}")
        seen.add(template_id)

        topology_type = template.get("topology_type")
        if not isinstance(topology_type, str) or not topology_type:
            raise ValueError(f"templates[{index}] must contain non-empty string field: topology_type")
        if topology_type not in SUPPORTED_LOCAL_ARENA_TOPOLOGIES:
            raise ValueError(f"templates[{index}] unsupported topology_type: {topology_type}")

        topology_params = template.get("topology_params")
        if not isinstance(topology_params, dict):
            raise ValueError(f"templates[{index}] field topology_params must be an object")
        _normalize_json_value(topology_params, field_name=f"templates[{index}].topology_params")
        width = topology_params.get("width")
        height = topology_params.get("height")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError(f"templates[{index}].topology_params.width must be integer > 0")
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ValueError(f"templates[{index}].topology_params.height must be integer > 0")

        role = template.get("role")
        if role != "local":
            raise ValueError(f"templates[{index}] role must be 'local'")

        anchors = template.get("anchors", [])
        if not isinstance(anchors, list):
            raise ValueError(f"templates[{index}] field anchors must be a list when present")
        seen_anchor_ids: set[str] = set()
        for anchor_index, anchor in enumerate(anchors):
            if not isinstance(anchor, dict):
                raise ValueError(f"templates[{index}].anchors[{anchor_index}] must be an object")
            anchor_id = anchor.get("anchor_id")
            if not isinstance(anchor_id, str) or not anchor_id:
                raise ValueError(f"templates[{index}].anchors[{anchor_index}].anchor_id must be non-empty string")
            if anchor_id in seen_anchor_ids:
                raise ValueError(f"templates[{index}] duplicate anchor_id: {anchor_id}")
            seen_anchor_ids.add(anchor_id)
            coord = anchor.get("coord")
            if not isinstance(coord, dict):
                raise ValueError(f"templates[{index}].anchors[{anchor_index}].coord must be an object")
            x = coord.get("x")
            y = coord.get("y")
            if isinstance(x, bool) or not isinstance(x, int):
                raise ValueError(f"templates[{index}].anchors[{anchor_index}].coord.x must be an integer")
            if isinstance(y, bool) or not isinstance(y, int):
                raise ValueError(f"templates[{index}].anchors[{anchor_index}].coord.y must be an integer")
            tags = anchor.get("tags", [])
            if not isinstance(tags, list):
                raise ValueError(f"templates[{index}].anchors[{anchor_index}].tags must be a list when present")
            for tag_index, tag in enumerate(tags):
                if not isinstance(tag, str) or not tag:
                    raise ValueError(
                        f"templates[{index}].anchors[{anchor_index}].tags[{tag_index}] must be non-empty string"
                    )
            _normalize_json_value(anchor.get("metadata", {}), field_name=f"templates[{index}].anchors[{anchor_index}].metadata")

        for field in ("doors", "interactables"):
            rows = template.get(field, [])
            if not isinstance(rows, list):
                raise ValueError(f"templates[{index}] field {field} must be a list when present")
            seen_row_ids: set[str] = set()
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError(f"templates[{index}].{field}[{row_index}] must be an object")
                if field == "doors":
                    row_id = row.get("door_id")
                    id_field = "door_id"
                else:
                    row_id = row.get("interactable_id")
                    id_field = "interactable_id"
                if not isinstance(row_id, str) or not row_id:
                    raise ValueError(f"templates[{index}].{field}[{row_index}].{id_field} must be non-empty string")
                if row_id in seen_row_ids:
                    raise ValueError(f"templates[{index}] duplicate {id_field}: {row_id}")
                seen_row_ids.add(row_id)
                _normalize_json_value(row, field_name=f"templates[{index}].{field}[{row_index}]")

        _normalize_json_value(template.get("metadata", {}), field_name=f"templates[{index}].metadata")

    default_template_id = payload.get("default_template_id")
    if not isinstance(default_template_id, str) or not default_template_id:
        raise ValueError("local arena templates must contain non-empty string field: default_template_id")
    if default_template_id not in seen:
        raise ValueError(f"default_template_id references unknown template: {default_template_id}")


def _registry_from_payload(payload: dict[str, Any]) -> LocalArenaTemplateRegistry:
    validate_local_arena_templates_payload(payload)
    normalized_templates: list[LocalArenaTemplate] = []
    for row in payload["templates"]:
        anchors = sorted((dict(anchor) for anchor in row.get("anchors", [])), key=lambda anchor: str(anchor["anchor_id"]))
        normalized_anchors: list[dict[str, Any]] = []
        for anchor in anchors:
            metadata = _normalize_json_value(anchor.get("metadata", {}), field_name="anchor.metadata")
            normalized_anchors.append(
                {
                    "anchor_id": str(anchor["anchor_id"]),
                    "coord": {"x": int(anchor["coord"]["x"]), "y": int(anchor["coord"]["y"])},
                    "tags": sorted(dict.fromkeys(str(tag) for tag in anchor.get("tags", []))),
                    "metadata": metadata,
                }
            )

        normalized_templates.append(
            LocalArenaTemplate(
                template_id=str(row["template_id"]),
                topology_type=str(row["topology_type"]),
                topology_params=_normalize_json_value(row["topology_params"], field_name="topology_params"),
                role="local",
                anchors=tuple(normalized_anchors),
                doors=tuple(
                    _normalize_json_value(door, field_name="door")
                    for door in sorted(row.get("doors", []), key=lambda value: str(value["door_id"]))
                ),
                interactables=tuple(
                    _normalize_json_value(interactable, field_name="interactable")
                    for interactable in sorted(
                        row.get("interactables", []), key=lambda value: str(value["interactable_id"])
                    )
                ),
                metadata=_normalize_json_value(row.get("metadata", {}), field_name="metadata"),
            )
        )

    normalized_templates.sort(key=lambda template: template.template_id)
    return LocalArenaTemplateRegistry(
        schema_version=int(payload["schema_version"]),
        templates=tuple(normalized_templates),
        default_template_id=str(payload["default_template_id"]),
    )


def load_local_arena_templates_payload(payload: dict[str, Any]) -> LocalArenaTemplateRegistry:
    """Public, test-friendly entrypoint. Performs full validation + deterministic normalization."""
    return _registry_from_payload(payload)


def load_local_arena_templates_json(path: str | Path) -> LocalArenaTemplateRegistry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _registry_from_payload(payload)
