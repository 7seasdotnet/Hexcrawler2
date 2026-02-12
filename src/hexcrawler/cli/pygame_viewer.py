from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation, TICKS_PER_DAY
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.world import HexCoord

# Axial orientation: pointy-top hexes (matches sim.movement.axial_to_world_xy).
HEX_SIZE = 28
GRID_RADIUS = 8
WINDOW_SIZE = (1024, 768)
SIM_TICK_SECONDS = 0.10  # 100ms fixed simulation tick.
PLAYER_ID = "scout"

# WASD mapping for axial neighbors in pointy-top coordinates.
# W: north-ish (0, -1), S: south-ish (0, +1), A: west (-1, 0), D: east (+1, 0).
MOVE_BY_KEY: dict[int, HexCoord] = {
    pygame.K_w: HexCoord(0, -1),
    pygame.K_s: HexCoord(0, 1),
    pygame.K_a: HexCoord(-1, 0),
    pygame.K_d: HexCoord(1, 0),
}

TERRAIN_COLORS: dict[str, tuple[int, int, int]] = {
    "plains": (132, 168, 94),
    "forest": (61, 120, 72),
    "hills": (153, 126, 90),
}
SITE_COLORS: dict[str, tuple[int, int, int]] = {
    "town": (80, 160, 255),
    "dungeon": (210, 85, 85),
}


@dataclass
class SimulationController:
    """Viewer command adapter; simulation remains source of truth."""

    sim: Simulation
    entity_id: str

    def queue_move(self, delta: HexCoord) -> None:
        entity = self.sim.state.entities[self.entity_id]
        destination = HexCoord(entity.hex_coord.q + delta.q, entity.hex_coord.r + delta.r)
        self.sim.set_entity_destination(self.entity_id, destination)

    def tick_once(self) -> None:
        self.sim.advance_ticks(1)


def _grid_coords(radius: int) -> list[HexCoord]:
    coords: list[HexCoord] = []
    for q in range(-radius, radius + 1):
        r_min = max(-radius, -q - radius)
        r_max = min(radius, -q + radius)
        for r in range(r_min, r_max + 1):
            coords.append(HexCoord(q, r))
    return coords


def _axial_to_pixel(coord: HexCoord, center: tuple[float, float]) -> tuple[float, float]:
    world_x, world_y = axial_to_world_xy(coord)
    return (center[0] + world_x * HEX_SIZE, center[1] + world_y * HEX_SIZE)


def _hex_points(center: tuple[float, float]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((center[0] + HEX_SIZE * math.cos(angle), center[1] + HEX_SIZE * math.sin(angle)))
    return points


def _draw_world(screen: pygame.Surface, sim: Simulation, center: tuple[float, float]) -> None:
    for coord in _grid_coords(GRID_RADIUS):
        pixel = _axial_to_pixel(coord, center)
        points = _hex_points(pixel)

        record = sim.state.world.get_hex_record(coord)
        terrain_type = record.terrain_type if record else "void"
        terrain_color = TERRAIN_COLORS.get(terrain_type, (90, 90, 96))
        pygame.draw.polygon(screen, terrain_color, points)
        pygame.draw.polygon(screen, (35, 35, 40), points, 1)

        if record and record.site_type != "none":
            site_color = SITE_COLORS.get(record.site_type, (245, 245, 120))
            pygame.draw.circle(screen, site_color, (int(pixel[0]), int(pixel[1])), 6)


def _draw_entity(screen: pygame.Surface, sim: Simulation, center: tuple[float, float]) -> None:
    entity = sim.state.entities[PLAYER_ID]
    world_x, world_y = entity.world_xy()
    x = int(center[0] + world_x * HEX_SIZE)
    y = int(center[1] + world_y * HEX_SIZE)
    pygame.draw.circle(screen, (255, 243, 130), (x, y), 8)
    pygame.draw.circle(screen, (15, 15, 15), (x, y), 8, 1)


def _draw_hud(screen: pygame.Surface, sim: Simulation, font: pygame.font.Font) -> None:
    entity = sim.state.entities[PLAYER_ID]
    lines = [
        f"CURRENT HEX: ({entity.hex_coord.q}, {entity.hex_coord.r})",
        f"ticks: {sim.state.tick}",
        f"day: {sim.state.tick // TICKS_PER_DAY}",
        "WASD to move | ESC to quit",
    ]
    y = 12
    for line in lines:
        surface = font.render(line, True, (240, 240, 240))
        screen.blit(surface, (12, y))
        y += 24


def run_pygame_viewer(map_path: str = "content/examples/basic_map.json") -> None:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=7)
    sim.add_entity(EntityState(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    pygame.init()
    pygame.display.set_caption("Hexcrawler Phase 1 Viewer")
    screen = pygame.display.set_mode(WINDOW_SIZE)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 22)

    center = (WINDOW_SIZE[0] / 2.0, WINDOW_SIZE[1] / 2.0)
    accumulator = 0.0
    running = True

    while running:
        dt = clock.tick(60) / 1000.0
        accumulator += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in MOVE_BY_KEY:
                    controller.queue_move(MOVE_BY_KEY[event.key])

        while accumulator >= SIM_TICK_SECONDS:
            controller.tick_once()
            accumulator -= SIM_TICK_SECONDS

        screen.fill((17, 18, 25))
        _draw_world(screen, sim, center)
        _draw_entity(screen, sim, center)
        _draw_hud(screen, sim, font)
        pygame.display.flip()

    pygame.quit()
