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

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.cli.runtime_profiles import (
    CORE_PLAYABLE,
    DEFAULT_RUNTIME_PROFILE,
    EXPERIMENTAL_WORLD,
    RUNTIME_PROFILE_CHOICES,
    SOAK_AUDIT,
    RuntimeProfile,
    configure_runtime_profile,
    configure_non_encounter_viewer_modules,
)
from hexcrawler.sim.core import HEX_TOPOLOGY_TYPES, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    LIST_RUMORS_INTENT,
    LIST_RUMORS_OUTCOME_KIND,
    LOCAL_ENCOUNTER_REWARD_EVENT_TYPE,
    SELECT_RUMORS_INTENT,
    SELECT_RUMORS_OUTCOME_KIND,
    LocalEncounterInstanceModule,
)
from hexcrawler.sim.campaign_danger import (
    ACCEPT_ENCOUNTER_OFFER_INTENT,
    FLEE_ENCOUNTER_OFFER_INTENT,
    CampaignDangerModule,
)
from hexcrawler.sim.combat import COMBAT_OUTCOME_EVENT_TYPE
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.greybridge_layout import GREYBRIDGE_SAFE_HUB_SPACE_ID, compile_greybridge_overlay
from hexcrawler.sim.exploration import (
    CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
    CAMPAIGN_AUTHOR_OUTCOME_EVENT_TYPE,
    ENTER_SAFE_HUB_INTENT_COMMAND_TYPE,
    EXIT_SAFE_HUB_INTENT_COMMAND_TYPE,
    LOOT_LOCAL_PROOF_INTENT_COMMAND_TYPE,
    EXPLORATION_OUTCOME_EVENT_TYPE,
    LOCAL_STRUCTURE_AUTHOR_INTENT_COMMAND_TYPE,
    LOCAL_STRUCTURE_AUTHOR_OUTCOME_EVENT_TYPE,
    LOCAL_DUNGEON_AUTHOR_INTENT_COMMAND_TYPE,
    RECOVERY_OUTCOME_EVENT_TYPE,
    REWARD_TURN_IN_OUTCOME_EVENT_TYPE,
    REWARD_TOKEN_ITEM_ID,
    SAFE_HUB_OUTCOME_EVENT_TYPE,
    SAFE_RECOVERY_INTENT_COMMAND_TYPE,
    TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
)
from hexcrawler.sim.interactions import INTERACTION_OUTCOME_EVENT_TYPE
from hexcrawler.sim.supplies import SUPPLY_OUTCOME_EVENT_TYPE
from hexcrawler.sim.signals import distance_between_locations
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import (
    axial_to_world_xy,
    normalized_vector,
    square_grid_cell_to_world_xy,
    world_xy_to_axial,
    world_xy_to_square_grid_cell,
)
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, CampaignPatrolRecord, LOCAL_SPACE_ROLE, HexCoord, SiteRecord
from hexcrawler.sim.wounds import (
    WOUND_INCAPACITATE_SEVERITY,
    is_incapacitated_from_wounds,
    movement_multiplier_from_wounds,
    wound_severity_total,
)

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
PENDING_OFFER_DECISION_TICK_CAP = 12
CALENDAR_MONTH_LENGTH_DAYS = 28
CALENDAR_MONTHS: tuple[str, ...] = (
    "Deepfrost",
    "Thawrise",
    "Seedwake",
    "Highsun",
    "Harvestfall",
    "Longnight",
)
MOON_PHASES: tuple[str, ...] = (
    "new",
    "waxing crescent",
    "first quarter",
    "waxing gibbous",
    "full",
    "waning gibbous",
    "last quarter",
    "waning crescent",
)

TERRAIN_COLORS: dict[str, tuple[int, int, int]] = {
    "plains": (132, 168, 94),
    "forest": (61, 120, 72),
    "hills": (153, 126, 90),
}
SITE_COLORS: dict[str, tuple[int, int, int]] = {
    "town": (80, 160, 255),
    "dungeon": (210, 85, 85),
    "dungeon_entrance": (210, 85, 85),
    "ruin": (176, 106, 210),
}
HOME_SITE_IDS: tuple[str, ...] = ("home_greybridge",)
ENCOUNTER_DEBUG_SIGNAL_LIMIT = 10
ENCOUNTER_DEBUG_TRACK_LIMIT = 10
ENCOUNTER_DEBUG_SPAWN_LIMIT = 10
ENCOUNTER_DEBUG_OUTCOME_LIMIT = 20
ENCOUNTER_DEBUG_ENTITY_LIMIT = 20
ENCOUNTER_DEBUG_RUMOR_LIMIT = 20
SUPPLY_DEBUG_OUTCOME_LIMIT = 20
SITE_ENTER_DEBUG_OUTCOME_LIMIT = 20
SITE_PRESSURE_DEBUG_ROW_LIMIT = 5
SITE_EVIDENCE_DEBUG_ROW_LIMIT = 5
ENCOUNTER_DEBUG_SECTION_ROWS = 6
PANEL_SECTION_ENTRY_LIMIT = 30
SELECTED_ENTITY_TRACE_LIMIT = 12
INVENTORY_DEBUG_LINES = 8
RECENT_SAVES_LIMIT = 8
CONTEXT_MENU_WIDTH = 260
CONTEXT_MENU_ROW_HEIGHT = 28
CONTEXT_MENU_TEXT_PADDING_X = 10
CONTEXT_MENU_TEXT_PADDING_Y = 6
CONTEXT_MENU_MIN_WIDTH = 360
LOCAL_VIEWPORT_FILL_RATIO = 0.72
HOME_PANEL_WIDTH = 560
HOME_PANEL_MIN_HEIGHT = 260
HOME_PANEL_BUTTON_HEIGHT = 34
HOME_MARKER_RADIUS = 18
HOME_MARKER_RING_RADIUS = 28
HOME_MARKER_RING_WIDTH = 3
LOCAL_INTERPOLATION_SNAP_DISTANCE = 0.08
RECENT_COMBAT_FEEDBACK_TICK_WINDOW = 20
RECENT_HIT_FLASH_TICK_WINDOW = 4
GREYBRIDGE_USE_PROMPT_RANGE = 1.25
BUILDING_USE_PROMPT_RANGE = 1.8
LOOT_PROMPT_RANGE = 1.8
FACING_SWING_RADIANS_PER_SECOND = 10.0

CORE_PLAYABLE_MAJOR_SITE_IDS: tuple[str, ...] = ("home_greybridge", "demo_dungeon_entrance")
CORE_PLAYABLE_DEFAULT_PATROL_ID = "patrol:core_playable"
CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE = "campaign_danger_patrol"
CORE_PLAYABLE_DEFAULT_PATROL_SPEED = 0.14
CORE_PLAYABLE_DEFAULT_PATROL_WORLD_POSITION: tuple[float, float] = (-2.60, 1.90)
CORE_PLAYABLE_DEFAULT_PATROL_ROUTE: tuple[tuple[float, float], ...] = ((-1.55, 2.4), (-3.2, 1.25))
CORE_PLAYABLE_DEFAULT_PATROL_LABEL = "Old Stair Approach Patrol"
CAMPAIGN_RENDER_LAYER_ORDER: tuple[str, ...] = (
    "map_base",
    "site_icons",
    "site_labels",
    "actors",
    "overlays_selection",
    "hud_panels_modals",
)

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
    payload: object | None = None


@dataclass(frozen=True)
class ContextMenuRowLayout:
    item_index: int
    row_rect: pygame.Rect
    lines: tuple[str, ...]


@dataclass
class ContextMenuState:
    pixel_x: int
    pixel_y: int
    items: tuple[ContextMenuItem, ...]


@dataclass
class HomePanelState:
    visible: bool = False
    site_id: str | None = None


@dataclass
class CampaignAuthoringMoveState:
    kind: str
    object_id: str
    label: str


@dataclass
class CampaignAuthoringPathEditState:
    patrol_id: str
    label: str


@dataclass
class LocalAuthoringMoveState:
    kind: str
    object_id: str
    label: str
    point_kind: str | None = None
    structure_id: str | None = None


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

    def attack_entity(self, target_entity_id: str) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type="attack_intent",
                params={
                    "attacker_id": self.entity_id,
                    "target_id": target_entity_id,
                    "mode": "melee",
                    "tags": ["viewer_local_attack"],
                },
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

    def safe_recovery_intent(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=SAFE_RECOVERY_INTENT_COMMAND_TYPE,
                params={},
            )
        )

    def turn_in_reward_token_intent(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
                params={},
            )
        )

    def enter_safe_hub_intent(self, site_id: str) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=ENTER_SAFE_HUB_INTENT_COMMAND_TYPE,
                params={"site_id": site_id},
            )
        )

    def exit_safe_hub_intent(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=EXIT_SAFE_HUB_INTENT_COMMAND_TYPE,
                params={},
            )
        )

    def loot_local_proof_intent(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=LOOT_LOCAL_PROOF_INTENT_COMMAND_TYPE,
                params={},
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

    def local_structure_author_intent(self, operation: str, **params: object) -> None:
        payload = {"operation": operation}
        payload.update(params)
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=LOCAL_STRUCTURE_AUTHOR_INTENT_COMMAND_TYPE,
                params=payload,
            )
        )

    def local_dungeon_author_intent(self, operation: str, **params: object) -> None:
        payload = {"operation": operation}
        payload.update(params)
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=LOCAL_DUNGEON_AUTHOR_INTENT_COMMAND_TYPE,
                params=payload,
            )
        )

    def campaign_author_intent(self, operation: str, **params: object) -> None:
        payload = {"operation": operation}
        payload.update(params)
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
                params=payload,
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

    def accept_encounter_offer(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,
                params={"entity_id": self.entity_id},
            )
        )

    def flee_encounter_offer(self) -> None:
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=self.entity_id,
                command_type=FLEE_ENCOUNTER_OFFER_INTENT,
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
    runtime_profile: RuntimeProfile | None = None
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

    def _resolved_runtime_profile(self) -> RuntimeProfile | None:
        if self.state.runtime_profile is not None:
            return self.state.runtime_profile
        return None

    def replace_simulation(self, sim: Simulation, *, identity: str | None = None) -> None:
        self.state.sim = sim
        self.controller.sim = sim
        if identity is not None:
            self.state.last_loaded_identity = identity

    def new_simulation(self, *, map_path: str | None = None, seed: int | None = None) -> Simulation:
        next_map = map_path if map_path is not None else self.state.map_path
        next_seed = self.state.sim.seed if seed is None else int(seed)
        resolved_profile = self._resolved_runtime_profile()
        if resolved_profile is None:
            sim = _build_viewer_simulation(next_map, with_encounters=self.state.with_encounters, seed=next_seed)
        else:
            sim = _build_viewer_simulation(next_map, runtime_profile=resolved_profile, seed=next_seed)
        self.state.map_path = next_map
        self.replace_simulation(sim, identity=f"map:{Path(next_map).name}")
        return sim

    def load_simulation(self, path: str) -> Simulation:
        resolved_profile = self._resolved_runtime_profile()
        if resolved_profile is None:
            sim = _load_viewer_simulation(path, with_encounters=self.state.with_encounters)
        else:
            sim = _load_viewer_simulation(path, runtime_profile=resolved_profile)
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

    def resolve_pending_offer_decision(self, *, tick_cap: int = PENDING_OFFER_DECISION_TICK_CAP) -> int:
        """Advance bounded authoritative ticks so pending-offer decision commands are consumed."""
        cap = max(1, int(tick_cap))
        advanced = 0
        while _pending_encounter_offer(self.state.sim) is not None and advanced < cap:
            self.state.sim.advance_ticks(1)
            advanced += 1
        return advanced


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
    pending_action_uid: str | None = None
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
    return f"debug filter: mode={debug_filter_state.mode} event_type={event_type}"


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
        f"tick={tick} | event={event_type} | action_uid={action_uid} | source_action_uid={source_action_uid} | "
        f"source_event_id={source_event_id} | request_event_id={request_event_id}"
    )

@dataclass(frozen=True)
class MarkerRecord:
    priority: int
    marker_id: str
    marker_kind: str
    color: tuple[int, int, int]
    radius: int
    label: str
    world_position: tuple[float, float] | None = None
    is_major_campaign_site: bool = False


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


@dataclass(frozen=True)
class CampaignSiteProjection:
    site_id: str
    site_name: str
    site_type: str
    anchor_source: str
    world_position: tuple[float, float]
    screen_position: tuple[int, int]
    on_screen: bool


@dataclass(frozen=True)
class MajorSiteEdgeIndicator:
    site_id: str
    site_name: str
    marker_color: tuple[int, int, int]
    position: tuple[int, int]
    label_position: tuple[int, int]
    label: str


def _is_major_campaign_site(site: SiteRecord) -> bool:
    site_type = str(site.site_type)
    tag_set = {str(tag) for tag in site.tags}
    if "major" in tag_set:
        return True
    if site_type in {"town", "dungeon", "dungeon_entrance"}:
        return True
    if site.entrance is not None:
        return True
    if "safe" in tag_set:
        return True
    return False


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_interpolation_alpha(*, elapsed_seconds: float, tick_duration_seconds: float) -> float:
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0.0:
        return 0.0
    if not math.isfinite(tick_duration_seconds) or tick_duration_seconds <= 0.0:
        return 1.0
    linear_alpha = clamp01(elapsed_seconds / tick_duration_seconds)
    return (linear_alpha * linear_alpha) * (3.0 - (2.0 * linear_alpha))


def lerp(start: float, end: float, alpha: float) -> float:
    return start + (end - start) * alpha


def _facing_angle_radians(facing: int) -> float:
    return (int(facing) % 6) * (math.pi / 3.0)


def _display_heading_angle_from_motion(
    *,
    previous_snapshot: RenderSnapshot,
    current_snapshot: RenderSnapshot,
    entity_id: str,
    fallback_angle: float | None = None,
) -> float | None:
    """Viewer-only display heading derived from motion, never serialized or authoritative."""
    previous = previous_snapshot.get(entity_id)
    current = current_snapshot.get(entity_id)
    if previous is None or current is None:
        return fallback_angle
    delta_x = float(current.x) - float(previous.x)
    delta_y = float(current.y) - float(previous.y)
    if math.hypot(delta_x, delta_y) <= 1e-9:
        return fallback_angle
    return math.atan2(delta_y, delta_x)


def _normalize_angle_signed(angle: float) -> float:
    wrapped = (angle + math.pi) % (2.0 * math.pi)
    return wrapped - math.pi


def _swing_facing_angle(current_angle: float, target_angle: float, *, max_step: float) -> float:
    if not math.isfinite(current_angle):
        return target_angle
    delta = _normalize_angle_signed(target_angle - current_angle)
    if abs(delta) <= max_step:
        return target_angle
    return current_angle + math.copysign(max_step, delta)


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
    if math.hypot(current.x - previous.x, current.y - previous.y) <= LOCAL_INTERPOLATION_SNAP_DISTANCE:
        return (current.x, current.y)
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


def _supported_viewer_topology(active_space: Any | None) -> str:
    if active_space is None:
        return OVERWORLD_HEX_TOPOLOGY
    topology_type = str(getattr(active_space, "topology_type", OVERWORLD_HEX_TOPOLOGY))
    if topology_type in HEX_TOPOLOGY_TYPES:
        return OVERWORLD_HEX_TOPOLOGY
    if topology_type in (OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY):
        return topology_type
    return "unsupported"


def _viewer_topology_diagnostic(active_space: Any | None) -> str | None:
    topology_type = _supported_viewer_topology(active_space)
    if topology_type != "unsupported":
        return None
    raw_topology_type = str(getattr(active_space, "topology_type", "?"))
    return f"unsupported_topology={raw_topology_type} (viewer projection disabled)"


def _marker_payload_id(marker: MarkerRecord, *, expected_kind: str | None = None) -> str | None:
    marker_id = marker.marker_id if isinstance(marker.marker_id, str) else ""
    if ":" not in marker_id:
        return None
    marker_kind, payload = marker_id.split(":", 1)
    if expected_kind is not None and marker_kind != expected_kind:
        return None
    payload = payload.strip()
    if not payload:
        return None
    return payload


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


def _site_label_for_marker(site: SiteRecord) -> str:
    label_source = site.name if isinstance(site.name, str) and site.name.strip() else site.site_id
    return _truncate_label(label_source, max_length=16)


def _site_marker_style(site: SiteRecord) -> tuple[tuple[int, int, int], int]:
    if site.site_type == "town":
        return SITE_COLORS.get("town", (80, 160, 255)), 11
    if site.site_type in {"dungeon", "dungeon_entrance", "ruin"}:
        return SITE_COLORS.get(site.site_type, SITE_COLORS.get("dungeon", (210, 85, 85))), 9
    return SITE_COLORS.get(site.site_type, (245, 245, 120)), 7


def _site_campaign_anchor_world(site: SiteRecord) -> tuple[float, float] | None:
    location = site.location if isinstance(site.location, dict) else {}
    anchor = location.get("campaign_anchor")
    if isinstance(anchor, dict):
        try:
            return float(anchor["x"]), float(anchor["y"])
        except (KeyError, TypeError, ValueError):
            pass
    coord = location.get("coord")
    if not isinstance(coord, dict):
        return None
    topology_type = str(location.get("topology_type", OVERWORLD_HEX_TOPOLOGY))
    if topology_type in HEX_TOPOLOGY_TYPES:
        try:
            return axial_to_world_xy(HexCoord(q=int(coord["q"]), r=int(coord["r"])))
        except (KeyError, TypeError, ValueError):
            return None
    if topology_type == SQUARE_GRID_TOPOLOGY:
        try:
            return float(coord["x"]) + 0.5, float(coord["y"]) + 0.5
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _site_world_position(site: SiteRecord) -> tuple[tuple[float, float] | None, str]:
    anchor_position = _site_campaign_anchor_world(site)
    location = site.location if isinstance(site.location, dict) else {}
    has_explicit_anchor = isinstance(location.get("campaign_anchor"), dict)
    if anchor_position is not None:
        return anchor_position, "campaign_anchor" if has_explicit_anchor else "legacy_hex_fallback"
    return None, "unsupported"


def _campaign_site_projections(
    sim: Simulation,
    center: tuple[float, float],
    zoom_scale: float,
    *,
    clip_rect: pygame.Rect | None = None,
) -> list[CampaignSiteProjection]:
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    if active_space is None or str(getattr(active_space, "role", "")) != "campaign":
        return []
    projections: list[CampaignSiteProjection] = []
    for site in sorted(sim.state.world.sites.values(), key=lambda current: current.site_id):
        if site.location.get("space_id") != active_space.space_id:
            continue
        world_position, anchor_source = _site_world_position(site)
        if world_position is None:
            continue
        px, py = _world_to_pixel(world_position[0], world_position[1], center, zoom_scale)
        point = (int(round(px)), int(round(py)))
        on_screen = True if clip_rect is None else clip_rect.collidepoint(point)
        projections.append(
            CampaignSiteProjection(
                site_id=site.site_id,
                site_name=site.name if isinstance(site.name, str) and site.name.strip() else site.site_id,
                site_type=site.site_type,
                anchor_source=anchor_source,
                world_position=world_position,
                screen_position=point,
                on_screen=on_screen,
            )
        )
    return projections


def _major_campaign_site_projections(
    sim: Simulation,
    center: tuple[float, float],
    zoom_scale: float,
    *,
    clip_rect: pygame.Rect | None = None,
) -> list[CampaignSiteProjection]:
    projections: list[CampaignSiteProjection] = []
    for row in _campaign_site_projections(sim, center, zoom_scale, clip_rect=clip_rect):
        site = sim.state.world.sites.get(row.site_id)
        if site is None or not _is_major_campaign_site(site):
            continue
        projections.append(row)
    return projections


def _campaign_site_diagnostic_rows(
    sim: Simulation,
    center: tuple[float, float],
    zoom_scale: float,
    *,
    clip_rect: pygame.Rect,
    max_rows: int = 6,
) -> list[str]:
    projections = _campaign_site_projections(sim, center, zoom_scale, clip_rect=clip_rect)
    if not projections:
        return ["campaign_sites loaded=0 visible=0 (campaign role only)"]
    sorted_rows = sorted(projections, key=lambda row: (row.site_id, row.site_type))
    visible_count = sum(1 for row in sorted_rows if row.on_screen)
    lines = [f"campaign_sites loaded={len(sorted_rows)} visible={visible_count} showing={min(max_rows, len(sorted_rows))}"]
    for row in sorted_rows[:max_rows]:
        lines.append(
            "site "
            f"id={row.site_id} type={row.site_type} anchor={row.anchor_source} "
            f"world=({row.world_position[0]:.2f},{row.world_position[1]:.2f}) "
            f"screen=({row.screen_position[0]},{row.screen_position[1]}) "
            f"on_screen={'yes' if row.on_screen else 'no'}"
        )
    return lines


def _major_site_visibility_diagnostic_rows(
    sim: Simulation,
    center: tuple[float, float],
    zoom_scale: float,
    *,
    clip_rect: pygame.Rect,
) -> list[str]:
    player = sim.state.entities.get(PLAYER_ID)
    if player is None:
        return ["campaign_major_sites player=missing"]
    player_hex = world_xy_to_axial(player.position_x, player.position_y)
    lines = [
        (
            "campaign_major_sites "
            f"player_world=({player.position_x:.2f},{player.position_y:.2f}) "
            f"player_hex=({player_hex.q},{player_hex.r})"
        )
    ]
    max_sites = 6
    for row in sorted(
        _major_campaign_site_projections(sim, center, zoom_scale, clip_rect=clip_rect),
        key=lambda current: current.site_id,
    )[:max_sites]:
        lines.append(
            "major_site "
            f"id={row.site_id} type={row.site_type} "
            f"world=({row.world_position[0]:.2f},{row.world_position[1]:.2f}) "
            f"screen=({row.screen_position[0]},{row.screen_position[1]}) "
            f"on_screen={'yes' if row.on_screen else 'no'}"
        )
    if len(lines) == 1:
        lines.append("major_site none")
    greybridge = sim.state.world.sites.get("home_greybridge")
    if greybridge is not None:
        greybridge_world, _ = _site_world_position(greybridge)
        if greybridge_world is not None:
            gx, gy = _world_to_pixel(greybridge_world[0], greybridge_world[1], center, zoom_scale)
            point = (int(round(gx)), int(round(gy)))
            lines.append(
                "major_site_focus "
                "id=home_greybridge "
                f"world=({greybridge_world[0]:.2f},{greybridge_world[1]:.2f}) "
                f"screen=({point[0]},{point[1]}) "
                f"on_screen={'yes' if clip_rect.collidepoint(point) else 'no'}"
            )
    dungeon_site: SiteRecord | None = None
    for site in sorted(sim.state.world.sites.values(), key=lambda row: row.site_id):
        if site.entrance is not None or site.site_type in {"dungeon", "dungeon_entrance"}:
            dungeon_site = site
            break
    if dungeon_site is not None:
        dungeon_world, _ = _site_world_position(dungeon_site)
        if dungeon_world is not None:
            dx, dy = _world_to_pixel(dungeon_world[0], dungeon_world[1], center, zoom_scale)
            point = (int(round(dx)), int(round(dy)))
            lines.append(
                "major_site_focus "
                f"id={dungeon_site.site_id} "
                f"world=({dungeon_world[0]:.2f},{dungeon_world[1]:.2f}) "
                f"screen=({point[0]},{point[1]}) "
                f"on_screen={'yes' if clip_rect.collidepoint(point) else 'no'}"
            )
    return lines


def _major_site_label_offset(
    site_screen: tuple[int, int],
    player_screen: tuple[int, int] | None,
) -> tuple[int, int, bool]:
    if player_screen is None:
        return (12, -16, False)
    if math.dist((float(site_screen[0]), float(site_screen[1])), (float(player_screen[0]), float(player_screen[1]))) <= 24.0:
        return (22, -34, True)
    return (12, -16, False)


def _major_site_edge_indicators(
    sim: Simulation,
    major_projections: list[CampaignSiteProjection],
    *,
    clip_rect: pygame.Rect,
) -> list[MajorSiteEdgeIndicator]:
    margin = 18
    min_x = clip_rect.left + margin
    max_x = clip_rect.right - margin
    min_y = clip_rect.top + margin
    max_y = clip_rect.bottom - margin
    center_x = float(clip_rect.centerx)
    center_y = float(clip_rect.centery)
    indicators: list[MajorSiteEdgeIndicator] = []
    for projection in major_projections:
        if projection.on_screen:
            continue
        site = sim.state.world.sites.get(projection.site_id)
        if site is None:
            continue
        marker_color, _ = _site_marker_style(site)
        raw_x = projection.screen_position[0]
        raw_y = projection.screen_position[1]
        clamped_x = max(min_x, min(max_x, raw_x))
        clamped_y = max(min_y, min(max_y, raw_y))
        label = _truncate_label(f"{projection.site_name} ↗", max_length=18)
        if raw_x < center_x:
            label_x = clamped_x + 10
        else:
            label_x = clamped_x - 120
        if raw_y < center_y:
            label_y = clamped_y + 8
        else:
            label_y = clamped_y - 18
        indicators.append(
            MajorSiteEdgeIndicator(
                site_id=projection.site_id,
                site_name=projection.site_name,
                marker_color=marker_color,
                position=(clamped_x, clamped_y),
                label_position=(label_x, label_y),
                label=label,
            )
        )
    return indicators


def _clamp_scroll_offset(current: int, delta: int, total_count: int, page_size: int) -> int:
    max_offset = max(0, total_count - page_size)
    return max(0, min(max_offset, current + delta))


def _scroll_page_size(rect: pygame.Rect | None, line_height: int = 16) -> int:
    if rect is None:
        return ENCOUNTER_DEBUG_SECTION_ROWS
    return max(1, rect.height // line_height)


def _section_entries(rows: list[str], *, entry_limit: int = PANEL_SECTION_ENTRY_LIMIT) -> list[str]:
    return list(reversed(rows[-entry_limit:]))


def _collect_world_markers(
    sim: Simulation,
    active_space_id: str,
    active_location_topology: str,
    *,
    include_incidental_records: bool,
) -> dict[MarkerCellRef, list[MarkerRecord]]:
    markers_by_cell: dict[MarkerCellRef, list[MarkerRecord]] = {}

    def add_marker(cell: MarkerCellRef | None, marker: MarkerRecord) -> None:
        if cell is None or not _is_in_current_space(cell.space_id, active_space_id) or cell.topology_type != active_location_topology:
            return
        markers_by_cell.setdefault(cell, []).append(marker)

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
            label = interactable.kind
            if isinstance(getattr(interactable, "metadata", None), dict):
                meta_label = interactable.metadata.get("label")
                if isinstance(meta_label, str) and meta_label.strip():
                    label = meta_label.strip()
            marker_color = (170, 170, 255)
            marker_radius = 5
            interactable_id = str(getattr(interactable, "interactable_id", ""))
            if interactable_id == "watch_hall":
                marker_color = (105, 176, 255)
                marker_radius = 7
                label = "Watch Hall (Turn-In)"
            elif interactable_id == "inn_infirmary":
                marker_color = (170, 226, 186)
                marker_radius = 7
                label = "Inn/Infirmary (Recover)"
            elif interactable_id == "town_gate_exit":
                marker_color = (238, 200, 124)
                marker_radius = 7
                label = "Gate (Exit to Campaign)"
            add_marker(
                _marker_cell_from_location(
                    {"space_id": active_space_id, "topology_type": space.topology_type, "coord": interactable.coord},
                    active_location_topology,
                ),
                MarkerRecord(
                    priority=0,
                    marker_id=f"interactable:{interactable.interactable_id}",
                    marker_kind="interactable",
                    color=marker_color,
                    radius=marker_radius,
                    label=_truncate_label(label, max_length=26),
                ),
            )
        for spawner in sorted(getattr(space, "local_hostile_spawners", []), key=lambda row: str(row.get("spawner_id", ""))):
            if not isinstance(spawner, dict):
                continue
            coord = spawner.get("coord")
            if not isinstance(coord, dict):
                continue
            add_marker(
                _marker_cell_from_location(
                    {"space_id": active_space_id, "topology_type": space.topology_type, "coord": coord},
                    active_location_topology,
                ),
                MarkerRecord(
                    priority=0,
                    marker_id=f"local_spawner:{spawner.get('spawner_id', '')}",
                    marker_kind="local_spawner",
                    color=(230, 120, 120),
                    radius=5,
                    label=_truncate_label(str(spawner.get("label", "hostile")), max_length=16),
                ),
            )
        for point in sorted(getattr(space, "local_transition_points", []), key=lambda row: str(row.get("point_id", ""))):
            if not isinstance(point, dict):
                continue
            coord = point.get("coord")
            if not isinstance(coord, dict):
                continue
            point_kind = str(point.get("point_kind", ""))
            marker_color = (145, 220, 160)
            if point_kind == "entry_anchor":
                marker_color = (123, 188, 255)
            elif point_kind == "extraction_exit":
                marker_color = (240, 204, 96)
            add_marker(
                _marker_cell_from_location(
                    {"space_id": active_space_id, "topology_type": space.topology_type, "coord": coord},
                    active_location_topology,
                ),
                MarkerRecord(
                    priority=0,
                    marker_id=f"local_transition:{point.get('point_id', '')}",
                    marker_kind="local_transition",
                    color=marker_color,
                    radius=5,
                    label=_truncate_label(str(point.get("label", point_kind)), max_length=18),
                ),
            )

    for entity in sorted(sim.state.entities.values(), key=lambda current: current.entity_id):
        entity_space_id = _entity_space_id(entity)
        if not _is_in_current_space(entity_space_id, active_space_id):
            continue
        if entity.entity_id == PLAYER_ID:
            # Player is rendered through interpolation in the primary entity pass.
            continue
        if str(entity.template_id or "") == "encounter_hostile_v1":
            # Local hostiles already render in the entity pass; adding a marker dot duplicates them.
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

    player = sim.state.entities.get(PLAYER_ID)
    if player is not None:
        player_space_id = _entity_space_id(player)
        if isinstance(player_space_id, str):
            return_context = _get_return_context_for_space(sim, player_space_id)
            if isinstance(return_context, dict):
                return_exit_coord = return_context.get("return_exit_coord")
                if isinstance(return_exit_coord, dict):
                    add_marker(
                        _marker_cell_from_location(
                            {
                                "space_id": player_space_id,
                                "topology_type": SQUARE_GRID_TOPOLOGY,
                                "coord": return_exit_coord,
                            },
                            active_location_topology,
                        ),
                        MarkerRecord(
                            priority=1,
                            marker_id=f"return_exit:{player_space_id}",
                            marker_kind="return_exit",
                            color=(145, 220, 160),
                            radius=5,
                            label="extract",
                        ),
                    )

    if include_incidental_records:
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


def _world_marker_placements(
    sim: Simulation,
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    include_incidental_records: bool = True,
) -> list[MarkerPlacement]:
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    if active_space is None:
        return []
    projection_topology = _supported_viewer_topology(active_space)
    if projection_topology == "unsupported":
        return []
    placements: list[MarkerPlacement] = []
    major_site_projections = _major_campaign_site_projections(sim, center, zoom_scale)
    major_site_ids = {row.site_id for row in major_site_projections}
    for site_projection in major_site_projections:
        site = sim.state.world.sites.get(site_projection.site_id)
        if site is None:
            continue
        marker_color, marker_radius = _site_marker_style(site)
        placements.append(
            MarkerPlacement(
                marker=MarkerRecord(
                    priority=-1 if site.site_type == "town" else 0,
                    marker_id=f"site:{site.site_id}",
                    marker_kind="site",
                    color=marker_color,
                    radius=marker_radius,
                    label=_site_label_for_marker(site),
                    world_position=site_projection.world_position,
                    is_major_campaign_site=True,
                ),
                x=site_projection.screen_position[0],
                y=site_projection.screen_position[1],
            )
        )
    for site_projection in _campaign_site_projections(sim, center, zoom_scale):
        if site_projection.site_id in major_site_ids:
            continue
        site = sim.state.world.sites.get(site_projection.site_id)
        if site is None:
            continue
        marker_color, marker_radius = _site_marker_style(site)
        placements.append(
            MarkerPlacement(
                marker=MarkerRecord(
                    priority=0,
                    marker_id=f"site:{site.site_id}",
                    marker_kind="site",
                    color=marker_color,
                    radius=marker_radius,
                    label=_site_label_for_marker(site),
                    world_position=site_projection.world_position,
                ),
                x=site_projection.screen_position[0],
                y=site_projection.screen_position[1],
            )
        )
    markers_by_cell = _collect_world_markers(
        sim,
        active_space.space_id,
        projection_topology,
        include_incidental_records=include_incidental_records,
    )
    for cell in sorted(markers_by_cell, key=lambda current: (current.space_id, current.topology_type, current.coord_key)):
        cell_markers = markers_by_cell[cell]
        anchored_markers = [marker for marker in cell_markers if marker.world_position is not None]
        for marker in anchored_markers:
            world_position = marker.world_position
            if world_position is None:
                continue
            px, py = _world_to_pixel(world_position[0], world_position[1], center, zoom_scale)
            placements.append(MarkerPlacement(marker=marker, x=int(round(px)), y=int(round(py))))
        unslotted_markers = [marker for marker in cell_markers if marker.world_position is None]
        if not unslotted_markers:
            continue
        center_x, center_y = _marker_cell_center(cell, center, zoom_scale)
        slotted, _ = _slot_markers_for_hex(center_x, center_y, unslotted_markers, cell)
        placements.extend(slotted)
    return placements


def _draw_major_site_edge_indicators(
    screen: pygame.Surface,
    sim: Simulation,
    major_projections: list[CampaignSiteProjection],
    font: pygame.font.Font,
    *,
    clip_rect: pygame.Rect,
) -> None:
    for indicator in _major_site_edge_indicators(sim, major_projections, clip_rect=clip_rect):
        indicator_radius = 7
        pygame.draw.circle(screen, (22, 24, 30), indicator.position, indicator_radius + 2)
        pygame.draw.circle(screen, indicator.marker_color, indicator.position, indicator_radius)
        pygame.draw.circle(screen, (248, 250, 255), indicator.position, indicator_radius, 1)
        text_surface = font.render(indicator.label, True, (248, 250, 255))
        outline_surface = font.render(indicator.label, True, (18, 20, 25))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            screen.blit(outline_surface, (indicator.label_position[0] + dx, indicator.label_position[1] + dy))
        screen.blit(text_surface, indicator.label_position)


def _draw_major_campaign_sites(
    screen: pygame.Surface,
    sim: Simulation,
    center: tuple[float, float],
    font: pygame.font.Font,
    *,
    clip_rect: pygame.Rect,
    zoom_scale: float = 1.0,
) -> None:
    major_projections = _major_campaign_site_projections(sim, center, zoom_scale, clip_rect=clip_rect)
    player = sim.state.entities.get(PLAYER_ID)
    player_screen: tuple[int, int] | None = None
    if player is not None:
        px, py = _world_to_pixel(player.position_x, player.position_y, center, zoom_scale)
        player_screen = (int(round(px)), int(round(py)))
    for projection in major_projections:
        if not projection.on_screen:
            continue
        site = sim.state.world.sites.get(projection.site_id)
        if site is None:
            continue
        marker_color, marker_radius = _site_marker_style(site)
        icon_pos = projection.screen_position
        label_dx, label_dy, overlaps_player = _major_site_label_offset(icon_pos, player_screen)
        ring_radius = max(HOME_MARKER_RING_RADIUS, marker_radius + 10) + (5 if overlaps_player else 0)
        pygame.draw.circle(screen, (255, 248, 180), icon_pos, ring_radius, HOME_MARKER_RING_WIDTH)
        pygame.draw.circle(screen, (36, 28, 12), icon_pos, ring_radius + 1, 1)
        pygame.draw.circle(screen, marker_color, icon_pos, max(marker_radius + 2, 12))
        pygame.draw.circle(screen, (10, 14, 20), icon_pos, max(marker_radius + 2, 12), 2)
        label = _site_label_for_marker(site)
        label_surface = font.render(label, True, (248, 250, 255))
        outline_surface = font.render(label, True, (18, 20, 25))
        label_pos = (icon_pos[0] + label_dx, icon_pos[1] + label_dy)
        label_box = label_surface.get_rect(topleft=label_pos)
        padded = pygame.Rect(label_box.left - 4, label_box.top - 2, label_box.width + 8, label_box.height + 4)
        pygame.draw.rect(screen, (32, 34, 40), padded, border_radius=4)
        pygame.draw.rect(screen, marker_color, padded, 1, border_radius=4)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            screen.blit(outline_surface, (label_pos[0] + dx, label_pos[1] + dy))
        screen.blit(label_surface, label_pos)
    _draw_major_site_edge_indicators(screen, sim, major_projections, font, clip_rect=clip_rect)


def _draw_site_markers_and_labels(
    screen: pygame.Surface,
    placements: list[MarkerPlacement],
    font: pygame.font.Font,
) -> None:
    for placement in placements:
        if placement.marker.marker_kind != "site":
            continue
        if placement.marker.is_major_campaign_site:
            continue
        if placement.marker.radius >= 11:
            pygame.draw.circle(screen, (255, 248, 180), (placement.x, placement.y), HOME_MARKER_RING_RADIUS, HOME_MARKER_RING_WIDTH)
            pygame.draw.circle(screen, (36, 28, 12), (placement.x, placement.y), HOME_MARKER_RING_RADIUS + 1, 1)
        pygame.draw.circle(screen, placement.marker.color, (placement.x, placement.y), placement.marker.radius)
        pygame.draw.circle(screen, (14, 24, 30), (placement.x, placement.y), placement.marker.radius, 1)
        label_surface = font.render(placement.marker.label, True, (248, 250, 255))
        outline_surface = font.render(placement.marker.label, True, (18, 20, 25))
        if placement.marker.radius >= 11:
            label_box = label_surface.get_rect()
            label_box.topleft = (placement.x + 10, placement.y - 10)
            padded = pygame.Rect(label_box.left - 4, label_box.top - 2, label_box.width + 8, label_box.height + 4)
            pygame.draw.rect(screen, (32, 34, 40), padded, border_radius=4)
            pygame.draw.rect(screen, placement.marker.color, padded, 1, border_radius=4)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            screen.blit(outline_surface, (placement.x + 8 + dx, placement.y - 8 + dy))
        screen.blit(label_surface, (placement.x + 8, placement.y - 8))


def _draw_non_site_markers(
    screen: pygame.Surface,
    placements: list[MarkerPlacement],
    font: pygame.font.Font,
) -> None:
    for placement in placements:
        if placement.marker.marker_kind == "site":
            continue
        pygame.draw.circle(screen, placement.marker.color, (placement.x, placement.y), placement.marker.radius)
        pygame.draw.circle(screen, (14, 24, 30), (placement.x, placement.y), placement.marker.radius, 1)
        label_surface = font.render(placement.marker.label, True, (248, 250, 255))
        outline_surface = font.render(placement.marker.label, True, (18, 20, 25))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            screen.blit(outline_surface, (placement.x + 8 + dx, placement.y - 8 + dy))
        screen.blit(label_surface, (placement.x + 8, placement.y - 8))


def _draw_world_markers(
    screen: pygame.Surface,
    sim: Simulation,
    center: tuple[float, float],
    font: pygame.font.Font,
    clip_rect: pygame.Rect,
    zoom_scale: float = 1.0,
) -> None:
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    include_incidental_records = True
    if active_space is not None and str(getattr(active_space, "role", "")) == "campaign":
        include_incidental_records = sim.get_rule_module("signal_propagation") is not None
    placements = _world_marker_placements(
        sim,
        center,
        zoom_scale,
        include_incidental_records=include_incidental_records,
    )
    _draw_site_markers_and_labels(screen, placements, font)
    _draw_non_site_markers(screen, placements, font)


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
    topology_diagnostic = _viewer_topology_diagnostic(active_space)
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
        _draw_greybridge_hub_bounds(screen, active_space=active_space, center=center, zoom_scale=zoom_scale)
        _draw_world_markers(screen, sim, center, marker_font, clip_rect=clip_rect, zoom_scale=zoom_scale)
        screen.set_clip(old_clip)
        return

    if topology_diagnostic is not None:
        text = _truncate_text_to_pixel_width(topology_diagnostic, marker_font, max(1, clip_rect.width - 20))
        screen.blit(marker_font.render(text, True, (250, 192, 128)), (clip_rect.x + 10, clip_rect.y + 10))
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
        _draw_world_markers(screen, sim, center, marker_font, clip_rect=clip_rect, zoom_scale=zoom_scale)
    screen.set_clip(old_clip)


def _draw_greybridge_hub_bounds(
    screen: pygame.Surface,
    *,
    active_space: Any,
    center: tuple[float, float],
    zoom_scale: float,
) -> None:
    if getattr(active_space, "space_id", "") != GREYBRIDGE_SAFE_HUB_SPACE_ID:
        return
    cell_size = HEX_SIZE * zoom_scale
    structure_primitives = getattr(active_space, "structure_primitives", []) if active_space is not None else []
    compiled_overlay = compile_greybridge_overlay(structure_primitives)
    opening_by_cell: dict[tuple[int, int], dict[str, object]] = {}
    for row in compiled_overlay["opening_rows"]:
        if not isinstance(row, dict):
            continue
        cell = row.get("cell")
        if not isinstance(cell, dict):
            continue
        try:
            key = (int(cell["x"]), int(cell["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        opening_by_cell[key] = row

    def to_px(x: float, y: float) -> tuple[int, int]:
        return (int(center[0] + x * cell_size), int(center[1] + y * cell_size))

    for segment in compiled_overlay["wall_segments"]:
        if not isinstance(segment, dict):
            continue
        x0 = float(segment.get("x0", 0))
        y0 = float(segment.get("y0", 0))
        x1 = float(segment.get("x1", 0))
        y1 = float(segment.get("y1", 0))
        p0 = to_px(x0, y0)
        p1 = to_px(x1, y1)
        pygame.draw.line(screen, (152, 164, 186), p0, p1, max(2, int(2 * zoom_scale)))

    for door_x, door_y in compiled_overlay["opening_cells"]:
        opening = opening_by_cell.get((int(door_x), int(door_y)), {})
        kind = str(opening.get("kind", "opening"))
        fill = (212, 189, 96)
        if kind == "gate_portal":
            fill = (176, 220, 124)
        px, py = to_px(float(door_x) + 0.5, float(door_y) + 0.5)
        pygame.draw.rect(screen, fill, pygame.Rect(px - 6, py - 3, 12, 6))


def _draw_frame_layers(
    *,
    screen: pygame.Surface,
    sim: Simulation,
    world_center: tuple[float, float],
    world_zoom_scale: float,
    viewport_rect: pygame.Rect,
    marker_font: pygame.font.Font,
    font: pygame.font.Font,
    debug_font: pygame.font.Font,
    status_message: str,
    hover_message: str | None,
    runtime_state: ViewerRuntimeState,
    follow_state: FollowSelectionState,
    show_local_arena_overlay: bool,
    layout: ViewerLayout,
    inspector_scroll: int,
    panel_scroll: dict[str, int],
    active_panel_section: str,
    rumor_panel_state: RumorPanelState,
    debug_filter_state: DebugFilterState,
    debug_panel_cache: DebugPanelRenderCache,
    home_panel_state: HomePanelState,
    context_menu: ContextMenuState | None,
    campaign_path_edit_state: CampaignAuthoringPathEditState | None,
    previous_snapshot: RenderSnapshot,
    current_snapshot: RenderSnapshot,
    current_space_id: str,
    alpha: float,
    visual_facing_by_entity: dict[str, float],
) -> tuple[pygame.Rect | None, int, dict[str, pygame.Rect], dict[str, int], dict[str, pygame.Rect]]:
    # Explicit campaign render-layer ownership:
    # 1) map_base, 2) site_icons, 3) site_labels, 4) actors/moving groups,
    # 5) overlays/selection, 6) HUD/panels/modals.
    _draw_world(screen, sim, world_center, marker_font, clip_rect=viewport_rect, zoom_scale=world_zoom_scale)
    player = sim.state.entities.get(PLAYER_ID)
    if player is not None:
        active_space = sim.state.world.spaces.get(player.space_id)
        if active_space is not None and str(getattr(active_space, "role", "")) == CAMPAIGN_SPACE_ROLE:
            _draw_campaign_patrol_routes(
                screen,
                sim,
                world_center=world_center,
                world_zoom_scale=world_zoom_scale,
                world_rect=viewport_rect,
                font=marker_font,
                campaign_path_edit_state=campaign_path_edit_state,
            )
    pygame.draw.rect(screen, (64, 68, 84), viewport_rect, 1)

    for entity_id in sorted(sim.state.entities):
        entity = sim.state.entities[entity_id]
        if not _is_in_current_space(_entity_space_id(entity), current_space_id):
            continue
        interpolated = interpolate_entity_position(previous_snapshot, current_snapshot, entity_id, alpha)
        if interpolated is None:
            continue
        facing_angle = visual_facing_by_entity.get(entity_id)
        if entity_id == PLAYER_ID:
            _draw_entity(
                screen,
                entity,
                interpolated[0],
                interpolated[1],
                world_center,
                world_zoom_scale,
                clip_rect=viewport_rect,
                facing_angle=facing_angle,
            )
        else:
            _draw_spawned_entity(
                screen,
                sim,
                entity,
                interpolated[0],
                interpolated[1],
                world_center,
                world_zoom_scale,
                clip_rect=viewport_rect,
                facing_angle=facing_angle,
            )
    player = sim.state.entities.get(PLAYER_ID)
    active_space = sim.state.world.spaces.get(player.space_id) if player is not None else None
    if active_space is not None and str(getattr(active_space, "role", "")) == "campaign":
        _draw_major_campaign_sites(
            screen,
            sim,
            world_center,
            marker_font,
            clip_rect=viewport_rect,
            zoom_scale=world_zoom_scale,
        )

    _draw_top_control_bar(screen, sim, font, runtime_state, layout.control_bar, follow_state)
    _draw_world_affordance_prompts(
        screen,
        sim,
        font,
        world_center=world_center,
        world_zoom_scale=world_zoom_scale,
        world_rect=layout.world_view,
    )
    _draw_hud(
        screen,
        sim,
        font,
        status_message,
        hover_message,
        runtime_state,
        layout.world_view,
        follow_state,
        world_center=world_center,
        world_zoom_scale=world_zoom_scale,
    )
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
    offer_buttons = _draw_encounter_offer_modal(screen, sim, marker_font, viewport_rect)
    if home_panel_state.visible:
        _draw_home_panel(screen, sim, font, viewport_rect)
    return inspector_content_rect, inspector_total_lines, panel_section_rects, panel_section_counts, offer_buttons


def _draw_entity(
    screen: pygame.Surface,
    entity: EntityState,
    world_x: float,
    world_y: float,
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    clip_rect: pygame.Rect,
    facing_angle: float | None = None,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    size = HEX_SIZE * zoom_scale
    x = int(center[0] + world_x * size)
    y = int(center[1] + world_y * size)
    pygame.draw.circle(screen, (255, 243, 130), (x, y), 8)
    pygame.draw.circle(screen, (15, 15, 15), (x, y), 8, 1)
    _draw_facing_wedge(screen, x=x, y=y, facing=entity.facing, color=(40, 40, 24), angle_override=facing_angle)
    screen.set_clip(old_clip)




def _draw_spawned_entity(
    screen: pygame.Surface,
    sim: Simulation,
    entity: EntityState,
    world_x: float,
    world_y: float,
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    clip_rect: pygame.Rect,
    facing_angle: float | None = None,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    size = HEX_SIZE * zoom_scale
    x = int(center[0] + world_x * size)
    y = int(center[1] + world_y * size)
    marker_color = (140, 225, 255)
    marker_radius = 6
    if str(entity.template_id or "") == "encounter_hostile_v1":
        marker_color = (214, 104, 98)
        marker_radius = 7
        if is_incapacitated_from_wounds(entity.wounds, threshold=WOUND_INCAPACITATE_SEVERITY):
            marker_color = (122, 124, 130)
            marker_radius = 8
    pygame.draw.circle(screen, marker_color, (x, y), marker_radius)
    pygame.draw.circle(screen, (14, 24, 30), (x, y), marker_radius, 1)
    _draw_facing_wedge(screen, x=x, y=y, facing=entity.facing, color=(18, 24, 28), angle_override=facing_angle)
    last_impact_tick = _last_combat_impact_tick_for_entity(sim, entity_id=entity.entity_id)
    if isinstance(last_impact_tick, int) and (int(sim.state.tick) - last_impact_tick) <= RECENT_HIT_FLASH_TICK_WINDOW:
        pygame.draw.circle(screen, (255, 220, 120), (x, y), marker_radius + 4, 2)
    if str(entity.template_id or "") == "encounter_hostile_v1" and is_incapacitated_from_wounds(
        entity.wounds, threshold=WOUND_INCAPACITATE_SEVERITY
    ):
        pygame.draw.line(screen, (30, 32, 38), (x - 4, y - 4), (x + 4, y + 4), 2)
        pygame.draw.line(screen, (30, 32, 38), (x + 4, y - 4), (x - 4, y + 4), 2)
    screen.set_clip(old_clip)


def _draw_facing_wedge(
    screen: pygame.Surface,
    *,
    x: int,
    y: int,
    facing: int,
    color: tuple[int, int, int],
    angle_override: float | None = None,
) -> None:
    angle = _facing_angle_radians(facing) if angle_override is None else float(angle_override)
    tip = (int(x + math.cos(angle) * 12), int(y + math.sin(angle) * 12))
    left = (int(x + math.cos(angle + 2.4) * 5), int(y + math.sin(angle + 2.4) * 5))
    right = (int(x + math.cos(angle - 2.4) * 5), int(y + math.sin(angle - 2.4) * 5))
    pygame.draw.polygon(screen, color, [tip, left, right])


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

    calendar = _calendar_presentation(sim)
    hash_suffix = simulation_hash(sim)[-8:]
    identity = runtime_state.last_loaded_identity or f"map:{Path(runtime_state.map_path).name}"
    metadata_text = (
        f"tick={sim.state.tick} day={calendar['day']} {calendar['hour']:02d}:{calendar['minute']:02d} "
        f"{calendar['day_night']} moon={calendar['moon_phase']} "
        f"seed={sim.seed} src={identity} hash={hash_suffix} follow={follow_state.status}"
    )
    sections_text = "Controls: Simulation | Save/Load | Time | View | Debug"
    left_label = _truncate_text_to_pixel_width(sections_text, font, 460)
    right_label = _truncate_text_to_pixel_width(metadata_text, font, max(160, bar_rect.width - 490))
    screen.blit(font.render(left_label, True, (235, 235, 240)), (10, 8))
    screen.blit(font.render(right_label, True, (220, 220, 225)), (480, 8))


def _find_safe_site_status(sim: Simulation, entity: EntityState) -> tuple[bool, str | None, str | None]:
    active_space = sim.state.world.spaces.get(entity.space_id)
    if active_space is None or str(getattr(active_space, "role", "")) != "campaign":
        return False, None, None

    location = _entity_location_text(sim, entity)
    first_matching_site: tuple[str, str] | None = None
    for site in sorted(sim.state.world.sites.values(), key=lambda row: row.site_id):
        site_location = site.location
        if site_location.get("space_id") != entity.space_id:
            continue
        coord = site_location.get("coord")
        if not isinstance(coord, dict):
            continue
        if active_space.topology_type == SQUARE_GRID_TOPOLOGY:
            here = world_xy_to_square_grid_cell(entity.position_x, entity.position_y)
            if coord.get("x") != here.get("x") or coord.get("y") != here.get("y"):
                continue
        else:
            if coord.get("q") != entity.hex_coord.q or coord.get("r") != entity.hex_coord.r:
                continue
        is_safe = site.site_type == "town" or ("safe" in site.tags)
        if is_safe:
            return True, site.site_id, site.site_type
        if first_matching_site is None:
            first_matching_site = (site.site_id, site.site_type)
    if first_matching_site is not None:
        return False, first_matching_site[0], first_matching_site[1]
    return False, None, None


def _is_home_site(site_id: object) -> bool:
    return isinstance(site_id, str) and site_id in HOME_SITE_IDS


def _inventory_counts_for_entity(sim: Simulation, entity: EntityState) -> tuple[int, int]:
    container_id = entity.inventory_container_id
    if container_id is None:
        return 0, 0
    container = sim.state.world.containers.get(container_id)
    if container is None:
        return 0, 0
    items = container.items
    proof = int(items.get(REWARD_TOKEN_ITEM_ID, 0)) if isinstance(items.get(REWARD_TOKEN_ITEM_ID, 0), int) else 0
    ration_raw = items.get("rations", 0)
    rations = int(ration_raw) if isinstance(ration_raw, int) else 0
    return max(0, proof), max(0, rations)


def _last_event_params(sim: Simulation, event_type: str, *, entity_id: str) -> dict[str, Any] | None:
    for entry in reversed(sim.get_event_trace()):
        if entry.get("event_type") != event_type:
            continue
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        if params.get("entity_id") != entity_id:
            continue
        return params
    return None


def _last_combat_outcome_for_entity(sim: Simulation, *, entity_id: str) -> dict[str, Any] | None:
    for entry in reversed(sim.get_event_trace()):
        if entry.get("event_type") != COMBAT_OUTCOME_EVENT_TYPE:
            continue
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        if params.get("attacker_id") == entity_id or params.get("target_id") == entity_id:
            return params
    return None


def _last_combat_impact_tick_for_entity(sim: Simulation, *, entity_id: str) -> int | None:
    for entry in reversed(sim.get_event_trace()):
        if entry.get("event_type") != COMBAT_OUTCOME_EVENT_TYPE:
            continue
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        if params.get("target_id") != entity_id:
            continue
        if params.get("applied") is not True:
            continue
        tick = params.get("tick")
        if isinstance(tick, int):
            return tick
    return None


def _combat_reason_label(reason: str) -> str:
    mapping = {
        "resolved": "hit",
        "invalid_arc": "blocked",
        "target_moved": "target_moved",
        "out_of_range": "out_of_range",
        "cooldown_blocked": "cooldown_blocked",
        "ineligible": "ineligible",
    }
    return mapping.get(reason, reason)


def _nearest_local_hostile(sim: Simulation, *, entity: EntityState) -> tuple[str, EntityState, float] | None:
    if entity.space_id not in sim.state.world.spaces:
        return None
    space = sim.state.world.spaces[entity.space_id]
    if space.role != LOCAL_SPACE_ROLE:
        return None
    entity_location = sim._entity_location_ref(entity)
    nearest: tuple[str, EntityState, float] | None = None
    for candidate_id in sorted(sim.state.entities):
        candidate = sim.state.entities[candidate_id]
        if candidate.space_id != entity.space_id:
            continue
        if str(candidate.template_id or "") != "encounter_hostile_v1":
            continue
        distance = distance_between_locations(entity_location, sim._entity_location_ref(candidate))
        if distance is None:
            continue
        if nearest is None or distance < nearest[2]:
            nearest = (candidate_id, candidate, float(distance))
    return nearest


def _enemy_loop_phase_line(sim: Simulation, *, entity: EntityState) -> str | None:
    nearest = _nearest_local_hostile(sim, entity=entity)
    if nearest is None:
        return None
    hostile_id, hostile, distance = nearest
    phase = "approach"
    hostile_event = _last_combat_outcome_for_entity(sim, entity_id=hostile_id)
    if hostile_event is not None and hostile_event.get("attacker_id") == hostile_id:
        reason = str(hostile_event.get("reason", ""))
        if reason == "windup_started":
            phase = "telegraph"
        elif hostile_event.get("strike_phase") in {"active", "active_miss"}:
            phase = "commit"
    if phase == "approach" and int(hostile.cooldown_until_tick) > int(sim.state.tick):
        phase = "recover"
    return f"enemy_loop={phase} enemy={hostile_id} distance={distance:.2f}"


def _player_feedback_lines(sim: Simulation, *, entity: EntityState) -> list[str]:
    lines: list[str] = []
    safe_hub_event = _last_event_params(sim, SAFE_HUB_OUTCOME_EVENT_TYPE, entity_id=entity.entity_id)
    if safe_hub_event is not None:
        lines.append(
            f"greybridge_hub_feedback={'ENTERED' if bool(safe_hub_event.get('applied')) else 'NO_CHANGE'} reason={safe_hub_event.get('reason', 'unknown')}"
        )

    reward_event = _last_event_params(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE, entity_id=entity.entity_id)
    if reward_event is not None:
        details = reward_event.get("details") if isinstance(reward_event.get("details"), dict) else {}
        if bool(reward_event.get("applied")):
            lines.append("reward_feedback=PROOF TOKEN LOOTED +1 (manual loot confirmed)")
        else:
            lines.append(f"reward_feedback=No proof token ({reward_event.get('reason', 'unknown')})")

    turn_in_event = _last_event_params(sim, REWARD_TURN_IN_OUTCOME_EVENT_TYPE, entity_id=entity.entity_id)
    if turn_in_event is not None:
        details = turn_in_event.get("details") if isinstance(turn_in_event.get("details"), dict) else {}
        granted_item = details.get("granted_item_id")
        granted_quantity = details.get("granted_quantity")
        if bool(turn_in_event.get("applied")) and granted_item == "rations" and isinstance(granted_quantity, int) and granted_quantity > 0:
            lines.append(f"turn_in_feedback=RATIONS GAINED +{granted_quantity} (proof converted at home)")
        else:
            lines.append(f"turn_in_feedback=No ration gain ({turn_in_event.get('reason', 'unknown')})")
        if isinstance(details.get("next_patrol_reason"), str):
            lines.append(f"patrol_feedback=NEXT PATROL: {details['next_patrol_reason']}")

    recovery_event = _last_event_params(sim, RECOVERY_OUTCOME_EVENT_TYPE, entity_id=entity.entity_id)
    if recovery_event is not None:
        details = recovery_event.get("details") if isinstance(recovery_event.get("details"), dict) else {}
        if recovery_event.get("outcome") == "scheduled":
            lines.append("recovery_feedback=Recover at Inn/Infirmary costs 0 rations, advances 60 ticks, clears up to one light wound.")
            rations_before = details.get("rations_before")
            if isinstance(rations_before, int):
                lines.append(f"recovery_rations=current={rations_before} cost=0")
        before = details.get("wound_severity_before")
        after = details.get("wound_severity_after")
        count_before = details.get("wound_count_before")
        count_after = details.get("wound_count_after")
        time_advanced = details.get("time_advanced_ticks")
        rations_before = details.get("rations_before")
        rations_after = details.get("rations_after")
        if isinstance(before, int) and isinstance(after, int):
            lines.append(f"recovery_wounds=severity {before}->{after} count {count_before}->{count_after}")
        if isinstance(rations_before, int) and isinstance(rations_after, int):
            lines.append(f"recovery_rations={rations_before}->{rations_after} (cost {max(0, rations_before-rations_after)})")
        if isinstance(time_advanced, int):
            lines.append(f"recovery_time_advanced_ticks={time_advanced}")
        reason = str(recovery_event.get("reason", "unknown"))
        if reason == "no_recoverable_wound":
            lines.append("recovery_result=no visible improvement (no recoverable light wound present)")
        elif reason == "light_wound_recovered":
            lines.append("recovery_result=one light wound recovered")
        else:
            lines.append(f"recovery_result={reason}")

    cooldown_remaining = max(0, int(entity.cooldown_until_tick) - int(sim.state.tick))
    lines.append(
        f"melee_state={'recovering' if cooldown_remaining > 0 else 'ready'} "
        f"recovery_ticks={cooldown_remaining} attack_available_in_ticks={cooldown_remaining}"
    )
    enemy_loop_line = _enemy_loop_phase_line(sim, entity=entity)
    if enemy_loop_line is not None:
        lines.append(enemy_loop_line)

    combat_event = _last_combat_outcome_for_entity(sim, entity_id=entity.entity_id)
    if combat_event is not None:
        event_tick = combat_event.get("tick")
        if isinstance(event_tick, int) and (int(sim.state.tick) - event_tick) > RECENT_COMBAT_FEEDBACK_TICK_WINDOW:
            return lines
        applied = bool(combat_event.get("applied"))
        attacker_id = combat_event.get("attacker_id")
        target_id = combat_event.get("target_id")
        if attacker_id == entity.entity_id:
            target_label = str(target_id) if isinstance(target_id, str) and target_id else "cell_target"
            neutralized = False
            if isinstance(target_id, str):
                target = sim.state.entities.get(target_id)
                if target is not None:
                    neutralized = is_incapacitated_from_wounds(target.wounds, threshold=WOUND_INCAPACITATE_SEVERITY)
            reason = str(combat_event.get("reason", "?"))
            if reason == "windup_started":
                resolve_tick = combat_event.get("resolve_tick")
                lines.append(
                    f"attack_feedback=COMMIT target={target_label} phase=windup resolve_tick={resolve_tick if isinstance(resolve_tick, int) else '?'}"
                )
                return lines
            if reason == "target_moved":
                lines.append(f"attack_feedback=MISS target={target_label} reason=target_moved_before_strike")
                return lines
            if reason == "cooldown_blocked":
                lines.append(f"attack_feedback=BLOCKED target={target_label} reason=cooldown_blocked")
                return lines
            lines.append(
                f"attack_feedback={'HIT' if applied else 'MISS'} target={target_label} "
                f"reason={_combat_reason_label(reason)} neutralized={'yes' if neutralized else 'no'}"
            )
        elif target_id == entity.entity_id:
            lines.append(
                f"incoming_feedback={'HIT' if applied else 'MISS'} "
                f"by={attacker_id if isinstance(attacker_id, str) else '?'} "
                f"reason={_combat_reason_label(str(combat_event.get('reason', '?')))}"
            )
    return lines


def _home_panel_lines(sim: Simulation, *, entity: EntityState) -> list[str]:
    lines: list[str] = []
    at_safe_site, safe_site_id, _ = _find_safe_site_status(sim, entity)
    at_home = at_safe_site and _is_home_site(safe_site_id)
    proof_tokens, rations = _inventory_counts_for_entity(sim, entity)
    movement_multiplier = movement_multiplier_from_wounds(entity.wounds)
    incapacitated = is_incapacitated_from_wounds(entity.wounds, threshold=WOUND_INCAPACITATE_SEVERITY)
    condition = "incapacitated" if incapacitated else ("slowed" if movement_multiplier < 1.0 else "mobile")
    has_light_wound = any(isinstance(w, dict) and w.get("severity") == 1 for w in entity.wounds)
    recovery_available = at_home and has_light_wound
    turn_in_available = at_home and proof_tokens > 0
    lines.extend(
        [
            "Greybridge Home Services (minimal node panel)",
            f"location_status={'at_home' if at_home else 'away_from_home'}",
            f"condition={condition} wound_total={wound_severity_total(entity.wounds)} move_mult={movement_multiplier:.2f}",
            f"inventory proof_token={proof_tokens} rations={rations}",
            f"recover={'AVAILABLE' if recovery_available else 'UNAVAILABLE'} "
            f"reason={'ready' if recovery_available else ('severity1_wound_required' if at_home else 'must_be_at_home')}",
            f"turn_in_proof={'AVAILABLE' if turn_in_available else 'UNAVAILABLE'} "
            f"reason={'ready' if turn_in_available else ('proof_token_required' if at_home else 'must_be_at_home')}",
            "town_interior=NOT_IMPLEMENTED (this panel is current honest interaction surface)",
        ]
    )
    return lines


def _draw_home_panel(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    viewport_rect: pygame.Rect,
) -> dict[str, pygame.Rect]:
    player = sim.state.entities.get(PLAYER_ID)
    if player is None:
        return {}
    lines = _home_panel_lines(sim, entity=player)
    panel_rect = _home_panel_rect(viewport_rect, len(lines))

    pygame.draw.rect(screen, (20, 24, 34), panel_rect)
    pygame.draw.rect(screen, (198, 208, 222), panel_rect, 2)
    title = "Enter/Use Home: Greybridge"
    screen.blit(font.render(title, True, (245, 245, 248)), (panel_rect.x + 12, panel_rect.y + 10))

    body_rect = pygame.Rect(panel_rect.x + 12, panel_rect.y + 38, panel_rect.width - 24, panel_rect.height - 98)
    _render_wrapped_lines(screen, font, body_rect, lines, scroll_offset=0)

    buttons = _home_panel_button_rects(panel_rect)
    for action, rect in buttons.items():
        text = {
            "recover": "Recover",
            "turn_in": "Turn In Proof",
            "close": "Leave/Close",
        }[action]
        pygame.draw.rect(screen, (46, 54, 76), rect)
        pygame.draw.rect(screen, (170, 176, 194), rect, 1)
        label = _truncate_text_to_pixel_width(text, font, rect.width - 14)
        text_surface = font.render(label, True, (245, 245, 250))
        text_pos = text_surface.get_rect(center=rect.center)
        screen.blit(text_surface, text_pos)
    return buttons


def _home_panel_button_rects(panel_rect: pygame.Rect) -> dict[str, pygame.Rect]:
    button_width = max(120, (panel_rect.width - 48) // 3)
    button_top = panel_rect.bottom - HOME_PANEL_BUTTON_HEIGHT - 12
    buttons: dict[str, pygame.Rect] = {}
    for index, action in enumerate(("recover", "turn_in", "close")):
        buttons[action] = pygame.Rect(
            panel_rect.x + 12 + (index * (button_width + 12)),
            button_top,
            button_width,
            HOME_PANEL_BUTTON_HEIGHT,
        )
    return buttons


def _home_panel_rect(viewport_rect: pygame.Rect, line_count: int) -> pygame.Rect:
    panel_width = min(HOME_PANEL_WIDTH, max(340, viewport_rect.width - 48))
    panel_height = max(HOME_PANEL_MIN_HEIGHT, min(viewport_rect.height - 40, HOME_PANEL_MIN_HEIGHT + (line_count * 24)))
    panel_rect = pygame.Rect(0, 0, panel_width, panel_height)
    panel_rect.center = viewport_rect.center
    return panel_rect


def _home_panel_buttons_for_click(
    sim: Simulation,
    viewport_rect: pygame.Rect,
) -> dict[str, pygame.Rect]:
    player = sim.state.entities.get(PLAYER_ID)
    if player is None:
        return {}
    lines = _home_panel_lines(sim, entity=player)
    panel_rect = _home_panel_rect(viewport_rect, len(lines))
    return _home_panel_button_rects(panel_rect)


def _player_facing_hud_lines(
    sim: Simulation,
    *,
    entity: EntityState,
    runtime_state: ViewerRuntimeState,
) -> list[str]:
    severity_total = wound_severity_total(entity.wounds)
    movement_multiplier = movement_multiplier_from_wounds(entity.wounds)
    incapacitated = is_incapacitated_from_wounds(entity.wounds, threshold=WOUND_INCAPACITATE_SEVERITY)
    condition = "incapacitated" if incapacitated else ("slowed" if movement_multiplier < 1.0 else "mobile")
    proof_tokens, rations = _inventory_counts_for_entity(sim, entity)
    pending_offer = _pending_encounter_offer(sim)
    at_safe_site, safe_site_id, _ = _find_safe_site_status(sim, entity)
    calendar = _calendar_presentation(sim)
    lines = [
        "WASD move | Enter/E use site | F fight | X flee | L loot | T turn in | R recover | Q exit hub",
        f"condition={condition} wound_total={severity_total}/{WOUND_INCAPACITATE_SEVERITY}",
        f"inventory proof_token={proof_tokens} rations={rations}",
        (
            f"time {calendar['hour']:02d}:{calendar['minute']:02d} | {calendar['day_night']} | "
            f"{calendar['month_name']} {calendar['day_of_month']} (day {calendar['day']}) | moon {calendar['moon_phase']}"
        ),
        f"runtime={'paused' if runtime_state.paused else 'running'} profile={runtime_state.runtime_profile or CORE_PLAYABLE}",
    ]
    lines.extend(_player_feedback_lines(sim, entity=entity))
    if pending_offer is not None:
        lines.append(
            f"encounter=offer_pending source={pending_offer.get('source_label', '?')} title={pending_offer.get('encounter_label', '?')}"
        )
    if entity.space_id == "safe_hub:greybridge":
        lines.append("site=INSIDE Greybridge hub | Watch Hall [T] | Inn/Infirmary [R] | Gate exit [Q/E]")
    elif _is_home_site(safe_site_id):
        lines.append("site=OUTSIDE Greybridge on campaign map | Enter/E to step into local hub")
    elif at_safe_site:
        lines.append(f"site=safe ({safe_site_id if isinstance(safe_site_id, str) else '-'})")
    return lines


def _nearest_lootable_hostile_for_player(sim: Simulation, *, entity: EntityState) -> EntityState | None:
    best: tuple[float, str, EntityState] | None = None
    for candidate in sim.state.entities.values():
        if candidate.space_id != entity.space_id or candidate.entity_id == entity.entity_id:
            continue
        if str(candidate.template_id or "") != "encounter_hostile_v1":
            continue
        if not is_incapacitated_from_wounds(candidate.wounds, threshold=WOUND_INCAPACITATE_SEVERITY):
            continue
        stats = candidate.stats if isinstance(candidate.stats, dict) else {}
        if bool(stats.get("proof_looted", False)):
            continue
        distance = math.dist((entity.position_x, entity.position_y), (candidate.position_x, candidate.position_y))
        if distance > LOOT_PROMPT_RANGE:
            continue
        row = (distance, candidate.entity_id, candidate)
        if best is None or (row[0], row[1]) < (best[0], best[1]):
            best = row
    return best[2] if best is not None else None


def _spatial_context_actions(sim: Simulation, *, player: EntityState) -> list[ContextMenuItem]:
    actions: list[ContextMenuItem] = []
    space = sim.state.world.spaces.get(player.space_id)
    if space is None:
        return actions
    role = str(getattr(space, "role", ""))
    if role == "campaign":
        nearest = _nearest_campaign_site_for_player(sim, player=player, max_distance_world=GREYBRIDGE_USE_PROMPT_RANGE)
        if nearest is not None and nearest.site_id == "home_greybridge":
            actions.append(ContextMenuItem(label="Enter Greybridge", action="enter_site", payload="home_greybridge"))
    if role == "local":
        lootable = _nearest_lootable_hostile_for_player(sim, entity=player)
        if lootable is not None:
            actions.append(ContextMenuItem(label=f"Loot proof token ({lootable.entity_id})", action="loot_local_proof"))
    if player.space_id == "safe_hub:greybridge":
        interactables = getattr(space, "interactables", {})
        if isinstance(interactables, dict):
            for interactable_id, action, label in (
                ("watch_hall", "home_turn_in", "Watch Hall: Turn in token"),
                ("inn_infirmary", "home_recover", "Inn/Infirmary: Recover"),
                ("town_gate_exit", "exit_safe_hub", "Greybridge Gate: Exit to campaign"),
            ):
                interactable = interactables.get(interactable_id)
                if interactable is None or not isinstance(getattr(interactable, "coord", None), dict):
                    continue
                world_x = float(interactable.coord.get("x", 0.0)) + 0.5
                world_y = float(interactable.coord.get("y", 0.0)) + 0.5
                if math.dist((player.position_x, player.position_y), (world_x, world_y)) <= BUILDING_USE_PROMPT_RANGE:
                    actions.append(ContextMenuItem(label=label, action=action))
    return actions


def _campaign_authored_object_at_world(
    sim: Simulation,
    *,
    world_x: float,
    world_y: float,
    max_distance_world: float = 0.60,
) -> dict[str, str] | None:
    best: tuple[float, dict[str, str]] | None = None
    for site in sim.state.world.sites.values():
        if site.site_type not in {"town", "dungeon_entrance"}:
            continue
        anchor = _site_campaign_anchor_world(site)
        if anchor is None:
            continue
        distance = math.dist((world_x, world_y), (anchor[0], anchor[1]))
        if distance > max_distance_world:
            continue
        payload = {
            "kind": "site",
            "id": site.site_id,
            "label": site.name if site.name else site.site_id,
        }
        if best is None or (distance, payload["id"]) < (best[0], best[1]["id"]):
            best = (distance, payload)
    for patrol in sim.state.world.campaign_patrols.values():
        spawn = patrol.spawn_position if isinstance(patrol.spawn_position, dict) else {}
        try:
            spawn_x = float(spawn["x"])
            spawn_y = float(spawn["y"])
        except (KeyError, TypeError, ValueError):
            continue
        distance = math.dist((world_x, world_y), (spawn_x, spawn_y))
        if distance > max_distance_world:
            continue
        payload = {
            "kind": "patrol",
            "id": patrol.patrol_id,
            "label": patrol.label if patrol.label else patrol.patrol_id,
        }
        if best is None or (distance, payload["id"]) < (best[0], best[1]["id"]):
            best = (distance, payload)
    return best[1] if best is not None else None


def _campaign_authoring_placement_items(world_x: float, world_y: float) -> list[ContextMenuItem]:
    coord = world_xy_to_axial(world_x, world_y)
    return [
        ContextMenuItem(label="Campaign Authoring...", action="noop"),
        ContextMenuItem(
            label="Place Town Here",
            action="campaign_author_place",
            payload={
                "kind": "town",
                "site_id": f"authoring_town_{coord.q}_{coord.r}",
                "label": "Authored Town",
                "position": {"x": float(world_x), "y": float(world_y)},
            },
        ),
        ContextMenuItem(
            label="Place Dungeon Entrance Here",
            action="campaign_author_place",
            payload={
                "kind": "dungeon_entrance",
                "site_id": f"authoring_dungeon_{coord.q}_{coord.r}",
                "label": "Authored Dungeon Entrance",
                "position": {"x": float(world_x), "y": float(world_y)},
            },
        ),
        ContextMenuItem(
            label="Place Patrol Here",
            action="campaign_author_place",
            payload={
                "kind": "patrol",
                "patrol_id": f"patrol:authoring_{coord.q}_{coord.r}",
                "label": "Authored Patrol",
                "position": {"x": float(world_x), "y": float(world_y)},
            },
        ),
    ]


def _campaign_authoring_edit_items(target: dict[str, str]) -> list[ContextMenuItem]:
    items = [
        ContextMenuItem(label=f"Campaign Authoring: {target['label']}", action="noop"),
    ]
    if target.get("kind") == "site":
        items.append(ContextMenuItem(label="Enter", action="enter_site", payload=target.get("id")))
    items.extend(
        [
            ContextMenuItem(label="Move", action="campaign_author_move", payload=target),
            ContextMenuItem(label="Delete", action="campaign_author_delete", payload=target),
        ]
    )
    if target.get("kind") == "patrol":
        items.append(ContextMenuItem(label="Edit Path", action="campaign_author_edit_path", payload=target))
    return items


def _local_dungeon_authored_target_at_cell(space: Any, *, cell: dict[str, int]) -> dict[str, str] | None:
    best: dict[str, str] | None = None
    for spawner in getattr(space, "local_hostile_spawners", []):
        if not isinstance(spawner, dict):
            continue
        coord = spawner.get("coord")
        if not isinstance(coord, dict):
            continue
        if int(coord.get("x", -9999)) == int(cell["x"]) and int(coord.get("y", -9999)) == int(cell["y"]):
            return {
                "kind": "spawner",
                "id": str(spawner.get("spawner_id", "")),
                "label": str(spawner.get("label", "Hostile Spawner")),
            }
    for point in getattr(space, "local_transition_points", []):
        if not isinstance(point, dict):
            continue
        coord = point.get("coord")
        if not isinstance(coord, dict):
            continue
        if int(coord.get("x", -9999)) == int(cell["x"]) and int(coord.get("y", -9999)) == int(cell["y"]):
            best = {
                "kind": "transition",
                "id": str(point.get("point_id", "")),
                "label": str(point.get("label", point.get("point_kind", "Transition Point"))),
                "point_kind": str(point.get("point_kind", "")),
            }
            break
    return best


def _is_local_structure_authoring_enabled_space(space_id: str) -> bool:
    return space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID or space_id.startswith("local_site:")


def _local_structure_authored_target_at_cell(space: Any, *, cell: dict[str, int]) -> dict[str, str] | None:
    opening_hit: dict[str, str] | None = None
    structure_hit: tuple[int, dict[str, str]] | None = None
    for row in getattr(space, "structure_primitives", []):
        if not isinstance(row, dict):
            continue
        structure_id = str(row.get("structure_id", "")).strip()
        if not structure_id:
            continue
        openings = row.get("openings", [])
        if isinstance(openings, (list, tuple)):
            for opening in openings:
                if not isinstance(opening, dict):
                    continue
                opening_cell = opening.get("cell")
                if not isinstance(opening_cell, dict):
                    continue
                if int(opening_cell.get("x", -9999)) == int(cell["x"]) and int(opening_cell.get("y", -9999)) == int(cell["y"]):
                    opening_hit = {
                        "kind": "opening",
                        "id": str(opening.get("opening_id", "")),
                        "label": str(opening.get("kind", "Opening")),
                        "structure_id": structure_id,
                    }
                    break
        bounds = row.get("bounds")
        if not isinstance(bounds, dict):
            continue
        try:
            bx = int(bounds.get("x", 0))
            by = int(bounds.get("y", 0))
            width = int(bounds.get("width", 1))
            height = int(bounds.get("height", 1))
        except (TypeError, ValueError):
            continue
        if width < 1 or height < 1:
            continue
        cx = int(cell["x"])
        cy = int(cell["y"])
        if bx <= cx < (bx + width) and by <= cy < (by + height):
            label = str(row.get("label", structure_id))
            area = width * height
            payload = {"kind": "structure", "id": structure_id, "label": label}
            if structure_hit is None or (area, structure_id) < (structure_hit[0], structure_hit[1]["id"]):
                structure_hit = (area, payload)
    if opening_hit is not None:
        return opening_hit
    if structure_hit is not None:
        return structure_hit[1]
    return None


def _default_structure_for_local_opening(space: Any, *, cell: dict[str, int]) -> str | None:
    target = _local_structure_authored_target_at_cell(space, cell=cell)
    if target is not None and target.get("kind") in {"structure", "opening"}:
        structure_id = str(target.get("structure_id", target.get("id", ""))).strip()
        if structure_id:
            return structure_id
    structure_ids = sorted(
        str(row.get("structure_id", "")).strip()
        for row in getattr(space, "structure_primitives", [])
        if isinstance(row, dict) and str(row.get("structure_id", "")).strip()
    )
    if len(structure_ids) == 1:
        return structure_ids[0]
    return None


def _local_structure_authoring_placement_items(space: Any, *, cell: dict[str, int]) -> list[ContextMenuItem]:
    cell_label = f"{cell['x']}_{cell['y']}"
    items = [
        ContextMenuItem(label="Local Structure Authoring...", action="noop"),
        ContextMenuItem(
            label="Place Room / Structure Here",
            action="local_structure_author_place_structure",
            payload={
                "structure_id": f"structure_{cell_label}",
                "label": f"Structure {cell_label}",
                "room_id": f"room_{cell_label}",
                "bounds": {"x": int(cell["x"]), "y": int(cell["y"]), "width": 4, "height": 3},
            },
        ),
    ]
    opening_structure_id = _default_structure_for_local_opening(space, cell=cell)
    if opening_structure_id:
        items.append(
            ContextMenuItem(
                label="Place Opening / Door Here",
                action="local_structure_author_place_opening",
                payload={
                    "structure_id": opening_structure_id,
                    "opening_id": f"opening_{cell_label}",
                    "kind": "door",
                    "cell": {"x": int(cell["x"]), "y": int(cell["y"])},
                },
            )
        )
    return items


def _local_dungeon_authoring_placement_items(space: Any, *, cell: dict[str, int]) -> list[ContextMenuItem]:
    cell_label = f"{cell['x']}_{cell['y']}"
    return [
        ContextMenuItem(label="Local Dungeon Authoring...", action="noop"),
        ContextMenuItem(
            label="Place Hostile Here",
            action="local_dungeon_author_place_spawner",
            payload={"spawner_id": f"spawner_{cell_label}", "coord": {"x": int(cell["x"]), "y": int(cell["y"])}},
        ),
        ContextMenuItem(
            label="Place Entry Point Here",
            action="local_dungeon_author_place_point",
            payload={"point_id": f"entry_{cell_label}", "coord": {"x": int(cell["x"]), "y": int(cell["y"])}, "point_kind": "entry_anchor"},
        ),
        ContextMenuItem(
            label="Place Exit / Extraction Here",
            action="local_dungeon_author_place_point",
            payload={"point_id": f"exit_{cell_label}", "coord": {"x": int(cell["x"]), "y": int(cell["y"])}, "point_kind": "extraction_exit"},
        ),
        ContextMenuItem(
            label="Place Return-to-Origin Exit Here",
            action="local_dungeon_author_place_point",
            payload={
                "point_id": f"return_{cell_label}",
                "coord": {"x": int(cell["x"]), "y": int(cell["y"])},
                "point_kind": "return_to_origin_exit",
            },
        ),
    ]


def _local_dungeon_authoring_edit_items(target: dict[str, str]) -> list[ContextMenuItem]:
    if target.get("kind") == "spawner":
        return [
            ContextMenuItem(label=f"Local Authoring: {target.get('label', target.get('id', 'Spawner'))}", action="noop"),
            ContextMenuItem(
                label="Move Hostile",
                action="local_dungeon_author_move_spawner",
                payload={"spawner_id": target.get("id"), "label": target.get("label")},
            ),
            ContextMenuItem(
                label="Delete Hostile",
                action="local_dungeon_author_delete_spawner",
                payload={"spawner_id": target.get("id")},
            ),
        ]
    point_kind = target.get("point_kind", "")
    use_label = "Use This Exit: Return to Origin" if point_kind in {"extraction_exit", "return_to_origin_exit"} else "Use Transition Point"
    return [
        ContextMenuItem(label=f"Local Authoring: {target.get('label', target.get('id', 'Point'))}", action="noop"),
        ContextMenuItem(
            label="Move Point",
            action="local_dungeon_author_move_point",
            payload={
                "point_id": target.get("id"),
                "point_kind": point_kind,
                "label": target.get("label"),
            },
        ),
        ContextMenuItem(
            label="Delete Point",
            action="local_dungeon_author_delete_point",
            payload={"point_id": target.get("id")},
        ),
        ContextMenuItem(
            label=use_label,
            action="local_dungeon_author_use_point",
            payload={"point_id": target.get("id")},
        ),
    ]


def _local_structure_authoring_edit_items(target: dict[str, str]) -> list[ContextMenuItem]:
    if target.get("kind") == "structure":
        return [
            ContextMenuItem(label=f"Local Structure: {target.get('label', target.get('id', 'Structure'))}", action="noop"),
            ContextMenuItem(
                label="Move Structure",
                action="local_structure_author_move_structure",
                payload={"structure_id": target.get("id"), "label": target.get("label")},
            ),
            ContextMenuItem(
                label="Delete Structure",
                action="local_structure_author_delete_structure",
                payload={"structure_id": target.get("id")},
            ),
        ]
    return [
        ContextMenuItem(label=f"Local Structure: {target.get('label', target.get('id', 'Opening'))}", action="noop"),
        ContextMenuItem(
            label="Move Opening",
            action="local_structure_author_move_opening",
            payload={
                "structure_id": target.get("structure_id"),
                "opening_id": target.get("id"),
                "kind": "door",
                "label": target.get("label"),
            },
        ),
        ContextMenuItem(
            label="Delete Opening",
            action="local_structure_author_delete_opening",
            payload={"structure_id": target.get("structure_id"), "opening_id": target.get("id")},
        ),
    ]


def _local_authored_target_at_cell(space: Any, *, cell: dict[str, int], include_dungeon_targets: bool) -> dict[str, str] | None:
    if include_dungeon_targets:
        dungeon_target = _local_dungeon_authored_target_at_cell(space, cell=cell)
        if dungeon_target is not None:
            return dungeon_target
    return _local_structure_authored_target_at_cell(space, cell=cell)


def _campaign_patrol_anchor_at_world(
    sim: Simulation,
    *,
    patrol_id: str,
    world_x: float,
    world_y: float,
    max_distance_world: float = 0.55,
) -> int | None:
    patrol = sim.state.world.campaign_patrols.get(patrol_id)
    if patrol is None:
        return None
    best: tuple[float, int] | None = None
    for index, anchor in enumerate(patrol.route_anchors):
        if not isinstance(anchor, dict):
            continue
        try:
            anchor_x = float(anchor["x"])
            anchor_y = float(anchor["y"])
        except (KeyError, TypeError, ValueError):
            continue
        distance = math.dist((world_x, world_y), (anchor_x, anchor_y))
        if distance > max_distance_world:
            continue
        if best is None or (distance, index) < best:
            best = (distance, index)
    return best[1] if best is not None else None


def _campaign_patrol_path_needed_count(sim: Simulation) -> int:
    needed = 0
    for patrol in sim.state.world.campaign_patrols.values():
        if len(patrol.route_anchors) < 1:
            needed += 1
    return needed


def _campaign_patrol_route_points(patrol: CampaignPatrolRecord) -> list[tuple[float, float]]:
    spawn = patrol.spawn_position if isinstance(patrol.spawn_position, dict) else {}
    try:
        spawn_x = float(spawn["x"])
        spawn_y = float(spawn["y"])
    except (KeyError, TypeError, ValueError):
        return []
    points: list[tuple[float, float]] = [(spawn_x, spawn_y)]
    for anchor in patrol.route_anchors:
        if not isinstance(anchor, dict):
            continue
        try:
            points.append((float(anchor["x"]), float(anchor["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def _draw_campaign_patrol_routes(
    screen: pygame.Surface,
    sim: Simulation,
    *,
    world_center: tuple[float, float],
    world_zoom_scale: float,
    world_rect: pygame.Rect,
    font: pygame.font.Font,
    campaign_path_edit_state: CampaignAuthoringPathEditState | None,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(world_rect)
    for patrol_id in sorted(sim.state.world.campaign_patrols):
        patrol = sim.state.world.campaign_patrols[patrol_id]
        route_points = _campaign_patrol_route_points(patrol)
        if not route_points:
            continue
        highlighted = campaign_path_edit_state is not None and campaign_path_edit_state.patrol_id == patrol_id
        spawn_px, spawn_py = _world_to_pixel(route_points[0][0], route_points[0][1], world_center, world_zoom_scale)
        spawn_color = (196, 252, 214) if highlighted else (156, 202, 180)
        pygame.draw.circle(screen, spawn_color, (int(spawn_px), int(spawn_py)), 6, 2)
        spawn_label = font.render("0", True, spawn_color)
        screen.blit(spawn_label, (int(spawn_px) + 7, int(spawn_py) - 9))
        if len(route_points) <= 1:
            continue
        line_color = (106, 220, 170) if highlighted else (86, 162, 132)
        pixel_points = [_world_to_pixel(x, y, world_center, world_zoom_scale) for x, y in route_points]
        pixel_points.append(pixel_points[0])
        pygame.draw.lines(screen, line_color, False, [(int(x), int(y)) for x, y in pixel_points], 2)
        close_from = pixel_points[-2]
        close_to = pixel_points[-1]
        close_mid = ((close_from[0] + close_to[0]) * 0.5, (close_from[1] + close_to[1]) * 0.5)
        loop_label = font.render("↺", True, line_color)
        screen.blit(loop_label, (int(close_mid[0]) + 4, int(close_mid[1]) - 10))
        for index, point in enumerate(route_points[1:], start=1):
            px, py = _world_to_pixel(point[0], point[1], world_center, world_zoom_scale)
            pygame.draw.circle(screen, line_color, (int(px), int(py)), 4)
            index_label = font.render(str(index), True, line_color)
            screen.blit(index_label, (int(px) + 6, int(py) - 8))
    screen.set_clip(old_clip)


def _draw_world_affordance_prompts(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    *,
    world_center: tuple[float, float],
    world_zoom_scale: float,
    world_rect: pygame.Rect,
) -> None:
    player = sim.state.entities.get(PLAYER_ID)
    if player is None:
        return
    active_space = sim.state.world.spaces.get(player.space_id)
    if active_space is None:
        return
    old_clip = screen.get_clip()
    screen.set_clip(world_rect)
    if str(getattr(active_space, "role", "")) == "campaign":
        nearest = _nearest_campaign_site_for_player(sim, player=player, max_distance_world=GREYBRIDGE_USE_PROMPT_RANGE)
        if nearest is not None and nearest.site_id == "home_greybridge":
            anchor = _site_campaign_anchor_world(nearest)
            if anchor is not None:
                px, py = _world_to_pixel(anchor[0], anchor[1], world_center, world_zoom_scale)
                prompt = "Press Enter/E: Enter Greybridge"
                label = font.render(prompt, True, (255, 248, 190))
                screen.blit(label, (int(px) - (label.get_width() // 2), int(py) - 40))
    elif player.space_id == "safe_hub:greybridge":
        banner = font.render("INSIDE GREYBRIDGE HUB", True, (214, 236, 255))
        screen.blit(banner, (world_rect.x + 10, world_rect.y + 32))
        interactables = getattr(active_space, "interactables", {})
        if isinstance(interactables, dict):
            for interactable_id in ("watch_hall", "inn_infirmary", "town_gate_exit"):
                interactable = interactables.get(interactable_id)
                if interactable is None or not isinstance(getattr(interactable, "coord", None), dict):
                    continue
                world_x = float(interactable.coord.get("x", 0.0)) + 0.5
                world_y = float(interactable.coord.get("y", 0.0)) + 0.5
                px, py = _world_to_pixel(world_x, world_y, world_center, world_zoom_scale)
                if interactable_id == "watch_hall":
                    title = "WATCH HALL (TURN-IN)"
                elif interactable_id == "inn_infirmary":
                    title = "INN / INFIRMARY (RECOVER)"
                else:
                    title = "TOWN GATE (EXIT)"
                title_surface = font.render(title, True, (240, 245, 255))
                screen.blit(title_surface, (int(px) - (title_surface.get_width() // 2), int(py) - 26))
                distance = math.dist((player.position_x, player.position_y), (world_x, world_y))
                if distance <= BUILDING_USE_PROMPT_RANGE:
                    if interactable_id == "watch_hall":
                        prompt = "Press T: Turn in proof token"
                    elif interactable_id == "inn_infirmary":
                        prompt = "Press R: Recover (cost 0 rations, +60 ticks, heal one light wound)"
                    else:
                        prompt = "Press Q or E: Exit Greybridge to campaign origin"
                    prompt_surface = font.render(prompt, True, (255, 246, 188))
                    screen.blit(prompt_surface, (int(px) - (prompt_surface.get_width() // 2), int(py) - 44))
    if str(getattr(active_space, "role", "")) == "local":
        lootable = _nearest_lootable_hostile_for_player(sim, entity=player)
        if lootable is not None:
            px, py = _world_to_pixel(lootable.position_x, lootable.position_y, world_center, world_zoom_scale)
            prompt = font.render("Proof available: Press L to loot", True, (255, 228, 176))
            screen.blit(prompt, (int(px) - (prompt.get_width() // 2), int(py) - 28))
    screen.set_clip(old_clip)


def _draw_hud(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    status_message: str | None,
    hover_message: str | None,
    runtime_state: ViewerRuntimeState,
    world_rect: pygame.Rect,
    follow_state: FollowSelectionState,
    *,
    world_center: tuple[float, float],
    world_zoom_scale: float,
) -> None:
    entity = sim.state.entities[PLAYER_ID]
    lines = _player_facing_hud_lines(sim, entity=entity, runtime_state=runtime_state)
    lines.append(f"follow={follow_state.status} | debug data in inspector/debug panel")

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


def _pending_encounter_offer(sim: Simulation) -> dict[str, Any] | None:
    state = sim.get_rules_state(CampaignDangerModule.name)
    if not isinstance(state, dict):
        return None
    pending_offer_by_player = state.get("pending_offer_by_player")
    if isinstance(pending_offer_by_player, dict):
        pending_offer = pending_offer_by_player.get(PLAYER_ID)
    else:
        # Backward-compat with pre-player-scoped state.
        pending_offer = state.get("pending_offer")
    if not isinstance(pending_offer, dict):
        return None
    return pending_offer


def _single_player_offer_pause(sim: Simulation) -> bool:
    return _pending_encounter_offer(sim) is not None


def _draw_encounter_offer_modal(
    screen: pygame.Surface,
    sim: Simulation,
    font: pygame.font.Font,
    viewport_rect: pygame.Rect,
) -> dict[str, pygame.Rect]:
    offer = _pending_encounter_offer(sim)
    if offer is None:
        return {}

    width = min(380, max(280, viewport_rect.width // 2))
    height = 146
    panel = pygame.Rect(
        viewport_rect.centerx - (width // 2),
        viewport_rect.y + 20,
        width,
        height,
    )
    pygame.draw.rect(screen, (26, 28, 38), panel)
    pygame.draw.rect(screen, (128, 132, 144), panel, 1)

    label = str(offer.get("encounter_label", "Encounter"))
    title = _truncate_text_to_pixel_width(f"Encounter: {label}", font, panel.width - 18)
    screen.blit(font.render(title, True, (245, 235, 190)), (panel.x + 9, panel.y + 10))
    source_label = str(offer.get("source_label", "contact source"))
    hint = _truncate_text_to_pixel_width(f"Source: {source_label}", font, panel.width - 18)
    screen.blit(font.render(hint, True, (220, 222, 230)), (panel.x + 9, panel.y + 38))
    action_hint = _truncate_text_to_pixel_width("Fight [F] or Flee [X]", font, panel.width - 18)
    screen.blit(font.render(action_hint, True, (220, 222, 230)), (panel.x + 9, panel.y + 58))
    waiting_hint = _truncate_text_to_pixel_width("Decision required: campaign flow paused until input.", font, panel.width - 18)
    screen.blit(font.render(waiting_hint, True, (236, 196, 160)), (panel.x + 9, panel.y + 78))

    button_w = 110
    button_h = 34
    fight_rect = pygame.Rect(panel.x + 24, panel.bottom - button_h - 14, button_w, button_h)
    flee_rect = pygame.Rect(panel.right - button_w - 24, panel.bottom - button_h - 14, button_w, button_h)
    for rect, text, color in (
        (fight_rect, "Fight", (125, 198, 128)),
        (flee_rect, "Flee", (208, 138, 112)),
    ):
        pygame.draw.rect(screen, color, rect)
        pygame.draw.rect(screen, (16, 18, 22), rect, 1)
        screen.blit(font.render(text, True, (15, 15, 15)), (rect.x + 30, rect.y + 8))
    return {"fight": fight_rect, "flee": flee_rect}


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
    command = controller.sim.input_log[-1] if controller.sim.input_log else None
    if command is None:
        rumor_state.pending_action_uid = None
    else:
        same_tick_index = sum(1 for current in controller.sim.input_log if int(current.tick) == int(command.tick)) - 1
        rumor_state.pending_action_uid = f"{int(command.tick)}:{max(0, same_tick_index)}"
    rumor_state.refresh_needed = False


def _consume_rumor_outcome(sim: Simulation, rumor_state: RumorPanelState) -> None:
    if not rumor_state.request_pending:
        return
    matched_outcome: dict[str, Any] | None = None
    outcome_kind = SELECT_RUMORS_OUTCOME_KIND if rumor_state.mode == "top" else LIST_RUMORS_OUTCOME_KIND
    rows_key = "selection" if rumor_state.mode == "top" else "rumors"
    for entry in sim.get_command_outcomes():
        if not isinstance(entry, dict) or entry.get("kind") != outcome_kind:
            continue
        action_uid = entry.get("action_uid") if isinstance(entry.get("action_uid"), str) else None
        if rumor_state.pending_action_uid is None:
            matched_outcome = entry
            continue
        if action_uid == rumor_state.pending_action_uid:
            matched_outcome = entry
            break
    if matched_outcome is None:
        return
    rows = matched_outcome.get(rows_key)
    rumor_state.rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    rumor_state.next_cursor = matched_outcome.get("next_cursor") if isinstance(matched_outcome.get("next_cursor"), str) else None
    rumor_state.outcome = str(matched_outcome.get("outcome", "?"))
    rumor_state.diagnostic = str(matched_outcome.get("diagnostic", ""))
    rumor_state.request_pending = False
    rumor_state.pending_action_uid = None


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
    content_rect = _render_panel_frame(screen, panel_rect, "Selected Entity", font)
    selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
    lines: list[str] = []
    if selected_entity_id:
        lines.extend(_selected_entity_lines(sim, selected_entity_id, follow_status=follow_state.status))
    else:
        lines.extend(["SELECTED ENTITY", "No entity selected.", f"Follow status={follow_state.status}"])
    lines.extend(
        [
            "",
            "VIEWER DISCIPLINE",
            "Read-only operator console: no direct simulation mutation.",
            "Campaign role: travel/time/logistics/encounter triggering.",
            "Local role: tactical movement/combat resolution.",
        ]
    )
    wrapped_count = _render_wrapped_lines(screen, font, content_rect, lines, scroll_offset=scroll_offset)
    return content_rect, wrapped_count


def collect_soak_metrics(sim: Simulation) -> dict[str, int]:
    """Read-only runtime growth counters for headless/viewer soak diagnostics.

    Space roles: campaign + local (inspection only; no mutation).
    """

    local_state = sim.get_rules_state("local_encounter_instance")
    active_local_spaces = 0
    return_in_progress_spaces = 0
    if isinstance(local_state, dict):
        active_by_local_space = local_state.get("active_by_local_space")
        if isinstance(active_by_local_space, dict):
            active_local_spaces = sum(1 for row in active_by_local_space.values() if isinstance(row, dict) and bool(row.get("is_active", True)))
        return_in_progress_by_local_space = local_state.get("return_in_progress_by_local_space")
        if isinstance(return_in_progress_by_local_space, dict):
            return_in_progress_spaces = sum(1 for value in return_in_progress_by_local_space.values() if bool(value))

    campaign_danger_state = sim.get_rules_state("campaign_danger")
    pending_offers = 0
    if isinstance(campaign_danger_state, dict):
        pending_offer_by_player = campaign_danger_state.get("pending_offer_by_player")
        if isinstance(pending_offer_by_player, dict):
            pending_offers = sum(1 for value in pending_offer_by_player.values() if isinstance(value, dict))

    return {
        "tick": int(sim.state.tick),
        "pending_events": len(sim.pending_events()),
        "event_trace": len(sim.state.event_trace),
        "entities": len(sim.state.entities),
        "signals": len(sim.state.world.signals),
        "tracks": len(sim.state.world.tracks),
        "spawn_descriptors": len(sim.state.world.spawn_descriptors),
        "input_log": len(sim.input_log),
        "active_local_spaces": int(active_local_spaces),
        "return_in_progress_spaces": int(return_in_progress_spaces),
        "pending_offers": int(pending_offers),
    }


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
        site_rows.append(f"campaign_player world=({player.position_x:.2f},{player.position_y:.2f}) hex=({player.hex_coord.q},{player.hex_coord.r})")
        coord = {"x": math.floor(player.position_x), "y": math.floor(player.position_y)}
        if sim.state.world.spaces.get(player.space_id) is None or sim.state.world.spaces[player.space_id].topology_type == OVERWORLD_HEX_TOPOLOGY:
            coord = player.hex_coord.to_dict()
        for site in sim.state.world.get_sites_at_location({"space_id": player.space_id, "coord": coord}):
            site_rows.extend(_site_debug_rows(site))
        for site in sorted(sim.state.world.sites.values(), key=lambda row: row.site_id):
            if not _is_major_campaign_site(site):
                continue
            anchor, anchor_source = _site_world_position(site)
            if anchor is None:
                continue
            site_rows.append(
                f"campaign_major_site id={site.site_id} type={site.site_type} "
                f"anchor={anchor_source} world=({anchor[0]:.2f},{anchor[1]:.2f})"
            )
        patrols = [
            entity
            for entity in sorted(sim.state.entities.values(), key=lambda row: row.entity_id)
            if entity.template_id == CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE and entity.entity_id != PLAYER_ID
        ]
        for patrol in patrols[:2]:
            site_rows.append(
                f"campaign_patrol id={patrol.entity_id} world=({patrol.position_x:.2f},{patrol.position_y:.2f}) template={patrol.template_id}"
            )

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


def _site_debug_rows(site: Any) -> list[str]:
    rows = [f"site_id={site.site_id} type={site.site_type} entrance={'yes' if site.entrance else 'no'}"]
    pressure_records = list(site.site_state.pressure_records)
    evidence_records = list(site.site_state.evidence_records)
    pressure_summary = site.site_state.get_pressure_summary()
    dominant_faction_id = pressure_summary.dominant_faction_id if pressure_summary.dominant_faction_id is not None else "none"
    rows.append(
        "pressure_summary "
        f"total={pressure_summary.total_pressure} "
        f"dominant={dominant_faction_id} "
        f"dominant_strength={pressure_summary.dominant_strength} "
        f"records={pressure_summary.record_count}"
    )
    pressure_count = len(pressure_records)
    if pressure_count > 0:
        recent_records = pressure_records[-SITE_PRESSURE_DEBUG_ROW_LIMIT:]
        rows.append(f"pressure_records={pressure_count} showing_recent={len(recent_records)}")
        for record in recent_records:
            source_event_id = record.source_event_id if record.source_event_id is not None else "-"
            rows.append(
                f"pressure faction={record.faction_id} type={record.pressure_type} "
                f"strength={record.strength} tick={record.tick} source={source_event_id}"
            )

    evidence_count = len(evidence_records)
    if evidence_count > 0:
        recent_evidence = evidence_records[-SITE_EVIDENCE_DEBUG_ROW_LIMIT:]
        rows.append(f"evidence_records={evidence_count} showing_recent={len(recent_evidence)}")
        for record in recent_evidence:
            faction_id = record.faction_id if record.faction_id is not None else "-"
            source_event_id = record.source_event_id if record.source_event_id is not None else "-"
            rows.append(
                f"evidence type={record.evidence_type} strength={record.strength} "
                f"tick={record.tick} faction={faction_id} source={source_event_id}"
            )
    return rows


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
    content_rect = _render_panel_frame(screen, panel_rect, "Debug & Event Trace", font, bg_color=(22, 24, 33))
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

    filter_mode_text = _truncate_text_to_pixel_width(f"mode:{debug_filter_state.mode}", font, max(60, content_rect.width // 3))
    filter_mode_surface = font.render(filter_mode_text, True, (240, 240, 245))
    filter_mode_rect = pygame.Rect(content_rect.right - filter_mode_surface.get_width() - 10, tab_y, filter_mode_surface.get_width() + 8, 20)
    pygame.draw.rect(screen, (44, 48, 64), filter_mode_rect)
    pygame.draw.rect(screen, (110, 115, 135), filter_mode_rect, 1)
    screen.blit(filter_mode_surface, (filter_mode_rect.x + 4, filter_mode_rect.y + 2))
    section_rects["debug_filter_mode"] = filter_mode_rect

    type_label = debug_filter_state.event_type_filter if debug_filter_state.event_type_filter is not None else "all"
    filter_type_text = _truncate_text_to_pixel_width(f"event:{type_label}", font, max(60, content_rect.width // 3))
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
        tag = _truncate_text_to_pixel_width(f"selected entity: {selected_entity_id}", font, max(1, panel_rect.width - 22))
        screen.blit(font.render(tag, True, (185, 215, 185)), (panel_rect.x + 10, panel_rect.y + 8))

    return section_rects, section_counts


def _context_menu_layout(
    menu_state: ContextMenuState,
    font: pygame.font.Font,
    viewport_rect: pygame.Rect,
) -> tuple[pygame.Rect, tuple[ContextMenuRowLayout, ...]]:
    width = max(CONTEXT_MENU_WIDTH, CONTEXT_MENU_MIN_WIDTH)
    max_line_width = max(1, width - (2 * CONTEXT_MENU_TEXT_PADDING_X))
    line_height = max(14, int(font.get_linesize()))

    provisional_rows: list[tuple[tuple[str, ...], int]] = []
    total_height = 0
    for item in menu_state.items:
        lines = tuple(_wrap_text_to_pixel_width(item.label, font, max_line_width))
        row_height = max(CONTEXT_MENU_ROW_HEIGHT, (len(lines) * line_height) + (2 * CONTEXT_MENU_TEXT_PADDING_Y))
        provisional_rows.append((lines, row_height))
        total_height += row_height

    menu_rect = pygame.Rect(menu_state.pixel_x, menu_state.pixel_y, width, max(1, total_height))
    menu_rect.clamp_ip(viewport_rect)

    rows: list[ContextMenuRowLayout] = []
    row_top = menu_rect.y
    for item_index, (lines, row_height) in enumerate(provisional_rows):
        row_rect = pygame.Rect(menu_rect.x, row_top, menu_rect.width, row_height)
        rows.append(ContextMenuRowLayout(item_index=item_index, row_rect=row_rect, lines=lines))
        row_top += row_height
    return menu_rect, tuple(rows)


def _context_menu_item_index_at_pixel(
    menu_state: ContextMenuState,
    font: pygame.font.Font,
    viewport_rect: pygame.Rect,
    pixel_pos: tuple[int, int],
) -> int | None:
    menu_rect, rows = _context_menu_layout(menu_state, font, viewport_rect)
    if not menu_rect.collidepoint(pixel_pos):
        return None
    for row in rows:
        if row.row_rect.collidepoint(pixel_pos):
            return row.item_index
    return None


def _draw_context_menu(
    screen: pygame.Surface,
    font: pygame.font.Font,
    menu_state: ContextMenuState | None,
    viewport_rect: pygame.Rect,
) -> pygame.Rect | None:
    if menu_state is None:
        return None

    menu_rect, rows = _context_menu_layout(menu_state, font, viewport_rect)
    pygame.draw.rect(screen, (32, 34, 44), menu_rect)
    pygame.draw.rect(screen, (185, 185, 200), menu_rect, 1)

    line_height = max(14, int(font.get_linesize()))
    for row in rows:
        item = menu_state.items[row.item_index]
        row_rect = row.row_rect
        pygame.draw.line(screen, (64, 68, 84), (row_rect.x, row_rect.bottom), (row_rect.right, row_rect.bottom), 1)
        text_y = row_rect.y + CONTEXT_MENU_TEXT_PADDING_Y
        for line in row.lines:
            label_text = _truncate_text_to_pixel_width(line, font, max(1, row_rect.width - (2 * CONTEXT_MENU_TEXT_PADDING_X)))
            label = font.render(label_text, True, (245, 245, 245))
            screen.blit(label, (row_rect.x + CONTEXT_MENU_TEXT_PADDING_X, text_y))
            text_y += line_height
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
    template_id = str(entity.template_id or "")
    if template_id == "campaign_danger_patrol":
        return "danger"
    if template_id == "encounter_hostile_v1":
        return "hostile"
    if entity.template_id:
        return template_id
    return _short_stable_id(entity.entity_id)


def _selected_entity_for_click(
    sim: Simulation,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 12.0,
) -> str | None:
    direct_entity_hit = _find_entity_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=radius_px)
    if direct_entity_hit is not None:
        return direct_entity_hit
    markers = _find_world_marker_candidates_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=radius_px)
    for marker in markers:
        if marker.marker_kind != "entity":
            continue
        entity_id = _marker_payload_id(marker, expected_kind="entity")
        if entity_id is None:
            continue
        if entity_id in sim.state.entities:
            return entity_id
    return None


def _calendar_presentation(sim: Simulation) -> dict[str, Any]:
    ticks_per_day = max(1, int(sim.get_ticks_per_day()))
    relative_ticks = int(sim.state.tick - sim.state.time.epoch_tick)
    if relative_ticks < 0:
        relative_ticks = 0
    day_index = relative_ticks // ticks_per_day
    tick_in_day = relative_ticks % ticks_per_day
    hour = (tick_in_day * 24) // ticks_per_day
    minute = ((tick_in_day * 24 * 60) // ticks_per_day) % 60
    day_night = "day" if 6 <= hour < 18 else "night"
    month_index = (day_index // CALENDAR_MONTH_LENGTH_DAYS) % len(CALENDAR_MONTHS)
    day_of_month = (day_index % CALENDAR_MONTH_LENGTH_DAYS) + 1
    lunar_segment = max(1, CALENDAR_MONTH_LENGTH_DAYS // len(MOON_PHASES))
    moon_phase_index = min(len(MOON_PHASES) - 1, (day_index % CALENDAR_MONTH_LENGTH_DAYS) // lunar_segment)
    return {
        "day": day_index + 1,
        "hour": int(hour),
        "minute": int(minute),
        "day_night": day_night,
        "month_name": CALENDAR_MONTHS[month_index],
        "day_of_month": int(day_of_month),
        "moon_phase": MOON_PHASES[moon_phase_index],
    }


def _queue_local_attack_for_click(
    sim: Simulation,
    controller: SimulationController,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float = 1.0,
    *,
    radius_px: float = 12.0,
) -> str | None:
    player = sim.state.entities.get(PLAYER_ID)
    if player is None:
        return None
    active_space = sim.state.world.spaces.get(player.space_id)
    if active_space is None or str(getattr(active_space, "role", "")) != LOCAL_SPACE_ROLE:
        return None
    target_entity_id = _selected_entity_for_click(sim, pixel_pos, center, zoom_scale, radius_px=radius_px)
    if target_entity_id is None or target_entity_id == PLAYER_ID:
        return None
    target = sim.state.entities.get(target_entity_id)
    if target is None or target.space_id != player.space_id:
        return None
    controller.attack_entity(target_entity_id)
    controller.set_selected_entity(target_entity_id)
    return f"attack queued -> {target_entity_id}"


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


def _open_home_panel_from_marker_click(
    sim: Simulation,
    *,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float,
) -> str | None:
    marker = _find_world_marker_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=12.0)
    if marker is None or marker.marker_kind != "site":
        return None
    site_id = _marker_payload_id(marker, expected_kind="site")
    if site_id is None or not _is_home_site(site_id):
        return None
    return site_id


def _site_for_marker_click(
    sim: Simulation,
    *,
    pixel_pos: tuple[int, int],
    center: tuple[float, float],
    zoom_scale: float,
) -> SiteRecord | None:
    marker = _find_world_marker_at_pixel(sim, pixel_pos, center, zoom_scale, radius_px=12.0)
    if marker is None or marker.marker_kind != "site":
        return None
    site_id = _marker_payload_id(marker, expected_kind="site")
    if site_id is None:
        return None
    return sim.state.world.sites.get(site_id)


def _nearest_campaign_site_for_player(
    sim: Simulation,
    *,
    player: EntityState,
    selected_site_id: str | None = None,
    max_distance_world: float = GREYBRIDGE_USE_PROMPT_RANGE,
) -> SiteRecord | None:
    active_space = sim.state.world.spaces.get(player.space_id)
    if active_space is None or str(getattr(active_space, "role", "")) != "campaign":
        return None

    if isinstance(selected_site_id, str) and selected_site_id:
        selected_site = sim.state.world.sites.get(selected_site_id)
        selected_anchor, _ = _site_world_position(selected_site) if selected_site is not None else (None, "unsupported")
        if (
            selected_site is not None
            and selected_site.location.get("space_id") == player.space_id
            and selected_anchor is not None
            and math.dist((player.position_x, player.position_y), selected_anchor) <= max_distance_world
        ):
            return selected_site

    candidates: list[tuple[float, str, SiteRecord]] = []
    for site in sim.state.world.sites.values():
        if site.location.get("space_id") != player.space_id:
            continue
        anchor, _ = _site_world_position(site)
        if anchor is None:
            continue
        distance = math.dist((player.position_x, player.position_y), anchor)
        if distance <= max_distance_world:
            candidates.append((distance, site.site_id, site))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][2]


def _use_campaign_site(
    sim: Simulation,
    controller: SimulationController,
    *,
    player: EntityState,
    selected_site_id: str | None,
) -> tuple[str, str | None, bool]:
    site = _nearest_campaign_site_for_player(
        sim,
        player=player,
        selected_site_id=selected_site_id,
        max_distance_world=GREYBRIDGE_USE_PROMPT_RANGE,
    )
    if site is None:
        return "no site in range (move closer or select a nearby site marker)", selected_site_id, False
    if site.entrance is not None:
        controller.enter_site(site.site_id)
        return f"entering site: {site.name if site.name else site.site_id}", site.site_id, False
    if site.site_type == "town" or "safe" in site.tags:
        controller.enter_safe_hub_intent(site.site_id)
        return f"entering Greybridge hub: {site.name if site.name else site.site_id}", site.site_id, False
    return f"site selected: {site.name if site.name else site.site_id} (no Enter/E action yet)", site.site_id, False


def _selected_entity_lines(
    sim: Simulation,
    selected_entity_id: str,
    *,
    follow_status: str = FOLLOW_STATUS_OFF,
) -> list[str]:
    entity = sim.state.entities.get(selected_entity_id)
    if entity is None:
        return ["SELECTED ENTITY", f"Entity ID: {selected_entity_id}", "Entity not found in current simulation state."]

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

    severity_total = wound_severity_total(entity.wounds)
    incapacitated = is_incapacitated_from_wounds(entity.wounds, threshold=WOUND_INCAPACITATE_SEVERITY)

    movement_multiplier = movement_multiplier_from_wounds(entity.wounds)
    condition_label = "incapacitated" if incapacitated else ("slowed" if movement_multiplier < 1.0 else "mobile")
    proof_tokens, rations = _inventory_counts_for_entity(sim, entity)
    at_safe_site, safe_site_id, safe_site_type = _find_safe_site_status(sim, entity)
    return_context = _get_return_context_for_space(sim, entity.space_id)

    lines = [
        "SELECTED ENTITY",
        f"Entity ID: {entity.entity_id}",
        f"Space ID: {entity.space_id}",
        f"Space role: {space_role}",
        f"Condition: {condition_label}",
        f"Wounds: count={len(entity.wounds)} severity_total={severity_total}",
        f"Incapacitated: {'YES' if incapacitated else 'NO'} (threshold={WOUND_INCAPACITATE_SEVERITY})",
        f"Movement multiplier: {movement_multiplier:.2f}",
        f"Extraction context: {'present' if return_context is not None else 'none'}",
        f"Safe site: {'yes' if at_safe_site else 'no'} ({safe_site_id if safe_site_id else '-'}:{safe_site_type if safe_site_type else '-'})",
        f"Inventory: proof_token={proof_tokens} rations={rations}",
        f"Faction: {faction_id if faction_id else '-'}",
        f"Role: {role_value if role_value else (entity.template_id if entity.template_id else '-')}",
        f"Location: {_entity_location_text(sim, entity)}",
        f"Target location: {target_summary}",
        f"Source belief: {source_belief_id if source_belief_id else '-'}",
        f"Source action UID: {source_action_uid}",
        "Selection state: active",
        f"Follow status: {follow_status}",
        "",
        "RECENT EVENTS",
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
    return f"tick={tick} | event={event_type} | action_uid={action_uid} | source_action_uid={source_action_uid}"


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
        "--runtime-profile",
        choices=RUNTIME_PROFILE_CHOICES,
        default=DEFAULT_RUNTIME_PROFILE,
        help="Runtime module composition profile.",
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




def _resolve_runtime_profile(
    *,
    runtime_profile: RuntimeProfile,
    with_encounters: bool | None,
) -> RuntimeProfile:
    if with_encounters is None:
        return runtime_profile
    return EXPERIMENTAL_WORLD if with_encounters else CORE_PLAYABLE


def _configure_simulation_modules(
    sim: Simulation,
    *,
    runtime_profile: RuntimeProfile,
    with_encounters: bool | None,
) -> None:
    if with_encounters is None:
        configure_runtime_profile(sim, runtime_profile)
        return
    if with_encounters:
        configure_runtime_profile(sim, EXPERIMENTAL_WORLD)
        return
    configure_non_encounter_viewer_modules(sim)


def _ensure_core_playable_default_scene(sim: Simulation, *, runtime_profile: RuntimeProfile) -> None:
    if runtime_profile != CORE_PLAYABLE:
        return
    if CORE_PLAYABLE_DEFAULT_PATROL_ID not in sim.state.world.campaign_patrols:
        sim.state.world.campaign_patrols[CORE_PLAYABLE_DEFAULT_PATROL_ID] = CampaignPatrolRecord(
            patrol_id=CORE_PLAYABLE_DEFAULT_PATROL_ID,
            template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
            space_id="overworld",
            spawn_position={
                "x": CORE_PLAYABLE_DEFAULT_PATROL_WORLD_POSITION[0],
                "y": CORE_PLAYABLE_DEFAULT_PATROL_WORLD_POSITION[1],
            },
            route_anchors=[{"x": x, "y": y} for x, y in CORE_PLAYABLE_DEFAULT_PATROL_ROUTE],
            label=CORE_PLAYABLE_DEFAULT_PATROL_LABEL,
            tags=["core_playable", "patrol"],
        )

    authored_patrol_ids = sorted(sim.state.world.campaign_patrols)
    keep_patrol_id = authored_patrol_ids[0] if authored_patrol_ids else CORE_PLAYABLE_DEFAULT_PATROL_ID
    authored_patrol = sim.state.world.campaign_patrols.get(keep_patrol_id)
    if authored_patrol is None:
        return
    patrol_ids = sorted(
        entity.entity_id
        for entity in sim.state.entities.values()
        if entity.template_id == authored_patrol.template_id and entity.entity_id != PLAYER_ID
    )
    if not patrol_ids:
        patrol = EntityState(
            entity_id=keep_patrol_id,
            position_x=float(authored_patrol.spawn_position["x"]),
            position_y=float(authored_patrol.spawn_position["y"]),
            speed_per_tick=CORE_PLAYABLE_DEFAULT_PATROL_SPEED,
            template_id=authored_patrol.template_id,
            stats={"faction_id": "hostile", "role": "patrol"},
        )
        sim.add_entity(patrol)
        patrol_ids = [patrol.entity_id]

    keep_entity_patrol_id = patrol_ids[0]
    for patrol_id in patrol_ids[1:]:
        sim.state.entities.pop(patrol_id, None)
    patrol = sim.state.entities.get(keep_entity_patrol_id)
    if patrol is not None:
        patrol.template_id = authored_patrol.template_id
        patrol.space_id = authored_patrol.space_id
        patrol.position_x = float(authored_patrol.spawn_position["x"])
        patrol.position_y = float(authored_patrol.spawn_position["y"])
        patrol.stats = dict(patrol.stats) if isinstance(patrol.stats, dict) else {}
        patrol.stats["faction_id"] = "hostile"
        patrol.stats["role"] = "patrol"


def _build_viewer_simulation(
    map_path: str,
    *,
    runtime_profile: RuntimeProfile = DEFAULT_RUNTIME_PROFILE,
    with_encounters: bool | None = None,
    seed: int = 7,
) -> Simulation:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    resolved_profile = _resolve_runtime_profile(runtime_profile=runtime_profile, with_encounters=with_encounters)
    _configure_simulation_modules(sim, runtime_profile=resolved_profile, with_encounters=with_encounters)
    _ensure_core_playable_default_scene(sim, runtime_profile=resolved_profile)
    return sim


def _load_viewer_simulation(
    save_path: str,
    *,
    runtime_profile: RuntimeProfile = DEFAULT_RUNTIME_PROFILE,
    with_encounters: bool | None = None,
) -> Simulation:
    _, sim = load_game_json(save_path)
    if PLAYER_ID not in sim.state.entities:
        sim.add_entity(EntityState.from_hex(entity_id=PLAYER_ID, hex_coord=HexCoord(0, 0), speed_per_tick=0.22))
    resolved_profile = _resolve_runtime_profile(runtime_profile=runtime_profile, with_encounters=with_encounters)
    _configure_simulation_modules(sim, runtime_profile=resolved_profile, with_encounters=with_encounters)
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
    runtime_profile: RuntimeProfile = DEFAULT_RUNTIME_PROFILE,
    with_encounters: bool | None = None,
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

    resolved_profile = _resolve_runtime_profile(runtime_profile=runtime_profile, with_encounters=with_encounters)
    print(f"[hexcrawler.viewer] runtime_profile={resolved_profile}")

    try:
        sim = _load_viewer_simulation(load_save, runtime_profile=resolved_profile) if load_save else _build_viewer_simulation(
            map_path,
            runtime_profile=resolved_profile,
        )
    except Exception as exc:
        print(f"[hexcrawler.viewer] failed to initialize simulation: {exc}", file=sys.stderr)
        pygame_module.quit()
        return 1

    runtime_state = ViewerRuntimeState(
        sim=sim,
        map_path=map_path,
        with_encounters=(resolved_profile != CORE_PLAYABLE) if with_encounters is None else with_encounters,
        current_save_path=load_save or save_path,
        runtime_profile=resolved_profile,
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
        nonlocal sim, context_menu, previous_snapshot, current_snapshot, last_tick_time, status_message, campaign_move_state, campaign_path_edit_state, last_sent_move_vector, selected_site_id
        try:
            sim = runtime_controller.load_simulation(path_value)
            previous_snapshot = extract_render_snapshot(sim)
            current_snapshot = previous_snapshot
            last_tick_time = pygame_module.time.get_ticks() / 1000.0
            context_menu = None
            push_recent_save(path_value)
            status_message = f"loaded {path_value}"
            campaign_move_state = None
            campaign_path_edit_state = None
            last_sent_move_vector = (0.0, 0.0)
            selected_site_id = None
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
        topology_diagnostic = _viewer_topology_diagnostic(active_space)
        clicked_world: tuple[float, float] | None = None
        if viewport_rect.collidepoint(event_pos):
            world_x, world_y = _pixel_to_world(event_pos[0], event_pos[1], world_center, world_zoom_scale)
            clicked_world = (world_x, world_y)
            markers = _find_world_marker_candidates_at_pixel(sim, event_pos, world_center, world_zoom_scale)
            if markers:
                for marker in markers:
                    items.append(ContextMenuItem(label=f"Marker: {marker.marker_kind} {marker.label}", action="noop"))
                    if marker.marker_kind == "entity":
                        entity_id = _marker_payload_id(marker, expected_kind="entity")
                        if entity_id is None:
                            items.append(ContextMenuItem(label="marker_id malformed: entity", action="noop"))
                            continue
                        items.append(ContextMenuItem(label=f"Select {marker.label}", action="select", payload=entity_id))
                        if sim.selected_entity_id(owner_entity_id=PLAYER_ID) == entity_id:
                            items.append(ContextMenuItem(label=f"Deselect {marker.label}", action="clear_selection"))
                    elif marker.marker_kind == "site":
                        site_id = _marker_payload_id(marker, expected_kind="site")
                        if site_id is None:
                            items.append(ContextMenuItem(label="marker_id malformed: site", action="noop"))
                            continue
                        site = sim.state.world.sites.get(site_id)
                        if site is not None:
                            site_label = site.name if site.name else site.site_id
                            items.append(ContextMenuItem(label=f"Select site: {site_label}", action="select_site", payload=site.site_id))
                            if site.entrance is not None:
                                items.append(ContextMenuItem(label=f"Enter {site_label}", action="enter_site", payload=site.site_id))
                            if site.site_type == "town" or "safe" in site.tags:
                                items.append(ContextMenuItem(label=f"Open services: {site_label}", action="open_home_panel", payload=site.site_id))
                    elif marker.marker_kind == "door":
                        door_id = _marker_payload_id(marker, expected_kind="door")
                        if door_id is None:
                            items.append(ContextMenuItem(label="marker_id malformed: door", action="noop"))
                            continue
                        items.append(ContextMenuItem(label="Door...", action="noop"))
                        items.append(ContextMenuItem(label="- Open (10 ticks)", action="interaction", payload=f"open:door:{door_id}:10"))
                        items.append(ContextMenuItem(label="- Close (10 ticks)", action="interaction", payload=f"close:door:{door_id}:10"))
                        items.append(ContextMenuItem(label="- Toggle (10 ticks)", action="interaction", payload=f"toggle:door:{door_id}:10"))
                    elif marker.marker_kind == "anchor":
                        anchor_id = _marker_payload_id(marker, expected_kind="anchor")
                        if anchor_id is None:
                            items.append(ContextMenuItem(label="marker_id malformed: anchor", action="noop"))
                            continue
                        items.append(ContextMenuItem(label="Exit (30 ticks)", action="interaction", payload=f"exit:anchor:{anchor_id}:30"))
                    elif marker.marker_kind == "interactable":
                        interactable_id = _marker_payload_id(marker, expected_kind="interactable")
                        if interactable_id is None:
                            items.append(ContextMenuItem(label="marker_id malformed: interactable", action="noop"))
                            continue
                        items.append(ContextMenuItem(label="Interactable...", action="noop"))
                        items.append(ContextMenuItem(label="- Inspect (10 ticks)", action="interaction", payload=f"inspect:interactable:{interactable_id}:10"))
                        items.append(ContextMenuItem(label="- Use (20 ticks)", action="interaction", payload=f"use:interactable:{interactable_id}:20"))
                    elif marker.marker_kind == "local_spawner":
                        spawner_id = _marker_payload_id(marker, expected_kind="local_spawner")
                        if spawner_id is not None:
                            items.append(ContextMenuItem(label="Local Spawner...", action="noop"))
                            items.append(
                                ContextMenuItem(
                                    label="Delete hostile spawner",
                                    action="local_dungeon_author_delete_spawner",
                                    payload={"spawner_id": spawner_id},
                                )
                            )
                    elif marker.marker_kind == "local_transition":
                        point_id = _marker_payload_id(marker, expected_kind="local_transition")
                        if point_id is not None:
                            items.append(ContextMenuItem(label="Local Transition Point...", action="noop"))
                            items.append(
                                ContextMenuItem(
                                    label="Delete transition point",
                                    action="local_dungeon_author_delete_point",
                                    payload={"point_id": point_id},
                                )
                            )
                            items.append(
                                ContextMenuItem(
                                    label="Use this exit",
                                    action="local_dungeon_author_use_point",
                                    payload={"point_id": point_id},
                                )
                            )
                items.append(ContextMenuItem(label="Explore...", action="noop"))
                items.append(ContextMenuItem(label="- Search (60 ticks)", action="explore", payload="search:60"))
                items.append(ContextMenuItem(label="- Listen (30 ticks)", action="explore", payload="listen:30"))
                items.append(ContextMenuItem(label="- Rest (120 ticks)", action="explore", payload="rest:120"))
                items.append(ContextMenuItem(label="Clear selection", action="clear_selection"))
                if active_space is not None and str(getattr(active_space, "role", "")) == CAMPAIGN_SPACE_ROLE:
                    if campaign_move_state is not None:
                        items.append(
                            ContextMenuItem(
                                label=f"Place moved {campaign_move_state.label} here",
                                action="campaign_author_move_commit",
                                payload={
                                    "kind": campaign_move_state.kind,
                                    "id": campaign_move_state.object_id,
                                    "position": {"x": float(world_x), "y": float(world_y)},
                                },
                            )
                        )
                        items.append(ContextMenuItem(label="Cancel move (Esc)", action="campaign_author_move_cancel"))
                    authored_target = _campaign_authored_object_at_world(sim, world_x=world_x, world_y=world_y)
                    if authored_target is not None:
                        items.extend(_campaign_authoring_edit_items(authored_target))
                    if campaign_path_edit_state is not None:
                        anchor_index = _campaign_patrol_anchor_at_world(
                            sim,
                            patrol_id=campaign_path_edit_state.patrol_id,
                            world_x=world_x,
                            world_y=world_y,
                        )
                        if anchor_index is not None:
                            items.append(
                                ContextMenuItem(
                                    label=f"Move route anchor #{anchor_index} here",
                                    action="campaign_author_path_move_anchor",
                                    payload={
                                        "patrol_id": campaign_path_edit_state.patrol_id,
                                        "anchor_index": anchor_index,
                                        "position": {"x": float(world_x), "y": float(world_y)},
                                    },
                                )
                            )
                            items.append(
                                ContextMenuItem(
                                    label=f"Delete route anchor #{anchor_index}",
                                    action="campaign_author_path_delete_anchor",
                                    payload={"patrol_id": campaign_path_edit_state.patrol_id, "anchor_index": anchor_index},
                                )
                            )
                        items.append(
                            ContextMenuItem(
                                label="Add route anchor here",
                                action="campaign_author_path_add_anchor",
                                payload={"patrol_id": campaign_path_edit_state.patrol_id, "position": {"x": float(world_x), "y": float(world_y)}},
                            )
                        )
                        items.append(ContextMenuItem(label="Finish path edit (Esc)", action="campaign_author_path_finish"))
            else:
                if topology_diagnostic is not None:
                    items.append(ContextMenuItem(label=topology_diagnostic, action="noop"))
                elif active_space is not None and str(getattr(active_space, "role", "")) == LOCAL_SPACE_ROLE:
                    local_cell = _world_to_local_cell(world_x, world_y, active_space=active_space)
                    if local_cell is not None:
                        local_world_x, local_world_y = square_grid_cell_to_world_xy(local_cell["x"], local_cell["y"])
                        items.append(ContextMenuItem(label="Move here", action="move_here", payload=f"{local_world_x},{local_world_y}"))
                        if player is not None and _is_local_structure_authoring_enabled_space(str(player.space_id)):
                            include_dungeon_targets = str(player.space_id).startswith("local_site:")
                            if local_move_state is not None:
                                items.append(
                                    ContextMenuItem(
                                        label=f"Place moved {local_move_state.label} here",
                                        action="local_author_move_commit",
                                        payload={
                                            "kind": local_move_state.kind,
                                            "id": local_move_state.object_id,
                                            "point_kind": local_move_state.point_kind,
                                            "structure_id": local_move_state.structure_id,
                                            "coord": {"x": int(local_cell['x']), "y": int(local_cell['y'])},
                                        },
                                    )
                                )
                                items.append(ContextMenuItem(label="Cancel move (Esc)", action="local_author_move_cancel"))
                            authored_target = _local_authored_target_at_cell(
                                active_space,
                                cell=local_cell,
                                include_dungeon_targets=include_dungeon_targets,
                            )
                            if authored_target is None:
                                items.extend(_local_structure_authoring_placement_items(active_space, cell=local_cell))
                                if include_dungeon_targets:
                                    items.extend(_local_dungeon_authoring_placement_items(active_space, cell=local_cell))
                            elif authored_target.get("kind") in {"structure", "opening"}:
                                items.extend(_local_structure_authoring_edit_items(authored_target))
                            elif include_dungeon_targets:
                                items.extend(_local_dungeon_authoring_edit_items(authored_target))
                        items.append(ContextMenuItem(label="Explore...", action="noop"))
                        items.append(ContextMenuItem(label="- Search (60 ticks)", action="explore", payload="search:60"))
                        items.append(ContextMenuItem(label="- Listen (30 ticks)", action="explore", payload="listen:30"))
                        items.append(ContextMenuItem(label="- Rest (120 ticks)", action="explore", payload="rest:120"))
                        items.append(ContextMenuItem(label="Clear selection", action="clear_selection"))
                else:
                    target_hex = world_xy_to_axial(world_x, world_y)
                    if sim.state.world.get_hex_record(target_hex) is not None:
                        if campaign_move_state is not None:
                            items.append(
                                ContextMenuItem(
                                    label=f"Place moved {campaign_move_state.label} here",
                                    action="campaign_author_move_commit",
                                    payload={
                                        "kind": campaign_move_state.kind,
                                        "id": campaign_move_state.object_id,
                                        "position": {"x": float(world_x), "y": float(world_y)},
                                    },
                                )
                            )
                            items.append(ContextMenuItem(label="Cancel move (Esc)", action="campaign_author_move_cancel"))
                        authored_target = _campaign_authored_object_at_world(sim, world_x=world_x, world_y=world_y)
                        if authored_target is not None:
                            items.extend(_campaign_authoring_edit_items(authored_target))
                        else:
                            items.extend(_campaign_authoring_placement_items(world_x, world_y))
                        if campaign_path_edit_state is not None:
                            anchor_index = _campaign_patrol_anchor_at_world(
                                sim,
                                patrol_id=campaign_path_edit_state.patrol_id,
                                world_x=world_x,
                                world_y=world_y,
                            )
                            if anchor_index is not None:
                                items.append(
                                    ContextMenuItem(
                                        label=f"Move route anchor #{anchor_index} here",
                                        action="campaign_author_path_move_anchor",
                                        payload={
                                            "patrol_id": campaign_path_edit_state.patrol_id,
                                            "anchor_index": anchor_index,
                                            "position": {"x": float(world_x), "y": float(world_y)},
                                        },
                                    )
                                )
                                items.append(
                                    ContextMenuItem(
                                        label=f"Delete route anchor #{anchor_index}",
                                        action="campaign_author_path_delete_anchor",
                                        payload={"patrol_id": campaign_path_edit_state.patrol_id, "anchor_index": anchor_index},
                                    )
                                )
                            items.append(
                                ContextMenuItem(
                                    label="Add route anchor here",
                                    action="campaign_author_path_add_anchor",
                                    payload={"patrol_id": campaign_path_edit_state.patrol_id, "position": {"x": float(world_x), "y": float(world_y)}},
                                )
                            )
                            items.append(ContextMenuItem(label="Finish path edit (Esc)", action="campaign_author_path_finish"))
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
        if player is not None:
            spatial_actions = _spatial_context_actions(sim, player=player)
            if spatial_actions:
                items.append(ContextMenuItem(label="Nearby actions...", action="noop"))
                items.extend(spatial_actions)
        if active_space is not None and str(getattr(active_space, "role", "")) == "local":
            return_context = _get_return_context_for_space(sim, active_space.space_id)
            authored_return_points = [
                row
                for row in getattr(active_space, "local_transition_points", [])
                if isinstance(row, dict)
                and bool(row.get("enabled", True))
                and str(row.get("point_kind", "")) in {"extraction_exit", "return_to_origin_exit"}
            ]
            if return_context is None and authored_return_points:
                point = sorted(authored_return_points, key=lambda row: str(row.get("point_id", "")))[0]
                items.append(
                    ContextMenuItem(
                        label=f"Return via authored exit ({point.get('point_id', '?')})",
                        action="local_dungeon_author_use_point",
                        payload={"point_id": str(point.get("point_id", ""))},
                    )
                )
            elif return_context is None:
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
        if clicked_world is not None and active_space is not None and str(getattr(active_space, "role", "")) == CAMPAIGN_SPACE_ROLE:
            if campaign_move_state is not None and not any(item.action == "campaign_author_move_commit" for item in items):
                items.append(
                    ContextMenuItem(
                        label=f"Place moved {campaign_move_state.label} here",
                        action="campaign_author_move_commit",
                        payload={
                            "kind": campaign_move_state.kind,
                            "id": campaign_move_state.object_id,
                            "position": {"x": float(clicked_world[0]), "y": float(clicked_world[1])},
                        },
                    )
                )
                items.append(ContextMenuItem(label="Cancel move (Esc)", action="campaign_author_move_cancel"))
            authored_target = _campaign_authored_object_at_world(sim, world_x=clicked_world[0], world_y=clicked_world[1])
            if authored_target is not None and not any(item.action == "campaign_author_delete" for item in items):
                items.extend(_campaign_authoring_edit_items(authored_target))
            if authored_target is None and not any(item.action == "campaign_author_place" for item in items):
                target_hex = world_xy_to_axial(clicked_world[0], clicked_world[1])
                if sim.state.world.get_hex_record(target_hex) is not None:
                    items.extend(_campaign_authoring_placement_items(clicked_world[0], clicked_world[1]))
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
    home_panel_state = HomePanelState()

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
    campaign_move_state: CampaignAuthoringMoveState | None = None
    local_move_state: LocalAuthoringMoveState | None = None
    campaign_path_edit_state: CampaignAuthoringPathEditState | None = None
    last_sent_move_vector = (0.0, 0.0)
    selected_site_id: str | None = None
    visual_facing_by_entity: dict[str, float] = {}

    while running:
        target_fps = 30 if runtime_state.paused else 60
        dt = clock.tick(target_fps) / 1000.0
        accumulator += dt

        offer_buttons: dict[str, pygame.Rect] = {}
        for event in pygame_module.event.get():
            if event.type == pygame_module.QUIT:
                running = False
            elif event.type == pygame_module.VIDEORESIZE:
                screen = pygame_module.display.set_mode((event.w, event.h), pygame_module.RESIZABLE)
                layout = _compute_viewer_layout(screen.get_size())
                viewport_rect = layout.world_view
                local_camera_cache = LocalCameraCache(center=(float(viewport_rect.centerx), float(viewport_rect.centery)), zoom_scale=1.0)
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_ESCAPE:
                if home_panel_state.visible:
                    home_panel_state.visible = False
                    status_message = "home panel closed"
                elif campaign_move_state is not None:
                    campaign_move_state = None
                    status_message = "campaign authoring: move canceled"
                elif local_move_state is not None:
                    local_move_state = None
                    status_message = "local authoring: move canceled"
                elif campaign_path_edit_state is not None:
                    patrol_label = campaign_path_edit_state.label
                    campaign_path_edit_state = None
                    status_message = f"campaign authoring: patrol path edit finished ({patrol_label})"
                else:
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
                selected_site_id = None
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
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_f:
                if _pending_encounter_offer(sim) is not None:
                    controller.accept_encounter_offer()
                    advanced = runtime_controller.resolve_pending_offer_decision()
                    if _pending_encounter_offer(sim) is None:
                        status_message = f"encounter offer accepted (resolved in {advanced} ticks)"
                    else:
                        status_message = f"encounter offer accept pending after {advanced} ticks (cap reached)"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_x:
                if _pending_encounter_offer(sim) is not None:
                    controller.flee_encounter_offer()
                    advanced = runtime_controller.resolve_pending_offer_decision()
                    if _pending_encounter_offer(sim) is None:
                        status_message = f"encounter offer fled (resolved in {advanced} ticks)"
                    else:
                        status_message = f"encounter offer flee pending after {advanced} ticks (cap reached)"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_l:
                controller.loot_local_proof_intent()
                status_message = "loot proof intent queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_t:
                controller.turn_in_reward_token_intent()
                status_message = "turn-in intent queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_r:
                controller.safe_recovery_intent()
                status_message = "recover intent queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_q:
                controller.exit_safe_hub_intent()
                status_message = "exit Greybridge hub intent queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_b:
                player = sim.state.entities.get(PLAYER_ID)
                if player is not None and player.space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID:
                    x, y = int(player.position_x), int(player.position_y)
                    controller.local_structure_author_intent(
                        "create_rect",
                        structure_id="authoring_demo_shell",
                        label="Author Demo",
                        room_id="authoring_demo",
                        bounds={"x": x, "y": y, "width": 4, "height": 3},
                        tags=["authoring_demo"],
                    )
                    status_message = "authoring: create demo structure queued"
                elif player is not None and player.space_id == "overworld":
                    controller.campaign_author_intent(
                        "create_or_update_site",
                        site_id="authoring_town_site",
                        site_kind="town",
                        label="Authoring Town",
                        position={"x": float(player.position_x), "y": float(player.position_y)},
                    )
                    status_message = "campaign authoring: town create/update queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_o:
                player = sim.state.entities.get(PLAYER_ID)
                if player is not None and player.space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID:
                    x, y = int(player.position_x), int(player.position_y)
                    controller.local_structure_author_intent(
                        "move_opening",
                        structure_id="authoring_demo_shell",
                        opening_id="authoring_demo_opening",
                        kind="door",
                        cell={"x": x, "y": y},
                    )
                    status_message = "authoring: move demo opening queued"
                elif player is not None and player.space_id == "overworld":
                    controller.campaign_author_intent(
                        "create_or_update_site",
                        site_id="authoring_dungeon_site",
                        site_kind="dungeon_entrance",
                        label="Authoring Dungeon Entrance",
                        position={"x": float(player.position_x), "y": float(player.position_y)},
                    )
                    status_message = "campaign authoring: dungeon create/update queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_p:
                player = sim.state.entities.get(PLAYER_ID)
                if player is not None and player.space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID:
                    controller.local_structure_author_intent(
                        "remove_opening",
                        structure_id="authoring_demo_shell",
                        opening_id="authoring_demo_opening",
                    )
                    status_message = "authoring: remove demo opening queued"
                elif player is not None and player.space_id == "overworld":
                    controller.campaign_author_intent(
                        "create_or_update_patrol",
                        patrol_id="patrol:authoring_demo",
                        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
                        label="Authoring Demo Patrol",
                        position={"x": float(player.position_x), "y": float(player.position_y)},
                        route_anchors=[{"x": float(player.position_x) + 1.0, "y": float(player.position_y)}],
                        tags=["authoring_demo"],
                    )
                    status_message = "campaign authoring: patrol create/update queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_m:
                player = sim.state.entities.get(PLAYER_ID)
                if player is not None and player.space_id == "overworld":
                    controller.campaign_author_intent(
                        "move_patrol_anchor",
                        patrol_id="patrol:authoring_demo",
                        anchor_index=0,
                        position={"x": float(player.position_x), "y": float(player.position_y)},
                    )
                    status_message = "campaign authoring: patrol anchor move queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_DELETE:
                player = sim.state.entities.get(PLAYER_ID)
                if player is not None and player.space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID:
                    controller.local_structure_author_intent("delete_structure", structure_id="authoring_demo_shell")
                    status_message = "authoring: delete demo structure queued"
                elif player is not None and player.space_id == "overworld":
                    controller.campaign_author_intent("delete_site", site_id="authoring_town_site")
                    controller.campaign_author_intent("delete_site", site_id="authoring_dungeon_site")
                    controller.campaign_author_intent("delete_patrol", patrol_id="patrol:authoring_demo")
                    status_message = "campaign authoring: delete demo town/dungeon/patrol queued"
            elif event.type == pygame_module.KEYDOWN and event.key == pygame_module.K_SPACE:
                player = sim.state.entities.get(PLAYER_ID)
                selected_entity_id = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
                if player is not None and selected_entity_id is not None:
                    active_space = sim.state.world.spaces.get(player.space_id)
                    target = sim.state.entities.get(selected_entity_id)
                    if (
                        active_space is not None
                        and str(getattr(active_space, "role", "")) == LOCAL_SPACE_ROLE
                        and target is not None
                        and target.entity_id != PLAYER_ID
                        and target.space_id == player.space_id
                    ):
                        controller.attack_entity(target.entity_id)
                        status_message = f"attack queued -> {target.entity_id}"
            elif event.type == pygame_module.KEYDOWN and event.key in (pygame_module.K_RETURN, pygame_module.K_e):
                player = sim.state.entities.get(PLAYER_ID)
                if player is not None:
                    active_space = sim.state.world.spaces.get(player.space_id)
                    if active_space is not None and str(getattr(active_space, "role", "")) == "campaign":
                        status_message, selected_site_id, open_site_panel = _use_campaign_site(
                            sim,
                            controller,
                            player=player,
                            selected_site_id=selected_site_id,
                        )
                        if open_site_panel:
                            home_panel_state.visible = True
                            home_panel_state.site_id = selected_site_id
                    else:
                        controller.exit_safe_hub_intent()
                        status_message = "exit Greybridge hub intent queued"
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
                row_index = _context_menu_item_index_at_pixel(context_menu, font, viewport_rect, event.pos)
                if row_index is not None and 0 <= row_index < len(context_menu.items):
                        item = context_menu.items[row_index]
                        if item.action == "move_here" and item.payload is not None:
                            x_str, y_str = item.payload.split(",", 1)
                            controller.set_target_world(float(x_str), float(y_str))
                        elif item.action == "campaign_author_place" and isinstance(item.payload, dict):
                            kind = str(item.payload.get("kind", ""))
                            position = item.payload.get("position", {})
                            if kind == "town":
                                controller.campaign_author_intent(
                                    "create_or_update_site",
                                    site_id=str(item.payload.get("site_id", "")),
                                    site_kind="town",
                                    label=str(item.payload.get("label", "Authored Town")),
                                    position=position,
                                )
                                status_message = "campaign authoring: town placement queued"
                            elif kind == "dungeon_entrance":
                                controller.campaign_author_intent(
                                    "create_or_update_site",
                                    site_id=str(item.payload.get("site_id", "")),
                                    site_kind="dungeon_entrance",
                                    label=str(item.payload.get("label", "Authored Dungeon Entrance")),
                                    position=position,
                                )
                                status_message = "campaign authoring: dungeon entrance placement queued"
                            elif kind == "patrol":
                                px = float(position.get("x", 0.0)) if isinstance(position, dict) else 0.0
                                py = float(position.get("y", 0.0)) if isinstance(position, dict) else 0.0
                                patrol_id = str(item.payload.get("patrol_id", ""))
                                patrol_label = str(item.payload.get("label", "Authored Patrol"))
                                controller.campaign_author_intent(
                                    "create_or_update_patrol",
                                    patrol_id=patrol_id,
                                    template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
                                    label=patrol_label,
                                    position={"x": px, "y": py},
                                    route_anchors=[],
                                    tags=["authoring"],
                                )
                                campaign_path_edit_state = CampaignAuthoringPathEditState(patrol_id=patrol_id, label=patrol_label)
                                status_message = (
                                    f"campaign authoring: patrol placement queued ({patrol_label}); "
                                    "Add at least 1 route anchor to start loop. Right-click to add anchor(s), right-click anchor to move/delete, Esc to finish"
                                )
                        elif item.action == "campaign_author_move" and isinstance(item.payload, dict):
                            target_kind = str(item.payload.get("kind", ""))
                            target_id = str(item.payload.get("id", ""))
                            target_label = str(item.payload.get("label", target_id))
                            if target_kind in {"site", "patrol"} and target_id:
                                campaign_move_state = CampaignAuthoringMoveState(
                                    kind=target_kind,
                                    object_id=target_id,
                                    label=target_label,
                                )
                                status_message = f"campaign authoring: move pending for {target_label}; right-click destination and choose place"
                        elif item.action == "campaign_author_edit_path" and isinstance(item.payload, dict):
                            target_kind = str(item.payload.get("kind", ""))
                            target_id = str(item.payload.get("id", ""))
                            target_label = str(item.payload.get("label", target_id))
                            if target_kind == "patrol" and target_id:
                                campaign_path_edit_state = CampaignAuthoringPathEditState(patrol_id=target_id, label=target_label)
                                status_message = (
                                    f"campaign authoring: path edit for {target_label}; "
                                    "right-click to add anchor, right-click anchor to move/delete, Esc to finish"
                                )
                        elif item.action == "campaign_author_path_move_anchor" and isinstance(item.payload, dict):
                            patrol_id = str(item.payload.get("patrol_id", "")).strip()
                            anchor_index = item.payload.get("anchor_index")
                            position = item.payload.get("position", {})
                            controller.campaign_author_intent(
                                "move_patrol_anchor",
                                patrol_id=patrol_id,
                                anchor_index=anchor_index,
                                position=position,
                            )
                            status_message = f"campaign authoring: patrol anchor move queued ({patrol_id} #{anchor_index})"
                        elif item.action == "campaign_author_move_commit" and isinstance(item.payload, dict):
                            target_kind = str(item.payload.get("kind", ""))
                            target_id = str(item.payload.get("id", ""))
                            position = item.payload.get("position", {})
                            if target_kind == "site":
                                controller.campaign_author_intent("move_site", site_id=target_id, position=position)
                                status_message = f"campaign authoring: moved site {target_id}"
                                campaign_move_state = None
                            elif target_kind == "patrol":
                                controller.campaign_author_intent("move_patrol_spawn", patrol_id=target_id, position=position)
                                status_message = f"campaign authoring: moved patrol {target_id}"
                                campaign_move_state = None
                        elif item.action == "campaign_author_move_cancel":
                            campaign_move_state = None
                            status_message = "campaign authoring: move canceled"
                        elif item.action == "local_author_move_cancel":
                            local_move_state = None
                            status_message = "local authoring: move canceled"
                        elif item.action == "campaign_author_delete" and isinstance(item.payload, dict):
                            target_kind = str(item.payload.get("kind", ""))
                            target_id = str(item.payload.get("id", ""))
                            if target_kind == "site" and target_id:
                                controller.campaign_author_intent("delete_site", site_id=target_id)
                                status_message = f"campaign authoring: delete site queued ({target_id})"
                            elif target_kind == "patrol" and target_id:
                                controller.campaign_author_intent("delete_patrol", patrol_id=target_id)
                                status_message = f"campaign authoring: delete patrol queued ({target_id})"
                            if campaign_move_state is not None and campaign_move_state.object_id == target_id:
                                campaign_move_state = None
                            if campaign_path_edit_state is not None and campaign_path_edit_state.patrol_id == target_id and target_kind == "patrol":
                                campaign_path_edit_state = None
                        elif item.action == "campaign_author_path_add_anchor" and isinstance(item.payload, dict):
                            patrol_id = str(item.payload.get("patrol_id", "")).strip()
                            position = item.payload.get("position", {})
                            patrol = sim.state.world.campaign_patrols.get(patrol_id)
                            if patrol is not None:
                                anchor_index = len(patrol.route_anchors)
                                controller.campaign_author_intent(
                                    "move_patrol_anchor",
                                    patrol_id=patrol_id,
                                    anchor_index=anchor_index,
                                    position=position,
                                )
                                status_message = f"campaign authoring: patrol anchor added ({patrol_id} #{anchor_index})"
                        elif item.action == "campaign_author_path_delete_anchor" and isinstance(item.payload, dict):
                            patrol_id = str(item.payload.get("patrol_id", "")).strip()
                            anchor_index = item.payload.get("anchor_index")
                            controller.campaign_author_intent(
                                "delete_patrol_anchor",
                                patrol_id=patrol_id,
                                anchor_index=anchor_index,
                            )
                            status_message = f"campaign authoring: patrol anchor delete queued ({patrol_id} #{anchor_index})"
                        elif item.action == "campaign_author_path_finish":
                            if campaign_path_edit_state is not None:
                                patrol_label = campaign_path_edit_state.label
                                campaign_path_edit_state = None
                                status_message = f"campaign authoring: patrol path edit finished ({patrol_label})"
                        elif item.action == "local_dungeon_author_place_spawner" and isinstance(item.payload, dict):
                            controller.local_dungeon_author_intent(
                                "upsert_hostile_spawner",
                                spawner_id=str(item.payload.get("spawner_id", "")),
                                coord=item.payload.get("coord", {}),
                                template_id="encounter_hostile_v1",
                                count=1,
                                enabled=True,
                            )
                            status_message = "local authoring: hostile spawner placed"
                        elif item.action == "local_dungeon_author_move_spawner" and isinstance(item.payload, dict):
                            spawner_id = str(item.payload.get("spawner_id", "")).strip()
                            if spawner_id:
                                local_move_state = LocalAuthoringMoveState(
                                    kind="spawner",
                                    object_id=spawner_id,
                                    label=str(item.payload.get("label", "hostile spawner")),
                                )
                                status_message = "local authoring: move pending for hostile spawner; right-click destination and choose place"
                        elif item.action == "local_dungeon_author_delete_spawner" and isinstance(item.payload, dict):
                            controller.local_dungeon_author_intent(
                                "delete_hostile_spawner",
                                spawner_id=str(item.payload.get("spawner_id", "")),
                            )
                            status_message = "local authoring: hostile spawner deleted"
                        elif item.action == "local_dungeon_author_place_point" and isinstance(item.payload, dict):
                            controller.local_dungeon_author_intent(
                                "upsert_transition_point",
                                point_id=str(item.payload.get("point_id", "")),
                                coord=item.payload.get("coord", {}),
                                point_kind=str(item.payload.get("point_kind", "")),
                                enabled=True,
                            )
                            status_message = "local authoring: transition point placed"
                        elif item.action == "local_dungeon_author_move_point" and isinstance(item.payload, dict):
                            point_id = str(item.payload.get("point_id", "")).strip()
                            if point_id:
                                local_move_state = LocalAuthoringMoveState(
                                    kind="transition",
                                    object_id=point_id,
                                    label=str(item.payload.get("label", "transition point")),
                                    point_kind=str(item.payload.get("point_kind", "")),
                                )
                                status_message = "local authoring: move pending for transition point; right-click destination and choose place"
                        elif item.action == "local_dungeon_author_delete_point" and isinstance(item.payload, dict):
                            controller.local_dungeon_author_intent(
                                "delete_transition_point",
                                point_id=str(item.payload.get("point_id", "")),
                            )
                            status_message = "local authoring: transition point deleted"
                        elif item.action == "local_structure_author_place_structure" and isinstance(item.payload, dict):
                            controller.local_structure_author_intent(
                                "create_rect",
                                structure_id=str(item.payload.get("structure_id", "")),
                                label=str(item.payload.get("label", "Structure")),
                                room_id=str(item.payload.get("room_id", "room")),
                                bounds=item.payload.get("bounds", {}),
                                tags=["authoring"],
                            )
                            status_message = "local structure authoring: structure placement queued"
                        elif item.action == "local_structure_author_place_opening" and isinstance(item.payload, dict):
                            controller.local_structure_author_intent(
                                "upsert_opening",
                                structure_id=str(item.payload.get("structure_id", "")),
                                opening_id=str(item.payload.get("opening_id", "")),
                                kind=str(item.payload.get("kind", "door")),
                                cell=item.payload.get("cell", {}),
                            )
                            status_message = "local structure authoring: opening placement queued"
                        elif item.action == "local_structure_author_move_structure" and isinstance(item.payload, dict):
                            structure_id = str(item.payload.get("structure_id", "")).strip()
                            if structure_id:
                                local_move_state = LocalAuthoringMoveState(
                                    kind="structure",
                                    object_id=structure_id,
                                    label=str(item.payload.get("label", structure_id)),
                                )
                                status_message = "local structure authoring: move pending for structure; right-click destination and choose place"
                        elif item.action == "local_structure_author_move_opening" and isinstance(item.payload, dict):
                            opening_id = str(item.payload.get("opening_id", "")).strip()
                            structure_id = str(item.payload.get("structure_id", "")).strip()
                            if opening_id and structure_id:
                                local_move_state = LocalAuthoringMoveState(
                                    kind="opening",
                                    object_id=opening_id,
                                    label=str(item.payload.get("label", opening_id)),
                                    structure_id=structure_id,
                                )
                                status_message = "local structure authoring: move pending for opening; right-click destination and choose place"
                        elif item.action == "local_structure_author_delete_structure" and isinstance(item.payload, dict):
                            controller.local_structure_author_intent(
                                "delete_structure",
                                structure_id=str(item.payload.get("structure_id", "")),
                            )
                            status_message = "local structure authoring: delete structure queued"
                        elif item.action == "local_structure_author_delete_opening" and isinstance(item.payload, dict):
                            controller.local_structure_author_intent(
                                "remove_opening",
                                structure_id=str(item.payload.get("structure_id", "")),
                                opening_id=str(item.payload.get("opening_id", "")),
                            )
                            status_message = "local structure authoring: delete opening queued"
                        elif item.action == "local_author_move_commit" and isinstance(item.payload, dict):
                            target_kind = str(item.payload.get("kind", ""))
                            target_id = str(item.payload.get("id", ""))
                            coord = item.payload.get("coord", {})
                            if target_kind == "spawner":
                                controller.local_dungeon_author_intent(
                                    "upsert_hostile_spawner",
                                    spawner_id=target_id,
                                    coord=coord,
                                    template_id="encounter_hostile_v1",
                                    count=1,
                                    enabled=True,
                                )
                                status_message = "local authoring: hostile spawner moved"
                                local_move_state = None
                            elif target_kind == "transition":
                                controller.local_dungeon_author_intent(
                                    "upsert_transition_point",
                                    point_id=target_id,
                                    coord=coord,
                                    point_kind=str(item.payload.get("point_kind", "")),
                                    enabled=True,
                                )
                                status_message = "local authoring: transition point moved"
                                local_move_state = None
                            elif target_kind == "structure":
                                active_player = sim.state.entities.get(PLAYER_ID)
                                space = sim.state.world.spaces.get(active_player.space_id) if active_player is not None else None
                                source = None
                                for row in getattr(space, "structure_primitives", []):
                                    if isinstance(row, dict) and str(row.get("structure_id", "")) == target_id:
                                        source = row
                                        break
                                bounds = source.get("bounds", {}) if isinstance(source, dict) else {}
                                width = int(bounds.get("width", 4)) if isinstance(bounds, dict) else 4
                                height = int(bounds.get("height", 3)) if isinstance(bounds, dict) else 3
                                label = str(source.get("label", target_id)) if isinstance(source, dict) else target_id
                                room_id = str(source.get("room_id", target_id)) if isinstance(source, dict) else target_id
                                tags = source.get("tags", ()) if isinstance(source, dict) else ()
                                controller.local_structure_author_intent(
                                    "create_rect",
                                    structure_id=target_id,
                                    label=label,
                                    room_id=room_id,
                                    bounds={"x": int(coord.get("x", 0)), "y": int(coord.get("y", 0)), "width": width, "height": height},
                                    tags=tags,
                                )
                                status_message = "local structure authoring: structure moved"
                                local_move_state = None
                            elif target_kind == "opening":
                                controller.local_structure_author_intent(
                                    "move_opening",
                                    structure_id=str(item.payload.get("structure_id", "")),
                                    opening_id=target_id,
                                    kind="door",
                                    cell=coord,
                                )
                                status_message = "local structure authoring: opening moved"
                                local_move_state = None
                        elif item.action == "local_dungeon_author_use_point" and isinstance(item.payload, dict):
                            controller.local_dungeon_author_intent(
                                "use_transition_point",
                                point_id=str(item.payload.get("point_id", "")),
                            )
                            status_message = "local authoring: extraction queued"
                        elif item.action == "select" and item.payload is not None:
                            controller.set_selected_entity(item.payload)
                        elif item.action == "clear_selection":
                            controller.clear_selected_entity()
                        elif item.action == "select_site" and item.payload is not None:
                            selected_site_id = item.payload
                            status_message = f"selected site -> {item.payload}"
                        elif item.action == "load_recent" and item.payload is not None:
                            load_simulation_from_path(item.payload)
                        elif item.action == "enter_site" and item.payload is not None:
                            controller.enter_site(item.payload)
                        elif item.action == "open_home_panel":
                            home_panel_state.visible = True
                            home_panel_state.site_id = item.payload
                            status_message = f"site services opened: {item.payload if item.payload else 'town'}"
                        elif item.action == "home_recover":
                            controller.safe_recovery_intent()
                            status_message = "recover intent queued"
                        elif item.action == "home_turn_in":
                            controller.turn_in_reward_token_intent()
                            status_message = "turn-in intent queued"
                        elif item.action == "loot_local_proof":
                            controller.loot_local_proof_intent()
                            status_message = "loot proof intent queued"
                        elif item.action == "exit_safe_hub":
                            controller.exit_safe_hub_intent()
                            status_message = "exit Greybridge hub intent queued"
                        elif item.action == "explore" and item.payload is not None:
                            action, duration_str = item.payload.split(":", 1)
                            controller.explore_intent(action, int(duration_str))
                        elif item.action == "interaction" and item.payload is not None:
                            interaction_type, target_kind, target_id, duration_str = item.payload.split(":", 3)
                            controller.interaction_intent(interaction_type, target_kind, target_id, int(duration_str))
                        elif item.action == "return_to_origin":
                            controller.end_local_encounter()
                context_menu = None
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and home_panel_state.visible:
                home_buttons = _home_panel_buttons_for_click(sim, viewport_rect)
                if home_buttons.get("recover") is not None and home_buttons["recover"].collidepoint(event.pos):
                    controller.safe_recovery_intent()
                    status_message = "recover intent queued"
                elif home_buttons.get("turn_in") is not None and home_buttons["turn_in"].collidepoint(event.pos):
                    controller.turn_in_reward_token_intent()
                    status_message = "turn-in intent queued"
                elif home_buttons.get("close") is not None and home_buttons["close"].collidepoint(event.pos):
                    home_panel_state.visible = False
                    status_message = "home panel closed"
                else:
                    panel_player = sim.state.entities.get(PLAYER_ID)
                    if panel_player is not None:
                        panel_rect = _home_panel_rect(viewport_rect, len(_home_panel_lines(sim, entity=panel_player)))
                        if not panel_rect.collidepoint(event.pos):
                            home_panel_state.visible = False
            elif event.type == pygame_module.MOUSEBUTTONDOWN and event.button == 1 and viewport_rect.collidepoint(event.pos):
                if home_panel_state.visible:
                    continue
                if _pending_encounter_offer(sim) is not None:
                    if offer_buttons.get("fight") is not None and offer_buttons["fight"].collidepoint(event.pos):
                        controller.accept_encounter_offer()
                        advanced = runtime_controller.resolve_pending_offer_decision()
                        if _pending_encounter_offer(sim) is None:
                            status_message = f"encounter offer accepted (resolved in {advanced} ticks)"
                        else:
                            status_message = f"encounter offer accept pending after {advanced} ticks (cap reached)"
                        continue
                    if offer_buttons.get("flee") is not None and offer_buttons["flee"].collidepoint(event.pos):
                        controller.flee_encounter_offer()
                        advanced = runtime_controller.resolve_pending_offer_decision()
                        if _pending_encounter_offer(sim) is None:
                            status_message = f"encounter offer fled (resolved in {advanced} ticks)"
                        else:
                            status_message = f"encounter offer flee pending after {advanced} ticks (cap reached)"
                        continue
                site_id = _open_home_panel_from_marker_click(
                    sim,
                    pixel_pos=event.pos,
                    center=world_center,
                    zoom_scale=world_zoom_scale,
                )
                selected_site = _site_for_marker_click(
                    sim,
                    pixel_pos=event.pos,
                    center=world_center,
                    zoom_scale=world_zoom_scale,
                )
                if selected_site is not None:
                    selected_site_id = selected_site.site_id
                    status_message = f"selected site -> {selected_site.name if selected_site.name else selected_site.site_id}"
                    if site_id is not None:
                        home_panel_state.visible = True
                        home_panel_state.site_id = site_id
                        status_message = f"site services opened: {selected_site.name if selected_site.name else selected_site.site_id}"
                    continue
                attack_status = _queue_local_attack_for_click(
                    sim,
                    controller,
                    event.pos,
                    world_center,
                    world_zoom_scale,
                    radius_px=12.0,
                )
                status_message = attack_status or _queue_selection_command_for_click(
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

        single_player_offer_pause = _single_player_offer_pause(sim)
        accumulator, ticks_advanced = _drain_sim_accumulator(
            accumulator,
            SIM_TICK_SECONDS,
            paused=(runtime_state.paused or single_player_offer_pause),
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

        max_facing_step = max(0.0, float(dt)) * FACING_SWING_RADIANS_PER_SECOND
        tracked_ids = set(sim.state.entities.keys())
        for stale_id in tuple(visual_facing_by_entity.keys()):
            if stale_id not in tracked_ids:
                visual_facing_by_entity.pop(stale_id, None)
        for entity_id, entity in sim.state.entities.items():
            authoritative_facing_angle = _facing_angle_radians(entity.facing)
            prior_display_heading = visual_facing_by_entity.get(entity_id)
            fallback_display_heading = authoritative_facing_angle if prior_display_heading is None else prior_display_heading
            target_angle = _display_heading_angle_from_motion(
                previous_snapshot=previous_snapshot,
                current_snapshot=current_snapshot,
                entity_id=entity_id,
                fallback_angle=fallback_display_heading,
            )
            current_angle = visual_facing_by_entity.get(entity_id, fallback_display_heading)
            visual_facing_by_entity[entity_id] = _swing_facing_angle(current_angle, target_angle, max_step=max_facing_step)

        frame_status_message = status_message
        if player is not None and player.space_id == "overworld":
            if campaign_move_state is not None:
                frame_status_message = (
                    f"campaign authoring: moving {campaign_move_state.label}; "
                    "right-click destination then choose place moved object (Esc cancels)"
                )
            elif campaign_path_edit_state is not None:
                frame_status_message = (
                    f"campaign authoring: editing path for {campaign_path_edit_state.label}; "
                    "right-click to add anchor, right-click existing anchor to move/delete (Esc finishes)"
                )
            elif not frame_status_message:
                path_needed_count = _campaign_patrol_path_needed_count(sim)
                path_needed_suffix = ""
                if path_needed_count > 0:
                    noun = "patrol" if path_needed_count == 1 else "patrols"
                    path_needed_suffix = (
                        f" | {path_needed_count} {noun} path needed "
                        "(Add at least 1 route anchor to start loop.)"
                    )
                frame_status_message = (
                    "campaign authoring: right-click empty space to place town/dungeon/patrol; "
                    "right-click site/patrol to move/delete (hotkeys are debug fallback)"
                    f"{path_needed_suffix}"
                )
        elif player is not None and str(player.space_id).startswith("local_site:"):
            if local_move_state is not None:
                frame_status_message = (
                    f"local authoring: moving {local_move_state.label}; "
                    "right-click destination then choose place moved object (Esc cancels)"
                )
            elif not frame_status_message:
                frame_status_message = (
                    "local authoring: right-click empty space to place structure/opening/hostile/entry/exit; "
                    "right-click authored targets to move/delete (hotkeys are debug fallback)"
                )

        screen.fill((17, 18, 25))
        inspector_content_rect, inspector_total_lines, panel_section_rects, panel_section_counts, offer_buttons = _draw_frame_layers(
            screen=screen,
            sim=sim,
            world_center=world_center,
            world_zoom_scale=world_zoom_scale,
            viewport_rect=viewport_rect,
            marker_font=marker_font,
            font=font,
            debug_font=debug_font,
            status_message=frame_status_message,
            hover_message=hover_message,
            runtime_state=runtime_state,
            follow_state=follow_state,
            show_local_arena_overlay=show_local_arena_overlay,
            layout=layout,
            inspector_scroll=inspector_scroll,
            panel_scroll=panel_scroll,
            active_panel_section=active_panel_section,
            rumor_panel_state=rumor_panel_state,
            debug_filter_state=debug_filter_state,
            debug_panel_cache=debug_panel_cache,
            home_panel_state=home_panel_state,
            context_menu=context_menu,
            campaign_path_edit_state=campaign_path_edit_state,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            current_space_id=current_space_id,
            alpha=alpha,
            visual_facing_by_entity=visual_facing_by_entity,
        )
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
            runtime_profile=args.runtime_profile,
            headless=headless,
            load_save=args.load_save,
            save_path=args.save_path,
        )
    )


if __name__ == "__main__":
    main()
