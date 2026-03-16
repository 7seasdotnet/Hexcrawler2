from __future__ import annotations

import math
from typing import Any

from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, SimEvent, Simulation
from hexcrawler.sim.encounters import ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, HexCoord

CAMPAIGN_DANGER_CONTACT_EVENT_TYPE = "campaign_danger_contact"
ACCEPT_ENCOUNTER_OFFER_INTENT = "accept_encounter_offer"
FLEE_ENCOUNTER_OFFER_INTENT = "flee_encounter_offer"
DEFAULT_DANGER_ENTITY_ID = "danger:raider_patrol_alpha"
DEFAULT_DANGER_SPACE_ID = "overworld"
DEFAULT_DANGER_SPEED_PER_TICK = 0.12
DEFAULT_CONTACT_RADIUS = 0.72
DEFAULT_FLEE_IGNORE_TICKS = 20
MAX_FLEE_IGNORE_SOURCES = 8
MAX_PENDING_PLAYERS = 8


class CampaignDangerModule(RuleModule):
    """Deterministic campaign-role danger visibility, movement, and contact handoff."""

    name = "campaign_danger"
    _STATE_OVERLAP_BY_DANGER = "overlap_by_danger"
    _STATE_PENDING_OFFER_BY_PLAYER = "pending_offer_by_player"
    _STATE_FLEE_IGNORE_UNTIL_BY_PLAYER = "flee_ignore_until_by_player"

    def __init__(
        self,
        *,
        danger_entity_id: str = DEFAULT_DANGER_ENTITY_ID,
        danger_space_id: str = DEFAULT_DANGER_SPACE_ID,
        contact_radius: float = DEFAULT_CONTACT_RADIUS,
        flee_ignore_ticks: int = DEFAULT_FLEE_IGNORE_TICKS,
    ) -> None:
        self._danger_entity_id = danger_entity_id
        self._danger_space_id = danger_space_id
        self._contact_radius = float(contact_radius)
        self._flee_ignore_ticks = int(flee_ignore_ticks)
        first_x, first_y = axial_to_world_xy(HexCoord(2, -1))
        second_x, second_y = axial_to_world_xy(HexCoord(2, 1))
        self._patrol_waypoints = ((first_x, first_y), (second_x, second_y))

    def on_simulation_start(self, sim: Simulation) -> None:
        self._ensure_danger_entity(sim)
        sim.set_rules_state(self.name, self._normalized_state(sim))

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        del tick
        danger = sim.state.entities.get(self._danger_entity_id)
        if danger is None:
            return
        if not self._is_campaign_entity(sim, danger):
            return

        if danger.target_position is None:
            danger.target_position = self._next_waypoint(danger)
            return

        if self._distance_sq(
            danger.position_x,
            danger.position_y,
            danger.target_position[0],
            danger.target_position[1],
        ) <= 0.0001:
            danger.target_position = self._next_waypoint(danger)

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        danger = sim.state.entities.get(self._danger_entity_id)
        player = sim.state.entities.get(DEFAULT_PLAYER_ENTITY_ID)
        state = self._normalized_state(sim)
        overlap_by_danger = dict(state[self._STATE_OVERLAP_BY_DANGER])
        pending_offer_by_player = dict(state[self._STATE_PENDING_OFFER_BY_PLAYER])
        flee_ignore_until_by_player = {
            str(player_id): dict(source_map)
            for player_id, source_map in state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER].items()
        }

        prior_overlap = bool(overlap_by_danger.get(self._danger_entity_id, False))
        overlap = self._is_campaign_overlap(sim=sim, danger=danger, player=player)

        if overlap and not prior_overlap and danger is not None and player is not None:
            player_id = player.entity_id
            player_flee_ignore = flee_ignore_until_by_player.get(player_id, {})
            if self._has_pending_offer(state, player_entity_id=player_id) or self._has_active_local_encounter_state(sim=sim, player=player):
                pass
            elif tick < int(player_flee_ignore.get(self._danger_entity_id, 0)):
                pass
            else:
                player_location = sim._entity_location_ref(player).to_dict()
                offer = self._build_pending_offer(
                    tick=tick,
                    danger_entity_id=self._danger_entity_id,
                    player=player,
                    location=player_location,
                )
                pending_offer_by_player[player_id] = offer
                sim.schedule_event_at(
                    tick=tick + 1,
                    event_type=CAMPAIGN_DANGER_CONTACT_EVENT_TYPE,
                    params={
                        "tick": tick,
                        "danger_entity_id": self._danger_entity_id,
                        "player_entity_id": DEFAULT_PLAYER_ENTITY_ID,
                        "space_id": player.space_id,
                        "distance": math.sqrt(
                            self._distance_sq(
                                player.position_x,
                                player.position_y,
                                danger.position_x,
                                danger.position_y,
                            )
                        ),
                        "encounter_label": offer["encounter_label"],
                        "outcome": "offer_created",
                    },
                )

        overlap_by_danger[self._danger_entity_id] = overlap
        state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
        state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER] = flee_ignore_until_by_player
        sim.set_rules_state(self.name, state)

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        del command_index
        if command.command_type not in {ACCEPT_ENCOUNTER_OFFER_INTENT, FLEE_ENCOUNTER_OFFER_INTENT}:
            return False

        state = self._normalized_state(sim)
        pending_offer_by_player = dict(state[self._STATE_PENDING_OFFER_BY_PLAYER])
        flee_ignore_until_by_player = {
            str(player_id): dict(source_map)
            for player_id, source_map in state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER].items()
        }
        player_id = str(command.entity_id) if isinstance(command.entity_id, str) and command.entity_id else DEFAULT_PLAYER_ENTITY_ID
        offer = pending_offer_by_player.get(player_id)
        if offer is None:
            return True

        player = sim.state.entities.get(player_id)
        if player is None:
            pending_offer_by_player.pop(player_id, None)
            state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
            sim.set_rules_state(self.name, state)
            return True

        if command.command_type == ACCEPT_ENCOUNTER_OFFER_INTENT:
            if self._has_active_local_encounter_state(sim=sim, player=player):
                return True
            player_location = sim._entity_location_ref(player).to_dict()
            sim.schedule_event_at(
                tick=command.tick + 1,
                event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
                params={
                    "tick": command.tick,
                    "context": str(offer.get("context", "campaign_danger_contact")),
                    "trigger": str(offer.get("trigger", "campaign_contact")),
                    "danger_entity_id": str(offer.get("danger_entity_id", self._danger_entity_id)),
                    "location": player_location,
                    "roll": int(offer.get("roll", 0)),
                    "category": str(offer.get("category", "hostile")),
                    "table_id": str(offer.get("table_id", "campaign_danger_contact")),
                    "entry_id": str(offer.get("entry_id", "danger_patrol")),
                    "suggested_local_template_id": str(offer.get("suggested_local_template_id", "local_template_forest")),
                    "tags": list(offer.get("tags", ["campaign", "danger_contact"])),
                },
            )
            sim.schedule_event_at(
                tick=command.tick + 1,
                event_type=CAMPAIGN_DANGER_CONTACT_EVENT_TYPE,
                params={
                    "tick": command.tick,
                    "danger_entity_id": str(offer.get("danger_entity_id", self._danger_entity_id)),
                    "player_entity_id": DEFAULT_PLAYER_ENTITY_ID,
                    "space_id": player.space_id,
                    "encounter_label": str(offer.get("encounter_label", "danger contact")),
                    "outcome": "offer_accepted",
                },
            )
            source_id = str(offer.get("danger_entity_id", self._danger_entity_id))
            player_flee_ignore = dict(flee_ignore_until_by_player.get(player_id, {}))
            player_flee_ignore[source_id] = command.tick + 2
            flee_ignore_until_by_player[player_id] = player_flee_ignore
            pending_offer_by_player.pop(player_id, None)
        else:
            sim.schedule_event_at(
                tick=command.tick + 1,
                event_type=CAMPAIGN_DANGER_CONTACT_EVENT_TYPE,
                params={
                    "tick": command.tick,
                    "danger_entity_id": str(offer.get("danger_entity_id", self._danger_entity_id)),
                    "player_entity_id": DEFAULT_PLAYER_ENTITY_ID,
                    "space_id": player.space_id,
                    "encounter_label": str(offer.get("encounter_label", "danger contact")),
                    "outcome": "offer_fled",
                },
            )
            source_id = str(offer.get("danger_entity_id", self._danger_entity_id))
            player_flee_ignore = dict(flee_ignore_until_by_player.get(player_id, {}))
            player_flee_ignore[source_id] = command.tick + max(1, self._flee_ignore_ticks)
            flee_ignore_until_by_player[player_id] = player_flee_ignore
            pending_offer_by_player.pop(player_id, None)
        state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
        state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER] = flee_ignore_until_by_player
        sim.set_rules_state(self.name, state)
        return True

    def _ensure_danger_entity(self, sim: Simulation) -> None:
        if self._danger_entity_id in sim.state.entities:
            return
        first_waypoint = self._patrol_waypoints[0]
        sim.add_entity(
            EntityState(
                entity_id=self._danger_entity_id,
                position_x=float(first_waypoint[0]),
                position_y=float(first_waypoint[1]),
                speed_per_tick=DEFAULT_DANGER_SPEED_PER_TICK,
                target_position=self._patrol_waypoints[1],
                space_id=self._danger_space_id,
                template_id="campaign_danger_patrol",
            )
        )

    def _next_waypoint(self, entity: EntityState) -> tuple[float, float]:
        if self._distance_sq(entity.position_x, entity.position_y, *self._patrol_waypoints[0]) <= 0.0001:
            return self._patrol_waypoints[1]
        return self._patrol_waypoints[0]

    def _is_campaign_overlap(self, *, sim: Simulation, danger: EntityState | None, player: EntityState | None) -> bool:
        if danger is None or player is None:
            return False
        if danger.space_id != player.space_id:
            return False
        if not self._is_campaign_entity(sim, danger) or not self._is_campaign_entity(sim, player):
            return False
        return self._distance_sq(player.position_x, player.position_y, danger.position_x, danger.position_y) <= (
            self._contact_radius * self._contact_radius
        )

    def _is_campaign_entity(self, sim: Simulation, entity: EntityState) -> bool:
        space = sim.state.world.spaces.get(entity.space_id)
        if space is None:
            return False
        return space.role == CAMPAIGN_SPACE_ROLE

    def _normalized_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        overlap_by_danger = state.get(self._STATE_OVERLAP_BY_DANGER, {})
        if not isinstance(overlap_by_danger, dict):
            raise ValueError("campaign_danger.rules_state.overlap_by_danger must be an object")
        normalized_overlap: dict[str, bool] = {}
        for danger_id, value in overlap_by_danger.items():
            if not isinstance(danger_id, str) or not danger_id:
                raise ValueError("campaign_danger.rules_state.overlap_by_danger keys must be non-empty strings")
            if not isinstance(value, bool):
                raise ValueError("campaign_danger.rules_state.overlap_by_danger values must be booleans")
            normalized_overlap[danger_id] = value
        raw_pending_offer_by_player = state.get(self._STATE_PENDING_OFFER_BY_PLAYER, {})
        if not isinstance(raw_pending_offer_by_player, dict):
            raise ValueError("campaign_danger.rules_state.pending_offer_by_player must be an object")
        pending_offer_by_player: dict[str, dict[str, Any]] = {}
        for player_id in sorted(raw_pending_offer_by_player):
            if not isinstance(player_id, str) or not player_id:
                raise ValueError("campaign_danger.rules_state.pending_offer_by_player keys must be non-empty strings")
            normalized_offer = self._normalize_pending_offer(raw_pending_offer_by_player[player_id])
            if normalized_offer is None:
                continue
            pending_offer_by_player[player_id] = normalized_offer
        if len(pending_offer_by_player) > MAX_PENDING_PLAYERS:
            ordered = sorted(
                pending_offer_by_player.items(),
                key=lambda item: (int(item[1].get("tick", 0)), item[0]),
            )
            pending_offer_by_player = dict(ordered[-MAX_PENDING_PLAYERS:])

        raw_flee_ignore_by_player = state.get(self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER, {})
        if not isinstance(raw_flee_ignore_by_player, dict):
            raise ValueError("campaign_danger.rules_state.flee_ignore_until_by_player must be an object")
        flee_ignore_until_by_player: dict[str, dict[str, int]] = {}
        for player_id in sorted(raw_flee_ignore_by_player):
            if not isinstance(player_id, str) or not player_id:
                raise ValueError("campaign_danger.rules_state.flee_ignore_until_by_player keys must be non-empty strings")
            raw_flee_ignore = raw_flee_ignore_by_player[player_id]
            if not isinstance(raw_flee_ignore, dict):
                raise ValueError(
                    "campaign_danger.rules_state.flee_ignore_until_by_player values must be objects"
                )
            source_until: dict[str, int] = {}
            for source_id in sorted(raw_flee_ignore):
                if not isinstance(source_id, str) or not source_id:
                    raise ValueError(
                        "campaign_danger.rules_state.flee_ignore_until_by_player source keys must be non-empty strings"
                    )
                until_tick = int(raw_flee_ignore[source_id])
                if until_tick <= 0:
                    continue
                source_until[source_id] = until_tick
            if len(source_until) > MAX_FLEE_IGNORE_SOURCES:
                ordered = sorted(source_until.items(), key=lambda item: (item[1], item[0]))
                source_until = dict(ordered[-MAX_FLEE_IGNORE_SOURCES:])
            if source_until:
                flee_ignore_until_by_player[player_id] = source_until
        if len(flee_ignore_until_by_player) > MAX_PENDING_PLAYERS:
            flee_ignore_until_by_player = dict(sorted(flee_ignore_until_by_player.items())[-MAX_PENDING_PLAYERS:])

        return {
            self._STATE_OVERLAP_BY_DANGER: normalized_overlap,
            self._STATE_PENDING_OFFER_BY_PLAYER: pending_offer_by_player,
            self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER: flee_ignore_until_by_player,
        }

    def _normalize_pending_offer(self, raw_pending_offer: Any) -> dict[str, Any] | None:
        if raw_pending_offer is None:
            return None
        if not isinstance(raw_pending_offer, dict):
            raise ValueError("campaign_danger.rules_state.pending_offer must be an object when present")

        required_str = {
            "player_entity_id",
            "danger_entity_id",
            "encounter_label",
            "context",
            "trigger",
            "category",
            "table_id",
            "entry_id",
            "suggested_local_template_id",
        }
        normalized: dict[str, Any] = {}
        for key in required_str:
            value = raw_pending_offer.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"campaign_danger.rules_state.pending_offer.{key} must be a non-empty string")
            normalized[key] = value

        normalized["tick"] = int(raw_pending_offer.get("tick", 0))
        normalized["roll"] = int(raw_pending_offer.get("roll", 0))
        tags = raw_pending_offer.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError("campaign_danger.rules_state.pending_offer.tags must be a list")
        normalized["tags"] = [str(tag) for tag in tags]
        location = raw_pending_offer.get("location")
        if not isinstance(location, dict):
            raise ValueError("campaign_danger.rules_state.pending_offer.location must be an object")
        normalized["location"] = dict(location)
        return normalized

    def _build_pending_offer(
        self,
        *,
        tick: int,
        danger_entity_id: str,
        player: EntityState,
        location: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "tick": int(tick),
            "player_entity_id": player.entity_id,
            "danger_entity_id": danger_entity_id,
            "encounter_label": "Raider Patrol",
            "context": "campaign_danger_contact",
            "trigger": "campaign_contact",
            "location": dict(location),
            "roll": 0,
            "category": "hostile",
            "table_id": "campaign_danger_contact",
            "entry_id": "danger_patrol",
            "suggested_local_template_id": "local_template_forest",
            "tags": ["campaign", "danger_contact", f"space:{player.space_id}"],
        }

    @staticmethod
    def _has_pending_offer(state: dict[str, Any], *, player_entity_id: str) -> bool:
        pending_offer_by_player = state.get("pending_offer_by_player")
        if not isinstance(pending_offer_by_player, dict):
            return False
        return isinstance(pending_offer_by_player.get(player_entity_id), dict)

    @staticmethod
    def _has_active_local_encounter_state(*, sim: Simulation, player: EntityState) -> bool:
        player_space = sim.state.world.spaces.get(player.space_id)
        if player_space is not None and player_space.role != CAMPAIGN_SPACE_ROLE:
            return True
        local_state = sim.get_rules_state("local_encounter_instance")
        if not isinstance(local_state, dict):
            return False
        active_by_local_space = local_state.get("active_by_local_space")
        if isinstance(active_by_local_space, dict) and active_by_local_space:
            return True
        return_in_progress = local_state.get("return_in_progress_by_local_space")
        if isinstance(return_in_progress, dict) and any(bool(v) for v in return_in_progress.values()):
            return True
        return False

    @staticmethod
    def _distance_sq(ax: float, ay: float, bx: float, by: float) -> float:
        dx = ax - bx
        dy = ay - by
        return dx * dx + dy * dy
