from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hexcrawler.content.encounters import DEFAULT_ENCOUNTER_TABLE_PATH, load_encounter_table_json
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation, TICKS_PER_DAY
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
)
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.movement import axial_to_world_xy, normalized_vector, world_xy_to_axial
from hexcrawler.sim.world import HexCoord

HEX_SIZE = 28
GRID_RADIUS = 8
WINDOW_SIZE = (1440, 900)
PANEL_WIDTH = 520
VIEWPORT_MARGIN = 12
PANEL_MARGIN = 12
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
ENCOUNTER_DEBUG_SIGNAL_LIMIT = 10
ENCOUNTER_DEBUG_TRACK_LIMIT = 10
ENCOUNTER_DEBUG_OUTCOME_LIMIT = 20
ENCOUNTER_DEBUG_SECTION_ROWS = 6

pygame: Any | None = None


@dataclass
class ContextMenuState:
    pixel_x: int
    pixel_y: int
    world_x: float
    world_y: float


@dataclass
class EncounterPanelScrollState:
    signals_offset: int = 0
    tracks_offset: int = 0
    outcomes_offset: int = 0

    def offset_for(self, section: str) -> int:
        if section == "signals":
            return self.signals_offset
        if section == "tracks":
            return self.tracks_offset
        return self.outcomes_offset

    def scroll(self, section: str, delta: int, total_count: int, page_size: int) -> None:
        max_offset = max(0, total_count - page_size)
        next_offset = max(0, min(max_offset, self.offset_for(section) + delta))
        if section == "signals":
            self.signals_offset = next_offset
        elif section == "tracks":
            self.tracks_offset = next_offset
        else:
            self.outcomes_offset = next_offset


@dataclass
class SimulationController:
    """Viewer command adapter; simulation remains source of truth."""

    sim: Simulation
    entity_id: str

    def set_move_vector(self, x: float, y: float) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="set_move_vector",
                params={"x": x, "y": y},
            )
        )

    def set_target_world(self, x: float, y: float) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="set_target_position",
                params={"x": x, "y": y},
            )
        )

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


def _viewport_rect() -> pygame.Rect:
    panel_x = WINDOW_SIZE[0] - PANEL_WIDTH - PANEL_MARGIN
    width = panel_x - (VIEWPORT_MARGIN * 2)
    return pygame.Rect(VIEWPORT_MARGIN, VIEWPORT_MARGIN, width, WINDOW_SIZE[1] - (VIEWPORT_MARGIN * 2))


def _panel_rect() -> pygame.Rect:
    panel_x = WINDOW_SIZE[0] - PANEL_WIDTH - PANEL_MARGIN
    return pygame.Rect(panel_x, PANEL_MARGIN, PANEL_WIDTH, WINDOW_SIZE[1] - (PANEL_MARGIN * 2))


def _draw_world(
    screen: pygame.Surface,
    sim: Simulation,
    center: tuple[float, float],
    *,
    clip_rect: pygame.Rect,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
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
    screen.set_clip(old_clip)


def _draw_entity(
    screen: pygame.Surface,
    world_x: float,
    world_y: float,
    center: tuple[float, float],
    *,
    clip_rect: pygame.Rect,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    x = int(center[0] + world_x * HEX_SIZE)
    y = int(center[1] + world_y * HEX_SIZE)
    pygame.draw.circle(screen, (255, 243, 130), (x, y), 8)
    pygame.draw.circle(screen, (15, 15, 15), (x, y), 8, 1)
    screen.set_clip(old_clip)


def _draw_hud(screen: pygame.Surface, sim: Simulation, font: pygame.font.Font) -> None:
    entity = sim.state.entities[PLAYER_ID]
    lines = [
        f"CURRENT HEX: ({entity.hex_coord.q}, {entity.hex_coord.r})",
        f"ticks: {sim.state.tick}",
        f"day: {sim.state.tick // TICKS_PER_DAY}",
        "WASD move | RMB menu | F5 save | F9 load | ESC quit",
    ]
    y = 12
    for line in lines:
        surface = font.render(line, True, (240, 240, 240))
        screen.blit(surface, (12, y))
        y += 24


def _format_location(location: object) -> str:
    if not isinstance(location, dict):
        return "loc=?"
    topology = str(location.get("topology_type", "?"))
    coord = location.get("coord")
    if isinstance(coord, dict):
        q = coord.get("q")
        r = coord.get("r")
        return f"{topology}:{q},{r}"
    return f"{topology}:?"


def _draw_encounter_debug_panel(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    scroll_state: EncounterPanelScrollState,
) -> tuple[dict[str, pygame.Rect], dict[str, int]]:
    panel_rect = _panel_rect()
    pygame.draw.rect(screen, (24, 26, 36), panel_rect)
    pygame.draw.rect(screen, (95, 98, 110), panel_rect, 1)

    y = panel_rect.y + 8
    header = font.render("Encounter Debug", True, (245, 245, 245))
    screen.blit(header, (panel_rect.x + 10, y))
    y += 18
    hint = font.render("Mouse wheel/PgUp/PgDn scroll hovered section", True, (190, 192, 202))
    screen.blit(hint, (panel_rect.x + 10, y))
    y += 18

    module_present = sim.get_rule_module(EncounterCheckModule.name) is not None
    if not module_present:
        message = font.render(
            "Encounter debug not enabled; run with --with-encounters",
            True,
            (220, 180, 130),
        )
        screen.blit(message, (panel_rect.x + 10, y))
        return {}, {}

    state = sim.get_rules_state(EncounterCheckModule.name)
    kv_rows = [
        ("last_check_tick", str(int(state.get("last_check_tick", -1)))),
        ("checks_emitted", str(int(state.get("checks_emitted", 0)))),
        ("eligible_count", str(int(state.get("eligible_count", 0)))),
        (
            "cooldown_ticks_left",
            str(max(0, int(state.get("cooldown_until_tick", -1)) - sim.state.tick)),
        ),
        ("ineligible_streak", str(int(state.get("ineligible_streak", 0)))),
    ]
    for key, value in kv_rows:
        line = font.render(f"{key}: {value}", True, (224, 224, 224))
        screen.blit(line, (panel_rect.x + 10, y))
        y += 18

    recent_signals = list(reversed(sim.state.world.signals[-ENCOUNTER_DEBUG_SIGNAL_LIMIT:]))
    recent_tracks = list(reversed(sim.state.world.tracks[-ENCOUNTER_DEBUG_TRACK_LIMIT:]))
    filtered_trace = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE
    ]
    recent_outcomes = list(reversed(filtered_trace[-ENCOUNTER_DEBUG_OUTCOME_LIMIT:]))

    signal_rows = [
        (
            f"  created={record.get('created_tick', '?')} "
            f"template={record.get('template_id', '?')} "
            f"location={_format_location(record.get('location'))} "
            f"expires={record.get('expires_tick', '-') if record.get('expires_tick') is not None else '-'}"
        )
        for record in recent_signals
    ]
    track_rows = [
        (
            f"  created={record.get('created_tick', '?')} "
            f"template={record.get('template_id', '?')} "
            f"location={_format_location(record.get('location'))} "
            f"expires={record.get('expires_tick', '-') if record.get('expires_tick') is not None else '-'}"
        )
        for record in recent_tracks
    ]
    outcome_rows = []
    for entry in recent_outcomes:
        params = entry.get("params")
        params = params if isinstance(params, dict) else {}
        template_id = params.get("template_id")
        outcome_rows.append(
            f"  tick={entry.get('tick', '?')} "
            f"action_uid={params.get('action_uid', '?')} "
            f"action_type={params.get('action_type', '?')} "
            f"outcome={params.get('outcome', '?')} "
            f"template={template_id if template_id not in (None, '') else '-'}"
        )

    section_rects: dict[str, pygame.Rect] = {}
    section_counts: dict[str, int] = {}

    def render_section(section: str, title: str, rows: list[str]) -> None:
        nonlocal y
        total = len(rows)
        section_counts[section] = total
        offset = scroll_state.offset_for(section)
        section_top = y
        header_line = font.render(
            f"{title} ({total}) [{offset + 1 if total else 0}-{min(total, offset + ENCOUNTER_DEBUG_SECTION_ROWS)}]",
            True,
            (245, 245, 245),
        )
        screen.blit(header_line, (panel_rect.x + 10, y))
        y += 16
        slice_rows = rows[offset : offset + ENCOUNTER_DEBUG_SECTION_ROWS]
        if not slice_rows:
            screen.blit(font.render("  none", True, (205, 205, 210)), (panel_rect.x + 10, y))
            y += 16
        for row in slice_rows:
            screen.blit(font.render(row, True, (205, 205, 210)), (panel_rect.x + 10, y))
            y += 16
        section_rects[section] = pygame.Rect(panel_rect.x + 6, section_top, panel_rect.width - 12, y - section_top)
        y += 6

    y += 4
    render_section("signals", "Recent Signals", signal_rows)
    render_section("tracks", "Recent Tracks", track_rows)
    render_section("outcomes", "Recent Action Outcomes", outcome_rows)
    return section_rects, section_counts


def _draw_context_menu(
    screen: pygame.Surface,
    font: pygame.font.Font,
    menu_state: ContextMenuState | None,
    viewport_rect: pygame.Rect,
) -> pygame.Rect | None:
    if menu_state is None:
        return None

    menu_rect = pygame.Rect(menu_state.pixel_x, menu_state.pixel_y, 130, 34)
    menu_rect.clamp_ip(viewport_rect)
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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Force SDL dummy video driver for CI/testing and exit without opening a real window.",
    )
    parser.add_argument(
        "--load-save",
        help="Optional canonical save JSON path to load simulation state on startup.",
    )
    parser.add_argument(
        "--save-path",
        default="saves/session_save.json",
        help="Canonical save JSON path used by F5 save and fallback F9 load.",
    )
    return parser


def _env_flag_enabled(var_name: str) -> bool:
    return os.environ.get(var_name, "").strip().lower() in {"1", "true", "yes", "on"}


def _print_startup_banner() -> None:
    try:
        pygame_version = importlib.metadata.version("pygame")
    except importlib.metadata.PackageNotFoundError:
        pygame_version = "not-installed"
    print(
        "[hexcrawler.viewer] startup "
        f"python={platform.python_version()} "
        f"pygame={pygame_version} "
        f"platform={platform.platform()}"
    )
    for name in ("SDL_VIDEODRIVER", "SDL_AUDIODRIVER", "SDL_VIDEO_WINDOW_POS"):
        value = os.environ.get(name, "<unset>")
        print(f"[hexcrawler.viewer] env {name}={value}")


def _ensure_pygame_imported() -> Any:
    global pygame
    if pygame is None:
        import pygame as pygame_module

        pygame = pygame_module
    return pygame


def _register_encounter_modules(sim: Simulation) -> None:
    if sim.get_rule_module(EncounterCheckModule.name) is not None:
        return
    sim.register_rule_module(EncounterCheckModule())
    sim.register_rule_module(EncounterSelectionModule(load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)))
    sim.register_rule_module(EncounterActionModule())
    sim.register_rule_module(EncounterActionExecutionModule())


def _build_viewer_simulation(map_path: str, *, with_encounters: bool) -> Simulation:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=7)
    if with_encounters:
        _register_encounter_modules(sim)
    sim.add_entity(EntityState.from_hex(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    return sim


def _load_viewer_simulation(save_path: str, *, with_encounters: bool) -> Simulation:
    _, sim = load_game_json(save_path)
    should_enable_encounters = with_encounters or EncounterCheckModule.name in sim.state.rules_state
    if should_enable_encounters:
        _register_encounter_modules(sim)
    print(
        "[hexcrawler.viewer] loaded "
        f"path={save_path} tick={sim.state.tick} "
        f"input_log={len(sim.input_log)} "
        f"world_hash={world_hash(sim.state.world)} "
        f"simulation_hash={simulation_hash(sim)}"
    )
    return sim


def _save_viewer_simulation(sim: Simulation, save_path: str) -> None:
    save_game_json(save_path, sim.state.world, sim)
    payload = json.loads(Path(save_path).read_text(encoding="utf-8"))
    print(
        "[hexcrawler.viewer] saved "
        f"path={save_path} "
        f"save_hash={payload.get('save_hash', '<missing>')} "
        f"world_hash={world_hash(sim.state.world)} "
        f"simulation_hash={simulation_hash(sim)}"
    )


def run_pygame_viewer(
    map_path: str = "content/examples/basic_map.json",
    *,
    with_encounters: bool = False,
    headless: bool = False,
    load_save: str | None = None,
    save_path: str = "saves/session_save.json",
) -> int:
    if headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        print("[hexcrawler.viewer] warning: headless mode active; no window will open.")

    _print_startup_banner()
    pygame_module = _ensure_pygame_imported()

    try:
        pygame_module.init()
    except Exception as exc:
        print(
            "[hexcrawler.viewer] failed during pygame.init(): "
            f"{exc}. Hint: verify a working SDL video driver (set SDL_VIDEODRIVER=dummy for headless mode).",
            file=sys.stderr,
        )
        return 1

    try:
        sim = _load_viewer_simulation(load_save, with_encounters=with_encounters) if load_save else _build_viewer_simulation(
            map_path,
            with_encounters=with_encounters,
        )
    except Exception as exc:
        print(f"[hexcrawler.viewer] failed to initialize simulation: {exc}", file=sys.stderr)
        pygame_module.quit()
        return 1

    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    try:
        pygame_module.display.set_caption("Hexcrawler Phase 5A Viewer")
        screen = pygame_module.display.set_mode(WINDOW_SIZE)
    except Exception as exc:
        print(
            "[hexcrawler.viewer] failed during pygame.display.set_mode(...): "
            f"{exc}. Hint: GUI sessions require a valid display; in CI/WSL/remote shells use --headless or HEXCRAWLER_HEADLESS=1.",
            file=sys.stderr,
        )
        pygame_module.quit()
        return 1

    driver_name = pygame_module.display.get_driver()
    print(f"[hexcrawler.viewer] display initialized: {driver_name}, window size={WINDOW_SIZE}")

    if headless:
        controller.tick_once()
        pygame_module.quit()
        return 0

    clock = pygame_module.time.Clock()
    font = pygame_module.font.SysFont("consolas", 22)
    debug_font = pygame_module.font.SysFont("consolas", 16)

    viewport_rect = _viewport_rect()
    world_center = (float(viewport_rect.centerx), float(viewport_rect.centery))
    panel_scroll = EncounterPanelScrollState()
    panel_section_rects: dict[str, pygame.Rect] = {}
    panel_section_counts: dict[str, int] = {}
    active_panel_section = "outcomes"

    accumulator = 0.0
    running = True
    context_menu: ContextMenuState | None = None
    previous_snapshot = extract_render_snapshot(sim)
    current_snapshot = previous_snapshot
    tick_duration_seconds = SIM_TICK_SECONDS
    last_tick_time = pygame_module.time.get_ticks() / 1000.0

    while running:
        dt = clock.tick(60) / 1000.0
        accumulator += dt

        for event in pygame_module.event.get():
            if event.type == pygame_module.QUIT:
                running = False
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_ESCAPE:
                running = False
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F5:
                _save_viewer_simulation(sim, save_path)
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F9:
                load_target = load_save if load_save else save_path
                if load_target and Path(load_target).exists():
                    try:
                        sim = _load_viewer_simulation(load_target, with_encounters=with_encounters)
                        controller.sim = sim
                        previous_snapshot = extract_render_snapshot(sim)
                        current_snapshot = previous_snapshot
                        last_tick_time = pygame_module.time.get_ticks() / 1000.0
                        context_menu = None
                    except Exception as exc:
                        print(f"[hexcrawler.viewer] load failed path={load_target}: {exc}", file=sys.stderr)
                else:
                    print(f"[hexcrawler.viewer] load skipped; file not found path={load_target}")
            elif event.type == pygame_module.KEYDOWN and event.key in (pygame_module.K_PAGEUP, pygame_module.K_PAGEDOWN):
                delta = -1 if event.key == pygame_module.K_PAGEUP else 1
                panel_scroll.scroll(
                    active_panel_section,
                    delta,
                    panel_section_counts.get(active_panel_section, 0),
                    ENCOUNTER_DEBUG_SECTION_ROWS,
                )
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button in (4, 5):
                if _panel_rect().collidepoint(event.pos):
                    for section_name, section_rect in panel_section_rects.items():
                        if section_rect.collidepoint(event.pos):
                            active_panel_section = section_name
                            panel_scroll.scroll(
                                section_name,
                                -1 if event.button == 4 else 1,
                                panel_section_counts.get(section_name, 0),
                                ENCOUNTER_DEBUG_SECTION_ROWS,
                            )
                            break
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 3:
                if not viewport_rect.collidepoint(event.pos):
                    context_menu = None
                    continue
                world_x, world_y = _pixel_to_world(event.pos[0], event.pos[1], world_center)
                target_hex = world_xy_to_axial(world_x, world_y)
                if sim.state.world.get_hex_record(target_hex) is None:
                    context_menu = None
                else:
                    context_menu = ContextMenuState(event.pos[0], event.pos[1], world_x, world_y)
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and context_menu is not None:
                menu_rect = pygame_module.Rect(context_menu.pixel_x, context_menu.pixel_y, 130, 34)
                if menu_rect.collidepoint(event.pos):
                    controller.set_target_world(context_menu.world_x, context_menu.world_y)
                context_menu = None

        move_x, move_y = _current_input_vector()
        controller.set_move_vector(move_x, move_y)

        while accumulator >= SIM_TICK_SECONDS:
            previous_snapshot = current_snapshot
            controller.tick_once()
            current_snapshot = extract_render_snapshot(sim)
            last_tick_time = pygame_module.time.get_ticks() / 1000.0
            accumulator -= SIM_TICK_SECONDS

        now_seconds = pygame_module.time.get_ticks() / 1000.0
        alpha = clamp01((now_seconds - last_tick_time) / tick_duration_seconds)

        screen.fill((17, 18, 25))
        _draw_world(screen, sim, world_center, clip_rect=viewport_rect)
        pygame.draw.rect(screen, (64, 68, 84), viewport_rect, 1)
        interpolated = interpolate_entity_position(previous_snapshot, current_snapshot, PLAYER_ID, alpha)
        if interpolated is not None:
            _draw_entity(screen, interpolated[0], interpolated[1], world_center, clip_rect=viewport_rect)
        _draw_hud(screen, sim, font)
        panel_section_rects, panel_section_counts = _draw_encounter_debug_panel(screen, sim, debug_font, panel_scroll)
        _draw_context_menu(screen, font, context_menu, viewport_rect)
        pygame_module.display.flip()

    pygame_module.quit()
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    headless = args.headless or _env_flag_enabled("HEXCRAWLER_HEADLESS")
    raise SystemExit(
        run_pygame_viewer(
            map_path=args.map_path,
            with_encounters=args.with_encounters,
            headless=headless,
            load_save=args.load_save,
            save_path=args.save_path,
        )
    )


if __name__ == "__main__":
    main()
