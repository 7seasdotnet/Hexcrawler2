from __future__ import annotations

import copy
from typing import Any

from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE

MOVE_GROUP_INTENT_COMMAND_TYPE = "move_group_intent"
GROUP_MOVE_ARRIVAL_EVENT_TYPE = "group_move_arrival"
GROUP_MOVE_SCHEDULED_EVENT_TYPE = "group_move_scheduled"
GROUP_MOVE_ARRIVED_EVENT_TYPE = "group_move_arrived"
GROUP_MOVE_ARRIVAL_IGNORED_EVENT_TYPE = "group_move_arrival_ignored"
MAX_GROUP_TRAVEL_TICKS = 10_000


class GroupMovementModule(RuleModule):
    """Phase 6D-M13 deterministic campaign-role group movement seam (campaign role only)."""

    name = "group_movement"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != MOVE_GROUP_INTENT_COMMAND_TYPE:
            return False

        group_id = str(command.params.get("group_id", ""))
        group = sim.state.world.groups.get(group_id)
        if group is None:
            self._schedule_ignored(
                sim=sim,
                tick=command.tick,
                group_id=group_id,
                move_uid=f"{command.tick}:{command_index}",
                reason="unknown_group",
            )
            return True

        group_space = sim.state.world.spaces.get(str(group.location.get("space_id", "")))
        if group_space is None or group_space.role != CAMPAIGN_SPACE_ROLE:
            self._schedule_ignored(
                sim=sim,
                tick=command.tick,
                group_id=group_id,
                move_uid=f"{command.tick}:{command_index}",
                reason="group_not_in_campaign_space",
            )
            return True

        dest_cell, error = self._parse_campaign_cell_ref(sim, command.params.get("dest_cell"))
        if error is not None:
            self._schedule_ignored(
                sim=sim,
                tick=command.tick,
                group_id=group_id,
                move_uid=f"{command.tick}:{command_index}",
                reason=error,
            )
            return True

        travel_ticks_raw = command.params.get("travel_ticks")
        if isinstance(travel_ticks_raw, bool) or not isinstance(travel_ticks_raw, int):
            self._schedule_ignored(
                sim=sim,
                tick=command.tick,
                group_id=group_id,
                move_uid=f"{command.tick}:{command_index}",
                reason="invalid_travel_ticks",
            )
            return True
        travel_ticks = int(travel_ticks_raw)
        if travel_ticks < 1 or travel_ticks > MAX_GROUP_TRAVEL_TICKS:
            self._schedule_ignored(
                sim=sim,
                tick=command.tick,
                group_id=group_id,
                move_uid=f"{command.tick}:{command_index}",
                reason="invalid_travel_ticks",
            )
            return True

        depart_tick = int(command.tick)
        arrive_tick = depart_tick + travel_ticks
        move_uid = f"{command.tick}:{command_index}"
        from_cell = {
            "space_id": str(group.location["space_id"]),
            "coord": copy.deepcopy(group.cell),
        }

        group.moving = {
            "dest_cell": copy.deepcopy(dest_cell),
            "depart_tick": depart_tick,
            "arrive_tick": arrive_tick,
            "move_uid": move_uid,
        }
        sim.state.world.groups[group.group_id] = group

        sim.schedule_event_at(
            tick=arrive_tick,
            event_type=GROUP_MOVE_ARRIVAL_EVENT_TYPE,
            params={
                "group_id": group.group_id,
                "move_uid": move_uid,
                "from_cell": copy.deepcopy(from_cell),
                "to_cell": copy.deepcopy(dest_cell),
                "arrive_tick": arrive_tick,
            },
        )

        sim.schedule_event_at(
            tick=depart_tick,
            event_type=GROUP_MOVE_SCHEDULED_EVENT_TYPE,
            params={
                "group_id": group.group_id,
                "from_cell": copy.deepcopy(from_cell),
                "to_cell": copy.deepcopy(dest_cell),
                "depart_tick": depart_tick,
                "arrive_tick": arrive_tick,
                "travel_ticks": travel_ticks,
                "move_uid": move_uid,
            },
        )
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != GROUP_MOVE_ARRIVAL_EVENT_TYPE:
            return

        group_id = str(event.params.get("group_id", ""))
        group = sim.state.world.groups.get(group_id)
        if group is None:
            return

        moving = group.moving
        if moving is None:
            self._schedule_arrival_ignored(sim=sim, tick=event.tick, group_id=group_id, move_uid=event.params.get("move_uid"), reason="no_plan")
            return

        event_move_uid = str(event.params.get("move_uid", ""))
        event_arrive_tick = event.params.get("arrive_tick")
        if event_move_uid != str(moving.get("move_uid")) or event_arrive_tick != int(moving.get("arrive_tick", -1)):
            self._schedule_arrival_ignored(sim=sim, tick=event.tick, group_id=group_id, move_uid=event_move_uid, reason="stale_uid")
            return

        if group.last_arrival_uid == event_move_uid:
            self._schedule_arrival_ignored(sim=sim, tick=event.tick, group_id=group_id, move_uid=event_move_uid, reason="already_applied")
            return

        from_cell = {
            "space_id": str(group.location["space_id"]),
            "coord": copy.deepcopy(group.cell),
        }
        dest_cell = dict(moving["dest_cell"])
        group.location["space_id"] = str(dest_cell["space_id"])
        group.location["coord"] = copy.deepcopy(dest_cell["coord"])
        group.cell = copy.deepcopy(dest_cell["coord"])
        group.moving = None
        group.last_arrival_uid = event_move_uid
        sim.state.world.groups[group.group_id] = group

        sim.schedule_event_at(
            tick=event.tick,
            event_type=GROUP_MOVE_ARRIVED_EVENT_TYPE,
            params={
                "group_id": group.group_id,
                "from_cell": from_cell,
                "to_cell": copy.deepcopy(dest_cell),
                "arrive_tick": int(event.tick),
                "move_uid": event_move_uid,
            },
        )

    @staticmethod
    def _is_json_safe(value: Any) -> bool:
        if value is None or isinstance(value, (str, int, float, bool)):
            return True
        if isinstance(value, list):
            return all(GroupMovementModule._is_json_safe(item) for item in value)
        if isinstance(value, dict):
            return all(isinstance(key, str) and GroupMovementModule._is_json_safe(item) for key, item in value.items())
        return False

    @classmethod
    def _parse_campaign_cell_ref(cls, sim: Simulation, payload: Any) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(payload, dict):
            return None, "invalid_target_cell"
        if set(payload) != {"space_id", "coord"}:
            return None, "invalid_target_cell"
        space_id = payload.get("space_id")
        if not isinstance(space_id, str) or not space_id:
            return None, "invalid_target_cell"
        space = sim.state.world.spaces.get(space_id)
        if space is None or space.role != CAMPAIGN_SPACE_ROLE:
            return None, "invalid_target_cell"
        coord = payload.get("coord")
        if not cls._is_json_safe(coord):
            return None, "invalid_target_cell"
        if not space.is_valid_cell(coord):
            return None, "invalid_target_cell_coord_for_space"
        return {"space_id": space_id, "coord": copy.deepcopy(coord)}, None

    @staticmethod
    def _schedule_ignored(sim: Simulation, *, tick: int, group_id: str, move_uid: str, reason: str) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=GROUP_MOVE_ARRIVAL_IGNORED_EVENT_TYPE,
            params={
                "group_id": group_id,
                "move_uid": move_uid,
                "reason": reason,
            },
        )

    @staticmethod
    def _schedule_arrival_ignored(sim: Simulation, *, tick: int, group_id: str, move_uid: Any, reason: str) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=GROUP_MOVE_ARRIVAL_IGNORED_EVENT_TYPE,
            params={
                "group_id": group_id,
                "move_uid": str(move_uid or ""),
                "reason": reason,
            },
        )
