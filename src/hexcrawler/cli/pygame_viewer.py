from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import pygame

from hexcrawler.content.encounters import DEFAULT_ENCOUNTER_TABLE_PATH, load_encounter_table_json
from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation, TICKS_PER_DAY
from hexcrawler.sim.encounters import (
    ENCOUNTER_CHECK_EVENT_TYPE,
    ENCOUNTER_ROLL_EVENT_TYPE,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
)
from hexcrawler.sim.movement import axial_to_world_xy, normalized_vector, world_xy_to_axial
from hexcrawler.sim.world import HexCoord

HEX_SIZE = 28
GRID_RADIUS = 8
WINDOW_SIZE = (1024, 768)
SIM_TICK_SECONDS = 0.10
PLAYER_ID = "scout"

TERRAIN_COLORS: dict[str, tuple[int, int, int]] = {
    "plains": (132, 168, 94),
    "forest": (61, 120, 72),
    "hills": (153, 126, 90),
}
SITE_COLORS: dict[str, tuple[int, int, int]] = {
    "town": (80, 160, 255),
    "dungeon": (210, 85, 85),
}
ENCOUNTER_DEBUG_EVENT_LIMIT = 20


@dataclass
class ContextMenuState:
    pixel_x: int
    pixel_y: int
    world_x: float
    world_y: float


@dataclass
class SimulationController:
    """Viewer command adapter; simulation remains source of truth."""

    sim: Simulation
    entity_id: str

    def set_move_vector(self, x: float, y: float) -> None:
        self.sim.set_entity_move_vector(self.entity_id, x, y)

    def set_target_world(self, x: float, y: float) -> None:
        self.sim.set_entity_target_position(self.entity_id, x, y)

    def tick_once(self) -> None:
        self.sim.advance_ticks(1)


@dataclass(frozen=True)
class RenderEntitySnapshot:
    x: float
    y: float


RenderSnapshot = dict[str, RenderEntitySnapshot]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def lerp(start: float, end: float, alpha: float) -> float:
    return start + (end - start) * alpha


def extract_render_snapshot(sim: Simulation) -> RenderSnapshot:
    return {
        entity_id: RenderEntitySnapshot(x=entity.position_x, y=entity.position_y)
        for entity_id, entity in sim.state.entities.items()
    }


def interpolate_entity_position(
    prev_snapshot: RenderSnapshot,
    curr_snapshot: RenderSnapshot,
    entity_id: str,
    alpha: float,
) -> tuple[float, float] | None:
    previous = prev_snapshot.get(entity_id)
    current = curr_snapshot.get(entity_id)
    if previous is None and current is None:
        return None
    if previous is None:
        return (current.x, current.y)
    if current is None:
        return (previous.x, previous.y)
    return (lerp(previous.x, current.x, alpha), lerp(previous.y, current.y, alpha))


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


def _pixel_to_world(pixel_x: int, pixel_y: int, center: tuple[float, float]) -> tuple[float, float]:
    return ((pixel_x - center[0]) / HEX_SIZE, (pixel_y - center[1]) / HEX_SIZE)


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


def _draw_entity(screen: pygame.Surface, world_x: float, world_y: float, center: tuple[float, float]) -> None:
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
        "WASD move | RMB menu | ESC quit",
    ]
    y = 12
    for line in lines:
        surface = font.render(line, True, (240, 240, 240))
        screen.blit(surface, (12, y))
        y += 24


def _draw_encounter_debug_panel(screen: pygame.Surface, sim: Simulation, font: pygame.font.Font) -> None:
    panel_rect = pygame.Rect(WINDOW_SIZE[0] - 388, 12, 376, 360)
    pygame.draw.rect(screen, (24, 26, 36), panel_rect)
    pygame.draw.rect(screen, (95, 98, 110), panel_rect, 1)

    y = panel_rect.y + 8
    header = font.render("Encounter Debug", True, (245, 245, 245))
    screen.blit(header, (panel_rect.x + 10, y))
    y += 24

    module_present = sim.get_rule_module(EncounterCheckModule.name) is not None
    if not module_present:
        message = font.render(
            "Encounter module not enabled. Run with --with-encounters.",
            True,
            (220, 180, 130),
        )
        screen.blit(message, (panel_rect.x + 10, y))
        return

    state = sim.get_rules_state(EncounterCheckModule.name)
    last_check_tick = int(state.get("last_check_tick", -1))
    checks_emitted = int(state.get("checks_emitted", 0))
    eligible_count = int(state.get("eligible_count", 0))
    ineligible_streak = int(state.get("ineligible_streak", 0))
    cooldown_until_tick = int(state.get("cooldown_until_tick", -1))

    cooldown_active = sim.state.tick < cooldown_until_tick
    cooldown_ticks_remaining = max(0, cooldown_until_tick - sim.state.tick)

    kv_rows = [
        ("last_check_tick", str(last_check_tick)),
        ("checks_emitted", str(checks_emitted)),
        ("eligible_count", str(eligible_count)),
        ("ineligible_streak", str(ineligible_streak)),
        ("cooldown_until_tick", str(cooldown_until_tick)),
        ("cooldown_active", str(cooldown_active)),
        ("cooldown_ticks_left", str(cooldown_ticks_remaining)),
    ]
    for key, value in kv_rows:
        line = font.render(f"{key}: {value}", True, (224, 224, 224))
        screen.blit(line, (panel_rect.x + 10, y))
        y += 18

    y += 4
    list_header = font.render("Recent encounter events", True, (245, 245, 245))
    screen.blit(list_header, (panel_rect.x + 10, y))
    y += 20

    filtered_trace = [
        entry
        for entry in sim.get_event_trace()
        if entry.get("event_type") in {ENCOUNTER_CHECK_EVENT_TYPE, ENCOUNTER_ROLL_EVENT_TYPE}
    ]
    for entry in reversed(filtered_trace[-ENCOUNTER_DEBUG_EVENT_LIMIT:]):
        params = entry.get("params", {})
        tick = entry.get("tick")
        event_type = entry.get("event_type")
        source_tick = params.get("tick")
        context = params.get("context")
        roll = params.get("roll")
        roll_text = f", roll={roll}" if roll is not None else ""
        line = font.render(
            f"t={tick} {event_type} src={source_tick} ctx={context}{roll_text}",
            True,
            (205, 205, 210),
        )
        screen.blit(line, (panel_rect.x + 10, y))
        y += 16
        if y > panel_rect.bottom - 16:
            break


def _draw_context_menu(
    screen: pygame.Surface,
    font: pygame.font.Font,
    menu_state: ContextMenuState | None,
) -> pygame.Rect | None:
    if menu_state is None:
        return None

    menu_rect = pygame.Rect(menu_state.pixel_x, menu_state.pixel_y, 130, 34)
    pygame.draw.rect(screen, (32, 34, 44), menu_rect)
    pygame.draw.rect(screen, (185, 185, 200), menu_rect, 1)

    label = font.render("Move Here", True, (245, 245, 245))
    screen.blit(label, (menu_rect.x + 10, menu_rect.y + 6))
    return menu_rect


def _current_input_vector() -> tuple[float, float]:
    keys = pygame.key.get_pressed()
    x = 0.0
    y = 0.0
    if keys[pygame.K_w]:
        y -= 1.0
    if keys[pygame.K_s]:
        y += 1.0
    if keys[pygame.K_a]:
        x -= 1.0
    if keys[pygame.K_d]:
        x += 1.0
    return normalized_vector(x, y)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python run_game.py",
        description="Run the Hexcrawler pygame viewer.",
    )
    parser.add_argument(
        "--map-path",
        default="content/examples/basic_map.json",
        help="Path to world map JSON template.",
    )
    parser.add_argument(
        "--with-encounters",
        action="store_true",
        help="Enable encounter module registration for encounter debug data.",
    )
    return parser


def _build_viewer_simulation(map_path: str, *, with_encounters: bool) -> Simulation:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=7)
    if with_encounters:
        sim.register_rule_module(EncounterCheckModule())
        sim.register_rule_module(
            EncounterSelectionModule(
                load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)
            )
        )
        sim.register_rule_module(EncounterActionModule())
    sim.add_entity(EntityState.from_hex(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    return sim


def run_pygame_viewer(
    map_path: str = "content/examples/basic_map.json",
    *,
    with_encounters: bool = False,
) -> None:
    sim = _build_viewer_simulation(map_path, with_encounters=with_encounters)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    pygame.init()
    pygame.display.set_caption("Hexcrawler Phase 1 Viewer")
    screen = pygame.display.set_mode(WINDOW_SIZE)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 22)
    debug_font = pygame.font.SysFont("consolas", 16)

    center = (WINDOW_SIZE[0] / 2.0, WINDOW_SIZE[1] / 2.0)
    accumulator = 0.0
    running = True
    context_menu: ContextMenuState | None = None
    previous_snapshot = extract_render_snapshot(sim)
    current_snapshot = previous_snapshot
    tick_duration_seconds = SIM_TICK_SECONDS
    last_tick_time = pygame.time.get_ticks() / 1000.0

    while running:
        dt = clock.tick(60) / 1000.0
        accumulator += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                world_x, world_y = _pixel_to_world(event.pos[0], event.pos[1], center)
                target_hex = world_xy_to_axial(world_x, world_y)
                if sim.state.world.get_hex_record(target_hex) is None:
                    context_menu = None
                else:
                    context_menu = ContextMenuState(event.pos[0], event.pos[1], world_x, world_y)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and context_menu is not None:
                menu_rect = pygame.Rect(context_menu.pixel_x, context_menu.pixel_y, 130, 34)
                if menu_rect.collidepoint(event.pos):
                    controller.set_target_world(context_menu.world_x, context_menu.world_y)
                context_menu = None

        move_x, move_y = _current_input_vector()
        controller.set_move_vector(move_x, move_y)

        while accumulator >= SIM_TICK_SECONDS:
            previous_snapshot = current_snapshot
            controller.tick_once()
            current_snapshot = extract_render_snapshot(sim)
            last_tick_time = pygame.time.get_ticks() / 1000.0
            accumulator -= SIM_TICK_SECONDS

        now_seconds = pygame.time.get_ticks() / 1000.0
        alpha = clamp01((now_seconds - last_tick_time) / tick_duration_seconds)

        screen.fill((17, 18, 25))
        _draw_world(screen, sim, center)
        interpolated = interpolate_entity_position(previous_snapshot, current_snapshot, PLAYER_ID, alpha)
        if interpolated is not None:
            _draw_entity(screen, interpolated[0], interpolated[1], center)
        _draw_hud(screen, sim, font)
        _draw_encounter_debug_panel(screen, sim, debug_font)
        _draw_context_menu(screen, font, context_menu)
        pygame.display.flip()

    pygame.quit()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    run_pygame_viewer(map_path=args.map_path, with_encounters=args.with_encounters)
