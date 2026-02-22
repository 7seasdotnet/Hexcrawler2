from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hexcrawler.content.encounters import DEFAULT_ENCOUNTER_TABLE_PATH, load_encounter_table_json
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    LocalEncounterInstanceModule,
    EncounterSelectionModule,
    RumorPipelineModule,
    SpawnMaterializationModule,
)
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.combat import CombatExecutionModule
from hexcrawler.sim.entity_stats import EntityStatsExecutionModule
from hexcrawler.sim.exploration import EXPLORATION_OUTCOME_EVENT_TYPE, ExplorationExecutionModule
from hexcrawler.sim.interactions import INTERACTION_OUTCOME_EVENT_TYPE, InteractionExecutionModule
from hexcrawler.sim.signals import SignalPropagationModule
from hexcrawler.sim.supplies import SUPPLY_OUTCOME_EVENT_TYPE, SupplyConsumptionModule
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
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
ENCOUNTER_DEBUG_SPAWN_LIMIT = 10
ENCOUNTER_DEBUG_OUTCOME_LIMIT = 20
ENCOUNTER_DEBUG_ENTITY_LIMIT = 20
ENCOUNTER_DEBUG_RUMOR_LIMIT = 20
SUPPLY_DEBUG_OUTCOME_LIMIT = 20
SITE_ENTER_DEBUG_OUTCOME_LIMIT = 20
ENCOUNTER_DEBUG_SECTION_ROWS = 6
PANEL_SECTION_ENTRY_LIMIT = 30
INVENTORY_DEBUG_LINES = 8
RECENT_SAVES_LIMIT = 8
CONTEXT_MENU_WIDTH = 260
CONTEXT_MENU_ROW_HEIGHT = 28
CONTEXT_MENU_TEXT_PADDING_X = 10
LOCAL_VIEWPORT_FILL_RATIO = 0.72

MARKER_SCATTER_RADIUS_MIN = 8.0
MARKER_SCATTER_RADIUS_MAX = 18.0
MARKER_SCATTER_STEP = 3.0
MARKER_SEPARATION_MIN = 11.0
MARKER_PLACEMENT_ATTEMPTS = 8

pygame: Any | None = None


PANEL_SECTION_ORDER: tuple[str, ...] = (
    "encounters",
    "outcomes",
    "rumors",
    "supplies",
    "sites",
    "entities",
)

PANEL_SECTION_TITLES: dict[str, str] = {
    "encounters": "Encounters",
    "outcomes": "Outcomes",
    "rumors": "Rumors",
    "supplies": "Supplies",
    "sites": "Sites",
    "entities": "Entities",
}

@dataclass(frozen=True)
class ContextMenuItem:
    label: str
    action: str
    payload: str | None = None


@dataclass
class ContextMenuState:
    pixel_x: int
    pixel_y: int
    items: tuple[ContextMenuItem, ...]


@dataclass
class EncounterPanelScrollState:
    offsets: dict[str, int] = field(default_factory=lambda: {section: 0 for section in PANEL_SECTION_ORDER})

    def offset_for(self, section: str) -> int:
        return self.offsets.get(section, 0)

    def scroll(self, section: str, delta: int, total_count: int, page_size: int) -> None:
        self.offsets[section] = _clamp_scroll_offset(self.offset_for(section), delta, total_count, page_size)


@dataclass
class LocalCameraCache:
    space_id: str | None = None
    viewport_size: tuple[int, int] = (0, 0)
    topology_params_signature: str | None = None
    center: tuple[float, float] = (0.0, 0.0)
    zoom_scale: float = 1.0


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

    def set_selected_entity(self, selected_entity_id: str) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="set_selected_entity",
                params={"selected_entity_id": selected_entity_id},
            )
        )

    def clear_selected_entity(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="clear_selected_entity",
                params={},
            )
        )

    def enter_site(self, site_id: str) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="enter_site",
                params={"site_id": site_id},
            )
        )

    def explore_intent(self, action: str, duration_ticks: int) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="explore_intent",
                params={"action": action, "duration_ticks": duration_ticks},
            )
        )

    def interaction_intent(self, interaction_type: str, target_kind: str, target_id: str, duration_ticks: int) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="interaction_intent",
                params={
                    "interaction_type": interaction_type,
                    "target": {"kind": target_kind, "id": target_id},
                    "duration_ticks": duration_ticks,
                },
            )
        )

    def end_local_encounter(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="end_local_encounter_intent",
                params={"entity_id": self.entity_id},
            )
        )

    def tick_once(self) -> None:
        self.sim.advance_ticks(1)


@dataclass(frozen=True)
class RenderEntitySnapshot:
    x: float
    y: float


RenderSnapshot = dict[str, RenderEntitySnapshot]


@dataclass(frozen=True)
class MarkerRecord:
    priority: int
    marker_id: str
    marker_kind: str
    color: tuple[int, int, int]
    radius: int
    label: str


@dataclass(frozen=True)
class MarkerCellRef:
    space_id: str
    topology_type: str
    coord_key: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class MarkerPlacement:
    marker: MarkerRecord
    x: int
    y: int


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


def _pixel_to_world(pixel_x: int, pixel_y: int, center: tuple[float, float], zoom_scale: float = 1.0) -> tuple[float, float]:
    size = HEX_SIZE * zoom_scale
    return ((pixel_x - center[0]) / size, (pixel_y - center[1]) / size)


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


def _local_space_square_bounds(active_space: Any) -> tuple[float, float, float, float] | None:
    if active_space is None or str(getattr(active_space, "role", "")) != "local":
        return None
    if getattr(active_space, "topology_type", None) != SQUARE_GRID_TOPOLOGY:
        return None
    params = getattr(active_space, "topology_params", None)
    if not isinstance(params, dict):
        return None
    width = params.get("width")
    height = params.get("height")
    origin = params.get("origin", {"x": 0, "y": 0})
    if not isinstance(origin, dict):
        return None
    try:
        width_i = int(width)
        height_i = int(height)
        origin_x = int(origin.get("x", 0))
        origin_y = int(origin.get("y", 0))
    except (TypeError, ValueError):
        return None
    if width_i <= 0 or height_i <= 0:
        return None
    return (float(origin_x), float(origin_y), float(width_i), float(height_i))


def _camera_center_and_zoom(sim: Simulation, viewport_rect: pygame.Rect) -> tuple[tuple[float, float], float]:
    center = (float(viewport_rect.centerx), float(viewport_rect.centery))
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    bounds = _local_space_square_bounds(active_space)
    if bounds is None:
        return center, 1.0
    origin_x, origin_y, width, height = bounds
    arena_center_x = origin_x + (width * 0.5)
    arena_center_y = origin_y + (height * 0.5)

    target_width_px = float(viewport_rect.width) * LOCAL_VIEWPORT_FILL_RATIO
    arena_width_px = width * HEX_SIZE
    if arena_width_px <= 0:
        return center, 1.0
    zoom_scale = max(1.0, min(target_width_px / arena_width_px, 2.0))
    center = (
        float(viewport_rect.centerx) - (arena_center_x * HEX_SIZE * zoom_scale),
        float(viewport_rect.centery) - (arena_center_y * HEX_SIZE * zoom_scale),
    )
    return center, zoom_scale


def _topology_params_signature(active_space: Any) -> str | None:
    if active_space is None:
        return None
    if str(getattr(active_space, "role", "")) != "local":
        return None
    if getattr(active_space, "topology_type", None) != SQUARE_GRID_TOPOLOGY:
        return None
    params = getattr(active_space, "topology_params", None)
    if not isinstance(params, dict):
        return None
    return json.dumps(params, sort_keys=True)


def _cached_camera_center_and_zoom(
    sim: Simulation,
    viewport_rect: pygame.Rect,
    cache: LocalCameraCache,
) -> tuple[tuple[float, float], float]:
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    active_space_id = active_space.space_id if active_space is not None else None
    topology_signature = _topology_params_signature(active_space)
    viewport_size = (int(viewport_rect.width), int(viewport_rect.height))
    if (
        cache.space_id != active_space_id
        or cache.viewport_size != viewport_size
        or cache.topology_params_signature != topology_signature
    ):
        center, zoom_scale = _camera_center_and_zoom(sim, viewport_rect)
        cache.space_id = active_space_id
        cache.viewport_size = viewport_size
        cache.topology_params_signature = topology_signature
        cache.center = center
        cache.zoom_scale = zoom_scale
    return cache.center, cache.zoom_scale




def _wrap_text_to_pixel_width(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    if max_width <= 0:
        return [text]
    words = text.split(" ")
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
            continue
        if font.size(current)[0] > max_width:
            lines.extend(_hard_wrap_text(current, font, max_width))
        else:
            lines.append(current)
        current = word
    if font.size(current)[0] > max_width:
        lines.extend(_hard_wrap_text(current, font, max_width))
    else:
        lines.append(current)
    return lines


def _hard_wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    if not text:
        return [""]
    rows: list[str] = []
    remaining = text
    while remaining:
        cut = len(remaining)
        while cut > 1 and font.size(remaining[:cut])[0] > max_width:
            cut -= 1
        rows.append(remaining[:cut])
        remaining = remaining[cut:]
    return rows


def _marker_cell_from_location(location: object, default_topology_type: str) -> MarkerCellRef | None:
    if not isinstance(location, dict):
        return None
    coord = location.get("coord")
    if not isinstance(coord, dict):
        return None
    topology_type = str(location.get("topology_type", default_topology_type))
    raw_space_id = location.get("space_id")
    space_id = raw_space_id if isinstance(raw_space_id, str) and raw_space_id.strip() else "overworld"
    if topology_type == OVERWORLD_HEX_TOPOLOGY:
        try:
            normalized = {"q": int(coord["q"]), "r": int(coord["r"])}
        except Exception:
            return None
    elif topology_type == SQUARE_GRID_TOPOLOGY:
        try:
            normalized = {"x": int(coord["x"]), "y": int(coord["y"])}
        except Exception:
            return None
    else:
        return None
    coord_key = tuple(sorted((axis, int(value)) for axis, value in normalized.items()))
    return MarkerCellRef(space_id=space_id, topology_type=topology_type, coord_key=coord_key)


def _is_in_current_space(obj_space_id: str | None, current_space_id: str) -> bool:
    if obj_space_id is None:
        return current_space_id == "overworld"
    return obj_space_id == current_space_id


def _entity_space_id(entity: EntityState) -> str | None:
    value = getattr(entity, "space_id", None)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _truncate_label(text: str, max_length: int = 10) -> str:
    normalized = text.strip()
    if not normalized:
        return "?"
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 1:
        return normalized[:max_length]
    return f"{normalized[: max_length - 1]}…"


def _short_stable_id(value: str, max_length: int = 10) -> str:
    return _truncate_label(value.split(":")[-1], max_length=max_length)


def _clamp_scroll_offset(current: int, delta: int, total_count: int, page_size: int) -> int:
    max_offset = max(0, total_count - page_size)
    return max(0, min(max_offset, current + delta))


def _section_entries(rows: list[str], *, entry_limit: int = PANEL_SECTION_ENTRY_LIMIT) -> list[str]:
    return list(reversed(rows[-entry_limit:]))


def _collect_world_markers(sim: Simulation, active_space_id: str, active_location_topology: str) -> dict[MarkerCellRef, list[MarkerRecord]]:
    markers_by_cell: dict[MarkerCellRef, list[MarkerRecord]] = {}

    def add_marker(cell: MarkerCellRef | None, marker: MarkerRecord) -> None:
        if cell is None or not _is_in_current_space(cell.space_id, active_space_id) or cell.topology_type != active_location_topology:
            return
        markers_by_cell.setdefault(cell, []).append(marker)

    for site in sorted(sim.state.world.sites.values(), key=lambda current: current.site_id):
        add_marker(
            _marker_cell_from_location(site.location, active_location_topology),
            MarkerRecord(
                priority=0,
                marker_id=f"site:{site.site_id}",
                marker_kind="site",
                color=SITE_COLORS.get(site.site_type, (245, 245, 120)),
                radius=6,
                label=_truncate_label(site.name if site.name else site.site_id, max_length=12),
            ),
        )

    space = sim.state.world.spaces.get(active_space_id)
    if space is not None:
        for door in sorted(space.doors.values(), key=lambda row: row.door_id):
            add_marker(
                _marker_cell_from_location(
                    {"space_id": active_space_id, "topology_type": space.topology_type, "coord": door.a},
                    active_location_topology,
                ),
                MarkerRecord(
                    priority=0,
                    marker_id=f"door:{door.door_id}",
                    marker_kind="door",
                    color=(220, 180, 80) if door.state == "closed" else (130, 210, 150),
                    radius=5,
                    label=_truncate_label(f"door:{door.state}", max_length=12),
                ),
            )
        for anchor in sorted(space.anchors.values(), key=lambda row: row.anchor_id):
            add_marker(
                _marker_cell_from_location(
                    {"space_id": active_space_id, "topology_type": space.topology_type, "coord": anchor.coord},
                    active_location_topology,
                ),
                MarkerRecord(
                    priority=0,
                    marker_id=f"anchor:{anchor.anchor_id}",
                    marker_kind="anchor",
                    color=(255, 120, 120),
                    radius=5,
                    label=_truncate_label(anchor.kind, max_length=12),
                ),
            )
        for interactable in sorted(space.interactables.values(), key=lambda row: row.interactable_id):
            add_marker(
                _marker_cell_from_location(
                    {"space_id": active_space_id, "topology_type": space.topology_type, "coord": interactable.coord},
                    active_location_topology,
                ),
                MarkerRecord(
                    priority=0,
                    marker_id=f"interactable:{interactable.interactable_id}",
                    marker_kind="interactable",
                    color=(170, 170, 255),
                    radius=5,
                    label=_truncate_label(interactable.kind, max_length=12),
                ),
            )

    for entity in sorted(sim.state.entities.values(), key=lambda current: current.entity_id):
        if entity.entity_id == PLAYER_ID or not entity.entity_id.startswith("spawn:"):
            continue
        entity_space_id = _entity_space_id(entity)
        if not _is_in_current_space(entity_space_id, active_space_id):
            continue
        label = entity.template_id if entity.template_id else _short_stable_id(entity.entity_id)
        if active_location_topology == SQUARE_GRID_TOPOLOGY:
            cell = MarkerCellRef(
                space_id=entity_space_id or "overworld",
                topology_type=active_location_topology,
                coord_key=(("x", math.floor(entity.position_x)), ("y", math.floor(entity.position_y))),
            )
        else:
            cell = MarkerCellRef(
                space_id=entity_space_id or "overworld",
                topology_type=active_location_topology,
                coord_key=(("q", entity.hex_coord.q), ("r", entity.hex_coord.r)),
            )
        add_marker(
            cell,
            MarkerRecord(
                priority=1,
                marker_id=f"entity:{entity.entity_id}",
                marker_kind="entity",
                color=(140, 225, 255),
                radius=5,
                label=_truncate_label(label),
            ),
        )

    for index, record in enumerate(sim.state.world.spawn_descriptors):
        action_uid = str(record.get("action_uid", "?"))
        add_marker(
            _marker_cell_from_location(record.get("location"), active_location_topology),
            MarkerRecord(
                priority=2,
                marker_id=f"spawn_desc:{action_uid}:{index}",
                marker_kind="spawn_desc",
                color=(96, 198, 255),
                radius=4,
                label="spawn",
            ),
        )

    for record in sim.state.world.signals:
        add_marker(
            _marker_cell_from_location(record.get("location"), active_location_topology),
            MarkerRecord(
                priority=3,
                marker_id=f"signal:{record.get('signal_uid', '')}",
                marker_kind="signal",
                color=(255, 202, 96),
                radius=4,
                label=_truncate_label(str(record.get("template_id", "sig")) if record.get("template_id") else "sig"),
            ),
        )

    for record in sim.state.world.tracks:
        add_marker(
            _marker_cell_from_location(record.get("location"), active_location_topology),
            MarkerRecord(
                priority=4,
                marker_id=f"track:{record.get('track_uid', '')}",
                marker_kind="track",
                color=(205, 183, 255),
                radius=3,
                label=_truncate_label(str(record.get("template_id", "trk")) if record.get("template_id") else "trk"),
            ),
        )

    for cell, markers in markers_by_cell.items():
        markers.sort(key=lambda row: (row.priority, row.marker_id))
    return markers_by_cell
def _marker_cell_center(cell: MarkerCellRef, center: tuple[float, float], zoom_scale: float = 1.0) -> tuple[float, float]:
    size = HEX_SIZE * zoom_scale
    if cell.topology_type == SQUARE_GRID_TOPOLOGY:
        world_x = float(dict(cell.coord_key)["x"]) + 0.5
        world_y = float(dict(cell.coord_key)["y"]) + 0.5
        return center[0] + world_x * size, center[1] + world_y * size
    return _axial_to_pixel(HexCoord(q=dict(cell.coord_key)["q"], r=dict(cell.coord_key)["r"]), center)


def _placement_signature(cell: MarkerCellRef, marker: MarkerRecord) -> str:
    return "|".join(
        [
            cell.space_id,
            cell.topology_type,
            repr(cell.coord_key),
            marker.marker_id,
            marker.marker_kind,
        ]
    )


def _stable_unit_pair(signature: str, attempt: int) -> tuple[float, float]:
    digest = hashlib.sha256(f"{signature}:{attempt}".encode("utf-8")).digest()
    angle_u = int.from_bytes(digest[:8], "big") / float(2**64)
    radius_u = int.from_bytes(digest[8:16], "big") / float(2**64)
    return angle_u, radius_u


def _slot_markers_for_hex(center_x: float, center_y: float, markers: list[MarkerRecord], cell: MarkerCellRef) -> tuple[list[MarkerPlacement], int]:
    placements: list[MarkerPlacement] = []
    for marker in markers:
        signature = _placement_signature(cell, marker)
        chosen_point: tuple[float, float] | None = None
        for attempt in range(MARKER_PLACEMENT_ATTEMPTS):
            angle_u, radius_u = _stable_unit_pair(signature, attempt)
            angle = angle_u * math.tau
            radius = MARKER_SCATTER_RADIUS_MIN + (MARKER_SCATTER_RADIUS_MAX - MARKER_SCATTER_RADIUS_MIN) * radius_u + (
                attempt * MARKER_SCATTER_STEP
            )
            radius = min(radius, MARKER_SCATTER_RADIUS_MAX + (MARKER_PLACEMENT_ATTEMPTS * MARKER_SCATTER_STEP))
            candidate = (center_x + math.cos(angle) * radius, center_y + math.sin(angle) * radius)
            if all((candidate[0] - current.x) ** 2 + (candidate[1] - current.y) ** 2 >= MARKER_SEPARATION_MIN**2 for current in placements):
                chosen_point = candidate
                break
        if chosen_point is None:
            fallback_index = len(placements)
            angle = fallback_index * 2.399963229728653
            radius = MARKER_SCATTER_RADIUS_MIN + fallback_index * MARKER_SCATTER_STEP
            chosen_point = (center_x + math.cos(angle) * radius, center_y + math.sin(angle) * radius)
        placements.append(MarkerPlacement(marker=marker, x=int(round(chosen_point[0])), y=int(round(chosen_point[1]))))
    return placements, 0


def _world_marker_placements(sim: Simulation, center: tuple[float, float], zoom_scale: float = 1.0) -> list[MarkerPlacement]:
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    if active_space is None:
        return []
    placements: list[MarkerPlacement] = []
    markers_by_cell = _collect_world_markers(
        sim,
        active_space.space_id,
        SQUARE_GRID_TOPOLOGY if active_space.topology_type == SQUARE_GRID_TOPOLOGY else OVERWORLD_HEX_TOPOLOGY,
    )
    for cell in sorted(markers_by_cell, key=lambda current: (current.space_id, current.topology_type, current.coord_key)):
        center_x, center_y = _marker_cell_center(cell, center, zoom_scale)
        slotted, _ = _slot_markers_for_hex(center_x, center_y, markers_by_cell[cell], cell)
        placements.extend(slotted)
    return placements


def _draw_world_markers(
    screen: pygame.Surface,
    sim: Simulation,
    center: tuple[float, float],
    font: pygame.font.Font,
    zoom_scale: float = 1.0,
) -> None:
    for placement in _world_marker_placements(sim, center, zoom_scale):
        pygame.draw.circle(screen, placement.marker.color, (placement.x, placement.y), placement.marker.radius)
        pygame.draw.circle(screen, (14, 24, 30), (placement.x, placement.y), placement.marker.radius, 1)
        label_surface = font.render(placement.marker.label, True, (248, 250, 255))
        outline_surface = font.render(placement.marker.label, True, (18, 20, 25))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            screen.blit(outline_surface, (placement.x + 8 + dx, placement.y - 8 + dy))
        screen.blit(label_surface, (placement.x + 8, placement.y - 8))


def _draw_world(
    screen: pygame.Surface,
    sim: Simulation,
    center: tuple[float, float],
    marker_font: pygame.font.Font,
    *,
    clip_rect: pygame.Rect,
    zoom_scale: float = 1.0,
) -> None:
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    if active_space is not None and active_space.topology_type == SQUARE_GRID_TOPOLOGY:
        cell_size = HEX_SIZE * zoom_scale
        for coord in active_space.iter_cells():
            world_x = float(coord["x"]) + 0.5
            world_y = float(coord["y"]) + 0.5
            pixel_x = center[0] + world_x * cell_size
            pixel_y = center[1] + world_y * cell_size
            rect = pygame.Rect(int(pixel_x - cell_size / 2), int(pixel_y - cell_size / 2), int(cell_size), int(cell_size))
            pygame.draw.rect(screen, (58, 58, 64), rect)
            pygame.draw.rect(screen, (35, 35, 40), rect, 1)
        _draw_world_markers(screen, sim, center, marker_font, zoom_scale)
        screen.set_clip(old_clip)
        return

    for coord in _grid_coords(GRID_RADIUS):
        pixel = _axial_to_pixel(coord, center)
        points = _hex_points(pixel)

        record = sim.state.world.get_hex_record(coord)
        terrain_type = record.terrain_type if record else "void"
        terrain_color = TERRAIN_COLORS.get(terrain_type, (90, 90, 96))
        pygame.draw.polygon(screen, terrain_color, points)
        pygame.draw.polygon(screen, (35, 35, 40), points, 1)

    if active_space is None or active_space.topology_type == OVERWORLD_HEX_TOPOLOGY:
        _draw_world_markers(screen, sim, center, marker_font, zoom_scale)
    screen.set_clip(old_clip)


def _draw_entity(
    screen: pygame.Surface,
    world_x: float,
    world_y: float,
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    clip_rect: pygame.Rect,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    size = HEX_SIZE * zoom_scale
    x = int(center[0] + world_x * size)
    y = int(center[1] + world_y * size)
    pygame.draw.circle(screen, (255, 243, 130), (x, y), 8)
    pygame.draw.circle(screen, (15, 15, 15), (x, y), 8, 1)
    screen.set_clip(old_clip)




def _draw_spawned_entity(
    screen: pygame.Surface,
    world_x: float,
    world_y: float,
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    clip_rect: pygame.Rect,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    size = HEX_SIZE * zoom_scale
    x = int(center[0] + world_x * size)
    y = int(center[1] + world_y * size)
    pygame.draw.circle(screen, (140, 225, 255), (x, y), 5)
    pygame.draw.circle(screen, (14, 24, 30), (x, y), 5, 1)
    screen.set_clip(old_clip)


def _draw_hud(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    status_message: str | None,
    hover_message: str | None,
) -> None:
    entity = sim.state.entities[PLAYER_ID]
    active_space = sim.state.world.spaces.get(entity.space_id)
    if active_space is not None and active_space.topology_type == SQUARE_GRID_TOPOLOGY:
        coord_text = f"x={math.floor(entity.position_x)},y={math.floor(entity.position_y)}"
    else:
        coord_text = f"q={entity.hex_coord.q},r={entity.hex_coord.r}"
    ticks_per_day = sim.get_ticks_per_day()
    day_display = sim.get_day_index() + 1
    tick_in_day = sim.get_tick_in_day()
    hours = (tick_in_day * 24) // ticks_per_day
    minutes = ((tick_in_day * 24 * 60) // ticks_per_day) % 60
    context_line = (
        f"space={entity.space_id} | {coord_text} | tick={sim.state.tick} | "
        f"day={day_display} | time={hours:02d}:{minutes:02d}"
    )
    lines = [
        context_line,
        "WASD move | RMB menu | F3 arena overlay | F5 save | F9 load | ESC quit",
    ]
    if status_message:
        lines.append(f"status: {status_message}")
    if hover_message:
        lines.append(hover_message)
    y = 12
    for line in lines:
        surface = font.render(line, True, (240, 240, 240))
        screen.blit(surface, (12, y))
        y += 24


def _active_local_arena_template_id(sim: Simulation, active_space_id: str, active_space: Any) -> str:
    if isinstance(getattr(active_space, "metadata", None), dict):
        value = active_space.metadata.get("template_id")
        if isinstance(value, str) and value:
            return value
    local_encounter_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    if isinstance(local_encounter_state, dict):
        applied = local_encounter_state.get("applied_template_by_local_space")
        if isinstance(applied, dict):
            value = applied.get(active_space_id)
            if isinstance(value, str) and value:
                return value
    return "unknown"


def _get_return_context_for_space(sim: Simulation, local_space_id: str) -> dict[str, Any] | None:
    local_encounter_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    if not isinstance(local_encounter_state, dict):
        return None
    active_by_local_space = local_encounter_state.get("active_by_local_space")
    if not isinstance(active_by_local_space, dict):
        return None
    context = active_by_local_space.get(local_space_id)
    if not isinstance(context, dict):
        return None
    if not isinstance(context.get("from_space_id"), str) or not context.get("from_space_id"):
        return None
    return context


def _is_return_in_progress(sim: Simulation, local_space_id: str) -> bool:
    local_encounter_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    if not isinstance(local_encounter_state, dict):
        return False
    in_progress_by_local_space = local_encounter_state.get("return_in_progress_by_local_space")
    if not isinstance(in_progress_by_local_space, dict):
        return False
    return bool(in_progress_by_local_space.get(local_space_id, False))


def _draw_local_arena_overlay(
    screen: pygame.Surface,
    sim: Simulation,
    center: tuple[float, float],
    font: pygame.font.Font,
    zoom_scale: float = 1.0,
    *,
    clip_rect: pygame.Rect,
) -> None:
    entity = sim.state.entities.get(PLAYER_ID)
    if entity is None:
        return
    active_space = sim.state.world.spaces.get(entity.space_id)
    if active_space is None:
        return
    role = str(getattr(active_space, "role", "unknown"))
    lines = [f"arena_overlay: ON | space_id={active_space.space_id} | role={role}"]

    local_encounter_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    active_context = None
    if isinstance(local_encounter_state, dict):
        active_by_local_space = local_encounter_state.get("active_by_local_space")
        if isinstance(active_by_local_space, dict):
            context = active_by_local_space.get(active_space.space_id)
            if isinstance(context, dict):
                active_context = context

    if role == "local":
        lines.append(f"template_id={_active_local_arena_template_id(sim, active_space.space_id, active_space)}")
    if isinstance(active_context, dict):
        request_event_id = active_context.get("request_event_id")
        from_space_id = active_context.get("from_space_id")
        if isinstance(request_event_id, str) and request_event_id:
            lines.append(f"request_event_id={request_event_id}")
        if isinstance(from_space_id, str) and from_space_id:
            lines.append(f"origin_from_space_id={from_space_id}")

    if active_space.topology_type != SQUARE_GRID_TOPOLOGY:
        lines.append(f"Local arena overlay unsupported for topology_type={active_space.topology_type}")
    else:
        old_clip = screen.get_clip()
        screen.set_clip(clip_rect)
        cell_size = HEX_SIZE * zoom_scale
        for anchor in sorted(active_space.anchors.values(), key=lambda row: row.anchor_id):
            anchor_x = center[0] + (float(anchor.coord["x"]) + 0.5) * cell_size
            anchor_y = center[1] + (float(anchor.coord["y"]) + 0.5) * cell_size
            pygame.draw.circle(screen, (255, 122, 122), (int(anchor_x), int(anchor_y)), 4)
            label = font.render(f"a:{anchor.anchor_id}", True, (255, 230, 230))
            screen.blit(label, (int(anchor_x) + 6, int(anchor_y) - 10))
        for door in sorted(active_space.doors.values(), key=lambda row: row.door_id):
            door_x = center[0] + (float(door.a["x"]) + 0.5) * cell_size
            door_y = center[1] + (float(door.a["y"]) + 0.5) * cell_size
            pygame.draw.rect(screen, (255, 214, 116), (int(door_x) - 3, int(door_y) - 3, 7, 7))
            label = font.render(f"d:{door.door_id} ({door.state})", True, (255, 240, 214))
            screen.blit(label, (int(door_x) + 6, int(door_y) - 10))
        for interactable in sorted(active_space.interactables.values(), key=lambda row: row.interactable_id):
            obj_x = center[0] + (float(interactable.coord["x"]) + 0.5) * cell_size
            obj_y = center[1] + (float(interactable.coord["y"]) + 0.5) * cell_size
            pygame.draw.circle(screen, (175, 175, 255), (int(obj_x), int(obj_y)), 3)
            label = font.render(f"i:{interactable.interactable_id}", True, (230, 230, 255))
            screen.blit(label, (int(obj_x) + 6, int(obj_y) - 10))
        screen.set_clip(old_clip)

    y = 94
    for line in lines:
        screen.blit(font.render(line, True, (240, 240, 240)), (12, y))
        y += 18


def _format_location(location: object) -> str:
    if not isinstance(location, dict):
        return "loc=?"
    topology = str(location.get("topology_type", "?"))
    coord = location.get("coord")
    if isinstance(coord, dict):
        if "q" in coord and "r" in coord:
            return f"{topology}:{coord.get('q')},{coord.get('r')}"
        if "x" in coord and "y" in coord:
            return f"{topology}:{coord.get('x')},{coord.get('y')}"
    return f"{topology}:?"




def _entity_location_text(sim: Simulation, entity: EntityState) -> str:
    space = sim.state.world.spaces.get(entity.space_id)
    if space is not None and space.topology_type == SQUARE_GRID_TOPOLOGY:
        return f"square_grid:{math.floor(entity.position_x)},{math.floor(entity.position_y)}"
    return f"overworld_hex:{entity.hex_coord.q},{entity.hex_coord.r}"

def _draw_encounter_debug_panel(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    scroll_state: EncounterPanelScrollState,
    active_section: str,
) -> tuple[dict[str, pygame.Rect], dict[str, int]]:
    panel_rect = _panel_rect()
    pygame.draw.rect(screen, (24, 26, 36), panel_rect)
    pygame.draw.rect(screen, (95, 98, 110), panel_rect, 1)

    selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
    spawned_entities = [
        entity for entity in sorted(sim.state.entities.values(), key=lambda current: current.entity_id)
        if entity.entity_id != PLAYER_ID and entity.entity_id.startswith("spawn:")
    ]
    recent_signals = _section_entries([
        (
            f"tick={record.get('created_tick', '?')} template={record.get('template_id', '?')} "
            f"loc={_format_location(record.get('location'))} expires={record.get('expires_tick', '-') if record.get('expires_tick') is not None else '-'}"
        )
        for record in sim.state.world.signals
    ])
    recent_tracks = _section_entries([
        (
            f"tick={record.get('created_tick', '?')} template={record.get('template_id', '?')} "
            f"loc={_format_location(record.get('location'))} expires={record.get('expires_tick', '-') if record.get('expires_tick') is not None else '-'}"
        )
        for record in sim.state.world.tracks
    ])
    recent_spawns = _section_entries([
        (
            f"tick={record.get('created_tick', '?')} template={record.get('template_id', '?')} "
            f"qty={record.get('quantity', '?')} loc={_format_location(record.get('location'))}"
        )
        for record in sim.state.world.spawn_descriptors
    ])
    encounter_rows = recent_signals + recent_tracks + recent_spawns

    filtered_trace = [
        entry
        for entry in sim.get_event_trace()
        if entry.get("event_type") in {ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE, EXPLORATION_OUTCOME_EVENT_TYPE, INTERACTION_OUTCOME_EVENT_TYPE}
    ]
    outcome_rows = _section_entries([
        (
            f"tick={entry.get('tick', '?')} action_uid={params.get('action_uid', '?')} action={params.get('action_type', params.get('action', '?'))} "
            f"outcome={params.get('outcome', '?')} template={params.get('template_id', '-') or '-'}"
        )
        for entry in filtered_trace
        for params in [entry.get("params") if isinstance(entry.get("params"), dict) else {}]
    ])
    rumor_rows = _section_entries([
        (
            f"rumor_id={record.get('rumor_id', '?')} hop={record.get('hop', '?')} confidence={record.get('confidence', '?')} "
            f"loc={_format_location(record.get('location'))} template={record.get('template_id', '?')}"
        )
        for record in sim.state.world.rumors
    ])
    supply_outcomes = [entry for entry in sim.get_event_trace() if entry.get("event_type") == SUPPLY_OUTCOME_EVENT_TYPE]
    supply_rows = _section_entries([
        (
            f"tick={entry.get('tick', '?')} entity={params.get('entity_id', '?')} item={params.get('item_id', '?')} "
            f"qty={params.get('quantity', '?')} remaining={params.get('remaining_quantity', '-')} outcome={params.get('outcome', '?')}"
        )
        for entry in supply_outcomes
        for params in [entry.get("params") if isinstance(entry.get("params"), dict) else {}]
    ])
    site_rows: list[str] = []
    player = sim.state.entities.get(PLAYER_ID)
    if player is not None:
        coord = {"x": math.floor(player.position_x), "y": math.floor(player.position_y)}
        if sim.state.world.spaces.get(player.space_id) is None or sim.state.world.spaces[player.space_id].topology_type == OVERWORLD_HEX_TOPOLOGY:
            coord = player.hex_coord.to_dict()
        for site in sim.state.world.get_sites_at_location({"space_id": player.space_id, "coord": coord}):
            site_rows.append(f"site_id={site.site_id} type={site.site_type} entrance={'yes' if site.entrance else 'no'}")
    site_rows = _section_entries(site_rows)
    entity_rows = _section_entries([
        (
            f"entity_id={entity.entity_id} template={entity.template_id if entity.template_id else '-'} "
            f"loc={_entity_location_text(sim, entity)} action_uid={entity.source_action_uid if entity.source_action_uid else '-'}"
        )
        for entity in spawned_entities
    ])

    rows_by_section = {
        "encounters": encounter_rows,
        "outcomes": outcome_rows,
        "rumors": rumor_rows,
        "supplies": supply_rows,
        "sites": site_rows,
        "entities": entity_rows,
    }

    section_rects: dict[str, pygame.Rect] = {}
    section_counts = {section: len(rows) for section, rows in rows_by_section.items()}

    y = panel_rect.y + 8
    title = font.render("Encounter Debug | Site=S Spawn=E Desc=D Signal=G Track=T Door/Anchor/Int", True, (245, 245, 245))
    screen.blit(title, (panel_rect.x + 10, y))
    y += 18

    tab_x = panel_rect.x + 10
    for section in PANEL_SECTION_ORDER:
        tab_label = PANEL_SECTION_TITLES[section]
        color = (70, 100, 160) if section == active_section else (50, 54, 70)
        tab_surface = font.render(tab_label, True, (235, 235, 240))
        tab_rect = pygame.Rect(tab_x, y, tab_surface.get_width() + 12, 20)
        pygame.draw.rect(screen, color, tab_rect)
        pygame.draw.rect(screen, (110, 115, 135), tab_rect, 1)
        screen.blit(tab_surface, (tab_rect.x + 6, tab_rect.y + 2))
        section_rects[section] = tab_rect
        tab_x += tab_rect.width + 6
    y += 26

    section_rows = rows_by_section.get(active_section, [])
    offset = scroll_state.offset_for(active_section)
    visible_rows = section_rows[offset : offset + ENCOUNTER_DEBUG_SECTION_ROWS]
    header_line = font.render(
        f"{PANEL_SECTION_TITLES.get(active_section, active_section)} ({len(section_rows)}) [{offset + 1 if section_rows else 0}-{min(len(section_rows), offset + ENCOUNTER_DEBUG_SECTION_ROWS)}]",
        True,
        (245, 245, 245),
    )
    screen.blit(header_line, (panel_rect.x + 10, y))
    y += 18
    row_area_top = y
    row_area_bottom = panel_rect.bottom - 10
    if not visible_rows:
        screen.blit(font.render("  none", True, (205, 205, 210)), (panel_rect.x + 10, y))
    for row in visible_rows:
        wrapped = _wrap_text_to_pixel_width(f"  {row}", font, panel_rect.width - 24)
        for wrapped_row in wrapped:
            if y > row_area_bottom:
                break
            screen.blit(font.render(wrapped_row, True, (205, 205, 210)), (panel_rect.x + 10, y))
            y += 16
        if y > row_area_bottom:
            break
    section_rects["rows"] = pygame.Rect(panel_rect.x + 6, row_area_top, panel_rect.width - 12, max(1, row_area_bottom - row_area_top))

    if selected_entity_id is not None:
        selected_surface = font.render(f"selected={selected_entity_id}", True, (185, 215, 185))
        screen.blit(selected_surface, (panel_rect.x + 10, panel_rect.bottom - 24))
    return section_rects, section_counts


def _context_menu_rect(menu_state: ContextMenuState, viewport_rect: pygame.Rect) -> pygame.Rect:
    height = max(1, len(menu_state.items)) * CONTEXT_MENU_ROW_HEIGHT
    menu_rect = pygame.Rect(menu_state.pixel_x, menu_state.pixel_y, CONTEXT_MENU_WIDTH, height)
    menu_rect.clamp_ip(viewport_rect)
    return menu_rect


def _draw_context_menu(
    screen: pygame.Surface,
    font: pygame.font.Font,
    menu_state: ContextMenuState | None,
    viewport_rect: pygame.Rect,
) -> pygame.Rect | None:
    if menu_state is None:
        return None

    menu_rect = _context_menu_rect(menu_state, viewport_rect)
    pygame.draw.rect(screen, (32, 34, 44), menu_rect)
    pygame.draw.rect(screen, (185, 185, 200), menu_rect, 1)

    for index, item in enumerate(menu_state.items):
        row_rect = pygame.Rect(menu_rect.x, menu_rect.y + (index * CONTEXT_MENU_ROW_HEIGHT), menu_rect.width, CONTEXT_MENU_ROW_HEIGHT)
        pygame.draw.line(screen, (64, 68, 84), (row_rect.x, row_rect.bottom), (row_rect.right, row_rect.bottom), 1)
        max_label_width = menu_rect.width - (2 * CONTEXT_MENU_TEXT_PADDING_X)
        label_text = _truncate_text_to_pixel_width(item.label, font, max_label_width)
        label = font.render(label_text, True, (245, 245, 245))
        screen.blit(label, (row_rect.x + CONTEXT_MENU_TEXT_PADDING_X, row_rect.y + 5))
    return menu_rect


def _truncate_text_to_pixel_width(text: str, font: Any, max_width: int) -> str:
    normalized = text.strip() if isinstance(text, str) else ""
    if not normalized:
        return "?"
    if max_width <= 0:
        return "..."
    if font.size(normalized)[0] <= max_width:
        return normalized
    ellipsis = "..."
    if font.size(ellipsis)[0] > max_width:
        return ellipsis
    limit = len(normalized)
    while limit > 0:
        candidate = f"{normalized[:limit]}{ellipsis}"
        if font.size(candidate)[0] <= max_width:
            return candidate
        limit -= 1
    return ellipsis


def _world_to_pixel(world_x: float, world_y: float, center: tuple[float, float], zoom_scale: float = 1.0) -> tuple[float, float]:
    size = HEX_SIZE * zoom_scale
    return (center[0] + world_x * size, center[1] + world_y * size)


def _find_entity_at_pixel(
    sim: Simulation,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 10.0,
) -> str | None:
    player = sim.state.entities.get(PLAYER_ID)
    current_space_id = _entity_space_id(player) if player is not None else "overworld"
    if current_space_id is None:
        current_space_id = "overworld"
    candidates: list[tuple[float, str]] = []
    for entity in sorted(sim.state.entities.values(), key=lambda current: current.entity_id):
        if not _is_in_current_space(_entity_space_id(entity), current_space_id):
            continue
        px, py = _world_to_pixel(entity.position_x, entity.position_y, center, zoom_scale)
        dx = pixel_pos[0] - px
        dy = pixel_pos[1] - py
        distance_sq = (dx * dx) + (dy * dy)
        if distance_sq <= radius_px * radius_px:
            candidates.append((distance_sq, entity.entity_id))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][1]




def _find_world_marker_candidates_at_pixel(
    sim: Simulation,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 10.0,
) -> list[MarkerRecord]:
    candidates: list[tuple[float, str, MarkerRecord]] = []
    for placement in _world_marker_placements(sim, center, zoom_scale):
        dx = pixel_pos[0] - placement.x
        dy = pixel_pos[1] - placement.y
        distance_sq = (dx * dx) + (dy * dy)
        hit_radius = max(radius_px, float(placement.marker.radius + 2))
        if distance_sq <= hit_radius * hit_radius:
            candidates.append((distance_sq, placement.marker.marker_id, placement.marker))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in candidates]


def _find_world_marker_at_pixel(
    sim: Simulation,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 10.0,
) -> MarkerRecord | None:
    candidates = _find_world_marker_candidates_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=radius_px)
    if not candidates:
        return None
    return candidates[0]


def _hover_readout(sim: Simulation, pixel_pos: tuple[int, int], center: tuple[float, float], zoom_scale: float = 1.0) -> str | None:
    marker = _find_world_marker_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=12.0)
    player = sim.state.entities.get(PLAYER_ID)
    current_space_id = _entity_space_id(player) if player is not None else "overworld"
    if current_space_id is None:
        current_space_id = "overworld"
    if marker is not None:
        return f"hover: kind={marker.marker_kind} id={marker.marker_id} space_id={current_space_id}"
    entity_id = _find_entity_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=12.0)
    if entity_id is None:
        return None
    entity = sim.state.entities.get(entity_id)
    if entity is None:
        return None
    template = entity.template_id if entity.template_id else "unknown"
    entity_space_id = _entity_space_id(entity) or "overworld"
    return f"hover: kind=entity id={entity.entity_id} template={template} space_id={entity_space_id}"


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
        default="content/examples/viewer_map.json",
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




def _register_supply_module(sim: Simulation) -> None:
    if sim.get_rule_module(SupplyConsumptionModule.name) is not None:
        return
    sim.register_rule_module(SupplyConsumptionModule())




def _register_combat_module(sim: Simulation) -> None:
    if sim.get_rule_module(CombatExecutionModule.name) is not None:
        return
    sim.register_rule_module(CombatExecutionModule())

def _register_entity_stats_module(sim: Simulation) -> None:
    if sim.get_rule_module(EntityStatsExecutionModule.name) is not None:
        return
    sim.register_rule_module(EntityStatsExecutionModule())

def _register_exploration_module(sim: Simulation) -> None:
    if sim.get_rule_module(ExplorationExecutionModule.name) is not None:
        return
    sim.register_rule_module(ExplorationExecutionModule())


def _register_interaction_module(sim: Simulation) -> None:
    if sim.get_rule_module(InteractionExecutionModule.name) is not None:
        return
    sim.register_rule_module(InteractionExecutionModule())


def _register_signal_module(sim: Simulation) -> None:
    if sim.get_rule_module(SignalPropagationModule.name) is not None:
        return
    sim.register_rule_module(SignalPropagationModule())


def _register_encounter_modules(sim: Simulation) -> None:
    if sim.get_rule_module(EncounterCheckModule.name) is not None:
        return
    sim.register_rule_module(EncounterCheckModule())
    sim.register_rule_module(EncounterSelectionModule(load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)))
    sim.register_rule_module(EncounterActionModule())
    sim.register_rule_module(EncounterActionExecutionModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(RumorPipelineModule())
    sim.register_rule_module(SpawnMaterializationModule())


def _build_viewer_simulation(map_path: str, *, with_encounters: bool) -> Simulation:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=7)
    if with_encounters:
        _register_encounter_modules(sim)
    sim.add_entity(EntityState.from_hex(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    _register_exploration_module(sim)
    _register_interaction_module(sim)
    _register_signal_module(sim)
    _register_entity_stats_module(sim)
    _register_combat_module(sim)
    _register_supply_module(sim)
    return sim


def _load_viewer_simulation(save_path: str, *, with_encounters: bool) -> Simulation:
    _, sim = load_game_json(save_path)
    should_enable_encounters = with_encounters or EncounterCheckModule.name in sim.state.rules_state
    if should_enable_encounters:
        _register_encounter_modules(sim)
    if PLAYER_ID not in sim.state.entities:
        sim.add_entity(EntityState.from_hex(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    _register_exploration_module(sim)
    _register_interaction_module(sim)
    _register_signal_module(sim)
    _register_entity_stats_module(sim)
    _register_combat_module(sim)
    if SupplyConsumptionModule.name in sim.state.rules_state or PLAYER_ID in sim.state.entities:
        _register_supply_module(sim)
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
    map_path: str = "content/examples/viewer_map.json",
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
        pygame_module.display.set_caption("Hexcrawler Phase 5G Viewer")
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

    def push_recent_save(path_value: str | None) -> None:
        if not path_value:
            return
        normalized = str(Path(path_value))
        if normalized in recent_saves:
            recent_saves.remove(normalized)
        recent_saves.insert(0, normalized)
        del recent_saves[RECENT_SAVES_LIMIT:]

    def load_simulation_from_path(path_value: str) -> bool:
        nonlocal sim, context_menu, previous_snapshot, current_snapshot, last_tick_time, status_message
        try:
            sim = _load_viewer_simulation(path_value, with_encounters=with_encounters)
            controller.sim = sim
            previous_snapshot = extract_render_snapshot(sim)
            current_snapshot = previous_snapshot
            last_tick_time = pygame_module.time.get_ticks() / 1000.0
            context_menu = None
            push_recent_save(path_value)
            status_message = f"loaded {path_value}"
            return True
        except Exception as exc:
            status_message = f"load failed: {exc}"
            print(f"[hexcrawler.viewer] load failed path={path_value}: {exc}", file=sys.stderr)
            return False

    def build_recent_save_items() -> list[ContextMenuItem]:
        if not recent_saves:
            return [ContextMenuItem(label="Load recent save... (none)", action="noop")]
        return [
            ContextMenuItem(label=f"Load recent: {Path(path_value).name}", action="load_recent", payload=path_value)
            for path_value in recent_saves
        ]

    def build_context_menu(event_pos: tuple[int, int]) -> ContextMenuState | None:
        items: list[ContextMenuItem] = []
        player = sim.state.entities.get(PLAYER_ID)
        active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
        if viewport_rect.collidepoint(event_pos):
            markers = _find_world_marker_candidates_at_pixel(sim, event_pos, world_center, world_zoom_scale)
            if markers:
                for marker in markers:
                    items.append(ContextMenuItem(label=f"Marker: {marker.marker_kind} {marker.label}", action="noop"))
                    if marker.marker_kind == "entity":
                        entity_id = marker.marker_id.split(":", 1)[1]
                        items.append(ContextMenuItem(label=f"Select {marker.label}", action="select", payload=entity_id))
                        if sim.selected_entity_id(owner_entity_id=PLAYER_ID) == entity_id:
                            items.append(ContextMenuItem(label=f"Deselect {marker.label}", action="clear_selection"))
                    elif marker.marker_kind == "site":
                        site_id = marker.marker_id.split(":", 1)[1]
                        site = sim.state.world.sites.get(site_id)
                        if site is not None and site.entrance is not None:
                            site_label = site.name if site.name else site.site_id
                            items.append(ContextMenuItem(label=f"Enter {site_label}", action="enter_site", payload=site.site_id))
                    elif marker.marker_kind == "door":
                        door_id = marker.marker_id.split(":", 1)[1]
                        items.append(ContextMenuItem(label="Door...", action="noop"))
                        items.append(ContextMenuItem(label="- Open (10 ticks)", action="interaction", payload=f"open:door:{door_id}:10"))
                        items.append(ContextMenuItem(label="- Close (10 ticks)", action="interaction", payload=f"close:door:{door_id}:10"))
                        items.append(ContextMenuItem(label="- Toggle (10 ticks)", action="interaction", payload=f"toggle:door:{door_id}:10"))
                    elif marker.marker_kind == "anchor":
                        anchor_id = marker.marker_id.split(":", 1)[1]
                        items.append(ContextMenuItem(label="Exit (30 ticks)", action="interaction", payload=f"exit:anchor:{anchor_id}:30"))
                    elif marker.marker_kind == "interactable":
                        interactable_id = marker.marker_id.split(":", 1)[1]
                        items.append(ContextMenuItem(label="Interactable...", action="noop"))
                        items.append(ContextMenuItem(label="- Inspect (10 ticks)", action="interaction", payload=f"inspect:interactable:{interactable_id}:10"))
                        items.append(ContextMenuItem(label="- Use (20 ticks)", action="interaction", payload=f"use:interactable:{interactable_id}:20"))
                items.append(ContextMenuItem(label="Explore...", action="noop"))
                items.append(ContextMenuItem(label="- Search (60 ticks)", action="explore", payload="search:60"))
                items.append(ContextMenuItem(label="- Listen (30 ticks)", action="explore", payload="listen:30"))
                items.append(ContextMenuItem(label="- Rest (120 ticks)", action="explore", payload="rest:120"))
                items.append(ContextMenuItem(label="Clear selection", action="clear_selection"))
            else:
                world_x, world_y = _pixel_to_world(event_pos[0], event_pos[1], world_center, world_zoom_scale)
                target_hex = world_xy_to_axial(world_x, world_y)
                if sim.state.world.get_hex_record(target_hex) is not None:
                    items.append(ContextMenuItem(label="Move here", action="move_here", payload=f"{world_x},{world_y}"))
                    hex_sites = sim.state.world.get_sites_at_location({"space_id": "overworld", "coord": target_hex.to_dict()})
                    if hex_sites:
                        items.append(ContextMenuItem(label="Inspect Site...", action="noop"))
                        for site in hex_sites:
                            site_label = site.name if site.name else site.site_id
                            items.append(ContextMenuItem(label=f"- {site.site_id} ({site.site_type})", action="noop"))
                            if site.entrance is not None:
                                items.append(ContextMenuItem(label=f"Enter {site_label}", action="enter_site", payload=site.site_id))
                    items.append(ContextMenuItem(label="Explore...", action="noop"))
                    items.append(ContextMenuItem(label="- Search (60 ticks)", action="explore", payload="search:60"))
                    items.append(ContextMenuItem(label="- Listen (30 ticks)", action="explore", payload="listen:30"))
                    items.append(ContextMenuItem(label="- Rest (120 ticks)", action="explore", payload="rest:120"))
                    items.append(ContextMenuItem(label="Clear selection", action="clear_selection"))
        if active_space is not None and str(getattr(active_space, "role", "")) == "local":
            return_context = _get_return_context_for_space(sim, active_space.space_id)
            if return_context is None:
                items.append(ContextMenuItem(label="Return to origin (unavailable)", action="noop"))
                items.append(ContextMenuItem(label=f"No active return context for {active_space.space_id}", action="noop"))
            elif _is_return_in_progress(sim, active_space.space_id):
                items.append(ContextMenuItem(label="Returning…", action="noop"))
            else:
                from_space_id = str(return_context.get("from_space_id", "?"))
                detail_parts = [from_space_id]
                from_location = return_context.get("from_location")
                if isinstance(from_location, dict):
                    detail_parts.append(_format_location(from_location))
                request_event_id = return_context.get("request_event_id")
                if isinstance(request_event_id, str) and request_event_id:
                    detail_parts.append(f"req={request_event_id}")
                items.append(
                    ContextMenuItem(
                        label=f"Return to origin ({' | '.join(detail_parts)})",
                        action="return_to_origin",
                    )
                )
        items.extend(build_recent_save_items())
        if not items:
            return None
        return ContextMenuState(pixel_x=event_pos[0], pixel_y=event_pos[1], items=tuple(items))

    clock = pygame_module.time.Clock()
    font = pygame_module.font.SysFont("consolas", 22)
    debug_font = pygame_module.font.SysFont("consolas", 16)
    marker_font = pygame_module.font.SysFont("consolas", 13)

    viewport_rect = _viewport_rect()
    world_center = (float(viewport_rect.centerx), float(viewport_rect.centery))
    world_zoom_scale = 1.0
    local_camera_cache = LocalCameraCache(center=world_center, zoom_scale=world_zoom_scale)
    panel_scroll = EncounterPanelScrollState()
    panel_section_rects: dict[str, pygame.Rect] = {}
    panel_section_counts: dict[str, int] = {}
    active_panel_section = "encounters"
    show_local_arena_overlay = False

    accumulator = 0.0
    running = True
    context_menu: ContextMenuState | None = None
    previous_snapshot = extract_render_snapshot(sim)
    current_snapshot = previous_snapshot
    tick_duration_seconds = SIM_TICK_SECONDS
    last_tick_time = pygame_module.time.get_ticks() / 1000.0
    recent_saves: list[str] = []
    push_recent_save(save_path)
    push_recent_save(load_save)
    status_message: str | None = None

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
                push_recent_save(save_path)
                status_message = f"saved {save_path}"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F9:
                load_target = load_save if load_save else save_path
                if load_target and Path(load_target).exists():
                    load_simulation_from_path(load_target)
                else:
                    status_message = f"load failed: file not found ({load_target})"
                    print(f"[hexcrawler.viewer] load skipped; file not found path={load_target}")
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F3:
                show_local_arena_overlay = not show_local_arena_overlay
                status_message = f"local arena overlay {'on' if show_local_arena_overlay else 'off'}"
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
                    delta = -1 if event.button == 4 else 1
                    if panel_section_rects.get("rows") is not None and panel_section_rects["rows"].collidepoint(event.pos):
                        panel_scroll.scroll(
                            active_panel_section,
                            delta,
                            panel_section_counts.get(active_panel_section, 0),
                            ENCOUNTER_DEBUG_SECTION_ROWS,
                        )
                    else:
                        for section_name in PANEL_SECTION_ORDER:
                            section_rect = panel_section_rects.get(section_name)
                            if section_rect is not None and section_rect.collidepoint(event.pos):
                                active_panel_section = section_name
                                break
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and _panel_rect().collidepoint(event.pos):
                for section_name in PANEL_SECTION_ORDER:
                    section_rect = panel_section_rects.get(section_name)
                    if section_rect is not None and section_rect.collidepoint(event.pos):
                        active_panel_section = section_name
                        break
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 3:
                context_menu = build_context_menu(event.pos)
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and context_menu is not None:
                menu_rect = _context_menu_rect(context_menu, viewport_rect)
                if menu_rect.collidepoint(event.pos):
                    row_index = (event.pos[1] - menu_rect.y) // CONTEXT_MENU_ROW_HEIGHT
                    if 0 <= row_index < len(context_menu.items):
                        item = context_menu.items[row_index]
                        if item.action == "move_here" and item.payload is not None:
                            x_str, y_str = item.payload.split(",", 1)
                            controller.set_target_world(float(x_str), float(y_str))
                        elif item.action == "select" and item.payload is not None:
                            controller.set_selected_entity(item.payload)
                        elif item.action == "clear_selection":
                            controller.clear_selected_entity()
                        elif item.action == "load_recent" and item.payload is not None:
                            load_simulation_from_path(item.payload)
                        elif item.action == "enter_site" and item.payload is not None:
                            controller.enter_site(item.payload)
                        elif item.action == "explore" and item.payload is not None:
                            action, duration_str = item.payload.split(":", 1)
                            controller.explore_intent(action, int(duration_str))
                        elif item.action == "interaction" and item.payload is not None:
                            interaction_type, target_kind, target_id, duration_str = item.payload.split(":", 3)
                            controller.interaction_intent(interaction_type, target_kind, target_id, int(duration_str))
                        elif item.action == "return_to_origin":
                            controller.end_local_encounter()
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

        player = sim.state.entities.get(PLAYER_ID)
        current_space_id = _entity_space_id(player) if player is not None else "overworld"
        if current_space_id is None:
            current_space_id = "overworld"
        world_center, world_zoom_scale = _cached_camera_center_and_zoom(sim, viewport_rect, local_camera_cache)

        hover_message: str | None = None
        mouse_pos = pygame_module.mouse.get_pos()
        if viewport_rect.collidepoint(mouse_pos):
            hover_message = _hover_readout(sim, mouse_pos, world_center, world_zoom_scale)

        screen.fill((17, 18, 25))
        _draw_world(screen, sim, world_center, marker_font, clip_rect=viewport_rect, zoom_scale=world_zoom_scale)
        pygame.draw.rect(screen, (64, 68, 84), viewport_rect, 1)
        for entity_id in sorted(sim.state.entities):
            entity = sim.state.entities[entity_id]
            if not _is_in_current_space(_entity_space_id(entity), current_space_id):
                continue
            interpolated = interpolate_entity_position(previous_snapshot, current_snapshot, entity_id, alpha)
            if interpolated is None:
                continue
            if entity_id == PLAYER_ID:
                _draw_entity(screen, interpolated[0], interpolated[1], world_center, world_zoom_scale, clip_rect=viewport_rect)
            else:
                _draw_spawned_entity(screen, interpolated[0], interpolated[1], world_center, world_zoom_scale, clip_rect=viewport_rect)
        _draw_hud(screen, sim, font, status_message, hover_message)
        if show_local_arena_overlay:
            _draw_local_arena_overlay(screen, sim, world_center, marker_font, world_zoom_scale, clip_rect=viewport_rect)
        panel_section_rects, panel_section_counts = _draw_encounter_debug_panel(screen, sim, debug_font, panel_scroll, active_panel_section)
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
