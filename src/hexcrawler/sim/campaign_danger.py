from __future__ import annotations

import math
from typing import Any

from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimEvent, Simulation
from hexcrawler.sim.encounters import ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, HexCoord

CAMPAIGN_DANGER_CONTACT_EVENT_TYPE = "campaign_danger_contact"
DEFAULT_DANGER_ENTITY_ID = "danger:raider_patrol_alpha"
DEFAULT_DANGER_SPACE_ID = "overworld"
DEFAULT_DANGER_SPEED_PER_TICK = 0.12
DEFAULT_CONTACT_RADIUS = 0.72


class CampaignDangerModule(RuleModule):
    """Deterministic campaign-role danger visibility, movement, and contact handoff."""

    name = "campaign_danger"
    _STATE_OVERLAP_BY_DANGER = "overlap_by_danger"

    def __init__(
        self,
        *,
        danger_entity_id: str = DEFAULT_DANGER_ENTITY_ID,
        danger_space_id: str = DEFAULT_DANGER_SPACE_ID,
        contact_radius: float = DEFAULT_CONTACT_RADIUS,
    ) -> None:
        self._danger_entity_id = danger_entity_id
        self._danger_space_id = danger_space_id
        self._contact_radius = float(contact_radius)
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

        prior_overlap = bool(overlap_by_danger.get(self._danger_entity_id, False))
        overlap = self._is_campaign_overlap(sim=sim, danger=danger, player=player)

        if overlap and not prior_overlap and danger is not None and player is not None:
            player_location = sim._entity_location_ref(player).to_dict()
            sim.schedule_event_at(
                tick=tick + 1,
                event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
                params={
                    "tick": tick,
                    "context": "campaign_danger_contact",
                    "trigger": "campaign_contact",
                    "danger_entity_id": self._danger_entity_id,
                    "location": player_location,
                    "roll": 0,
                    "category": "hostile",
                    "table_id": "campaign_danger_contact",
                    "entry_id": "danger_patrol",
                    "suggested_local_template_id": "local_template_forest",
                    "tags": ["campaign", "danger_contact"],
                },
            )
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
                },
            )

        overlap_by_danger[self._danger_entity_id] = overlap
        sim.set_rules_state(self.name, {self._STATE_OVERLAP_BY_DANGER: overlap_by_danger})

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
        return {self._STATE_OVERLAP_BY_DANGER: normalized_overlap}

    @staticmethod
    def _distance_sq(ax: float, ay: float, bx: float, by: float) -> float:
        dx = ax - bx
        dy = ay - by
        return dx * dx + dy * dy
