from __future__ import annotations

from typing import Any

from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, SimCommand, Simulation
from hexcrawler.sim.movement import normalized_vector
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.signals import distance_between_locations
from hexcrawler.sim.world import LOCAL_SPACE_ROLE

HOSTILE_TEMPLATE_ID = "encounter_hostile_v1"
MAX_TRACKED_ATTACKERS = 512
WOUND_INCAPACITATE_SEVERITY = 3
LOCAL_CONTACT_ATTACK_COOLDOWN_TICKS = 2


class LocalHostileBehaviorModule(RuleModule):
    """Minimal deterministic hostile local-role behavior bridge.

    Applies only to local-role spaces and emits existing authoritative intents
    (`set_move_vector` and `attack_intent`) rather than mutating combat state directly.
    """

    name = "local_hostile_behavior"
    _STATE_LAST_ATTACK_TICK_BY_ENTITY = "last_attack_tick_by_entity"
    _STATE_CONTACT_LATCH_BY_ENTITY = "contact_latch_by_entity"

    def on_simulation_start(self, sim: Simulation) -> None:
        sim.set_rules_state(self.name, self._rules_state(sim))

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        state = self._rules_state(sim)
        last_attack_tick_by_entity = dict(state[self._STATE_LAST_ATTACK_TICK_BY_ENTITY])
        contact_latch_by_entity = dict(state[self._STATE_CONTACT_LATCH_BY_ENTITY])

        player = sim.state.entities.get(DEFAULT_PLAYER_ENTITY_ID)
        if player is None:
            return

        player_space = sim.state.world.spaces.get(player.space_id)
        if player_space is None or player_space.role != LOCAL_SPACE_ROLE:
            return

        for entity_id in sorted(sim.state.entities):
            entity = sim.state.entities[entity_id]
            if entity.template_id != HOSTILE_TEMPLATE_ID:
                continue
            if entity.space_id != player.space_id:
                continue
            if self._is_incapacitated(entity.wounds):
                self._append_move_intent(sim, tick=tick, entity_id=entity_id, move_x=0.0, move_y=0.0)
                continue

            hostile_location = sim._entity_location_ref(entity)
            player_location = sim._entity_location_ref(player)
            distance = distance_between_locations(hostile_location, player_location)
            if distance is not None and distance <= 1:
                # Hold hostile movement while in melee contact so command ordering
                # cannot re-introduce same-cell shove loops before combat intent resolves.
                self._append_move_intent(sim, tick=tick, entity_id=entity_id, move_x=0.0, move_y=0.0)
                latched = bool(contact_latch_by_entity.get(entity_id, False))
                if latched:
                    continue
                last_attack_tick = last_attack_tick_by_entity.get(entity_id)
                if isinstance(last_attack_tick, int) and (tick - last_attack_tick) < LOCAL_CONTACT_ATTACK_COOLDOWN_TICKS:
                    continue
                sim.append_command(
                    SimCommand(
                        tick=tick,
                        entity_id=entity_id,
                        command_type=ATTACK_INTENT_COMMAND_TYPE,
                        params={
                            "attacker_id": entity_id,
                            "target_id": DEFAULT_PLAYER_ENTITY_ID,
                            "mode": "melee",
                            "tags": ["local_hostile_behavior"],
                        },
                    )
                )
                last_attack_tick_by_entity[entity_id] = tick
                contact_latch_by_entity[entity_id] = True
                continue

            contact_latch_by_entity[entity_id] = False
            delta_x = player.position_x - entity.position_x
            delta_y = player.position_y - entity.position_y
            move_x, move_y = normalized_vector(delta_x, delta_y)
            self._append_move_intent(sim, tick=tick, entity_id=entity_id, move_x=move_x, move_y=move_y)

        state[self._STATE_LAST_ATTACK_TICK_BY_ENTITY] = {
            key: int(value)
            for key, value in sorted(last_attack_tick_by_entity.items())[-MAX_TRACKED_ATTACKERS:]
            if isinstance(key, str) and key and isinstance(value, int)
        }
        state[self._STATE_CONTACT_LATCH_BY_ENTITY] = {
            key: bool(value)
            for key, value in sorted(contact_latch_by_entity.items())[-MAX_TRACKED_ATTACKERS:]
            if isinstance(key, str) and key
        }
        sim.set_rules_state(self.name, state)

    @staticmethod
    def _is_incapacitated(wounds: list[dict[str, Any]]) -> bool:
        severity_total = 0
        for wound in wounds:
            severity = wound.get("severity") if isinstance(wound, dict) else None
            if isinstance(severity, int) and severity > 0:
                severity_total += severity
        return severity_total >= WOUND_INCAPACITATE_SEVERITY

    @staticmethod
    def _append_move_intent(sim: Simulation, *, tick: int, entity_id: str, move_x: float, move_y: float) -> None:
        sim.append_command(
            SimCommand(
                tick=tick,
                entity_id=entity_id,
                command_type="set_move_vector",
                params={"x": float(move_x), "y": float(move_y)},
            )
        )

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw_last_attack_tick_by_entity = state.get(self._STATE_LAST_ATTACK_TICK_BY_ENTITY, {})
        if not isinstance(raw_last_attack_tick_by_entity, dict):
            raise ValueError("local_hostile_behavior.last_attack_tick_by_entity must be an object")
        raw_contact_latch_by_entity = state.get(self._STATE_CONTACT_LATCH_BY_ENTITY, {})
        if not isinstance(raw_contact_latch_by_entity, dict):
            raise ValueError("local_hostile_behavior.contact_latch_by_entity must be an object")

        normalized: dict[str, int] = {}
        for entity_id, tick_value in sorted(raw_last_attack_tick_by_entity.items()):
            if not isinstance(entity_id, str) or not entity_id:
                continue
            if not isinstance(tick_value, int) or tick_value < 0:
                raise ValueError("local_hostile_behavior.last_attack_tick_by_entity values must be non-negative integers")
            normalized[entity_id] = tick_value
        if len(normalized) > MAX_TRACKED_ATTACKERS:
            normalized = dict(list(normalized.items())[-MAX_TRACKED_ATTACKERS:])

        normalized_latch: dict[str, bool] = {}
        for entity_id, latched in sorted(raw_contact_latch_by_entity.items()):
            if not isinstance(entity_id, str) or not entity_id:
                continue
            normalized_latch[entity_id] = bool(latched)
        if len(normalized_latch) > MAX_TRACKED_ATTACKERS:
            normalized_latch = dict(list(normalized_latch.items())[-MAX_TRACKED_ATTACKERS:])

        return {
            self._STATE_LAST_ATTACK_TICK_BY_ENTITY: normalized,
            self._STATE_CONTACT_LATCH_BY_ENTITY: normalized_latch,
        }
