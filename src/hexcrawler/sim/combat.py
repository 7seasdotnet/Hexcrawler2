from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from hexcrawler.sim.core import MAX_AFFECTED_PER_ACTION, MAX_WOUNDS, SimCommand, SimEvent, Simulation, _normalize_facing_token
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import axial_to_world_xy, world_xy_to_axial, world_xy_to_square_grid_cell
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.signals import distance_between_locations
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE

ATTACK_INTENT_COMMAND_TYPE = "attack_intent"
TURN_INTENT_COMMAND_TYPE = "turn_intent"
COMBAT_OUTCOME_EVENT_TYPE = "combat_outcome"
TURN_OUTCOME_EVENT_TYPE = "turn_outcome"
ATTACK_RESOLVE_EVENT_TYPE = "attack_resolve"
DEFAULT_CALLED_REGION = "torso"
MELEE_WINDUP_TICKS = 2
MELEE_ACTIVE_WINDOW_TICKS = 1
MELEE_RECOVERY_TICKS = 5
MELEE_TOTAL_COMMIT_TICKS = MELEE_WINDUP_TICKS + MELEE_ACTIVE_WINDOW_TICKS + MELEE_RECOVERY_TICKS
DEFAULT_WOUND_SEVERITY = 1
STARTER_HOSTILE_INCOMING_SEVERITY_BONUS_STAT = "starter_incoming_wound_severity_bonus"
COMBAT_CADENCE_PROBE_MAX_ROWS = 96



@dataclass(frozen=True)
class WeaponMotionProfile:
    profile_id: str
    motion_family: str
    windup_ticks: int
    impact_tick: int
    recovery_ticks: int
    reach: float
    arc_degrees: float
    visual_weight: float
    tracking_degrees: float


WEAPON_MOTION_PROFILES: dict[str, WeaponMotionProfile] = {
    "default_melee": WeaponMotionProfile("default_melee", "slash", 2, 2, 5, 1.0, 90.0, 1.0, 0.0),
    "slash": WeaponMotionProfile("slash", "slash", 2, 2, 5, 1.05, 105.0, 1.0, 0.0),
    "thrust": WeaponMotionProfile("thrust", "thrust", 2, 2, 4, 1.35, 35.0, 0.85, 0.0),
    "chop": WeaponMotionProfile("chop", "chop", 3, 3, 6, 1.0, 70.0, 1.35, 0.0),
    "stab": WeaponMotionProfile("stab", "stab", 1, 1, 3, 0.8, 30.0, 0.65, 0.0),
    "bash": WeaponMotionProfile("bash", "bash", 2, 2, 5, 0.9, 80.0, 1.25, 0.0),
}
DEFAULT_WEAPON_PROFILE_ID = "default_melee"


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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class CombatExecutionModule(RuleModule):
    name = "combat"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type == TURN_INTENT_COMMAND_TYPE:
            self._handle_turn_intent(sim, command=command, command_index=command_index)
            return True
        if command.command_type != ATTACK_INTENT_COMMAND_TYPE:
            return False

        attacker_id = command.params.get("attacker_id")
        mode = command.params.get("mode")
        target_id = command.params.get("target_id")
        target_cell_payload = command.params.get("target_cell")
        weapon_ref = command.params.get("weapon_ref")
        weapon_profile = self._authoritative_weapon_motion_profile_for_attack(sim=sim, attacker_id=attacker_id, supplied_profile_id=command.params.get("weapon_profile_id"), weapon_ref=weapon_ref)
        weapon_profile_payload = self._weapon_profile_payload(weapon_profile)
        committed_aim = self._parse_committed_aim(command.params.get("committed_aim"))
        target_point = self._parse_target_point(command.params.get("target_point"))
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
            if self._is_campaign_space_entity(sim, attacker_id):
                reason = "tactical_not_allowed_in_campaign_space"
            else:
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
                            elif resolved_target_id is not None:
                                arc_reason = self._validate_melee_arc_admissibility(
                                    sim=sim,
                                    attacker_id=attacker_id,
                                    target_id=resolved_target_id,
                                )
                                if arc_reason is not None:
                                    reason = arc_reason

                        if reason == "resolved" and attacker.cooldown_until_tick > command.tick:
                            reason = "not_ready"

                        if reason == "resolved":
                            applied = True
                            attacker.cooldown_until_tick = int(command.tick) + weapon_profile.windup_ticks + 1 + weapon_profile.recovery_ticks
                            resolve_tick = int(command.tick) + weapon_profile.impact_tick
                            if committed_aim is None:
                                committed_aim = self._aim_from_attacker_to_cell(sim=sim, attacker_id=attacker_id, target_cell=target_cell)
                            self._append_combat_outcome_and_trace(
                                sim,
                                {
                                    "tick": int(command.tick),
                                    "intent": ATTACK_INTENT_COMMAND_TYPE,
                                    "action_uid": f"{command.tick}:{command_index}",
                                    "attacker_id": attacker_id,
                                    "target_id": resolved_target_id,
                                    "target_cell": copy.deepcopy(target_cell) if target_cell is not None else None,
                                    "mode": mode,
                                    "weapon_ref": weapon_ref if isinstance(weapon_ref, str) else None,
                                    "weapon_profile_id": weapon_profile.profile_id,
                                    "weapon_profile": copy.deepcopy(weapon_profile_payload),
                                    "committed_aim": copy.deepcopy(committed_aim),
                                    "target_point": copy.deepcopy(target_point),
                                    "cadence_state": "WINDUP",
                                    "called_region": called_region,
                                    "region_hit": None,
                                    "applied": False,
                                    "reason": "windup_started",
                                    "strike_phase": "windup",
                                    "resolve_tick": resolve_tick,
                                    "impact_tick": resolve_tick,
                                    "recovery_until_tick": attacker.cooldown_until_tick,
                                    "wound_deltas": [],
                                    "roll_trace": [],
                                    "tags": list(tags),
                                }
                            )
                            sim.schedule_event_at(
                                tick=resolve_tick,
                                event_type=ATTACK_RESOLVE_EVENT_TYPE,
                                params={
                                    "tick": int(command.tick),
                                    "resolve_tick": resolve_tick,
                                    "action_uid": f"{command.tick}:{command_index}",
                                    "attacker_id": attacker_id,
                                    "target_id": resolved_target_id,
                                    "target_cell": copy.deepcopy(target_cell) if target_cell is not None else None,
                                    "mode": mode,
                                    "weapon_ref": weapon_ref if isinstance(weapon_ref, str) else None,
                                    "weapon_profile_id": weapon_profile.profile_id,
                                    "weapon_profile": copy.deepcopy(weapon_profile_payload),
                                    "committed_aim": copy.deepcopy(committed_aim),
                                    "target_point": copy.deepcopy(target_point),
                                    "cadence_state": "IMPACT",
                                    "called_region": called_region,
                                    "tags": list(tags),
                                    "attacker_facing": int(attacker.facing),
                                },
                            )

        if not applied and reason == "not_ready":
            sim.append_command_outcome({
                "tick": int(command.tick),
                "command_type": ATTACK_INTENT_COMMAND_TYPE,
                "attacker_id": attacker_id if isinstance(attacker_id, str) else None,
                "applied": False,
                "reason": "not_ready",
                "feedback": "RECOVERING",
            })
        elif not applied:
            outcome = {
                "tick": int(command.tick),
                "intent": ATTACK_INTENT_COMMAND_TYPE,
                "action_uid": f"{command.tick}:{command_index}",
                "attacker_id": attacker_id if isinstance(attacker_id, str) else None,
                "target_id": target_id if isinstance(target_id, str) else resolved_target_id,
                "target_cell": copy.deepcopy(target_cell) if target_cell is not None else None,
                "mode": mode if isinstance(mode, str) else None,
                "weapon_ref": weapon_ref if isinstance(weapon_ref, str) else None,
                "weapon_profile_id": weapon_profile.profile_id,
                "weapon_profile": copy.deepcopy(weapon_profile_payload),
                "committed_aim": copy.deepcopy(committed_aim),
                "target_point": copy.deepcopy(target_point),
                "cadence_state": "REJECTED",
                "called_region": called_region,
                "region_hit": None,
                "applied": False,
                "reason": reason,
                "strike_phase": "rejected",
                "wound_deltas": [],
                "roll_trace": [],
                "tags": list(tags),
            }
            self._append_combat_outcome_and_trace(sim, outcome)
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != ATTACK_RESOLVE_EVENT_TYPE:
            return
        attacker_id = event.params.get("attacker_id")
        target_id = event.params.get("target_id")
        target_cell = event.params.get("target_cell")
        called_region = event.params.get("called_region")
        tags = event.params.get("tags")
        mode = event.params.get("mode")
        weapon_ref = event.params.get("weapon_ref")
        weapon_profile = self._weapon_motion_profile_for_payload(event.params.get("weapon_profile_id"), weapon_ref=weapon_ref)
        weapon_profile_payload = self._weapon_profile_payload(weapon_profile)
        committed_aim = self._parse_committed_aim(event.params.get("committed_aim"))
        target_point = self._parse_target_point(event.params.get("target_point"))

        reason = "resolved"
        applied = False
        resolved_target_id = target_id if isinstance(target_id, str) else None

        if not isinstance(attacker_id, str) or attacker_id not in sim.state.entities:
            reason = "invalid_attacker"
        elif not isinstance(target_cell, dict):
            reason = "invalid_target"
        else:
            attacker = sim.state.entities[attacker_id]
            if self._is_campaign_space_entity(sim, attacker_id):
                reason = "tactical_not_allowed_in_campaign_space"
            elif attacker.space_id != str(target_cell.get("space_id", "")):
                reason = "space_mismatch"
            elif not self._mode_is_melee(str(mode)):
                reason = "invalid_mode"
            else:
                if resolved_target_id is None:
                    resolved_target_id = self._entity_id_at_cell(sim, target_cell)
                if resolved_target_id is None:
                    reason = "no_target_in_cell"
                elif resolved_target_id not in sim.state.entities:
                    reason = "invalid_target"
                else:
                    current_target_coord = self._entity_coord(sim, resolved_target_id)
                    if current_target_coord is None:
                        reason = "invalid_target"
                    elif current_target_coord != target_cell.get("coord"):
                        reason = "target_moved"
                    else:
                        attacker_facing = event.params.get("attacker_facing")
                        arc_reason = self._validate_melee_arc_admissibility(
                            sim=sim,
                            attacker_id=attacker_id,
                            target_id=resolved_target_id,
                            facing_override=attacker_facing if isinstance(attacker_facing, int) else None,
                        )
                        reason = arc_reason or "resolved"
                        if reason == "resolved":
                            applied = True

        if not isinstance(called_region, str) or not called_region:
            called_region = DEFAULT_CALLED_REGION
        normalized_tags = list(tags) if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags) else []
        affected = self._build_affected_outcomes(
            sim=sim,
            resolved_target_id=resolved_target_id,
            called_region=called_region,
            applied=applied,
            reason=reason,
        )
        if affected:
            self._apply_wounds_from_affected(
                sim=sim,
                tick=int(event.tick),
                attacker_id=attacker_id if isinstance(attacker_id, str) else None,
                called_region=called_region,
                affected=affected,
            )
        outcome = {
            "tick": int(event.tick),
            "intent": ATTACK_INTENT_COMMAND_TYPE,
            "action_uid": event.params.get("action_uid"),
            "attacker_id": attacker_id if isinstance(attacker_id, str) else None,
            "target_id": resolved_target_id,
            "target_cell": copy.deepcopy(target_cell) if isinstance(target_cell, dict) else None,
            "mode": mode if isinstance(mode, str) else None,
            "weapon_ref": weapon_ref if isinstance(weapon_ref, str) else None,
            "weapon_profile_id": weapon_profile.profile_id,
            "weapon_profile": copy.deepcopy(weapon_profile_payload),
            "committed_aim": copy.deepcopy(committed_aim),
            "target_point": copy.deepcopy(target_point),
            "cadence_state": "IMPACT" if applied else "IMPACT_MISS",
            "called_region": called_region,
            "region_hit": called_region if applied else None,
            "applied": applied,
            "reason": reason,
            "strike_phase": "active" if applied else "active_miss",
            "wound_deltas": [],
            "roll_trace": [],
            "tags": normalized_tags,
            "recovery_until_tick": (
                sim.state.entities[attacker_id].cooldown_until_tick
                if isinstance(attacker_id, str) and attacker_id in sim.state.entities
                else None
            ),
        }
        if affected:
            outcome["affected"] = affected
        self._append_combat_outcome_and_trace(sim, outcome)


    @classmethod
    def _append_combat_outcome_and_trace(cls, sim: Simulation, outcome: dict[str, Any]) -> None:
        sim.append_combat_outcome(outcome)
        normalized = sim.state.combat_log[-1]
        trace_key = f"combat:{normalized.get('action_uid')}:{normalized.get('tick')}:{normalized.get('reason')}"
        sim._append_event_trace_entry(
            {
                "tick": int(normalized["tick"]),
                "event_id": sim._trace_event_id_as_int(trace_key),
                "event_type": COMBAT_OUTCOME_EVENT_TYPE,
                "params": copy.deepcopy(normalized),
                "module_hooks_called": False,
            }
        )

    @classmethod
    def _wound_severity_for_target(cls, *, sim: Simulation, entity_id: str) -> int:
        entity = sim.state.entities.get(entity_id)
        bonus = 0
        if entity is not None and isinstance(entity.stats, dict):
            raw_bonus = entity.stats.get(STARTER_HOSTILE_INCOMING_SEVERITY_BONUS_STAT, 0)
            if isinstance(raw_bonus, int) and not isinstance(raw_bonus, bool):
                bonus = max(0, min(3, raw_bonus))
        return DEFAULT_WOUND_SEVERITY + bonus

    @staticmethod
    def _append_wound_with_fifo_cap(entity_wounds: list[dict[str, Any]], wound: dict[str, Any]) -> None:
        entity_wounds.append(copy.deepcopy(wound))
        while len(entity_wounds) > MAX_WOUNDS:
            entity_wounds.pop(0)

    @classmethod
    def _apply_wounds_from_affected(
        cls,
        *,
        sim: Simulation,
        tick: int,
        attacker_id: str | None,
        called_region: str,
        affected: list[dict[str, Any]],
    ) -> None:
        for entry in affected:
            if entry.get("applied") is not True:
                continue
            entity_id = entry.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            entity = sim.state.entities.get(entity_id)
            if entity is None:
                continue
            wound = {
                "region": cls._resolve_wound_region(entry=entry, called_region=called_region),
                "severity": cls._wound_severity_for_target(sim=sim, entity_id=entity_id),
                "tags": [],
                "inflicted_tick": int(tick),
                "source": attacker_id if isinstance(attacker_id, str) else None,
            }
            cls._append_wound_with_fifo_cap(entity.wounds, wound)
            entry["wound_deltas"] = [{"op": "append", "wound": copy.deepcopy(wound)}]

    @staticmethod
    def _resolve_wound_region(*, entry: dict[str, Any], called_region: str) -> str:
        region_hit = entry.get("region_hit")
        if isinstance(region_hit, str) and region_hit:
            return region_hit
        affected_called_region = entry.get("called_region")
        if isinstance(affected_called_region, str) and affected_called_region:
            return affected_called_region
        if isinstance(called_region, str) and called_region:
            return called_region
        return DEFAULT_CALLED_REGION

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
        entries = cls._sort_affected_entries(entries)
        return cls._truncate_affected_entries(entries)

    @classmethod
    def _sort_affected_entries(cls, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(entries, key=cls._affected_sort_key)

    @classmethod
    def _affected_sort_key(cls, entry: dict[str, Any]) -> tuple[int, int, int, str, str]:
        cell = entry.get("cell") if isinstance(entry, dict) else None
        cell_key = cls._cell_sort_key(cell)
        entity_id = entry.get("entity_id") if isinstance(entry, dict) else None
        entity_key = entity_id if isinstance(entity_id, str) else ""
        return (cell_key[0], cell_key[1], cell_key[2], cell_key[3], entity_key)

    @staticmethod
    def _cell_sort_key(cell: Any) -> tuple[int, int, int, str]:
        if not isinstance(cell, dict):
            return (1, 0, 0, "")
        coord = cell.get("coord")
        if isinstance(coord, dict) and isinstance(coord.get("q"), int) and isinstance(coord.get("r"), int):
            return (0, int(coord["q"]), int(coord["r"]), "")
        return (1, 0, 0, _canonical_json(cell.get("coord")))

    def _handle_turn_intent(self, sim: Simulation, *, command: SimCommand, command_index: int) -> None:
        entity_id = command.params.get("entity_id")
        facing_raw = command.params.get("facing")
        tags = command.params.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            tags = []

        applied = False
        reason = "resolved"
        normalized_facing = 0

        if not isinstance(entity_id, str) or not entity_id:
            reason = "invalid_entity"
        elif entity_id not in sim.state.entities:
            reason = "invalid_entity"
        elif self._is_campaign_space_entity(sim, entity_id):
            reason = "tactical_not_allowed_in_campaign_space"
        elif facing_raw is None:
            reason = "invalid_facing"
        else:
            try:
                normalized_facing = _normalize_facing_token(facing_raw)
            except ValueError:
                reason = "invalid_facing"
            else:
                sim.state.entities[entity_id].facing = normalized_facing
                applied = True

        sim.schedule_event_at(
            tick=command.tick,
            event_type=TURN_OUTCOME_EVENT_TYPE,
            params={
                "tick": int(command.tick),
                "intent": TURN_INTENT_COMMAND_TYPE,
                "action_uid": f"{command.tick}:{command_index}",
                "entity_id": entity_id if isinstance(entity_id, str) else None,
                "facing": int(normalized_facing) if applied else None,
                "applied": applied,
                "reason": reason,
                "tags": list(tags),
            },
        )


    @classmethod
    def _authoritative_weapon_motion_profile_for_attack(
        cls,
        *,
        sim: Simulation,
        attacker_id: Any,
        supplied_profile_id: Any,
        weapon_ref: Any = None,
    ) -> WeaponMotionProfile:
        """Resolve combat timing from authoritative actor/equipment state.

        Equipment identity is not implemented yet, so viewer-supplied profile IDs are
        deliberately ignored and all melee normalizes to default_melee.  The ignored
        arguments remain in the signature to make the future equipment validation seam
        explicit without allowing input spoofing to change timing/reach/arc behavior.
        """
        _ = (sim, attacker_id, supplied_profile_id, weapon_ref)
        return WEAPON_MOTION_PROFILES[DEFAULT_WEAPON_PROFILE_ID]

    @classmethod
    def _weapon_motion_profile_for_payload(cls, profile_id: Any, *, weapon_ref: Any = None) -> WeaponMotionProfile:
        if isinstance(profile_id, str) and profile_id in WEAPON_MOTION_PROFILES:
            return WEAPON_MOTION_PROFILES[profile_id]
        if isinstance(profile_id, str):
            normalized = profile_id.strip().lower()
            if normalized in WEAPON_MOTION_PROFILES:
                return WEAPON_MOTION_PROFILES[normalized]
        if isinstance(weapon_ref, str):
            normalized_ref = weapon_ref.strip().lower()
            for keyword, mapped_id in {
                "spear": "thrust",
                "polearm": "thrust",
                "pike": "thrust",
                "lance": "thrust",
                "axe": "chop",
                "hatchet": "chop",
                "sword": "slash",
                "sabre": "slash",
                "dagger": "stab",
                "knife": "stab",
                "mace": "bash",
                "hammer": "bash",
                "club": "bash",
            }.items():
                if keyword in normalized_ref:
                    return WEAPON_MOTION_PROFILES[mapped_id]
        return WEAPON_MOTION_PROFILES[DEFAULT_WEAPON_PROFILE_ID]

    @staticmethod
    def _weapon_profile_payload(profile: WeaponMotionProfile) -> dict[str, Any]:
        return {
            "profile_id": profile.profile_id,
            "motion_family": profile.motion_family,
            "windup_ticks": profile.windup_ticks,
            "impact_tick": profile.impact_tick,
            "recovery_ticks": profile.recovery_ticks,
            # Forensic cadence evidence only.  Reach/arc/visual geometry are derived
            # from the stable profile table at runtime rather than serialized here.
        }

    @staticmethod
    def _parse_committed_aim(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        x = payload.get("x")
        y = payload.get("y")
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            return None
        if not isinstance(y, (int, float)) or isinstance(y, bool):
            return None
        magnitude = (float(x) * float(x) + float(y) * float(y)) ** 0.5
        if magnitude <= 0.0001:
            return None
        result: dict[str, Any] = {"x": round(float(x) / magnitude, 6), "y": round(float(y) / magnitude, 6)}
        space_id = payload.get("space_id")
        if isinstance(space_id, str) and space_id:
            result["space_id"] = space_id
        facing = payload.get("facing")
        if isinstance(facing, int) and not isinstance(facing, bool):
            result["facing"] = int(facing)
        return result

    @staticmethod
    def _parse_target_point(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        x = payload.get("x")
        y = payload.get("y")
        space_id = payload.get("space_id")
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            return None
        if not isinstance(y, (int, float)) or isinstance(y, bool):
            return None
        result: dict[str, Any] = {"x": round(float(x), 6), "y": round(float(y), 6)}
        if isinstance(space_id, str) and space_id:
            result["space_id"] = space_id
        return result

    @classmethod
    def _aim_from_attacker_to_cell(cls, *, sim: Simulation, attacker_id: str, target_cell: dict[str, Any] | None) -> dict[str, Any] | None:
        attacker = sim.state.entities.get(attacker_id)
        if attacker is None or target_cell is None:
            return None
        space = sim.state.world.spaces.get(attacker.space_id)
        if space is None:
            return None
        coord = target_cell.get("coord")
        if space.topology_type == SQUARE_GRID_TOPOLOGY and isinstance(coord, dict):
            target_x = float(coord.get("x", 0)) + 0.5
            target_y = float(coord.get("y", 0)) + 0.5
        else:
            if not isinstance(coord, dict) or not isinstance(coord.get("q"), int) or not isinstance(coord.get("r"), int):
                return None
            target_x, target_y = axial_to_world_xy(type("_Coord", (), {"q": coord["q"], "r": coord["r"]})())
        dx = target_x - float(attacker.position_x)
        dy = target_y - float(attacker.position_y)
        magnitude = (dx * dx + dy * dy) ** 0.5
        if magnitude <= 0.0001:
            return None
        return {"space_id": attacker.space_id, "x": round(dx / magnitude, 6), "y": round(dy / magnitude, 6), "facing": int(attacker.facing)}

    @classmethod
    def _validate_melee_arc_admissibility(
        cls,
        *,
        sim: Simulation,
        attacker_id: str,
        target_id: str,
        facing_override: int | None = None,
    ) -> str | None:
        attacker = sim.state.entities.get(attacker_id)
        target = sim.state.entities.get(target_id)
        if attacker is None or target is None:
            return "invalid_target"
        if attacker.space_id != target.space_id:
            return "space_mismatch"
        space = sim.state.world.spaces.get(attacker.space_id)
        # TODO(Model B): replace topology-derived tactical admissibility with explicit
        # space-role checks once role metadata is serialized on spaces.
        if space is None or space.topology_type == SQUARE_GRID_TOPOLOGY:
            return None
        attacker_coord = cls._entity_coord(sim, attacker_id)
        target_coord = cls._entity_coord(sim, target_id)
        direction = cls._hex_neighbor_direction(attacker_coord=attacker_coord, target_coord=target_coord)
        if direction is None:
            return "invalid_arc_coord"
        facing = (facing_override if facing_override is not None else attacker.facing) % 6
        allowed = {(facing - 1) % 6, facing, (facing + 1) % 6}
        if direction not in allowed:
            return "invalid_arc"
        return None

    @staticmethod
    def _hex_neighbor_direction(*, attacker_coord: dict[str, Any] | None, target_coord: dict[str, Any] | None) -> int | None:
        if not isinstance(attacker_coord, dict) or not isinstance(target_coord, dict):
            return None
        if not isinstance(attacker_coord.get("q"), int) or not isinstance(attacker_coord.get("r"), int):
            return None
        if not isinstance(target_coord.get("q"), int) or not isinstance(target_coord.get("r"), int):
            return None
        dq = target_coord["q"] - attacker_coord["q"]
        dr = target_coord["r"] - attacker_coord["r"]
        directions = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        try:
            return directions.index((dq, dr))
        except ValueError:
            return None

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
        # Role gating is enforced at command ingress. The branch below is migration-only
        # compatibility for legacy overworld+custom topology payloads.
        is_campaign_hex_topology = space.topology_type in {OVERWORLD_HEX_TOPOLOGY, "hex_disk", "hex_rectangle", "hex_axial"}
        is_legacy_overworld_custom = entity.space_id == "overworld" and space.topology_type == "custom"
        if is_campaign_hex_topology or is_legacy_overworld_custom:
            return world_xy_to_axial(entity.position_x, entity.position_y).to_dict()
        return None

    @staticmethod
    def _is_campaign_space_entity(sim: Simulation, entity_id: str) -> bool:
        entity = sim.state.entities.get(entity_id)
        if entity is None:
            return False
        space = sim.state.world.spaces.get(entity.space_id)
        if space is None:
            return False
        return space.role == CAMPAIGN_SPACE_ROLE

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


def _combat_source_from_tags(tags: Any, *, fallback: str = "other") -> str:
    tag_set = {str(tag) for tag in tags} if isinstance(tags, list) else set()
    if "viewer_lmb_directional_melee" in tag_set:
        return "player_lmb"
    if "local_hostile_behavior" in tag_set:
        return "hostile_ai"
    if "visual_audit" in tag_set:
        return "visual_audit"
    if "test" in tag_set:
        return "test_driver"
    return fallback


def _combat_cadence_state_for_actor(sim: Simulation, actor_id: str) -> str:
    entity = sim.state.entities.get(actor_id)
    if entity is None:
        return "UNKNOWN"
    pending_impacts = [
        event for event in sim.pending_events()
        if event.event_type == ATTACK_RESOLVE_EVENT_TYPE and event.params.get("attacker_id") == actor_id
    ]
    if pending_impacts:
        return "WINDUP"
    if int(entity.cooldown_until_tick) > int(sim.state.tick):
        return "RECOVERING"
    return "READY"


def combat_cadence_probe(sim: Simulation) -> dict[str, Any]:
    """Return bounded deterministic combat-cadence diagnostics.

    The probe is a read-only derived report: it stores no viewer/camera/projection
    state and does not mutate the simulation.  It is safe for debug and audit
    surfaces, but it is not authoritative combat evidence.
    """

    accepted_by_uid: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(sim.state.combat_log[-COMBAT_CADENCE_PROBE_MAX_ROWS:]):
        if not isinstance(entry, dict):
            continue
        action_uid = str(entry.get("action_uid", ""))
        tags = entry.get("tags", [])
        weapon_profile = entry.get("weapon_profile") if isinstance(entry.get("weapon_profile"), dict) else {}
        reason = str(entry.get("reason", ""))
        accepted = reason == "windup_started"
        if accepted and action_uid:
            accepted_by_uid[action_uid] = entry
        accepted_row = accepted_by_uid.get(action_uid, entry if accepted else {})
        actor_id = entry.get("attacker_id") if isinstance(entry.get("attacker_id"), str) else None
        target_cell = copy.deepcopy(entry.get("target_cell")) if isinstance(entry.get("target_cell"), dict) else None
        row = {
            "row_id": index,
            "actor_id": actor_id,
            "faction": (sim.state.entities.get(actor_id).stats.get("faction_id") if actor_id in sim.state.entities and isinstance(sim.state.entities[actor_id].stats, dict) else None),
            "role": (sim.state.entities.get(actor_id).stats.get("role") if actor_id in sim.state.entities and isinstance(sim.state.entities[actor_id].stats, dict) else None),
            "source_path": "scheduled_impact" if reason in {"resolved", "no_target_in_cell", "target_moved", "invalid_arc"} and not accepted else _combat_source_from_tags(tags),
            "accepted_attack_tick": accepted_row.get("tick") if isinstance(accepted_row, dict) and accepted_row.get("reason") == "windup_started" else (entry.get("tick") if accepted else None),
            "windup_start_tick": accepted_row.get("tick") if isinstance(accepted_row, dict) and accepted_row.get("reason") == "windup_started" else None,
            "impact_tick": entry.get("tick") if reason != "windup_started" else entry.get("impact_tick"),
            "cooldown_until_tick": entry.get("recovery_until_tick"),
            "recovery_until_tick": entry.get("recovery_until_tick"),
            "current_cadence_state": _combat_cadence_state_for_actor(sim, actor_id) if actor_id else "UNKNOWN",
            "accepted": accepted,
            "rejection_reason": None if accepted or reason in {"resolved", "target_incapacitated"} else reason,
            "outcome_emitted": reason != "windup_started" and str(entry.get("strike_phase", "")) != "rejected",
            "combat_log_summary": {"index": index, "tick": entry.get("tick"), "reason": reason, "applied": entry.get("applied")},
            "event_trace_summary": None,
            "target_id": entry.get("target_id"),
            "target_cell": target_cell,
            "target_point": copy.deepcopy(entry.get("target_point")) if isinstance(entry.get("target_point"), dict) else None,
            "committed_aim": copy.deepcopy(entry.get("committed_aim")) if isinstance(entry.get("committed_aim"), dict) else None,
            "outcome_label": reason,
            "weapon_profile_id": entry.get("weapon_profile_id"),
            "motion_family": weapon_profile.get("motion_family"),
            "action_uid": action_uid or None,
        }
        rows.append(row)

    for outcome in sim.get_command_outcomes()[-COMBAT_CADENCE_PROBE_MAX_ROWS:]:
        if not isinstance(outcome, dict) or outcome.get("command_type") != ATTACK_INTENT_COMMAND_TYPE:
            continue
        actor_id = outcome.get("attacker_id") if isinstance(outcome.get("attacker_id"), str) else None
        rows.append({
            "row_id": len(rows),
            "actor_id": actor_id,
            "faction": (sim.state.entities.get(actor_id).stats.get("faction_id") if actor_id in sim.state.entities and isinstance(sim.state.entities[actor_id].stats, dict) else None),
            "role": (sim.state.entities.get(actor_id).stats.get("role") if actor_id in sim.state.entities and isinstance(sim.state.entities[actor_id].stats, dict) else None),
            "source_path": "other",
            "accepted_attack_tick": None,
            "windup_start_tick": None,
            "impact_tick": None,
            "cooldown_until_tick": sim.state.entities[actor_id].cooldown_until_tick if actor_id in sim.state.entities else None,
            "recovery_until_tick": sim.state.entities[actor_id].cooldown_until_tick if actor_id in sim.state.entities else None,
            "current_cadence_state": _combat_cadence_state_for_actor(sim, actor_id) if actor_id else "UNKNOWN",
            "accepted": False,
            "rejection_reason": outcome.get("reason"),
            "outcome_emitted": False,
            "combat_log_summary": None,
            "event_trace_summary": None,
            "target_id": None,
            "target_cell": None,
            "target_point": None,
            "committed_aim": None,
            "outcome_label": outcome.get("feedback"),
            "weapon_profile_id": None,
            "motion_family": None,
            "action_uid": None,
        })

    return {
        "tick": int(sim.state.tick),
        "max_rows": COMBAT_CADENCE_PROBE_MAX_ROWS,
        "rows": rows[-COMBAT_CADENCE_PROBE_MAX_ROWS:],
        "pending_impacts": [
            {
                "event_id": event.event_id,
                "tick": int(event.tick),
                "actor_id": event.params.get("attacker_id"),
                "target_id": event.params.get("target_id"),
                "source_path": "scheduled_impact",
            }
            for event in sim.pending_events()
            if event.event_type == ATTACK_RESOLVE_EVENT_TYPE
        ][-COMBAT_CADENCE_PROBE_MAX_ROWS:],
    }
