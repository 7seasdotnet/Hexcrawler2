from __future__ import annotations

import math
from typing import Any

from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, SimEvent, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_END_EVENT_TYPE,
    LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
)
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
DEFAULT_POST_ENCOUNTER_COOLDOWN_TICKS = 8
MAX_FLEE_IGNORE_SOURCES = 8
MAX_PENDING_PLAYERS = 8

ENCOUNTER_STATE_NONE = "none"
ENCOUNTER_STATE_PENDING_OFFER = "pending_offer"
ENCOUNTER_STATE_ACCEPTED_LOADING = "accepted_loading"
ENCOUNTER_STATE_IN_LOCAL = "in_local"
ENCOUNTER_STATE_RETURNING = "returning"
ENCOUNTER_STATE_POST_ENCOUNTER_COOLDOWN = "post_encounter_cooldown"
_ALLOWED_ENCOUNTER_STATES = {
    ENCOUNTER_STATE_NONE,
    ENCOUNTER_STATE_PENDING_OFFER,
    ENCOUNTER_STATE_ACCEPTED_LOADING,
    ENCOUNTER_STATE_IN_LOCAL,
    ENCOUNTER_STATE_RETURNING,
    ENCOUNTER_STATE_POST_ENCOUNTER_COOLDOWN,
}


class CampaignDangerModule(RuleModule):
    """Deterministic campaign-role danger visibility, movement, and contact handoff."""

    name = "campaign_danger"
    _STATE_OVERLAP_BY_DANGER = "overlap_by_danger"
    _STATE_PENDING_OFFER_BY_PLAYER = "pending_offer_by_player"
    _STATE_FLEE_IGNORE_UNTIL_BY_PLAYER = "flee_ignore_until_by_player"
    _STATE_ENCOUNTER_CONTROL_BY_PLAYER = "encounter_control_by_player"

    def __init__(
        self,
        *,
        danger_entity_id: str = DEFAULT_DANGER_ENTITY_ID,
        danger_space_id: str = DEFAULT_DANGER_SPACE_ID,
        contact_radius: float = DEFAULT_CONTACT_RADIUS,
        flee_ignore_ticks: int = DEFAULT_FLEE_IGNORE_TICKS,
        post_encounter_cooldown_ticks: int = DEFAULT_POST_ENCOUNTER_COOLDOWN_TICKS,
    ) -> None:
        self._danger_entity_id = danger_entity_id
        self._danger_space_id = danger_space_id
        self._contact_radius = float(contact_radius)
        self._flee_ignore_ticks = int(flee_ignore_ticks)
        self._post_encounter_cooldown_ticks = int(post_encounter_cooldown_ticks)
        first_x, first_y = axial_to_world_xy(HexCoord(2, -1))
        second_x, second_y = axial_to_world_xy(HexCoord(2, 1))
        self._patrol_waypoints = ((first_x, first_y), (second_x, second_y))

    def on_simulation_start(self, sim: Simulation) -> None:
        self._ensure_danger_entity(sim)
        sim.set_rules_state(self.name, self._normalized_state(sim))

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        state = self._normalized_state(sim)
        encounter_control_by_player = self._prune_encounter_control(
            dict(state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER]),
            tick=tick,
        )
        state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
        player = sim.state.entities.get(DEFAULT_PLAYER_ENTITY_ID)
        player_state = ENCOUNTER_STATE_NONE
        held_source_id: str | None = None
        if player is not None:
            player_state = self._encounter_state_for_player(encounter_control_by_player, player.entity_id)
            if player_state == ENCOUNTER_STATE_PENDING_OFFER:
                sim.stop_entity(player.entity_id)
                offer = state[self._STATE_PENDING_OFFER_BY_PLAYER].get(player.entity_id)
                if isinstance(offer, dict):
                    held_source_id = self._optional_non_empty_string(offer.get("danger_entity_id"))

        danger = sim.state.entities.get(self._danger_entity_id)
        hold_danger = (
            danger is not None
            and held_source_id == self._danger_entity_id
            and player_state == ENCOUNTER_STATE_PENDING_OFFER
        )
        if hold_danger and danger is not None:
            sim.stop_entity(danger.entity_id)
        elif danger is not None and self._is_campaign_entity(sim, danger):
            if danger.target_position is None:
                danger.target_position = self._next_waypoint(danger)
            elif self._distance_sq(
                danger.position_x,
                danger.position_y,
                danger.target_position[0],
                danger.target_position[1],
            ) <= 0.0001:
                danger.target_position = self._next_waypoint(danger)
        sim.set_rules_state(self.name, state)

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
        encounter_control_by_player = self._prune_encounter_control(
            dict(state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER]),
            tick=tick,
        )

        prior_overlap = bool(overlap_by_danger.get(self._danger_entity_id, False))
        overlap = self._is_campaign_overlap(sim=sim, danger=danger, player=player)

        if overlap and not prior_overlap and danger is not None and player is not None:
            player_id = player.entity_id
            if self._player_can_receive_offer(
                sim=sim,
                player=player,
                encounter_control_by_player=encounter_control_by_player,
                pending_offer_by_player=pending_offer_by_player,
                source_id=self._danger_entity_id,
                tick=tick,
                flee_ignore_until_by_player=flee_ignore_until_by_player,
            ):
                player_location = sim._entity_location_ref(player).to_dict()
                offer = self._build_pending_offer(
                    tick=tick,
                    source_entity_id=self._danger_entity_id,
                    source_label="campaign danger",
                    encounter_label="Raider Patrol",
                    player=player,
                    location=player_location,
                    context="campaign_danger_contact",
                    trigger="campaign_contact",
                    roll=0,
                    category="hostile",
                    table_id="campaign_danger_contact",
                    entry_id="danger_patrol",
                    suggested_local_template_id="local_template_forest",
                    tags=["campaign", "danger_contact", f"space:{player.space_id}"],
                )
                pending_offer_by_player[player_id] = offer
                encounter_control_by_player[player_id] = {
                    "state": ENCOUNTER_STATE_PENDING_OFFER,
                    "until_tick": -1,
                }
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
                        "source_label": offer["source_label"],
                        "outcome": "offer_created",
                    },
                )

        overlap_by_danger[self._danger_entity_id] = overlap
        state[self._STATE_OVERLAP_BY_DANGER] = overlap_by_danger
        state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
        state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER] = flee_ignore_until_by_player
        state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
        sim.set_rules_state(self.name, state)

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        state = self._normalized_state(sim)
        pending_offer_by_player = dict(state[self._STATE_PENDING_OFFER_BY_PLAYER])
        encounter_control_by_player = dict(state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER])

        if event.event_type == ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE:
            if bool(event.params.get("offer_required", False)) and not bool(event.params.get("offer_accepted", False)):
                player = sim.state.entities.get(DEFAULT_PLAYER_ENTITY_ID)
                if player is None:
                    return
                player_id = player.entity_id
                source_entity_id = self._optional_non_empty_string(event.params.get("source_entity_id")) or "encounter:global"
                flee_ignore_until_by_player = {
                    str(pid): dict(row)
                    for pid, row in state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER].items()
                }
                if not self._player_can_receive_offer(
                    sim=sim,
                    player=player,
                    encounter_control_by_player=encounter_control_by_player,
                    pending_offer_by_player=pending_offer_by_player,
                    source_id=source_entity_id,
                    tick=int(event.tick),
                    flee_ignore_until_by_player=flee_ignore_until_by_player,
                ):
                    return
                location_payload = event.params.get("location")
                if not isinstance(location_payload, dict):
                    return
                offer = self._build_pending_offer(
                    tick=int(event.params.get("tick", event.tick)),
                    source_entity_id=source_entity_id,
                    source_label=self._optional_non_empty_string(event.params.get("source_label")) or "encounter source",
                    encounter_label=self._offer_label_from_event(event),
                    player=player,
                    location=dict(location_payload),
                    context=str(event.params.get("context", "global")),
                    trigger=str(event.params.get("trigger", "idle")),
                    roll=int(event.params.get("roll", 0)),
                    category=str(event.params.get("category", "hostile")),
                    table_id=self._optional_non_empty_string(event.params.get("table_id")) or "encounter_table",
                    entry_id=self._optional_non_empty_string(event.params.get("entry_id")) or "encounter_entry",
                    suggested_local_template_id=self._optional_non_empty_string(event.params.get("suggested_local_template_id")) or "local_template_forest",
                    tags=list(event.params.get("entry_tags", ["campaign", "encounter"])),
                )
                pending_offer_by_player[player_id] = offer
                encounter_control_by_player[player_id] = {
                    "state": ENCOUNTER_STATE_PENDING_OFFER,
                    "until_tick": -1,
                }
                sim.schedule_event_at(
                    tick=event.tick + 1,
                    event_type=CAMPAIGN_DANGER_CONTACT_EVENT_TYPE,
                    params={
                        "tick": int(event.tick),
                        "danger_entity_id": source_entity_id,
                        "player_entity_id": player_id,
                        "space_id": player.space_id,
                        "encounter_label": offer["encounter_label"],
                        "source_label": offer["source_label"],
                        "outcome": "offer_created",
                    },
                )
                state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
                state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
                sim.set_rules_state(self.name, state)
                return

        if event.event_type == LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE:
            entity_id = self._optional_non_empty_string(event.params.get("entity_id"))
            if entity_id is not None:
                pending_offer_by_player.pop(entity_id, None)
                encounter_control_by_player[entity_id] = {"state": ENCOUNTER_STATE_IN_LOCAL, "until_tick": -1}
                state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
                state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
                sim.set_rules_state(self.name, state)
            return

        if event.event_type == LOCAL_ENCOUNTER_END_EVENT_TYPE:
            entity_id = self._optional_non_empty_string(event.params.get("entity_id"))
            if entity_id is None:
                return
            if self._encounter_state_for_player(encounter_control_by_player, entity_id) == ENCOUNTER_STATE_IN_LOCAL:
                encounter_control_by_player[entity_id] = {"state": ENCOUNTER_STATE_RETURNING, "until_tick": -1}
                state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
                sim.set_rules_state(self.name, state)
            return

        if event.event_type == LOCAL_ENCOUNTER_RETURN_EVENT_TYPE:
            entity_id = self._optional_non_empty_string(event.params.get("entity_id"))
            if entity_id is None:
                return
            encounter_control_by_player[entity_id] = {
                "state": ENCOUNTER_STATE_POST_ENCOUNTER_COOLDOWN,
                "until_tick": int(event.tick) + max(1, self._post_encounter_cooldown_ticks),
            }
            pending_offer_by_player.pop(entity_id, None)
            state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
            state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
            sim.set_rules_state(self.name, state)

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        del command_index
        state = self._normalized_state(sim)
        pending_offer_by_player = dict(state[self._STATE_PENDING_OFFER_BY_PLAYER])
        flee_ignore_until_by_player = {
            str(player_id): dict(source_map)
            for player_id, source_map in state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER].items()
        }
        encounter_control_by_player = self._prune_encounter_control(
            dict(state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER]),
            tick=int(command.tick),
        )

        player_id = str(command.entity_id) if isinstance(command.entity_id, str) and command.entity_id else DEFAULT_PLAYER_ENTITY_ID
        player_state = self._encounter_state_for_player(encounter_control_by_player, player_id)

        if command.command_type in {"set_move_vector", "set_target_position"} and player_state == ENCOUNTER_STATE_PENDING_OFFER:
            player = sim.state.entities.get(player_id)
            if player is not None and self._is_campaign_entity(sim, player):
                sim.stop_entity(player_id)
                return True

        if command.command_type not in {ACCEPT_ENCOUNTER_OFFER_INTENT, FLEE_ENCOUNTER_OFFER_INTENT}:
            return False

        offer = pending_offer_by_player.get(player_id)
        if offer is None:
            return True

        player = sim.state.entities.get(player_id)
        if player is None:
            pending_offer_by_player.pop(player_id, None)
            encounter_control_by_player[player_id] = {"state": ENCOUNTER_STATE_NONE, "until_tick": -1}
            state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
            state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
            sim.set_rules_state(self.name, state)
            return True

        if command.command_type == ACCEPT_ENCOUNTER_OFFER_INTENT:
            if self._has_active_local_encounter_state(sim=sim, player=player):
                return True
            offer_location = offer.get("location")
            if not isinstance(offer_location, dict):
                offer_location = sim._entity_location_ref(player).to_dict()
            else:
                offer_location = dict(offer_location)
            sim.schedule_event_at(
                tick=command.tick + 1,
                event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
                params={
                    "tick": command.tick,
                    "context": str(offer.get("context", "campaign_danger_contact")),
                    "trigger": str(offer.get("trigger", "campaign_contact")),
                    "source_entity_id": str(offer.get("danger_entity_id", self._danger_entity_id)),
                    "source_label": str(offer.get("source_label", "campaign danger")),
                    "danger_entity_id": str(offer.get("danger_entity_id", self._danger_entity_id)),
                    "location": offer_location,
                    "roll": int(offer.get("roll", 0)),
                    "category": str(offer.get("category", "hostile")),
                    "table_id": str(offer.get("table_id", "campaign_danger_contact")),
                    "entry_id": str(offer.get("entry_id", "danger_patrol")),
                    "suggested_local_template_id": str(offer.get("suggested_local_template_id", "local_template_forest")),
                    "entry_tags": list(offer.get("tags", ["campaign", "danger_contact"])),
                    "offer_required": True,
                    "offer_accepted": True,
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
                    "source_label": str(offer.get("source_label", "campaign danger")),
                    "outcome": "offer_accepted",
                },
            )
            source_id = str(offer.get("danger_entity_id", self._danger_entity_id))
            player_flee_ignore = dict(flee_ignore_until_by_player.get(player_id, {}))
            player_flee_ignore[source_id] = command.tick + 2
            flee_ignore_until_by_player[player_id] = player_flee_ignore
            encounter_control_by_player[player_id] = {"state": ENCOUNTER_STATE_ACCEPTED_LOADING, "until_tick": -1}
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
                    "source_label": str(offer.get("source_label", "campaign danger")),
                    "outcome": "offer_fled",
                },
            )
            source_id = str(offer.get("danger_entity_id", self._danger_entity_id))
            player_flee_ignore = dict(flee_ignore_until_by_player.get(player_id, {}))
            player_flee_ignore[source_id] = command.tick + max(1, self._flee_ignore_ticks)
            flee_ignore_until_by_player[player_id] = player_flee_ignore
            encounter_control_by_player[player_id] = {
                "state": ENCOUNTER_STATE_POST_ENCOUNTER_COOLDOWN,
                "until_tick": int(command.tick) + max(1, self._post_encounter_cooldown_ticks),
            }
            pending_offer_by_player.pop(player_id, None)

        state[self._STATE_PENDING_OFFER_BY_PLAYER] = pending_offer_by_player
        state[self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER] = flee_ignore_until_by_player
        state[self._STATE_ENCOUNTER_CONTROL_BY_PLAYER] = encounter_control_by_player
        sim.set_rules_state(self.name, state)
        return True

    def _player_can_receive_offer(
        self,
        *,
        sim: Simulation,
        player: EntityState,
        encounter_control_by_player: dict[str, dict[str, Any]],
        pending_offer_by_player: dict[str, dict[str, Any]],
        source_id: str,
        tick: int,
        flee_ignore_until_by_player: dict[str, dict[str, int]],
    ) -> bool:
        player_id = player.entity_id
        if self._encounter_state_for_player(encounter_control_by_player, player_id) != ENCOUNTER_STATE_NONE:
            return False
        if isinstance(pending_offer_by_player.get(player_id), dict):
            return False
        if self._has_active_local_encounter_state(sim=sim, player=player):
            return False
        player_flee_ignore = flee_ignore_until_by_player.get(player_id, {})
        return tick >= int(player_flee_ignore.get(source_id, 0))

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

        raw_overlap = state.get(self._STATE_OVERLAP_BY_DANGER, {})
        if not isinstance(raw_overlap, dict):
            raise ValueError("campaign_danger.rules_state.overlap_by_danger must be an object")
        normalized_overlap: dict[str, bool] = {}
        for key, value in sorted(raw_overlap.items()):
            if not isinstance(key, str) or not key:
                raise ValueError("campaign_danger.rules_state.overlap_by_danger keys must be non-empty strings")
            normalized_overlap[key] = bool(value)

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

        raw_control_by_player = state.get(self._STATE_ENCOUNTER_CONTROL_BY_PLAYER, {})
        if not isinstance(raw_control_by_player, dict):
            raise ValueError("campaign_danger.rules_state.encounter_control_by_player must be an object")
        encounter_control_by_player: dict[str, dict[str, Any]] = {}
        for player_id in sorted(raw_control_by_player):
            if not isinstance(player_id, str) or not player_id:
                raise ValueError("campaign_danger.rules_state.encounter_control_by_player keys must be non-empty strings")
            row = raw_control_by_player[player_id]
            if not isinstance(row, dict):
                raise ValueError("campaign_danger.rules_state.encounter_control_by_player values must be objects")
            state_name = str(row.get("state", ENCOUNTER_STATE_NONE))
            if state_name not in _ALLOWED_ENCOUNTER_STATES:
                state_name = ENCOUNTER_STATE_NONE
            until_tick = int(row.get("until_tick", -1))
            encounter_control_by_player[player_id] = {
                "state": state_name,
                "until_tick": until_tick,
            }
        if len(encounter_control_by_player) > MAX_PENDING_PLAYERS:
            encounter_control_by_player = dict(sorted(encounter_control_by_player.items())[-MAX_PENDING_PLAYERS:])

        return {
            self._STATE_OVERLAP_BY_DANGER: normalized_overlap,
            self._STATE_PENDING_OFFER_BY_PLAYER: pending_offer_by_player,
            self._STATE_FLEE_IGNORE_UNTIL_BY_PLAYER: flee_ignore_until_by_player,
            self._STATE_ENCOUNTER_CONTROL_BY_PLAYER: encounter_control_by_player,
        }

    def _normalize_pending_offer(self, raw_pending_offer: Any) -> dict[str, Any] | None:
        if raw_pending_offer is None:
            return None
        if not isinstance(raw_pending_offer, dict):
            raise ValueError("campaign_danger.rules_state.pending_offer must be an object when present")

        required_str = {
            "player_entity_id",
            "danger_entity_id",
            "source_label",
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
        source_entity_id: str,
        source_label: str,
        encounter_label: str,
        player: EntityState,
        location: dict[str, Any],
        context: str,
        trigger: str,
        roll: int,
        category: str,
        table_id: str,
        entry_id: str,
        suggested_local_template_id: str,
        tags: list[str],
    ) -> dict[str, Any]:
        return {
            "tick": int(tick),
            "player_entity_id": player.entity_id,
            "danger_entity_id": source_entity_id,
            "source_label": source_label,
            "encounter_label": encounter_label,
            "context": context,
            "trigger": trigger,
            "location": dict(location),
            "roll": int(roll),
            "category": category,
            "table_id": table_id,
            "entry_id": entry_id,
            "suggested_local_template_id": suggested_local_template_id,
            "tags": [str(tag) for tag in tags],
        }

    def _prune_encounter_control(self, control: dict[str, dict[str, Any]], *, tick: int) -> dict[str, dict[str, Any]]:
        pruned: dict[str, dict[str, Any]] = {}
        for player_id, row in sorted(control.items()):
            state_name = str(row.get("state", ENCOUNTER_STATE_NONE))
            until_tick = int(row.get("until_tick", -1))
            if state_name == ENCOUNTER_STATE_POST_ENCOUNTER_COOLDOWN and until_tick >= 0 and tick >= until_tick:
                state_name = ENCOUNTER_STATE_NONE
                until_tick = -1
            if state_name == ENCOUNTER_STATE_NONE:
                continue
            pruned[player_id] = {"state": state_name, "until_tick": until_tick}
        return pruned

    @staticmethod
    def _encounter_state_for_player(control: dict[str, dict[str, Any]], player_id: str) -> str:
        row = control.get(player_id)
        if not isinstance(row, dict):
            return ENCOUNTER_STATE_NONE
        state_name = str(row.get("state", ENCOUNTER_STATE_NONE))
        if state_name not in _ALLOWED_ENCOUNTER_STATES:
            return ENCOUNTER_STATE_NONE
        return state_name

    @staticmethod
    def _offer_label_from_event(event: SimEvent) -> str:
        entry_id = event.params.get("entry_id")
        if isinstance(entry_id, str) and entry_id:
            return f"Encounter: {entry_id}"
        category = event.params.get("category")
        if isinstance(category, str) and category:
            return f"Encounter: {category}"
        return "Encounter"

    @staticmethod
    def _optional_non_empty_string(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

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
