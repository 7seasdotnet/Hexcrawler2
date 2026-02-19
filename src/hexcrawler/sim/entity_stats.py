from __future__ import annotations

import copy
from typing import Any

from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.rules import RuleModule

ENTITY_STAT_INTENT_COMMAND_TYPE = "entity_stat_intent"
ENTITY_STAT_EXECUTE_EVENT_TYPE = "entity_stat_execute"
ENTITY_STAT_OUTCOME_EVENT_TYPE = "entity_stat_outcome"


class EntityStatsExecutionModule(RuleModule):
    name = "entity_stats"

    _STATE_EXECUTED_ACTION_UIDS = "executed_action_uids"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != ENTITY_STAT_INTENT_COMMAND_TYPE:
            return False

        action_uid = f"{command.tick}:{command_index}"
        op = command.params.get("op")
        key = command.params.get("key")
        duration_ticks = command.params.get("duration_ticks")
        target_entity_id = command.params.get("target_entity_id", command.entity_id)

        if not isinstance(target_entity_id, str) or not target_entity_id:
            target_entity_id = command.entity_id

        if not isinstance(op, str) or op not in {"set", "remove"}:
            self._append_outcome(
                sim,
                tick=command.tick,
                action_uid=action_uid,
                entity_id=target_entity_id,
                op=op if isinstance(op, str) else "",
                key=key if isinstance(key, str) else "",
                outcome="invalid_params",
                details={"reason": "invalid_op"},
            )
            return True

        if not isinstance(key, str) or not key:
            self._append_outcome(
                sim,
                tick=command.tick,
                action_uid=action_uid,
                entity_id=target_entity_id,
                op=op,
                key=key if isinstance(key, str) else "",
                outcome="invalid_params",
                details={"reason": "invalid_key"},
            )
            return True

        if not isinstance(duration_ticks, int) or duration_ticks < 0:
            self._append_outcome(
                sim,
                tick=command.tick,
                action_uid=action_uid,
                entity_id=target_entity_id,
                op=op,
                key=key,
                outcome="invalid_params",
                details={"reason": "invalid_duration_ticks"},
            )
            return True

        if op == "set" and "value" not in command.params:
            self._append_outcome(
                sim,
                tick=command.tick,
                action_uid=action_uid,
                entity_id=target_entity_id,
                op=op,
                key=key,
                outcome="invalid_params",
                details={"reason": "missing_value"},
            )
            return True

        sim.schedule_event_at(
            tick=command.tick + duration_ticks,
            event_type=ENTITY_STAT_EXECUTE_EVENT_TYPE,
            params={
                "action_uid": action_uid,
                "entity_id": target_entity_id,
                "op": op,
                "key": key,
                "value": copy.deepcopy(command.params.get("value")),
            },
        )
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != ENTITY_STAT_EXECUTE_EVENT_TYPE:
            return

        action_uid = str(event.params.get("action_uid", ""))
        entity_id_raw = event.params.get("entity_id")
        op = event.params.get("op")
        key = event.params.get("key")
        value = event.params.get("value")

        entity_id = str(entity_id_raw) if isinstance(entity_id_raw, str) else ""
        op_value = str(op) if isinstance(op, str) else ""
        key_value = str(key) if isinstance(key, str) else ""

        state = self._rules_state(sim)
        executed = set(state[self._STATE_EXECUTED_ACTION_UIDS])

        if action_uid in executed:
            self._append_outcome(
                sim,
                tick=event.tick,
                action_uid=action_uid,
                entity_id=entity_id,
                op=op_value,
                key=key_value,
                outcome="already_applied",
                details={},
            )
            return

        if (
            not action_uid
            or op_value not in {"set", "remove"}
            or not key_value
            or (op_value == "set" and "value" not in event.params)
        ):
            self._append_outcome(
                sim,
                tick=event.tick,
                action_uid=action_uid,
                entity_id=entity_id,
                op=op_value,
                key=key_value,
                outcome="invalid_params",
                details={"reason": "invalid_execute_payload"},
            )
            if action_uid:
                executed.add(action_uid)
                state[self._STATE_EXECUTED_ACTION_UIDS] = sorted(executed)
                sim.set_rules_state(self.name, state)
            return

        if entity_id not in sim.state.entities:
            self._append_outcome(
                sim,
                tick=event.tick,
                action_uid=action_uid,
                entity_id=entity_id,
                op=op_value,
                key=key_value,
                outcome="unknown_entity",
                details={},
            )
            executed.add(action_uid)
            state[self._STATE_EXECUTED_ACTION_UIDS] = sorted(executed)
            sim.set_rules_state(self.name, state)
            return

        entity = sim.state.entities[entity_id]
        try:
            updated_stats = sim.apply_stat_patch(
                entity.stats,
                {
                    "op": op_value,
                    "key": key_value,
                    "value": copy.deepcopy(value),
                },
            )
        except ValueError as exc:
            self._append_outcome(
                sim,
                tick=event.tick,
                action_uid=action_uid,
                entity_id=entity_id,
                op=op_value,
                key=key_value,
                outcome="invalid_params",
                details={"reason": str(exc)},
            )
            executed.add(action_uid)
            state[self._STATE_EXECUTED_ACTION_UIDS] = sorted(executed)
            sim.set_rules_state(self.name, state)
            return

        entity.stats = updated_stats
        executed.add(action_uid)
        state[self._STATE_EXECUTED_ACTION_UIDS] = sorted(executed)
        sim.set_rules_state(self.name, state)
        self._append_outcome(
            sim,
            tick=event.tick,
            action_uid=action_uid,
            entity_id=entity_id,
            op=op_value,
            key=key_value,
            outcome="applied",
            details={},
        )

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        executed = state.get(self._STATE_EXECUTED_ACTION_UIDS, [])
        if not isinstance(executed, list):
            raise ValueError("entity_stats.rules_state.executed_action_uids must be a list")
        return {self._STATE_EXECUTED_ACTION_UIDS: sorted({str(uid) for uid in executed if isinstance(uid, str) and uid})}

    def _append_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        action_uid: str,
        entity_id: str | None,
        op: str,
        key: str,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=ENTITY_STAT_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "action_uid": action_uid,
                "entity_id": entity_id,
                "op": op,
                "key": key,
                "outcome": outcome,
                "details": copy.deepcopy(details),
            },
        )
