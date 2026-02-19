from __future__ import annotations

import copy
from typing import Any

from hexcrawler.sim.core import MAX_AFFECTED_PER_ACTION, SimCommand, Simulation
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import world_xy_to_axial, world_xy_to_square_grid_cell
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.signals import distance_between_locations

ATTACK_INTENT_COMMAND_TYPE = "attack_intent"
COMBAT_OUTCOME_EVENT_TYPE = "combat_outcome"
DEFAULT_CALLED_REGION = "torso"
PLACEHOLDER_COOLDOWN_TICKS = 1


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _is_json_safe(value: Any) -> bool:
    if _is_json_primitive(value):
        return True
    if isinstance(value, list):
        return all(_is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_safe(nested) for key, nested in value.items())
    return False


class CombatExecutionModule(RuleModule):
    name = "combat"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != ATTACK_INTENT_COMMAND_TYPE:
            return False

        attacker_id = command.params.get("attacker_id")
        mode = command.params.get("mode")
        target_id = command.params.get("target_id")
        target_cell_payload = command.params.get("target_cell")
        weapon_ref = command.params.get("weapon_ref")
        target_region_raw = command.params.get("target_region")
        tags = command.params.get("tags", [])

        called_region = DEFAULT_CALLED_REGION
        if isinstance(target_region_raw, str) and target_region_raw:
            called_region = target_region_raw

        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            tags = []

        target_cell: dict[str, Any] | None = None
        resolved_target_id: str | None = None
        reason = "resolved"
        applied = False

        if not isinstance(attacker_id, str) or not attacker_id:
            reason = "invalid_attacker"
        elif not isinstance(mode, str) or not mode:
            reason = "invalid_mode"
        elif attacker_id not in sim.state.entities:
            reason = "invalid_attacker"
        else:
            attacker = sim.state.entities[attacker_id]
            target_id_value = str(target_id) if isinstance(target_id, str) and target_id else None
            if target_id_value is not None and target_id_value not in sim.state.entities:
                reason = "invalid_target"
            elif target_id_value is None and target_cell_payload is None:
                reason = "invalid_target"
            else:
                parsed_cell, cell_error = self._parse_cell_ref(sim, target_cell_payload)
                if cell_error is not None:
                    reason = cell_error
                else:
                    target_cell = parsed_cell
                    if target_id_value is not None:
                        target = sim.state.entities[target_id_value]
                        if attacker.space_id != target.space_id:
                            reason = "space_mismatch"
                        elif target_cell is not None:
                            target_coord = self._entity_coord(sim, target_id_value)
                            if target_coord is None:
                                reason = "invalid_target"
                            elif target_cell["space_id"] != target.space_id or target_cell["coord"] != target_coord:
                                reason = "target_cell_mismatch"
                    if reason == "resolved" and target_cell is None and target_id_value is not None:
                        target_coord = self._entity_coord(sim, target_id_value)
                        if target_coord is None:
                            reason = "invalid_target"
                        else:
                            target_cell = {"space_id": sim.state.entities[target_id_value].space_id, "coord": target_coord}

                    if reason == "resolved" and target_cell is not None:
                        if attacker.space_id != str(target_cell["space_id"]):
                            reason = "space_mismatch"

                    if reason == "resolved" and target_id_value is None and target_cell is not None:
                        resolved_target_id = self._entity_id_at_cell(sim, target_cell)
                        if resolved_target_id is None:
                            reason = "no_target_in_cell"

                    if reason == "resolved" and target_id_value is not None:
                        resolved_target_id = target_id_value

                    if reason == "resolved" and self._mode_is_melee(mode):
                        attacker_location = self._entity_location(sim, attacker_id)
                        target_location = {
                            "space_id": str(target_cell["space_id"]) if target_cell is not None else attacker.space_id,
                            "topology_type": attacker_location["topology_type"],
                            "coord": copy.deepcopy(target_cell["coord"]) if target_cell is not None else copy.deepcopy(attacker_location["coord"]),
                        }
                        if target_cell is None:
                            reason = "invalid_target"
                        elif target_location["space_id"] != attacker_location["space_id"]:
                            reason = "space_mismatch"
                        elif not self._is_adjacent(attacker_location, target_location):
                            reason = "out_of_range"

                    if reason == "resolved" and attacker.cooldown_until_tick > command.tick:
                        reason = "cooldown_blocked"

                    if reason == "resolved":
                        applied = True
                        attacker.cooldown_until_tick = int(command.tick) + PLACEHOLDER_COOLDOWN_TICKS

        affected = self._build_affected_outcomes(
            sim=sim,
            resolved_target_id=resolved_target_id,
            called_region=called_region,
            applied=applied,
            reason=reason,
        )

        outcome = {
                "tick": int(command.tick),
                "intent": ATTACK_INTENT_COMMAND_TYPE,
                "action_uid": f"{command.tick}:{command_index}",
                "attacker_id": attacker_id if isinstance(attacker_id, str) else None,
                "target_id": target_id if isinstance(target_id, str) else resolved_target_id,
                "target_cell": copy.deepcopy(target_cell) if target_cell is not None else None,
                "mode": mode if isinstance(mode, str) else None,
                "weapon_ref": weapon_ref if isinstance(weapon_ref, str) else None,
                "called_region": called_region,
                "region_hit": called_region if applied else None,
                "applied": applied,
                "reason": reason,
                "wound_deltas": [],
                "roll_trace": [],
                "tags": list(tags),
            }
        if affected:
            outcome["affected"] = affected
        sim.append_combat_outcome(outcome)
        return True

    @staticmethod
    def _truncate_affected_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(entries) <= MAX_AFFECTED_PER_ACTION:
            return entries
        return entries[:MAX_AFFECTED_PER_ACTION]

    @classmethod
    def _build_affected_outcomes(
        cls,
        *,
        sim: Simulation,
        resolved_target_id: str | None,
        called_region: str,
        applied: bool,
        reason: str,
    ) -> list[dict[str, Any]]:
        if not applied or resolved_target_id is None:
            return []
        resolved_coord = cls._entity_coord(sim, resolved_target_id)
        resolved_entity = sim.state.entities.get(resolved_target_id)
        if resolved_entity is None or resolved_coord is None:
            return []
        entries = [
            {
                "entity_id": resolved_target_id,
                "cell": {"space_id": resolved_entity.space_id, "coord": resolved_coord},
                "called_region": called_region,
                "region_hit": called_region,
                "wound_deltas": [],
                "applied": True,
                "reason": reason,
            }
        ]
        return cls._truncate_affected_entries(entries)

    @classmethod
    def _entity_id_at_cell(cls, sim: Simulation, cell: dict[str, Any]) -> str | None:
        matches: list[str] = []
        for entity_id in sorted(sim.state.entities):
            entity = sim.state.entities[entity_id]
            if entity.space_id != str(cell["space_id"]):
                continue
            coord = cls._entity_coord(sim, entity_id)
            if coord == cell["coord"]:
                matches.append(entity_id)
        if not matches:
            return None
        return matches[0]

    @staticmethod
    def _mode_is_melee(mode: str) -> bool:
        normalized = mode.strip().lower()
        return normalized == "melee" or normalized.startswith("melee_")

    @staticmethod
    def _entity_coord(sim: Simulation, entity_id: str) -> dict[str, int] | None:
        entity = sim.state.entities.get(entity_id)
        if entity is None:
            return None
        space = sim.state.world.spaces.get(entity.space_id)
        if space is None:
            return None
        if space.topology_type == SQUARE_GRID_TOPOLOGY:
            return world_xy_to_square_grid_cell(entity.position_x, entity.position_y)
        if space.topology_type == OVERWORLD_HEX_TOPOLOGY or space.topology_type.startswith("hex") or space.topology_type == "custom":
            return world_xy_to_axial(entity.position_x, entity.position_y).to_dict()
        return None

    @classmethod
    def _entity_location(cls, sim: Simulation, entity_id: str) -> dict[str, Any]:
        entity = sim.state.entities[entity_id]
        space = sim.state.world.spaces[entity.space_id]
        coord = cls._entity_coord(sim, entity_id)
        return {
            "space_id": entity.space_id,
            "topology_type": space.topology_type if space.topology_type == SQUARE_GRID_TOPOLOGY else OVERWORLD_HEX_TOPOLOGY,
            "coord": coord,
        }

    @classmethod
    def _parse_cell_ref(cls, sim: Simulation, payload: Any) -> tuple[dict[str, Any] | None, str | None]:
        if payload is None:
            return None, None
        if not isinstance(payload, dict):
            return None, "invalid_target_cell"

        space_id = payload.get("space_id")
        if not isinstance(space_id, str) or not space_id:
            return None, "invalid_target_cell"
        space = sim.state.world.spaces.get(space_id)
        if space is None:
            return None, "invalid_target_cell"

        coord_raw = payload.get("coord")
        if not _is_json_safe(coord_raw):
            return None, "invalid_target_cell"
        if not space.is_valid_cell(coord_raw):
            return None, "invalid_target_cell_coord_for_space"
        return {"space_id": space_id, "coord": copy.deepcopy(coord_raw)}, None

    @staticmethod
    def _is_adjacent(attacker: dict[str, Any], target: dict[str, Any]) -> bool:
        from hexcrawler.sim.location import LocationRef

        distance = distance_between_locations(
            LocationRef(
                space_id=str(attacker["space_id"]),
                topology_type=str(attacker["topology_type"]),
                coord=dict(attacker["coord"]),
            ),
            LocationRef(
                space_id=str(target["space_id"]),
                topology_type=str(target["topology_type"]),
                coord=dict(target["coord"]),
            ),
        )
        return distance == 1
