from __future__ import annotations

GREYBRIDGE_SAFE_HUB_SPACE_ID = "safe_hub:greybridge"

GREYBRIDGE_STRUCTURE_OVERLAY: tuple[dict[str, object], ...] = (
    {
        "structure_id": "watch_hall_shell",
        "label": "Watch Hall",
        "room_id": "watch_hall",
        "bounds": {"x": 8, "y": 1, "width": 6, "height": 4},
        "openings": (
            {"opening_id": "watch_hall_door", "kind": "door", "cell": {"x": 8, "y": 3}},
        ),
    },
    {
        "structure_id": "inn_infirmary_shell",
        "label": "Inn / Infirmary",
        "room_id": "inn_infirmary",
        "bounds": {"x": 8, "y": 5, "width": 6, "height": 5},
        "openings": (
            {"opening_id": "inn_infirmary_door", "kind": "door", "cell": {"x": 8, "y": 7}},
        ),
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
    },
)


def compile_greybridge_overlay() -> dict[str, tuple[tuple[int, int], ...] | tuple[dict[str, object], ...]]:
    blocked: set[tuple[int, int]] = set()
    openings: list[tuple[int, int]] = []
    wall_cells: set[tuple[int, int]] = set()
    for structure in GREYBRIDGE_STRUCTURE_OVERLAY:
        bounds = structure.get("bounds", {})
        if not isinstance(bounds, dict):
            continue
        try:
            x0 = int(bounds["x"])
            y0 = int(bounds["y"])
            width = int(bounds["width"])
            height = int(bounds["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        x1 = x0 + width - 1
        y1 = y0 + height - 1
        for x in range(x0, x1 + 1):
            wall_cells.add((x, y0))
            wall_cells.add((x, y1))
        for y in range(y0, y1 + 1):
            wall_cells.add((x0, y))
            wall_cells.add((x1, y))
        for opening in structure.get("openings", ()):
            if not isinstance(opening, dict):
                continue
            cell = opening.get("cell", {})
            if not isinstance(cell, dict):
                continue
            try:
                openings.append((int(cell["x"]), int(cell["y"])))
            except (KeyError, TypeError, ValueError):
                continue
    blocked = wall_cells.difference(openings)
    opening_rows: list[dict[str, object]] = []
    for structure in GREYBRIDGE_STRUCTURE_OVERLAY:
        for opening in structure.get("openings", ()):
            if isinstance(opening, dict):
                opening_rows.append(dict(opening))
    return {
        "blocked_cells": tuple(sorted(blocked)),
        "opening_cells": tuple(sorted(set(openings))),
        "wall_cells": tuple(sorted(wall_cells)),
        "opening_rows": tuple(opening_rows),
    }


_COMPILED_GREYBRIDGE_OVERLAY = compile_greybridge_overlay()
GREYBRIDGE_BLOCKED_CELLS = _COMPILED_GREYBRIDGE_OVERLAY["blocked_cells"]
GREYBRIDGE_DOOR_CELLS = _COMPILED_GREYBRIDGE_OVERLAY["opening_cells"]
GREYBRIDGE_WALL_CELLS = _COMPILED_GREYBRIDGE_OVERLAY["wall_cells"]
