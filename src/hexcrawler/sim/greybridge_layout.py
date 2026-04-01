from __future__ import annotations

from typing import Any

GREYBRIDGE_SAFE_HUB_SPACE_ID = "safe_hub:greybridge"

GREYBRIDGE_STRUCTURE_PRIMITIVES: tuple[dict[str, object], ...] = (
    {
        "structure_id": "watch_hall_shell",
        "label": "Watch Hall",
        "room_id": "watch_hall",
        "bounds": {"x": 8, "y": 1, "width": 6, "height": 4},
        "openings": (
            {"opening_id": "watch_hall_door", "kind": "door", "cell": {"x": 8, "y": 3}},
        ),
        "tags": ("service", "turn_in"),
    },
    {
        "structure_id": "inn_infirmary_shell",
        "label": "Inn / Infirmary",
        "room_id": "inn_infirmary",
        "bounds": {"x": 8, "y": 5, "width": 6, "height": 5},
        "openings": (
            {"opening_id": "inn_infirmary_door", "kind": "door", "cell": {"x": 8, "y": 7}},
        ),
        "tags": ("service", "recovery"),
    },
    {
        "structure_id": "gatehouse_shell",
        "label": "Greybridge Gatehouse",
        "room_id": "gatehouse",
        "bounds": {"x": 0, "y": 4, "width": 4, "height": 3},
        "openings": (
            {"opening_id": "gate_exit_portal", "kind": "gate_portal", "cell": {"x": 1, "y": 5}},
            {"opening_id": "gate_interior_passage", "kind": "opening", "cell": {"x": 3, "y": 5}},
        ),
        "tags": ("gate", "transition"),
    },
)


def normalize_structure_primitives(raw_structures: Any) -> tuple[dict[str, object], ...]:
    if not isinstance(raw_structures, (list, tuple)):
        raw_structures = GREYBRIDGE_STRUCTURE_PRIMITIVES
    normalized: list[dict[str, object]] = []
    for raw in raw_structures:
        if not isinstance(raw, dict):
            continue
        structure_id = str(raw.get("structure_id", "")).strip()
        if not structure_id:
            continue
        bounds = raw.get("bounds")
        if not isinstance(bounds, dict):
            continue
        try:
            x = int(bounds.get("x"))
            y = int(bounds.get("y"))
            width = int(bounds.get("width"))
            height = int(bounds.get("height"))
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        openings_raw = raw.get("openings", ())
        openings: list[dict[str, object]] = []
        if isinstance(openings_raw, (list, tuple)):
            for opening in openings_raw:
                if not isinstance(opening, dict):
                    continue
                opening_id = str(opening.get("opening_id", "")).strip()
                if not opening_id:
                    continue
                cell = opening.get("cell")
                if not isinstance(cell, dict):
                    continue
                try:
                    cell_x = int(cell.get("x"))
                    cell_y = int(cell.get("y"))
                except (TypeError, ValueError):
                    continue
                openings.append(
                    {
                        "opening_id": opening_id,
                        "kind": str(opening.get("kind", "opening")),
                        "cell": {"x": cell_x, "y": cell_y},
                    }
                )
        tags_raw = raw.get("tags", ())
        tags: list[str] = []
        if isinstance(tags_raw, (list, tuple)):
            for tag in tags_raw:
                tag_s = str(tag).strip()
                if tag_s:
                    tags.append(tag_s)
        normalized.append(
            {
                "structure_id": structure_id,
                "label": str(raw.get("label", structure_id)),
                "room_id": str(raw.get("room_id", structure_id)),
                "bounds": {"x": x, "y": y, "width": width, "height": height},
                "openings": tuple(sorted(openings, key=lambda row: str(row.get("opening_id", "")))),
                "tags": tuple(sorted(set(tags))),
            }
        )
    normalized.sort(key=lambda row: str(row["structure_id"]))
    return tuple(normalized)


def compile_structure_primitives(structures: Any) -> dict[str, object]:
    normalized = normalize_structure_primitives(structures)
    wall_cells: set[tuple[int, int]] = set()
    opening_cells: set[tuple[int, int]] = set()
    opening_rows: list[dict[str, object]] = []
    wall_segments: list[dict[str, object]] = []

    for structure in normalized:
        bounds = structure["bounds"]
        x0 = int(bounds["x"])
        y0 = int(bounds["y"])
        x1 = x0 + int(bounds["width"]) - 1
        y1 = y0 + int(bounds["height"]) - 1
        edge_cells: set[tuple[int, int]] = set()
        for x in range(x0, x1 + 1):
            edge_cells.add((x, y0))
            edge_cells.add((x, y1))
        for y in range(y0, y1 + 1):
            edge_cells.add((x0, y))
            edge_cells.add((x1, y))
        structure_openings: set[tuple[int, int]] = set()
        for opening in structure.get("openings", ()):  # type: ignore[assignment]
            if not isinstance(opening, dict):
                continue
            cell = opening.get("cell")
            if not isinstance(cell, dict):
                continue
            try:
                cell_key = (int(cell["x"]), int(cell["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            opening_cells.add(cell_key)
            structure_openings.add(cell_key)
            opening_rows.append(
                {
                    "structure_id": structure["structure_id"],
                    "opening_id": str(opening.get("opening_id", "")),
                    "kind": str(opening.get("kind", "opening")),
                    "cell": {"x": cell_key[0], "y": cell_key[1]},
                }
            )
        wall_cells.update(edge_cells.difference(structure_openings))
        wall_segments.extend(
            (
                {"structure_id": structure["structure_id"], "axis": "h", "x0": x0, "y0": y0, "x1": x1 + 1, "y1": y0},
                {"structure_id": structure["structure_id"], "axis": "h", "x0": x0, "y0": y1 + 1, "x1": x1 + 1, "y1": y1 + 1},
                {"structure_id": structure["structure_id"], "axis": "v", "x0": x0, "y0": y0, "x1": x0, "y1": y1 + 1},
                {"structure_id": structure["structure_id"], "axis": "v", "x0": x1 + 1, "y0": y0, "x1": x1 + 1, "y1": y1 + 1},
            )
        )

    blocked_cells = tuple(sorted(wall_cells.difference(opening_cells)))
    return {
        "structure_rows": normalized,
        "blocked_cells": blocked_cells,
        "opening_cells": tuple(sorted(opening_cells)),
        "wall_cells": tuple(sorted(wall_cells)),
        "opening_rows": tuple(sorted(opening_rows, key=lambda row: (str(row.get("structure_id", "")), str(row.get("opening_id", ""))))),
        "wall_segments": tuple(sorted(wall_segments, key=lambda row: (str(row.get("structure_id", "")), str(row.get("axis", "")), int(row.get("x0", 0)), int(row.get("y0", 0))))),
    }


def compile_greybridge_overlay(structures: Any = None) -> dict[str, object]:
    source = GREYBRIDGE_STRUCTURE_PRIMITIVES if structures is None else structures
    return compile_structure_primitives(source)


_COMPILED_GREYBRIDGE_OVERLAY = compile_greybridge_overlay()
GREYBRIDGE_BLOCKED_CELLS = _COMPILED_GREYBRIDGE_OVERLAY["blocked_cells"]
GREYBRIDGE_DOOR_CELLS = _COMPILED_GREYBRIDGE_OVERLAY["opening_cells"]
GREYBRIDGE_WALL_CELLS = _COMPILED_GREYBRIDGE_OVERLAY["wall_cells"]
