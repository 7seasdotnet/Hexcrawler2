from __future__ import annotations

import hashlib
from typing import Any

from hexcrawler.content.items import DEFAULT_ITEMS_PATH, load_items_json
from hexcrawler.content.supplies import DEFAULT_SUPPLY_PROFILES_PATH, SupplyConsumeDef, load_supply_profiles_json
from hexcrawler.sim.core import INVENTORY_OUTCOME_EVENT_TYPE, SimCommand, Simulation
from hexcrawler.sim.periodic import PeriodicScheduler
from hexcrawler.sim.rules import RuleModule

SUPPLY_OUTCOME_EVENT_TYPE = "supply_outcome"
SUPPLY_CONSUMPTION_TASK_PREFIX = "supply.consume"


class SupplyConsumptionModule(RuleModule):
    name = "supply_consumption"

    def __init__(self, *, profile_path: str = DEFAULT_SUPPLY_PROFILES_PATH) -> None:
        self._registry = load_supply_profiles_json(profile_path)
        self._known_item_ids = {item.item_id for item in load_items_json(DEFAULT_ITEMS_PATH).items}

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")

        sim.set_rules_state(self.name, self._rules_state(sim))
        profile_map = self._registry.by_id()

        for entity in sorted(sim.state.entities.values(), key=lambda current: current.entity_id):
            profile_id = entity.supply_profile_id
            if profile_id is None:
                continue
            profile = profile_map.get(profile_id)
            if profile is None:
                continue
            for consume in profile.consumes:
                task_name = self._task_name(entity_id=entity.entity_id, profile_id=profile_id, item_id=consume.item_id)
                scheduler.register_task(task_name=task_name, interval_ticks=consume.interval_ticks, start_tick=0)
                scheduler.set_task_callback(
                    task_name,
                    self._build_tick_callback(entity_id=entity.entity_id, consume=consume, task_name=task_name),
                )

    def _build_tick_callback(self, *, entity_id: str, consume: SupplyConsumeDef, task_name: str):
        def _on_periodic(sim: Simulation, tick: int) -> None:
            self._apply_consumption(sim=sim, tick=tick, entity_id=entity_id, consume=consume, task_name=task_name)

        return _on_periodic

    def _apply_consumption(
        self,
        *,
        sim: Simulation,
        tick: int,
        entity_id: str,
        consume: SupplyConsumeDef,
        task_name: str,
    ) -> None:
        entity = sim.state.entities.get(entity_id)
        if entity is None:
            return

        state = self._rules_state(sim)
        applied_action_uids = set(state.get("applied_action_uids", []))
        action_uid = self._action_uid(tick=tick, task_name=task_name)

        if action_uid in applied_action_uids:
            self._append_supply_outcome(
                sim,
                tick=tick,
                entity_id=entity_id,
                item_id=consume.item_id,
                quantity=consume.quantity,
                interval_ticks=consume.interval_ticks,
                action_uid=action_uid,
                outcome="already_applied",
                remaining=None,
            )
            return

        if consume.item_id not in self._known_item_ids:
            self._append_supply_outcome(
                sim,
                tick=tick,
                entity_id=entity_id,
                item_id=consume.item_id,
                quantity=consume.quantity,
                interval_ticks=consume.interval_ticks,
                action_uid=action_uid,
                outcome="unknown_item",
                remaining=None,
            )
            return

        container_id = entity.inventory_container_id
        if container_id is None or container_id not in sim.state.world.containers:
            self._append_supply_outcome(
                sim,
                tick=tick,
                entity_id=entity_id,
                item_id=consume.item_id,
                quantity=consume.quantity,
                interval_ticks=consume.interval_ticks,
                action_uid=action_uid,
                outcome="no_inventory_container",
                remaining=None,
            )
            return

        command = SimCommand(
            tick=tick,
            entity_id=entity_id,
            command_type="inventory_intent",
            params={
                "src_container_id": container_id,
                "dst_container_id": None,
                "item_id": consume.item_id,
                "quantity": consume.quantity,
                "reason": "consume",
                "action_uid": action_uid,
            },
        )
        sim._execute_inventory_intent(command, command_index=0)

        inventory_outcome = "already_applied"
        for entry in reversed(sim.state.event_trace):
            if entry.get("event_type") != INVENTORY_OUTCOME_EVENT_TYPE:
                continue
            params = entry.get("params")
            if not isinstance(params, dict):
                continue
            if params.get("action_uid") != action_uid:
                continue
            raw = params.get("outcome")
            if raw == "applied":
                inventory_outcome = "consumed"
                applied_action_uids.add(action_uid)
            elif raw == "insufficient_quantity":
                inventory_outcome = "insufficient_supply"
                warnings = list(state.get("warnings", []))
                warnings.append(
                    {
                        "tick": tick,
                        "entity_id": entity_id,
                        "item_id": consume.item_id,
                        "action_uid": action_uid,
                    }
                )
                state["warnings"] = warnings[-200:]
            elif isinstance(raw, str):
                inventory_outcome = raw
            break

        state["applied_action_uids"] = sorted(applied_action_uids)
        sim.set_rules_state(self.name, state)

        remaining = int(sim.state.world.containers[container_id].items.get(consume.item_id, 0))
        self._append_supply_outcome(
            sim,
            tick=tick,
            entity_id=entity_id,
            item_id=consume.item_id,
            quantity=consume.quantity,
            interval_ticks=consume.interval_ticks,
            action_uid=action_uid,
            outcome=inventory_outcome,
            remaining=remaining,
        )

    def _append_supply_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        entity_id: str,
        item_id: str,
        quantity: int,
        interval_ticks: int,
        action_uid: str,
        outcome: str,
        remaining: int | None,
    ) -> None:
        params: dict[str, Any] = {
            "tick": tick,
            "entity_id": entity_id,
            "item_id": item_id,
            "quantity": quantity,
            "interval_ticks": interval_ticks,
            "action_uid": action_uid,
            "outcome": outcome,
        }
        if remaining is not None:
            params["remaining_quantity"] = remaining
        sim._append_event_trace_entry(
            {
                "tick": tick,
                "event_id": sim._trace_event_id_as_int(f"supply:{action_uid}:{outcome}"),
                "event_type": SUPPLY_OUTCOME_EVENT_TYPE,
                "params": params,
                "module_hooks_called": True,
            }
        )

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        existing = sim.get_rules_state(self.name)
        applied = existing.get("applied_action_uids", [])
        warnings = existing.get("warnings", [])
        existing["applied_action_uids"] = sorted({str(uid) for uid in applied})
        existing["warnings"] = [warning for warning in warnings if isinstance(warning, dict)]
        return existing

    def _task_name(self, *, entity_id: str, profile_id: str, item_id: str) -> str:
        return f"{SUPPLY_CONSUMPTION_TASK_PREFIX}:{entity_id}:{profile_id}:{item_id}"

    def _action_uid(self, *, tick: int, task_name: str) -> str:
        digest = hashlib.sha256(f"supply:{tick}:{task_name}".encode("utf-8")).hexdigest()[:16]
        return f"supply:{tick}:{digest}"
