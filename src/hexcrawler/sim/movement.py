from __future__ import annotations

import math

from hexcrawler.sim.world import HexCoord

SQRT3 = math.sqrt(3.0)


def axial_to_world_xy(coord: HexCoord) -> tuple[float, float]:
    """Pointy-top axial to 2D coordinates."""
    x = SQRT3 * (coord.q + coord.r / 2.0)
    y = 1.5 * coord.r
    return (x, y)


def world_xy_to_axial(x: float, y: float) -> HexCoord:
    """Deterministic nearest-hex conversion for pointy-top axial coordinates."""
    q = (SQRT3 / 3.0 * x) - (1.0 / 3.0 * y)
    r = (2.0 / 3.0) * y

    cube_x = q
    cube_z = r
    cube_y = -cube_x - cube_z

    rounded_x = round(cube_x)
    rounded_y = round(cube_y)
    rounded_z = round(cube_z)

    dx = abs(rounded_x - cube_x)
    dy = abs(rounded_y - cube_y)
    dz = abs(rounded_z - cube_z)

    if dx > dy and dx > dz:
        rounded_x = -rounded_y - rounded_z
    elif dy > dz:
        rounded_y = -rounded_x - rounded_z
    else:
        rounded_z = -rounded_x - rounded_y

    return HexCoord(q=int(rounded_x), r=int(rounded_z))


def normalized_vector(x: float, y: float) -> tuple[float, float]:
    length_sq = x * x + y * y
    if length_sq == 0.0:
        return (0.0, 0.0)
    length = math.sqrt(length_sq)
    return (x / length, y / length)
