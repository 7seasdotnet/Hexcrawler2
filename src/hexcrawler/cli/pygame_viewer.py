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
    LIST_RUMORS_INTENT,
    LIST_RUMORS_OUTCOME_KIND,
    SELECT_RUMORS_INTENT,
    SELECT_RUMORS_OUTCOME_KIND,
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    LocalEncounterInstanceModule,
    EncounterSelectionModule,
    RumorPipelineModule,
    RumorDecayModule,
    RumorQueryModule,
    SiteEcologyModule,
    SpawnMaterializationModule,
)
from hexcrawler.sim.groups import GroupMovementModule
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.combat import CombatExecutionModule
from hexcrawler.sim.entity_stats import EntityStatsExecutionModule
from hexcrawler.sim.exploration import EXPLORATION_OUTCOME_EVENT_TYPE, ExplorationExecutionModule
from hexcrawler.sim.interactions import INTERACTION_OUTCOME_EVENT_TYPE, InteractionExecutionModule
from hexcrawler.sim.signals import SignalPropagationModule
from hexcrawler.sim.supplies import SUPPLY_OUTCOME_EVENT_TYPE, SupplyConsumptionModule
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import (
    axial_to_world_xy,
    normalized_vector,
    square_grid_cell_to_world_xy,
    world_xy_to_axial,
    world_xy_to_square_grid_cell,
)
from hexcrawler.sim.world import LOCAL_SPACE_ROLE, HexCoord

HEX_SIZE = 28
GRID_RADIUS = 8
WINDOW_SIZE = (1440, 900)
PANEL_WIDTH = 520
VIEWPORT_MARGIN = 12
PANEL_MARGIN = 12
TOP_BAR_HEIGHT = 34
DEBUG_PANEL_HEIGHT = 250
MIN_WORLD_WIDTH = 360
MIN_WORLD_HEIGHT = 220
INSPECTOR_MIN_WIDTH = 320
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
SELECTED_ENTITY_TRACE_LIMIT = 12
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

ENTITY_MARKER_COLORS: dict[str, tuple[int, int, int]] = {
    "player": (110, 240, 140),
    "investigator": (255, 186, 96),
    "spawn": (140, 225, 255),
    "default": (214, 214, 214),
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


@dataclass(frozen=True)
class ViewerLayout:
    window: tuple[int, int]
    control_bar: pygame.Rect
    world_view: pygame.Rect
    inspector_panel: pygame.Rect
    debug_panel: pygame.Rect


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

    def list_rumors(
        self,
        *,
        kind: str | None,
        site_key: str | None,
        group_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> None:
        params: dict[str, Any] = {"limit": int(limit)}
        if kind is not None:
            params["kind"] = kind
        if site_key is not None:
            params["site_key"] = site_key
        if group_id is not None:
            params["group_id"] = group_id
        if cursor is not None:
            params["cursor"] = cursor
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=LIST_RUMORS_INTENT,
                params=params,
            )
        )

    def select_rumors(
        self,
        *,
        kind: str | None,
        site_key: str | None,
        group_id: str | None,
        k: int,
        cursor: str | None,
    ) -> None:
        params: dict[str, Any] = {"k": int(k), "seed_tag": "top"}
        if kind is not None:
            params["kind"] = kind
        if site_key is not None:
            params["site_key"] = site_key
        if group_id is not None:
            params["group_id"] = group_id
        if cursor is not None:
            params["cursor"] = cursor
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=SELECT_RUMORS_INTENT,
                params=params,
            )
        )

    def tick_once(self) -> None:
        self.sim.advance_ticks(1)


@dataclass
class ViewerRuntimeState:
    sim: Simulation
    map_path: str
    with_encounters: bool
    current_save_path: str
    paused: bool = False
    last_loaded_identity: str | None = None


class ViewerRuntimeController:
    """Runtime control surface adapter; uses canonical init/save/load/advance pathways."""

    def __init__(self, state: ViewerRuntimeState, *, entity_id: str = PLAYER_ID) -> None:
        self.state = state
        self.entity_id = entity_id
        self.controller = SimulationController(sim=state.sim, entity_id=entity_id)

    @property
    def sim(self) -> Simulation:
        return self.state.sim

    def replace_simulation(self, sim: Simulation, *, identity: str | None = None) -> None:
        self.state.sim = sim
        self.controller.sim = sim
        if identity is not None:
            self.state.last_loaded_identity = identity

    def new_simulation(self, *, map_path: str | None = None, seed: int | None = None) -> Simulation:
        next_map = map_path if map_path is not None else self.state.map_path
        next_seed = self.state.sim.seed if seed is None else int(seed)
        sim = _build_viewer_simulation(next_map, with_encounters=self.state.with_encounters, seed=next_seed)
        self.state.map_path = next_map
        self.replace_simulation(sim, identity=f"map:{Path(next_map).name}")
        return sim

    def load_simulation(self, path: str) -> Simulation:
        sim = _load_viewer_simulation(path, with_encounters=self.state.with_encounters)
        self.replace_simulation(sim, identity=f"save:{Path(path).name}")
        self.state.current_save_path = path
        return sim

    def save_simulation(self, path: str | None = None) -> str:
        target_path = path if path is not None else self.state.current_save_path
        _save_viewer_simulation(self.state.sim, target_path)
        self.state.current_save_path = target_path
        self.state.last_loaded_identity = f"save:{Path(target_path).name}"
        return target_path

    def advance_ticks(self, tick_count: int) -> None:
        self.state.sim.advance_ticks(int(tick_count))

    def toggle_pause(self) -> bool:
        self.state.paused = not self.state.paused
        return self.state.paused


@dataclass(frozen=True)
class RenderEntitySnapshot:
    x: float
    y: float


RenderSnapshot = dict[str, RenderEntitySnapshot]


@dataclass
class RumorPanelState:
    mode: str = "all"
    kind_filter: str | None = None
    site_key_filter: str = ""
    group_id_filter: str = ""
    limit: int = 20
    top_k: int = 10
    cursor: str | None = None
    cursor_stack: list[str | None] = field(default_factory=list)
    next_cursor: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "idle"
    diagnostic: str = ""
    request_pending: bool = False
    refresh_needed: bool = True
    editing_field: str | None = None
    site_key_draft: str = ""
    group_id_draft: str = ""

    def request_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": int(self.limit), "k": int(self.top_k)}
        if self.kind_filter is not None:
            params["kind"] = self.kind_filter
        if self.site_key_filter:
            params["site_key"] = self.site_key_filter
        if self.group_id_filter:
            params["group_id"] = self.group_id_filter
        if self.cursor is not None:
            params["cursor"] = self.cursor
        return params


@dataclass(frozen=True)
class DebugPanelCacheKey:
    tick: int
    event_trace_size: int
    signal_count: int
    track_count: int
    spawn_count: int
    entity_count: int
    rumor_signature: str
    selected_entity_id: str | None
    debug_filter_mode: str
    debug_event_type_filter: str | None


@dataclass
class DebugPanelRenderCache:
    key: DebugPanelCacheKey | None = None
    rows_by_section: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DebugFilterState:
    mode: str = "all"
    event_type_filter: str | None = None


@dataclass
class FollowSelectionState:
    enabled: bool = False
    status: str = "off"


FOLLOW_STATUS_OFF = "off"
FOLLOW_STATUS_ON = "on"
FOLLOW_STATUS_INACTIVE = "inactive"


DEBUG_FILTER_MODE_ORDER: tuple[str, ...] = ("all", "selected_entity", "selected_context", "outcomes_only")
DEBUG_CONTEXT_FILTER_KEYS: tuple[str, ...] = ("action_uid", "source_action_uid", "source_event_id", "request_event_id")


RUMOR_KIND_FILTER_ORDER: tuple[str | None, ...] = (None, "group_arrival", "claim_opportunity", "site_claim")




def _debug_event_type(entry: dict[str, Any]) -> str:
    return str(entry.get("event_type", "?"))


def _debug_context_fields_from_entry(entry: dict[str, Any]) -> dict[str, str]:
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    fields: dict[str, str] = {}
    for key in DEBUG_CONTEXT_FILTER_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value:
            fields[key] = value
    return fields


def _derive_selected_context_filters(
    sim: Simulation,
    *,
    selected_entity_id: str | None,
    selected_entity: EntityState | None,
) -> dict[str, frozenset[str]]:
    filters: dict[str, set[str]] = {key: set() for key in DEBUG_CONTEXT_FILTER_KEYS}

    if selected_entity is not None and isinstance(selected_entity.source_action_uid, str) and selected_entity.source_action_uid:
        filters["action_uid"].add(selected_entity.source_action_uid)

    preferred_action_uid: str | None = None
    if selected_entity is not None and isinstance(selected_entity.source_action_uid, str) and selected_entity.source_action_uid:
        preferred_action_uid = selected_entity.source_action_uid

    if selected_entity_id is not None:
        for entry in reversed(sim.get_event_trace()):
            if not isinstance(entry, dict) or not _event_trace_entry_mentions_entity(entry, selected_entity_id):
                continue
            entry_fields = _debug_context_fields_from_entry(entry)
            if preferred_action_uid is not None and entry_fields.get("action_uid") != preferred_action_uid:
                continue
            for key, value in entry_fields.items():
                filters[key].add(value)
            break

    return {
        key: frozenset(sorted(values))
        for key, values in filters.items()
        if values
    }


def _event_trace_entry_matches_event_type(entry: dict[str, Any], event_type_filter: str | None) -> bool:
    if event_type_filter is None:
        return True
    return _debug_event_type(entry) == event_type_filter


def _event_trace_entry_matches_context_filters(
    entry: dict[str, Any],
    context_filters: dict[str, frozenset[str]],
) -> bool:
    if not context_filters:
        return False
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    for key, allowed_values in context_filters.items():
        value = params.get(key)
        if isinstance(value, str) and value in allowed_values:
            return True
    return False


def _cycle_debug_filter_mode(debug_filter_state: DebugFilterState) -> None:
    current_index = DEBUG_FILTER_MODE_ORDER.index(debug_filter_state.mode) if debug_filter_state.mode in DEBUG_FILTER_MODE_ORDER else 0
    debug_filter_state.mode = DEBUG_FILTER_MODE_ORDER[(current_index + 1) % len(DEBUG_FILTER_MODE_ORDER)]


def _cycle_debug_event_type_filter(sim: Simulation, debug_filter_state: DebugFilterState) -> None:
    event_types = sorted({_debug_event_type(entry) for entry in sim.get_event_trace() if isinstance(entry, dict)})
    order: list[str | None] = [None, *event_types]
    current_index = order.index(debug_filter_state.event_type_filter) if debug_filter_state.event_type_filter in order else 0
    debug_filter_state.event_type_filter = order[(current_index + 1) % len(order)]


def _debug_filter_label(debug_filter_state: DebugFilterState) -> str:
    event_type = debug_filter_state.event_type_filter if debug_filter_state.event_type_filter is not None else "all"
    return f"mode={debug_filter_state.mode} type={event_type}"


def _build_debug_filter_trace_rows(
    sim: Simulation,
    *,
    selected_entity_id: str | None,
    selected_context_filters: dict[str, frozenset[str]],
    event_type_filter: str | None,
    mode: str,
) -> list[dict[str, Any]]:
    include_outcome_types = {ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE, EXPLORATION_OUTCOME_EVENT_TYPE, INTERACTION_OUTCOME_EVENT_TYPE}
    rows: list[dict[str, Any]] = []
    for entry in sim.get_event_trace():
        if not isinstance(entry, dict):
            continue
        if not _event_trace_entry_matches_event_type(entry, event_type_filter):
            continue
        if mode == "selected_entity" and selected_entity_id is not None:
            if not _event_trace_entry_mentions_entity(entry, selected_entity_id):
                continue
        elif mode == "selected_context":
            if not _event_trace_entry_matches_context_filters(entry, selected_context_filters):
                continue
        elif mode == "outcomes_only":
            if _debug_event_type(entry) not in include_outcome_types:
                continue
        rows.append(entry)
    return rows


def _format_debug_trace_row(entry: dict[str, Any]) -> str:
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    event_type = _debug_event_type(entry)
    tick = entry.get("tick", "?")
    action_uid = params.get("action_uid", "-")
    if not isinstance(action_uid, str) or not action_uid:
        action_uid = "-"
    source_action_uid = params.get("source_action_uid", "-")
    if not isinstance(source_action_uid, str) or not source_action_uid:
        source_action_uid = "-"
    source_event_id = params.get("source_event_id", "-")
    if not isinstance(source_event_id, str) or not source_event_id:
        source_event_id = "-"
    request_event_id = params.get("request_event_id", "-")
    if not isinstance(request_event_id, str) or not request_event_id:
        request_event_id = "-"
    return (
        f"tick={tick} type={event_type} action_uid={action_uid} source_action_uid={source_action_uid} "
        f"source_event_id={source_event_id} request_event_id={request_event_id}"
    )

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


def compute_interpolation_alpha(*, elapsed_seconds: float, tick_duration_seconds: float) -> float:
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0.0:
        return 0.0
    if not math.isfinite(tick_duration_seconds) or tick_duration_seconds <= 0.0:
        return 1.0
    return clamp01(elapsed_seconds / tick_duration_seconds)


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


def _drain_sim_accumulator(accumulator: float, tick_seconds: float, *, paused: bool) -> tuple[float, int]:
    if not math.isfinite(accumulator) or accumulator < 0.0:
        accumulator = 0.0
    if not math.isfinite(tick_seconds) or tick_seconds <= 0.0:
        return 0.0, 0
    if paused:
        return min(accumulator, tick_seconds), 0
    ticks = 0
    while accumulator >= tick_seconds:
        accumulator -= tick_seconds
        ticks += 1
    return accumulator, ticks


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


def _world_to_local_cell(
    world_x: float,
    world_y: float,
    *,
    active_space: Any,
) -> dict[str, int] | None:
    if str(getattr(active_space, "role", "")) != LOCAL_SPACE_ROLE:
        return None
    if getattr(active_space, "topology_type", None) != SQUARE_GRID_TOPOLOGY:
        return None
    coord = world_xy_to_square_grid_cell(world_x, world_y)
    if not active_space.is_valid_cell(coord):
        return None
    return coord


def _hex_points(center: tuple[float, float]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((center[0] + HEX_SIZE * math.cos(angle), center[1] + HEX_SIZE * math.sin(angle)))
    return points


def _compute_control_bar_rect(window_size: tuple[int, int]) -> pygame.Rect:
    return pygame.Rect(0, 0, max(1, int(window_size[0])), TOP_BAR_HEIGHT)


def _compute_viewer_layout(window_size: tuple[int, int]) -> ViewerLayout:
    window_width = max(1, int(window_size[0]))
    window_height = max(TOP_BAR_HEIGHT + 1, int(window_size[1]))
    control_bar = _compute_control_bar_rect((window_width, window_height))

    content_top = control_bar.bottom + PANEL_MARGIN
    content_left = VIEWPORT_MARGIN
    content_right = max(content_left + 1, window_width - VIEWPORT_MARGIN)
    content_bottom = max(content_top + 1, window_height - VIEWPORT_MARGIN)
    content_width = max(1, content_right - content_left)
    content_height = max(1, content_bottom - content_top)

    debug_height = max(120, min(DEBUG_PANEL_HEIGHT, max(120, content_height // 2)))
    debug_top = max(content_top, content_bottom - debug_height)
    debug_panel = pygame.Rect(content_left, debug_top, content_width, max(1, content_bottom - debug_top))

    top_area_bottom = max(content_top + MIN_WORLD_HEIGHT, debug_panel.top - PANEL_MARGIN)
    top_area_height = max(1, top_area_bottom - content_top)

    inspector_width = min(PANEL_WIDTH, max(INSPECTOR_MIN_WIDTH, content_width // 4))
    if content_width - inspector_width - PANEL_MARGIN < MIN_WORLD_WIDTH:
        inspector_width = max(220, content_width - MIN_WORLD_WIDTH - PANEL_MARGIN)
    inspector_width = max(220, min(inspector_width, max(220, content_width - 60)))

    world_width = max(1, content_width - inspector_width - PANEL_MARGIN)
    if world_width < MIN_WORLD_WIDTH:
        shrink = MIN_WORLD_WIDTH - world_width
        inspector_width = max(220, inspector_width - shrink)
        world_width = max(1, content_width - inspector_width - PANEL_MARGIN)

    world_view = pygame.Rect(content_left, content_top, world_width, top_area_height)
    inspector_x = world_view.right + PANEL_MARGIN
    inspector_panel = pygame.Rect(inspector_x, content_top, max(1, content_right - inspector_x), top_area_height)

    return ViewerLayout(
        window=(window_width, window_height),
        control_bar=control_bar,
        world_view=world_view,
        inspector_panel=inspector_panel,
        debug_panel=debug_panel,
    )


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


def _render_panel_frame(
    screen: pygame.Surface,
    panel_rect: pygame.Rect,
    title: str,
    font: pygame.font.Font,
    *,
    bg_color: tuple[int, int, int] = (24, 26, 36),
) -> pygame.Rect:
    pygame.draw.rect(screen, bg_color, panel_rect)
    pygame.draw.rect(screen, (95, 98, 110), panel_rect, 1)
    header_rect = pygame.Rect(panel_rect.x + 8, panel_rect.y + 8, panel_rect.width - 16, 20)
    header_text = _truncate_text_to_pixel_width(title, font, header_rect.width)
    screen.blit(font.render(header_text, True, (242, 242, 248)), (header_rect.x, header_rect.y))
    content_top = header_rect.bottom + 6
    content_rect = pygame.Rect(panel_rect.x + 8, content_top, panel_rect.width - 16, max(1, panel_rect.bottom - content_top - 8))
    return content_rect


def _render_wrapped_lines(
    screen: pygame.Surface,
    font: pygame.font.Font,
    content_rect: pygame.Rect,
    lines: list[str],
    *,
    scroll_offset: int = 0,
    line_height: int = 16,
    color: tuple[int, int, int] = (212, 212, 220),
    pad_left: int = 2,
) -> int:
    old_clip = screen.get_clip()
    screen.set_clip(content_rect)
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_text_to_pixel_width(line, font, max(1, content_rect.width - (pad_left * 2))))
    start = max(0, int(scroll_offset))
    visible_line_count = max(1, content_rect.height // line_height)
    visible = wrapped[start : start + visible_line_count]
    y = content_rect.y
    for row in visible:
        screen.blit(font.render(row, True, color), (content_rect.x + pad_left, y))
        y += line_height
    screen.set_clip(old_clip)
    return len(wrapped)


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


def _selected_entity_in_active_space(sim: Simulation, selected_entity_id: str | None) -> EntityState | None:
    if selected_entity_id is None:
        return None
    selected_entity = sim.state.entities.get(selected_entity_id)
    if selected_entity is None:
        return None
    player = sim.state.entities.get(PLAYER_ID)
    current_space_id = _entity_space_id(player) if player is not None else "overworld"
    if current_space_id is None:
        current_space_id = "overworld"
    if not _is_in_current_space(_entity_space_id(selected_entity), current_space_id):
        return None
    return selected_entity


def _camera_center_for_entity(
    entity: EntityState,
    viewport_rect: pygame.Rect,
    *,
    zoom_scale: float,
) -> tuple[float, float]:
    size = HEX_SIZE * zoom_scale
    return (
        float(viewport_rect.centerx) - (float(entity.position_x) * size),
        float(viewport_rect.centery) - (float(entity.position_y) * size),
    )


def _focus_camera_on_selected(
    sim: Simulation,
    selected_entity_id: str | None,
    viewport_rect: pygame.Rect,
    *,
    zoom_scale: float,
) -> tuple[tuple[float, float] | None, str]:
    selected_entity = _selected_entity_in_active_space(sim, selected_entity_id)
    if selected_entity is None:
        return None, "focus selected: inactive"
    center = _camera_center_for_entity(selected_entity, viewport_rect, zoom_scale=zoom_scale)
    return center, f"focus selected: {selected_entity.entity_id}"


def _apply_follow_selected_camera(
    sim: Simulation,
    selected_entity_id: str | None,
    viewport_rect: pygame.Rect,
    *,
    zoom_scale: float,
    follow_state: FollowSelectionState,
) -> tuple[tuple[float, float] | None, str | None]:
    if not follow_state.enabled:
        follow_state.status = FOLLOW_STATUS_OFF
        return None, None
    selected_entity = _selected_entity_in_active_space(sim, selected_entity_id)
    if selected_entity is None:
        follow_state.enabled = False
        follow_state.status = FOLLOW_STATUS_INACTIVE
        return None, "follow selected: inactive"
    follow_state.status = FOLLOW_STATUS_ON
    center = _camera_center_for_entity(selected_entity, viewport_rect, zoom_scale=zoom_scale)
    return center, None


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


def _scroll_page_size(rect: pygame.Rect | None, line_height: int = 16) -> int:
    if rect is None:
        return ENCOUNTER_DEBUG_SECTION_ROWS
    return max(1, rect.height // line_height)


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
        entity_space_id = _entity_space_id(entity)
        if not _is_in_current_space(entity_space_id, active_space_id):
            continue
        label = _entity_marker_label(entity)
        _, marker_color = _entity_marker_role_and_color(entity)
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
                color=marker_color,
                radius=6 if entity.entity_id == PLAYER_ID else 5,
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


def _draw_top_control_bar(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    runtime_state: ViewerRuntimeState,
    bar_rect: pygame.Rect,
    follow_state: FollowSelectionState,
) -> None:
    pygame.draw.rect(screen, (28, 30, 40), bar_rect)
    pygame.draw.rect(screen, (95, 98, 110), bar_rect, 1)

    ticks_per_day = sim.get_ticks_per_day()
    day_display = sim.get_day_index() + 1
    tick_in_day = sim.get_tick_in_day()
    hours = (tick_in_day * 24) // ticks_per_day
    minutes = ((tick_in_day * 24 * 60) // ticks_per_day) % 60
    hash_suffix = simulation_hash(sim)[-8:]
    identity = runtime_state.last_loaded_identity or f"map:{Path(runtime_state.map_path).name}"
    metadata_text = (
        f"tick={sim.state.tick} day={day_display} {hours:02d}:{minutes:02d} "
        f"seed={sim.seed} src={identity} hash={hash_suffix} follow={follow_state.status}"
    )
    sections_text = "Simulation | Save/Load | Time | View | Debug"
    left_label = _truncate_text_to_pixel_width(sections_text, font, 460)
    right_label = _truncate_text_to_pixel_width(metadata_text, font, max(160, bar_rect.width - 490))
    screen.blit(font.render(left_label, True, (235, 235, 240)), (10, 8))
    screen.blit(font.render(right_label, True, (220, 220, 225)), (480, 8))


def _draw_hud(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    status_message: str | None,
    hover_message: str | None,
    runtime_state: ViewerRuntimeState,
    world_rect: pygame.Rect,
    follow_state: FollowSelectionState,
) -> None:
    entity = sim.state.entities[PLAYER_ID]
    active_space = sim.state.world.spaces.get(entity.space_id)
    if active_space is not None and active_space.topology_type == SQUARE_GRID_TOPOLOGY:
        coord_text = f"x={math.floor(entity.position_x)},y={math.floor(entity.position_y)}"
    else:
        coord_text = f"q={entity.hex_coord.q},r={entity.hex_coord.r}"
    context_line = f"space={entity.space_id} | {coord_text}"
    lines = [
        context_line,
        "WASD move | RMB menu | F2 pause/resume | F4 new sim | F5 save | F6 save as | F8/F9 load | 1/2/3 advance | ESC quit",
        "F7 focus selected | F12 follow selected toggle",
        f"runtime={'paused' if runtime_state.paused else 'running'}",
        f"follow_selected={follow_state.status}",
    ]
    if status_message:
        lines.append(f"status: {status_message}")
    if hover_message:
        lines.append(hover_message)
    old_clip = screen.get_clip()
    screen.set_clip(world_rect)
    y = world_rect.y + 8
    for line in lines:
        if y + 20 > world_rect.bottom:
            break
        label = _truncate_text_to_pixel_width(line, font, max(1, world_rect.width - 18))
        surface = font.render(label, True, (240, 240, 240))
        screen.blit(surface, (world_rect.x + 10, y))
        y += 20
    screen.set_clip(old_clip)


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

    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    y = clip_rect.y + 72
    for line in lines:
        if y + 18 > clip_rect.bottom:
            break
        text = _truncate_text_to_pixel_width(line, font, max(1, clip_rect.width - 12))
        screen.blit(font.render(text, True, (240, 240, 240)), (clip_rect.x + 6, y))
        y += 18
    screen.set_clip(old_clip)


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


def _refresh_rumor_query(controller: SimulationController, rumor_state: RumorPanelState) -> None:
    if rumor_state.request_pending or not rumor_state.refresh_needed:
        return
    params = rumor_state.request_params()
    if rumor_state.mode == "top":
        controller.select_rumors(
            kind=params.get("kind"),
            site_key=params.get("site_key"),
            group_id=params.get("group_id"),
            k=int(params.get("k", 10)),
            cursor=params.get("cursor"),
        )
    else:
        controller.list_rumors(
            kind=params.get("kind"),
            site_key=params.get("site_key"),
            group_id=params.get("group_id"),
            limit=int(params.get("limit", 20)),
            cursor=params.get("cursor"),
        )
    rumor_state.request_pending = True
    rumor_state.refresh_needed = False


def _consume_rumor_outcome(sim: Simulation, rumor_state: RumorPanelState) -> None:
    if not rumor_state.request_pending:
        return
    latest: dict[str, Any] | None = None
    outcome_kind = SELECT_RUMORS_OUTCOME_KIND if rumor_state.mode == "top" else LIST_RUMORS_OUTCOME_KIND
    rows_key = "selection" if rumor_state.mode == "top" else "rumors"
    for entry in sim.get_command_outcomes():
        if isinstance(entry, dict) and entry.get("kind") == outcome_kind:
            latest = entry
    if latest is None:
        return
    rows = latest.get(rows_key)
    rumor_state.rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    rumor_state.next_cursor = latest.get("next_cursor") if isinstance(latest.get("next_cursor"), str) else None
    rumor_state.outcome = str(latest.get("outcome", "?"))
    rumor_state.diagnostic = str(latest.get("diagnostic", ""))
    rumor_state.request_pending = False


def _cycle_rumor_kind_filter(rumor_state: RumorPanelState) -> None:
    current_index = 0
    for index, current_kind in enumerate(RUMOR_KIND_FILTER_ORDER):
        if current_kind == rumor_state.kind_filter:
            current_index = index
            break
    rumor_state.kind_filter = RUMOR_KIND_FILTER_ORDER[(current_index + 1) % len(RUMOR_KIND_FILTER_ORDER)]
    rumor_state.cursor = None
    rumor_state.cursor_stack = []
    rumor_state.refresh_needed = True


def _toggle_rumor_mode(rumor_state: RumorPanelState) -> None:
    rumor_state.mode = "top" if rumor_state.mode == "all" else "all"
    rumor_state.cursor = None
    rumor_state.cursor_stack = []
    rumor_state.next_cursor = None
    rumor_state.refresh_needed = True


def _cycle_rumor_top_k(rumor_state: RumorPanelState) -> None:
    values = (10, 20, 50)
    current_index = values.index(rumor_state.top_k) if rumor_state.top_k in values else 0
    rumor_state.top_k = values[(current_index + 1) % len(values)]
    rumor_state.cursor = None
    rumor_state.cursor_stack = []
    rumor_state.next_cursor = None
    rumor_state.refresh_needed = True


def _apply_rumor_text_filters(rumor_state: RumorPanelState) -> None:
    rumor_state.site_key_filter = rumor_state.site_key_draft.strip()
    rumor_state.group_id_filter = rumor_state.group_id_draft.strip()
    rumor_state.cursor = None
    rumor_state.cursor_stack = []
    rumor_state.refresh_needed = True


def _rumor_rows_from_state(rumor_state: RumorPanelState) -> list[str]:
    return _section_entries(
        [
            (
                f"kind={row.get('kind', '?')} tick={row.get('created_tick', '?')} "
                f"site_key={row.get('site_key', '-') if row.get('site_key') else '-'} "
                f"group_id={row.get('group_id', '-') if row.get('group_id') else '-'} "
                f"consumed={row.get('consumed', '-')}"
            )
            for row in rumor_state.rows
        ]
    )

def _draw_inspector_panel(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    panel_rect: pygame.Rect,
    scroll_offset: int,
    follow_state: FollowSelectionState,
) -> tuple[pygame.Rect, int]:
    content_rect = _render_panel_frame(screen, panel_rect, "Inspector", font)
    selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
    lines: list[str] = []
    if selected_entity_id:
        lines.extend(_selected_entity_lines(sim, selected_entity_id, follow_status=follow_state.status))
    else:
        lines.extend(["Selection", "Nothing selected", f"follow_selected={follow_state.status}"])
    lines.extend(
        [
            "",
            "Viewer discipline",
            "Read-only operator console: no direct simulation mutation.",
            "campaign role: travel/time/logistics/encounter triggering",
            "local role: tactical movement/combat resolution",
        ]
    )
    wrapped_count = _render_wrapped_lines(screen, font, content_rect, lines, scroll_offset=scroll_offset)
    return content_rect, wrapped_count


def _debug_panel_cache_key(sim: Simulation, rumor_state: RumorPanelState, debug_filter_state: DebugFilterState) -> DebugPanelCacheKey:
    rumor_signature = json.dumps({
        "mode": rumor_state.mode,
        "kind": rumor_state.kind_filter,
        "site": rumor_state.site_key_filter,
        "group": rumor_state.group_id_filter,
        "cursor": rumor_state.cursor,
        "rows": [str(row.get("rumor_id", "")) for row in rumor_state.rows if isinstance(row, dict)],
        "outcome": rumor_state.outcome,
    }, sort_keys=True)
    return DebugPanelCacheKey(
        tick=int(sim.state.tick),
        event_trace_size=len(sim.state.event_trace),
        signal_count=len(sim.state.world.signals),
        track_count=len(sim.state.world.tracks),
        spawn_count=len(sim.state.world.spawn_descriptors),
        entity_count=len(sim.state.entities),
        rumor_signature=rumor_signature,
        selected_entity_id=sim.selected_entity_id(owner_entity_id=PLAYER_ID),
        debug_filter_mode=debug_filter_state.mode,
        debug_event_type_filter=debug_filter_state.event_type_filter,
    )


def build_debug_panel_render_cache(
    sim: Simulation,
    rumor_state: RumorPanelState,
    debug_filter_state: DebugFilterState,
    cache: DebugPanelRenderCache,
) -> dict[str, list[str]]:
    next_key = _debug_panel_cache_key(sim, rumor_state, debug_filter_state)
    if cache.key == next_key and cache.rows_by_section:
        return cache.rows_by_section
    cache.key = next_key
    cache.rows_by_section = _debug_rows_by_section(sim, rumor_state, debug_filter_state)
    return cache.rows_by_section


def _debug_rows_by_section(sim: Simulation, rumor_state: RumorPanelState, debug_filter_state: DebugFilterState) -> dict[str, list[str]]:
    spawned_entities = [
        entity
        for entity in sorted(sim.state.entities.values(), key=lambda current: current.entity_id)
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
    selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
    selected_entity = sim.state.entities.get(selected_entity_id) if selected_entity_id is not None else None
    selected_context_filters = _derive_selected_context_filters(
        sim,
        selected_entity_id=selected_entity_id,
        selected_entity=selected_entity,
    )

    filtered_trace = _build_debug_filter_trace_rows(
        sim,
        selected_entity_id=selected_entity_id,
        selected_context_filters=selected_context_filters,
        event_type_filter=debug_filter_state.event_type_filter,
        mode=debug_filter_state.mode,
    )
    encounter_trace_rows = _section_entries([_format_debug_trace_row(entry) for entry in filtered_trace])
    encounter_rows = _section_entries(recent_signals + recent_tracks + recent_spawns + encounter_trace_rows)

    outcome_trace = [
        entry
        for entry in filtered_trace
        if _debug_event_type(entry) in {ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE, EXPLORATION_OUTCOME_EVENT_TYPE, INTERACTION_OUTCOME_EVENT_TYPE}
    ]
    outcome_rows = _section_entries([
        (
            f"tick={entry.get('tick', '?')} action_uid={params.get('action_uid', '?')} action={params.get('action_type', params.get('action', '?'))} "
            f"outcome={params.get('outcome', '?')} template={params.get('template_id', '-') or '-'}"
        )
        for entry in outcome_trace
        for params in [entry.get("params") if isinstance(entry.get("params"), dict) else {}]
    ])

    supply_outcomes = [entry for entry in filtered_trace if entry.get("event_type") == SUPPLY_OUTCOME_EVENT_TYPE]
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

    entity_rows = _section_entries([
        (
            f"entity_id={entity.entity_id} template={entity.template_id if entity.template_id else '-'} "
            f"loc={_entity_location_text(sim, entity)} action_uid={entity.source_action_uid if entity.source_action_uid else '-'}"
        )
        for entity in spawned_entities
    ])

    return {
        "encounters": encounter_rows,
        "outcomes": outcome_rows,
        "rumors": _rumor_rows_from_state(rumor_state),
        "supplies": supply_rows,
        "sites": _section_entries(site_rows),
        "entities": entity_rows,
    }


def _draw_encounter_debug_panel(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    scroll_state: EncounterPanelScrollState,
    active_section: str,
    rumor_state: RumorPanelState,
    debug_filter_state: DebugFilterState,
    panel_rect: pygame.Rect,
    cache: DebugPanelRenderCache,
) -> tuple[dict[str, pygame.Rect], dict[str, int]]:
    content_rect = _render_panel_frame(screen, panel_rect, "Debug / Event", font, bg_color=(22, 24, 33))
    section_rects: dict[str, pygame.Rect] = {}

    rows_by_section = build_debug_panel_render_cache(sim, rumor_state, debug_filter_state, cache)
    section_counts = {section: len(rows) for section, rows in rows_by_section.items()}

    tab_x = content_rect.x
    tab_y = content_rect.y
    for section_name in PANEL_SECTION_ORDER:
        tab_surface = font.render(PANEL_SECTION_TITLES.get(section_name, section_name), True, (240, 240, 245))
        tab_rect = pygame.Rect(tab_x, tab_y, tab_surface.get_width() + 12, 20)
        color = (64, 70, 92) if section_name == active_section else (44, 48, 64)
        pygame.draw.rect(screen, color, tab_rect)
        pygame.draw.rect(screen, (110, 115, 135), tab_rect, 1)
        screen.blit(tab_surface, (tab_rect.x + 6, tab_rect.y + 2))
        section_rects[section_name] = tab_rect
        tab_x = tab_rect.right + 6

    filter_mode_text = _truncate_text_to_pixel_width(f"filter:{debug_filter_state.mode}", font, max(60, content_rect.width // 3))
    filter_mode_surface = font.render(filter_mode_text, True, (240, 240, 245))
    filter_mode_rect = pygame.Rect(content_rect.right - filter_mode_surface.get_width() - 10, tab_y, filter_mode_surface.get_width() + 8, 20)
    pygame.draw.rect(screen, (44, 48, 64), filter_mode_rect)
    pygame.draw.rect(screen, (110, 115, 135), filter_mode_rect, 1)
    screen.blit(filter_mode_surface, (filter_mode_rect.x + 4, filter_mode_rect.y + 2))
    section_rects["debug_filter_mode"] = filter_mode_rect

    type_label = debug_filter_state.event_type_filter if debug_filter_state.event_type_filter is not None else "all"
    filter_type_text = _truncate_text_to_pixel_width(f"type:{type_label}", font, max(60, content_rect.width // 3))
    filter_type_surface = font.render(filter_type_text, True, (240, 240, 245))
    filter_type_rect = pygame.Rect(
        max(content_rect.x, filter_mode_rect.x - filter_type_surface.get_width() - 20),
        tab_y,
        filter_type_surface.get_width() + 8,
        20,
    )
    pygame.draw.rect(screen, (44, 48, 64), filter_type_rect)
    pygame.draw.rect(screen, (110, 115, 135), filter_type_rect, 1)
    screen.blit(filter_type_surface, (filter_type_rect.x + 4, filter_type_rect.y + 2))
    section_rects["debug_filter_type"] = filter_type_rect

    rows_rect = pygame.Rect(content_rect.x, tab_y + 26, content_rect.width, max(1, content_rect.bottom - (tab_y + 26)))
    section_rects["rows"] = rows_rect
    offset = scroll_state.offset_for(active_section)
    section_rows = rows_by_section.get(active_section, [])
    if not section_rows:
        section_rows = ["No rows yet for this section."]
    total_rows = _render_wrapped_lines(screen, font, rows_rect, section_rows, scroll_offset=offset)
    section_counts[active_section] = total_rows

    selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
    if selected_entity_id:
        tag = _truncate_text_to_pixel_width(f"selected={selected_entity_id}", font, max(1, panel_rect.width - 22))
        screen.blit(font.render(tag, True, (185, 215, 185)), (panel_rect.x + 10, panel_rect.y + 8))

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


def _entity_marker_role_and_color(entity: EntityState) -> tuple[str, tuple[int, int, int]]:
    role_value = entity.stats.get("role") if isinstance(entity.stats, dict) else None
    role = str(role_value).strip().lower() if isinstance(role_value, str) and role_value.strip() else ""
    if entity.entity_id == PLAYER_ID:
        return "player", ENTITY_MARKER_COLORS["player"]
    if role == "investigator" or str(entity.template_id or "") == "faction_investigator":
        return "investigator", ENTITY_MARKER_COLORS["investigator"]
    if entity.entity_id.startswith("spawn:"):
        return "spawn", ENTITY_MARKER_COLORS["spawn"]
    return "default", ENTITY_MARKER_COLORS["default"]


def _entity_marker_label(entity: EntityState) -> str:
    marker_role, _ = _entity_marker_role_and_color(entity)
    if marker_role == "player":
        return "player"
    if marker_role == "investigator":
        faction_id = entity.stats.get("faction_id") if isinstance(entity.stats, dict) else None
        if isinstance(faction_id, str) and faction_id:
            return f"inv:{faction_id}"
        return "investigator"
    if entity.template_id:
        return str(entity.template_id)
    return _short_stable_id(entity.entity_id)


def _selected_entity_for_click(
    sim: Simulation,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 12.0,
) -> str | None:
    markers = _find_world_marker_candidates_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=radius_px)
    for marker in markers:
        if marker.marker_kind != "entity":
            continue
        parts = marker.marker_id.split(":", 1)
        if len(parts) != 2:
            continue
        entity_id = parts[1]
        if entity_id in sim.state.entities:
            return entity_id
    return None


def _queue_selection_command_for_click(
    sim: Simulation,
    controller: SimulationController,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 12.0,
) -> str:
    selected_entity = _selected_entity_for_click(sim, pixel_pos, center, zoom_scale, radius_px=radius_px)
    if selected_entity is not None:
        controller.set_selected_entity(selected_entity)
        return f"selected {selected_entity}"
    controller.clear_selected_entity()
    return "selection cleared"


def _selected_entity_lines(
    sim: Simulation,
    selected_entity_id: str,
    *,
    follow_status: str = FOLLOW_STATUS_OFF,
) -> list[str]:
    entity = sim.state.entities.get(selected_entity_id)
    if entity is None:
        return ["Selection", f"entity_id={selected_entity_id}", "Entity not found in current simulation state."]

    stats = entity.stats if isinstance(entity.stats, dict) else {}
    faction_id = stats.get("faction_id") if isinstance(stats.get("faction_id"), str) else None
    role_value = stats.get("role") if isinstance(stats.get("role"), str) else None
    source_belief_id = stats.get("source_belief_id") if isinstance(stats.get("source_belief_id"), str) else None
    target_location = stats.get("target_location") if isinstance(stats.get("target_location"), dict) else None
    target_summary = _format_location(target_location) if target_location is not None else "-"
    space = sim.state.world.spaces.get(entity.space_id)
    space_role = space.role if space is not None and isinstance(space.role, str) else "campaign"
    source_action_uid = entity.source_action_uid if isinstance(entity.source_action_uid, str) and entity.source_action_uid else "-"

    recent_relevant_events = _selected_entity_recent_trace_rows(sim, selected_entity_id)

    lines = [
        "Selection",
        f"entity_id={entity.entity_id}",
        f"space_id={entity.space_id}",
        f"space_role={space_role}",
        f"faction_id={faction_id if faction_id else '-'}",
        f"role={role_value if role_value else (entity.template_id if entity.template_id else '-')}",
        f"location={_entity_location_text(sim, entity)}",
        f"target_location={target_summary}",
        f"source_belief_id={source_belief_id if source_belief_id else '-'}",
        f"source_action_uid={source_action_uid}",
        "selected_state=active",
        f"follow_selected={follow_status}",
        "",
        "Recent relevant events",
    ]
    if recent_relevant_events:
        lines.extend(recent_relevant_events)
    else:
        lines.append("No relevant event-trace rows for selected entity.")
    return lines


def _selected_entity_recent_trace_rows(sim: Simulation, selected_entity_id: str) -> list[str]:
    rows: list[str] = []
    for entry in sim.get_event_trace():
        if not _event_trace_entry_mentions_entity(entry, selected_entity_id):
            continue
        rows.append(_selected_entity_trace_row(entry))
    return _section_entries(rows, entry_limit=SELECTED_ENTITY_TRACE_LIMIT)


def _event_trace_entry_mentions_entity(entry: dict[str, Any], selected_entity_id: str) -> bool:
    if not isinstance(entry, dict):
        return False
    for candidate_id in _collect_known_entity_ids_from_trace_entry(entry):
        if candidate_id == selected_entity_id:
            return True
    return False


def _collect_known_entity_ids_from_trace_entry(entry: dict[str, Any]) -> tuple[str, ...]:
    known_fields = ("entity_id", "attacker_id", "target_id", "actor_id", "source_entity_id")
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    target = params.get("target") if isinstance(params.get("target"), dict) else None

    values: list[str] = []
    for field_name in known_fields:
        value = entry.get(field_name)
        if isinstance(value, str) and value:
            values.append(value)
        param_value = params.get(field_name)
        if isinstance(param_value, str) and param_value:
            values.append(param_value)
    if target is not None:
        target_id = target.get("id")
        if isinstance(target_id, str) and target_id:
            values.append(target_id)
    return tuple(values)


def _selected_entity_trace_row(entry: dict[str, Any]) -> str:
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    event_type = str(entry.get("event_type", "?"))
    tick = entry.get("tick", "?")
    action_uid = params.get("action_uid", "-")
    if not isinstance(action_uid, str) or not action_uid:
        action_uid = "-"
    source_action_uid = params.get("source_action_uid", "-")
    if not isinstance(source_action_uid, str) or not source_action_uid:
        source_action_uid = "-"
    return f"tick={tick} type={event_type} action_uid={action_uid} source_action_uid={source_action_uid}"


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
    sim.register_rule_module(SiteEcologyModule())
    sim.register_rule_module(RumorPipelineModule())
    sim.register_rule_module(RumorDecayModule())
    sim.register_rule_module(RumorQueryModule())
    sim.register_rule_module(SpawnMaterializationModule())
    sim.register_rule_module(GroupMovementModule())


def _build_viewer_simulation(map_path: str, *, with_encounters: bool, seed: int = 7) -> Simulation:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=seed)
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

    runtime_state = ViewerRuntimeState(
        sim=sim,
        map_path=map_path,
        with_encounters=with_encounters,
        current_save_path=load_save or save_path,
        last_loaded_identity=f"save:{Path(load_save).name}" if load_save else f"map:{Path(map_path).name}",
    )
    runtime_controller = ViewerRuntimeController(runtime_state, entity_id=PLAYER_ID)
    controller = runtime_controller.controller

    try:
        pygame_module.display.set_caption("Hexcrawler Phase 5G Viewer")
        screen = pygame_module.display.set_mode(WINDOW_SIZE, pygame_module.RESIZABLE)
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
        runtime_controller.advance_ticks(1)
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
        nonlocal sim, context_menu, previous_snapshot, current_snapshot, last_tick_time, status_message, last_sent_move_vector
        try:
            sim = runtime_controller.load_simulation(path_value)
            previous_snapshot = extract_render_snapshot(sim)
            current_snapshot = previous_snapshot
            last_tick_time = pygame_module.time.get_ticks() / 1000.0
            context_menu = None
            push_recent_save(path_value)
            status_message = f"loaded {path_value}"
            last_sent_move_vector = (0.0, 0.0)
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
        layout = _compute_viewer_layout(screen.get_size())
        viewport_rect = layout.world_view
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
                if active_space is not None and str(getattr(active_space, "role", "")) == LOCAL_SPACE_ROLE:
                    local_cell = _world_to_local_cell(world_x, world_y, active_space=active_space)
                    if local_cell is not None:
                        local_world_x, local_world_y = square_grid_cell_to_world_xy(local_cell["x"], local_cell["y"])
                        items.append(ContextMenuItem(label="Move here", action="move_here", payload=f"{local_world_x},{local_world_y}"))
                        items.append(ContextMenuItem(label="Explore...", action="noop"))
                        items.append(ContextMenuItem(label="- Search (60 ticks)", action="explore", payload="search:60"))
                        items.append(ContextMenuItem(label="- Listen (30 ticks)", action="explore", payload="listen:30"))
                        items.append(ContextMenuItem(label="- Rest (120 ticks)", action="explore", payload="rest:120"))
                        items.append(ContextMenuItem(label="Clear selection", action="clear_selection"))
                else:
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

    layout = _compute_viewer_layout(screen.get_size())
    viewport_rect = layout.world_view
    world_center = (float(viewport_rect.centerx), float(viewport_rect.centery))
    world_zoom_scale = 1.0
    local_camera_cache = LocalCameraCache(center=world_center, zoom_scale=world_zoom_scale)
    panel_scroll = EncounterPanelScrollState()
    inspector_scroll = 0
    inspector_content_rect: pygame.Rect | None = None
    inspector_total_lines = 0
    panel_section_rects: dict[str, pygame.Rect] = {}
    panel_section_counts: dict[str, int] = {}
    active_panel_section = "encounters"
    rumor_panel_state = RumorPanelState()
    debug_filter_state = DebugFilterState()
    follow_state = FollowSelectionState()
    show_local_arena_overlay = False
    debug_panel_cache = DebugPanelRenderCache()

    accumulator = 0.0
    running = True
    context_menu: ContextMenuState | None = None
    previous_snapshot = extract_render_snapshot(sim)
    current_snapshot = previous_snapshot
    tracked_space_id = _entity_space_id(sim.state.entities.get(PLAYER_ID)) or "overworld"
    tick_duration_seconds = SIM_TICK_SECONDS
    last_tick_time = pygame_module.time.get_ticks() / 1000.0
    recent_saves: list[str] = []
    push_recent_save(save_path)
    push_recent_save(load_save)
    status_message: str | None = None
    last_sent_move_vector = (0.0, 0.0)

    while running:
        target_fps = 30 if runtime_state.paused else 60
        dt = clock.tick(target_fps) / 1000.0
        accumulator += dt

        for event in pygame_module.event.get():
            if event.type == pygame_module.QUIT:
                running = False
            elif event.type == pygame_module.VIDEORESIZE:
                screen = pygame_module.display.set_mode((event.w, event.h), pygame_module.RESIZABLE)
                layout = _compute_viewer_layout(screen.get_size())
                viewport_rect = layout.world_view
                local_camera_cache = LocalCameraCache(center=(float(viewport_rect.centerx), float(viewport_rect.centery)), zoom_scale=1.0)
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_ESCAPE:
                running = False
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F2:
                paused = runtime_controller.toggle_pause()
                status_message = f"simulation {'paused' if paused else 'running'}"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F4:
                sim = runtime_controller.new_simulation(map_path=runtime_state.map_path, seed=runtime_state.sim.seed)
                previous_snapshot = extract_render_snapshot(sim)
                current_snapshot = previous_snapshot
                last_tick_time = pygame_module.time.get_ticks() / 1000.0
                status_message = f"new simulation map={runtime_state.map_path} seed={sim.seed}"
                last_sent_move_vector = (0.0, 0.0)
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F5:
                saved_path = runtime_controller.save_simulation()
                push_recent_save(saved_path)
                status_message = f"saved {saved_path}"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F6:
                save_as_path = str(Path(runtime_state.current_save_path).with_name(f"{Path(runtime_state.current_save_path).stem}_save_as.json"))
                saved_path = runtime_controller.save_simulation(save_as_path)
                push_recent_save(saved_path)
                status_message = f"saved as {saved_path}"
            elif event.type == pygame_module.KEYDOWN and event.key in (pygame_module.K_F8, pygame_module.K_F9):
                load_target = runtime_state.current_save_path
                if load_target and Path(load_target).exists():
                    load_simulation_from_path(load_target)
                else:
                    status_message = f"load failed: file not found ({load_target})"
                    print(f"[hexcrawler.viewer] load skipped; file not found path={load_target}")
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_1:
                runtime_controller.advance_ticks(10)
                previous_snapshot = extract_render_snapshot(sim)
                current_snapshot = previous_snapshot
                status_message = "advanced 10 ticks"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_2:
                runtime_controller.advance_ticks(100)
                previous_snapshot = extract_render_snapshot(sim)
                current_snapshot = previous_snapshot
                status_message = "advanced 100 ticks"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_3:
                runtime_controller.advance_ticks(1000)
                previous_snapshot = extract_render_snapshot(sim)
                current_snapshot = previous_snapshot
                status_message = "advanced 1000 ticks"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F3:
                show_local_arena_overlay = not show_local_arena_overlay
                status_message = f"local arena overlay {'on' if show_local_arena_overlay else 'off'}"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F10:
                _cycle_debug_filter_mode(debug_filter_state)
                status_message = _debug_filter_label(debug_filter_state)
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F11:
                _cycle_debug_event_type_filter(sim, debug_filter_state)
                status_message = _debug_filter_label(debug_filter_state)
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F12:
                follow_state.enabled = not follow_state.enabled
                if follow_state.enabled:
                    selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
                    center, follow_message = _apply_follow_selected_camera(
                        sim,
                        selected_entity_id,
                        viewport_rect,
                        zoom_scale=world_zoom_scale,
                        follow_state=follow_state,
                    )
                    if center is not None:
                        world_center = center
                    status_message = follow_message or "follow selected: on"
                else:
                    follow_state.status = FOLLOW_STATUS_OFF
                    status_message = "follow selected: off"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_F7:
                selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
                center, focus_message = _focus_camera_on_selected(
                    sim,
                    selected_entity_id,
                    viewport_rect,
                    zoom_scale=world_zoom_scale,
                )
                if center is not None:
                    world_center = center
                    local_camera_cache.center = center
                status_message = focus_message
            elif event.type == pygame_module.KEYDOWN and event.key in (pygame_module.K_PAGEUP, pygame_module.K_PAGEDOWN):
                delta = -1 if event.key == pygame_module.K_PAGEUP else 1
                panel_scroll.scroll(
                    active_panel_section,
                    delta,
                    panel_section_counts.get(active_panel_section, 0),
                    _scroll_page_size(panel_section_rects.get("rows")),
                )
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button in (4, 5):
                if layout.debug_panel.collidepoint(event.pos):
                    delta = -1 if event.button == 4 else 1
                    if panel_section_rects.get("rows") is not None and panel_section_rects["rows"].collidepoint(event.pos):
                        panel_scroll.scroll(
                            active_panel_section,
                            delta,
                            panel_section_counts.get(active_panel_section, 0),
                            _scroll_page_size(panel_section_rects.get("rows")),
                        )
                    else:
                        for section_name in PANEL_SECTION_ORDER:
                            section_rect = panel_section_rects.get(section_name)
                            if section_rect is not None and section_rect.collidepoint(event.pos):
                                active_panel_section = section_name
                                break
                elif inspector_content_rect is not None and layout.inspector_panel.collidepoint(event.pos):
                    inspector_scroll = _clamp_scroll_offset(
                        inspector_scroll,
                        delta,
                        inspector_total_lines,
                        max(1, inspector_content_rect.height // 16),
                    )
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and layout.debug_panel.collidepoint(event.pos):
                for section_name in PANEL_SECTION_ORDER:
                    section_rect = panel_section_rects.get(section_name)
                    if section_rect is not None and section_rect.collidepoint(event.pos):
                        active_panel_section = section_name
                        break
                if panel_section_rects.get("debug_filter_mode") is not None and panel_section_rects["debug_filter_mode"].collidepoint(event.pos):
                    _cycle_debug_filter_mode(debug_filter_state)
                    status_message = _debug_filter_label(debug_filter_state)
                elif panel_section_rects.get("debug_filter_type") is not None and panel_section_rects["debug_filter_type"].collidepoint(event.pos):
                    _cycle_debug_event_type_filter(sim, debug_filter_state)
                    status_message = _debug_filter_label(debug_filter_state)
                elif active_panel_section == "rumors":
                    if panel_section_rects.get("rumor_kind") is not None and panel_section_rects["rumor_kind"].collidepoint(event.pos):
                        _cycle_rumor_kind_filter(rumor_panel_state)
                        _refresh_rumor_query(controller, rumor_panel_state)
                    elif panel_section_rects.get("rumor_mode") is not None and panel_section_rects["rumor_mode"].collidepoint(event.pos):
                        _toggle_rumor_mode(rumor_panel_state)
                        _refresh_rumor_query(controller, rumor_panel_state)
                    elif panel_section_rects.get("rumor_top_k") is not None and panel_section_rects["rumor_top_k"].collidepoint(event.pos):
                        _cycle_rumor_top_k(rumor_panel_state)
                        _refresh_rumor_query(controller, rumor_panel_state)
                    elif panel_section_rects.get("rumor_next") is not None and panel_section_rects["rumor_next"].collidepoint(event.pos):
                        if rumor_panel_state.next_cursor is not None:
                            rumor_panel_state.cursor_stack.append(rumor_panel_state.cursor)
                            rumor_panel_state.cursor = rumor_panel_state.next_cursor
                            rumor_panel_state.refresh_needed = True
                            _refresh_rumor_query(controller, rumor_panel_state)
                    elif panel_section_rects.get("rumor_prev") is not None and panel_section_rects["rumor_prev"].collidepoint(event.pos):
                        if rumor_panel_state.cursor_stack:
                            rumor_panel_state.cursor = rumor_panel_state.cursor_stack.pop()
                            rumor_panel_state.refresh_needed = True
                            _refresh_rumor_query(controller, rumor_panel_state)
                    elif panel_section_rects.get("rumor_site") is not None and panel_section_rects["rumor_site"].collidepoint(event.pos):
                        rumor_panel_state.editing_field = "site_key"
                        rumor_panel_state.site_key_draft = rumor_panel_state.site_key_filter
                    elif panel_section_rects.get("rumor_group") is not None and panel_section_rects["rumor_group"].collidepoint(event.pos):
                        rumor_panel_state.editing_field = "group_id"
                        rumor_panel_state.group_id_draft = rumor_panel_state.group_id_filter
            elif (
                event.type == pygame_module.KEYDOWN
                and active_panel_section == "rumors"
                and rumor_panel_state.editing_field is not None
            ):
                if event.key == pygame_module.K_RETURN:
                    _apply_rumor_text_filters(rumor_panel_state)
                    rumor_panel_state.editing_field = None
                    _refresh_rumor_query(controller, rumor_panel_state)
                elif event.key == pygame_module.K_ESCAPE:
                    rumor_panel_state.editing_field = None
                elif event.key == pygame_module.K_BACKSPACE:
                    if rumor_panel_state.editing_field == "site_key":
                        rumor_panel_state.site_key_draft = rumor_panel_state.site_key_draft[:-1]
                    else:
                        rumor_panel_state.group_id_draft = rumor_panel_state.group_id_draft[:-1]
                elif isinstance(event.unicode, str) and event.unicode and event.unicode.isprintable():
                    if rumor_panel_state.editing_field == "site_key":
                        rumor_panel_state.site_key_draft += event.unicode
                    else:
                        rumor_panel_state.group_id_draft += event.unicode
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
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and viewport_rect.collidepoint(event.pos):
                status_message = _queue_selection_command_for_click(
                    sim,
                    controller,
                    event.pos,
                    world_center,
                    world_zoom_scale,
                    radius_px=12.0,
                )

        move_x, move_y = _current_input_vector()
        if not rumor_panel_state.request_pending:
            _refresh_rumor_query(controller, rumor_panel_state)
        if (move_x, move_y) != last_sent_move_vector:
            controller.set_move_vector(move_x, move_y)
            last_sent_move_vector = (move_x, move_y)

        accumulator, ticks_advanced = _drain_sim_accumulator(
            accumulator,
            SIM_TICK_SECONDS,
            paused=runtime_state.paused,
        )
        if ticks_advanced > 0:
            previous_snapshot = current_snapshot
            runtime_controller.advance_ticks(ticks_advanced)
            current_snapshot = extract_render_snapshot(sim)
            last_tick_time = pygame_module.time.get_ticks() / 1000.0

        now_seconds = pygame_module.time.get_ticks() / 1000.0
        _consume_rumor_outcome(sim, rumor_panel_state)
        alpha = compute_interpolation_alpha(
            elapsed_seconds=now_seconds - last_tick_time,
            tick_duration_seconds=tick_duration_seconds,
        )

        player = sim.state.entities.get(PLAYER_ID)
        current_space_id = _entity_space_id(player) if player is not None else "overworld"
        if current_space_id is None:
            current_space_id = "overworld"
        if current_space_id != tracked_space_id:
            tracked_space_id = current_space_id
            local_camera_cache = LocalCameraCache(center=(float(viewport_rect.centerx), float(viewport_rect.centery)), zoom_scale=1.0)
            previous_snapshot = current_snapshot
        world_center, world_zoom_scale = _cached_camera_center_and_zoom(sim, viewport_rect, local_camera_cache)
        selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
        follow_center, follow_message = _apply_follow_selected_camera(
            sim,
            selected_entity_id,
            viewport_rect,
            zoom_scale=world_zoom_scale,
            follow_state=follow_state,
        )
        if follow_center is not None:
            world_center = follow_center
            local_camera_cache.center = follow_center
        if follow_message is not None:
            status_message = follow_message

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
        _draw_top_control_bar(screen, sim, font, runtime_state, layout.control_bar, follow_state)
        _draw_hud(screen, sim, font, status_message, hover_message, runtime_state, layout.world_view, follow_state)
        if show_local_arena_overlay:
            _draw_local_arena_overlay(screen, sim, world_center, marker_font, world_zoom_scale, clip_rect=viewport_rect)
        inspector_content_rect, inspector_total_lines = _draw_inspector_panel(
            screen,
            sim,
            debug_font,
            layout.inspector_panel,
            inspector_scroll,
            follow_state,
        )
        panel_section_rects, panel_section_counts = _draw_encounter_debug_panel(
            screen,
            sim,
            debug_font,
            panel_scroll,
            active_panel_section,
            rumor_panel_state,
            debug_filter_state,
            layout.debug_panel,
            debug_panel_cache,
        )
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
