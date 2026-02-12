from __future__ import annotations

import math

from hexcrawler.sim.world import HexCoord

AXIAL_DIRECTIONS: tuple[HexCoord, ...] = (
    HexCoord(1, 0),
    HexCoord(1, -1),
    HexCoord(0, -1),
    HexCoord(-1, 0),
    HexCoord(-1, 1),
    HexCoord(0, 1),
)


def axial_to_world_xy(coord: HexCoord, offset_x: float = 0.0, offset_y: float = 0.0) -> tuple[float, float]:
    """Pointy-top axial to 2D coordinates."""
    x = math.sqrt(3.0) * (coord.q + coord.r / 2.0) + offset_x
    y = 1.5 * coord.r + offset_y
    return (x, y)


def nearest_direction_step(current: HexCoord, destination: HexCoord) -> HexCoord:
    if current == destination:
        return current

    best_coord = current
    best_distance = _axial_distance(current, destination)
    for delta in AXIAL_DIRECTIONS:
        candidate = HexCoord(current.q + delta.q, current.r + delta.r)
        distance = _axial_distance(candidate, destination)
        if distance < best_distance:
            best_distance = distance
            best_coord = candidate
    return best_coord


def _axial_distance(a: HexCoord, b: HexCoord) -> int:
    dq = a.q - b.q
    dr = a.r - b.r
    ds = (-a.q - a.r) - (-b.q - b.r)
    return int((abs(dq) + abs(dr) + abs(ds)) / 2)
