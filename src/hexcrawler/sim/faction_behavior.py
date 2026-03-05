from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hexcrawler.sim.beliefs import (
    BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
    BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE,
)
from hexcrawler.sim.rules import RuleModule

if TYPE_CHECKING:
    from hexcrawler.sim.core import SimEvent, Simulation

FACTION_BEHAVIOR_REQUEST_EVENT_TYPE = "faction_behavior_request"
FACTION_BEHAVIOR_REQUEST_BUDGET_EXHAUSTED_EVENT_TYPE = "faction_behavior_request_budget_exhausted"
FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE = "faction_behavior_action_stub"
FACTION_BEHAVIOR_ACTION_BUDGET_EXHAUSTED_EVENT_TYPE = "faction_behavior_action_budget_exhausted"
FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE = "faction_behavior_action_execute_request"
FACTION_BEHAVIOR_ACTION_EXECUTE_IGNORED_EVENT_TYPE = "faction_behavior_action_execute_ignored"
FACTION_BEHAVIOR_ACTION_EXECUTE_BUDGET_EXHAUSTED_EVENT_TYPE = "faction_behavior_action_execute_budget_exhausted"

MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK = 8
MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK = 8
MAX_FACTION_BEHAVIOR_EXECUTE_REQUESTS_PER_TICK = 8
MAX_APPLIED_SOURCE_EVENT_IDS = 512
MAX_APPLIED_ACTION_UIDS = 1024


class FactionBehaviorReactionIntegrationModule(RuleModule):
    """Slice 4A deterministic reaction->behavior request integration seam (campaign+local role-agnostic)."""

    name = "faction_behavior_integration"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type not in {
            BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE,
            BELIEF_REACTION_INVESTIGATE_UNKNOWN_ACTOR_EVENT_TYPE,
        }:
            return

        tick = int(event.tick)
        state = self._normalized_state(sim=sim)
        source_event_id = str(event.event_id)
        applied_source_event_ids = set(state["applied_source_event_ids"])
        if source_event_id in applied_source_event_ids:
            sim.set_rules_state(self.name, state)
            return

        pending = [
            item
            for item in state["pending_requests"]
            if int(item.get("tick", -1)) == tick
        ]
        if any(str(item.get("source_event_id", "")) == source_event_id for item in pending):
            sim.set_rules_state(self.name, state)
            return

        faction_id = str(event.params.get("faction_id", "")).strip().lower()
        belief_id = str(event.params.get("belief_id", "")).strip()
        if not faction_id or not belief_id:
            sim.set_rules_state(self.name, state)
            return

        request_type = (
            "investigate_contested"
            if event.event_type == BELIEF_REACTION_INVESTIGATE_CONTESTED_EVENT_TYPE
            else "investigate_unknown_actor"
        )
        pending.append(
            {
                "tick": tick,
                "source_event_id": source_event_id,
                "faction_id": faction_id,
                "request_type": request_type,
                "belief_id": belief_id,
                "base_key": self._normalize_base_key(event.params.get("base_key")),
                "subject": self._resolve_subject(sim=sim, event=event, faction_id=faction_id, belief_id=belief_id),
                "priority": 2 if request_type == "investigate_contested" else 1,
                "reason": "belief_reaction_hook",
            }
        )
        state["pending_requests"] = pending
        sim.set_rules_state(self.name, state)

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        state = self._normalized_state(sim=sim)
        pending = [item for item in state["pending_requests"] if int(item.get("tick", -1)) == tick]
        if not pending:
            sim.set_rules_state(self.name, state)
            return

        pending = sorted(
            pending,
            key=lambda item: (
                str(item.get("faction_id", "")),
                str(item.get("belief_id", "")),
                str(item.get("request_type", "")),
                str(item.get("source_event_id", "")),
            ),
        )

        remaining_pending = [item for item in state["pending_requests"] if int(item.get("tick", -1)) != tick]
        applied = list(state["applied_source_event_ids"])
        applied_set = set(applied)
        emitted = 0

        for item in pending:
            if emitted >= MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK:
                sim.schedule_event_at(
                    tick=tick + 1,
                    event_type=FACTION_BEHAVIOR_REQUEST_BUDGET_EXHAUSTED_EVENT_TYPE,
                    params={
                        "tick": tick,
                        "max_requests_per_tick": MAX_FACTION_BEHAVIOR_REQUESTS_PER_TICK,
                    },
                )
                break

            source_event_id = str(item.get("source_event_id", ""))
            if not source_event_id or source_event_id in applied_set:
                continue

            request_payload = {
                "tick": int(item["tick"]),
                "source_event_id": source_event_id,
                "faction_id": str(item["faction_id"]),
                "request_type": str(item["request_type"]),
                "belief_id": str(item["belief_id"]),
                "base_key": self._normalize_base_key(item.get("base_key")),
                "subject": dict(item["subject"]) if isinstance(item.get("subject"), dict) else {},
                "priority": int(item["priority"]),
                "reason": str(item["reason"]),
            }
            sim.schedule_event_at(
                tick=tick + 1,
                event_type=FACTION_BEHAVIOR_REQUEST_EVENT_TYPE,
                params=request_payload,
            )
            emitted += 1
            applied.append(source_event_id)
            applied_set.add(source_event_id)

        if len(applied) > MAX_APPLIED_SOURCE_EVENT_IDS:
            applied = applied[-MAX_APPLIED_SOURCE_EVENT_IDS:]
        state["applied_source_event_ids"] = applied
        state["pending_requests"] = remaining_pending
        state["last_processed_tick"] = tick
        sim.set_rules_state(self.name, state)

    def _resolve_subject(
        self,
        *,
        sim: Simulation,
        event: SimEvent,
        faction_id: str,
        belief_id: str,
    ) -> dict[str, Any]:
        subject = event.params.get("subject")
        if isinstance(subject, dict):
            return dict(subject)

        faction_state = sim.state.world.faction_beliefs.get(faction_id, {})
        if not isinstance(faction_state, dict):
            return {}
        belief_records = faction_state.get("belief_records", {})
        if not isinstance(belief_records, dict):
            return {}
        belief = belief_records.get(belief_id, {})
        if not isinstance(belief, dict):
            return {}
        belief_subject = belief.get("subject")
        if not isinstance(belief_subject, dict):
            return {}
        return dict(belief_subject)

    @staticmethod
    def _normalize_base_key(value: Any) -> str | None:
        if value is None:
            return None
        token = str(value)
        return token if token else None

    def _normalized_state(self, *, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)

        applied_source_event_ids: list[str] = []
        raw_applied = state.get("applied_source_event_ids", [])
        if isinstance(raw_applied, list):
            for value in raw_applied:
                token = str(value)
                if token and token not in applied_source_event_ids:
                    applied_source_event_ids.append(token)
        if len(applied_source_event_ids) > MAX_APPLIED_SOURCE_EVENT_IDS:
            applied_source_event_ids = applied_source_event_ids[-MAX_APPLIED_SOURCE_EVENT_IDS:]

        pending_requests: list[dict[str, Any]] = []
        raw_pending = state.get("pending_requests", [])
        if isinstance(raw_pending, list):
            for item in raw_pending:
                if not isinstance(item, dict):
                    continue
                tick = item.get("tick")
                if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                    continue
                source_event_id = str(item.get("source_event_id", ""))
                faction_id = str(item.get("faction_id", "")).strip().lower()
                request_type = str(item.get("request_type", ""))
                belief_id = str(item.get("belief_id", "")).strip()
                if not source_event_id or not faction_id or not belief_id:
                    continue
                if request_type not in {"investigate_contested", "investigate_unknown_actor"}:
                    continue
                pending_requests.append(
                    {
                        "tick": tick,
                        "source_event_id": source_event_id,
                        "faction_id": faction_id,
                        "request_type": request_type,
                        "belief_id": belief_id,
                        "base_key": self._normalize_base_key(item.get("base_key")),
                        "subject": dict(item["subject"]) if isinstance(item.get("subject"), dict) else {},
                        "priority": int(item.get("priority", 1)) if isinstance(item.get("priority", 1), int) else 1,
                        "reason": str(item.get("reason", "belief_reaction_hook")),
                    }
                )

        return {
            "applied_source_event_ids": applied_source_event_ids,
            "pending_requests": pending_requests,
            "last_processed_tick": int(state.get("last_processed_tick", -1)) if isinstance(state.get("last_processed_tick", -1), int) else -1,
        }


class FactionBehaviorPlannerModule(RuleModule):
    """Slice 4B deterministic behavior-planning grammar seam (campaign+local role-agnostic).

    Single emission boundary: requests are staged only in ``on_event_executed`` and emitted
    only during ``on_tick_end`` flush for that tick, so there is exactly one deterministic
    emission path for ``pending_action_stubs`` across replay/save-load boundaries.
    """

    name = "faction_behavior_planner"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != FACTION_BEHAVIOR_REQUEST_EVENT_TYPE:
            return

        tick = int(event.tick)
        state = self._normalized_state(sim=sim)
        source_request_event_id = str(event.event_id)
        applied_request_event_ids = set(state["applied_request_event_ids"])
        if source_request_event_id in applied_request_event_ids:
            sim.set_rules_state(self.name, state)
            return

        pending = [
            item
            for item in state["pending_action_stubs"]
            if int(item.get("tick", -1)) == tick
        ]
        if any(str(item.get("source_request_event_id", "")) == source_request_event_id for item in pending):
            sim.set_rules_state(self.name, state)
            return

        faction_id = str(event.params.get("faction_id", "")).strip().lower()
        belief_id = str(event.params.get("belief_id", "")).strip()
        request_type = str(event.params.get("request_type", "")).strip()
        if not faction_id or not belief_id or request_type not in {"investigate_contested", "investigate_unknown_actor"}:
            sim.set_rules_state(self.name, state)
            return

        pending.append(
            {
                "tick": tick,
                "source_request_event_id": source_request_event_id,
                "faction_id": faction_id,
                "request_type": request_type,
                "belief_id": belief_id,
                "base_key": self._normalize_base_key(event.params.get("base_key")),
                "subject": dict(event.params["subject"]) if isinstance(event.params.get("subject"), dict) else {},
                "reason": self._resolve_reason_token(request_type=request_type),
                "priority": self._resolve_priority(event.params.get("priority"), request_type=request_type),
            }
        )
        state["pending_action_stubs"] = pending
        sim.set_rules_state(self.name, state)

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        state = self._normalized_state(sim=sim)
        pending = [item for item in state["pending_action_stubs"] if int(item.get("tick", -1)) == tick]
        if not pending:
            sim.set_rules_state(self.name, state)
            return

        pending = sorted(
            pending,
            key=lambda item: (
                str(item.get("faction_id", "")),
                str(item.get("belief_id", "")),
                str(item.get("request_type", "")),
                str(item.get("source_request_event_id", "")),
            ),
        )

        remaining_pending = [item for item in state["pending_action_stubs"] if int(item.get("tick", -1)) != tick]
        applied = list(state["applied_request_event_ids"])
        applied_set = set(applied)
        emitted = 0

        for item in pending:
            if emitted >= MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK:
                sim.schedule_event_at(
                    tick=tick + 1,
                    event_type=FACTION_BEHAVIOR_ACTION_BUDGET_EXHAUSTED_EVENT_TYPE,
                    params={
                        "tick": tick,
                        "max_actions_per_tick": MAX_FACTION_BEHAVIOR_ACTIONS_PER_TICK,
                    },
                )
                break

            source_request_event_id = str(item.get("source_request_event_id", ""))
            if not source_request_event_id or source_request_event_id in applied_set:
                continue

            action_stub_payload = {
                "tick": int(item["tick"]),
                "source_request_event_id": source_request_event_id,
                "faction_id": str(item["faction_id"]),
                "request_type": str(item["request_type"]),
                "belief_id": str(item["belief_id"]),
                "base_key": self._normalize_base_key(item.get("base_key")),
                "subject": dict(item["subject"]) if isinstance(item.get("subject"), dict) else {},
                "actions": [
                    {
                        "action_type": "investigate_belief",
                        "template_id": "belief_investigation",
                        "params": {
                            "belief_id": str(item["belief_id"]),
                            "request_type": str(item["request_type"]),
                            "reason": str(item["reason"]),
                            "priority": int(item["priority"]),
                        },
                    }
                ],
            }
            sim.schedule_event_at(
                tick=tick + 1,
                event_type=FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE,
                params=action_stub_payload,
            )
            emitted += 1
            applied.append(source_request_event_id)
            applied_set.add(source_request_event_id)

        if len(applied) > MAX_APPLIED_SOURCE_EVENT_IDS:
            applied = applied[-MAX_APPLIED_SOURCE_EVENT_IDS:]
        state["applied_request_event_ids"] = applied
        state["pending_action_stubs"] = remaining_pending
        state["last_processed_tick"] = tick
        sim.set_rules_state(self.name, state)

    @staticmethod
    def _resolve_reason_token(*, request_type: str) -> str:
        if request_type == "investigate_contested":
            return "contested_belief"
        return "unknown_actor"

    @staticmethod
    def _resolve_priority(priority: Any, *, request_type: str) -> int:
        if isinstance(priority, int) and not isinstance(priority, bool):
            return priority
        return 2 if request_type == "investigate_contested" else 1

    @staticmethod
    def _normalize_base_key(value: Any) -> str | None:
        if value is None:
            return None
        token = str(value)
        return token if token else None

    def _normalized_state(self, *, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)

        applied_request_event_ids: list[str] = []
        raw_applied = state.get("applied_request_event_ids", [])
        if isinstance(raw_applied, list):
            for value in raw_applied:
                token = str(value)
                if token and token not in applied_request_event_ids:
                    applied_request_event_ids.append(token)
        if len(applied_request_event_ids) > MAX_APPLIED_SOURCE_EVENT_IDS:
            applied_request_event_ids = applied_request_event_ids[-MAX_APPLIED_SOURCE_EVENT_IDS:]

        pending_action_stubs: list[dict[str, Any]] = []
        raw_pending = state.get("pending_action_stubs", [])
        if isinstance(raw_pending, list):
            for item in raw_pending:
                if not isinstance(item, dict):
                    continue
                tick = item.get("tick")
                if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                    continue
                source_request_event_id = str(item.get("source_request_event_id", ""))
                faction_id = str(item.get("faction_id", "")).strip().lower()
                request_type = str(item.get("request_type", ""))
                belief_id = str(item.get("belief_id", "")).strip()
                if not source_request_event_id or not faction_id or not belief_id:
                    continue
                if request_type not in {"investigate_contested", "investigate_unknown_actor"}:
                    continue
                pending_action_stubs.append(
                    {
                        "tick": tick,
                        "source_request_event_id": source_request_event_id,
                        "faction_id": faction_id,
                        "request_type": request_type,
                        "belief_id": belief_id,
                        "base_key": self._normalize_base_key(item.get("base_key")),
                        "subject": dict(item["subject"]) if isinstance(item.get("subject"), dict) else {},
                        "reason": str(item.get("reason", self._resolve_reason_token(request_type=request_type))),
                        "priority": self._resolve_priority(item.get("priority"), request_type=request_type),
                    }
                )

        return {
            "applied_request_event_ids": applied_request_event_ids,
            "pending_action_stubs": pending_action_stubs,
            "last_processed_tick": int(state.get("last_processed_tick", -1)) if isinstance(state.get("last_processed_tick", -1), int) else -1,
        }


class FactionBehaviorExecutionSeamModule(RuleModule):
    """Slice 4C deterministic behavior grammar->execution-request seam (campaign+local role-agnostic).

    Single emission boundary: action execution requests are staged only in ``on_event_executed`` and emitted
    only during ``on_tick_end`` flush for that tick, guaranteeing one deterministic emission path.
    """

    name = "faction_behavior_execution"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != FACTION_BEHAVIOR_ACTION_STUB_EVENT_TYPE:
            return

        tick = int(event.tick)
        source_action_stub_event_id = str(event.event_id)
        if not source_action_stub_event_id:
            return

        state = self._normalized_state(sim=sim)
        pending = list(state["pending_execute_requests"])
        pending_action_uids = {str(item.get("action_uid", "")) for item in pending}
        applied_action_uids = set(state["applied_action_uids"])

        faction_id = str(event.params.get("faction_id", "")).strip().lower()
        actions = event.params.get("actions", [])
        if not faction_id or not isinstance(actions, list):
            sim.set_rules_state(self.name, state)
            return

        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            action_uid = f"{source_action_stub_event_id}:{index}"
            if action_uid in applied_action_uids or action_uid in pending_action_uids:
                continue

            action_type = str(action.get("action_type", "")).strip()
            template_id = str(action.get("template_id", "")).strip()
            params = action.get("params", {})
            belief_id = ""
            request_type = ""
            reason = ""
            priority = 1
            if isinstance(params, dict):
                belief_id = str(params.get("belief_id", event.params.get("belief_id", ""))).strip()
                request_type = str(params.get("request_type", event.params.get("request_type", ""))).strip()
                reason = str(params.get("reason", "")).strip()
                raw_priority = params.get("priority", 1)
                if isinstance(raw_priority, int) and not isinstance(raw_priority, bool):
                    priority = raw_priority

            pending.append(
                {
                    "tick": tick,
                    "source_action_stub_event_id": source_action_stub_event_id,
                    "action_uid": action_uid,
                    "faction_id": faction_id,
                    "action_type": action_type,
                    "template_id": template_id,
                    "belief_id": belief_id,
                    "request_type": request_type,
                    "reason": reason,
                    "priority": priority,
                }
            )
            pending_action_uids.add(action_uid)

        state["pending_execute_requests"] = pending
        sim.set_rules_state(self.name, state)

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        state = self._normalized_state(sim=sim)
        pending_for_tick = [item for item in state["pending_execute_requests"] if int(item.get("tick", -1)) == tick]
        if not pending_for_tick:
            sim.set_rules_state(self.name, state)
            return

        pending_for_tick = sorted(
            pending_for_tick,
            key=lambda item: (
                str(item.get("faction_id", "")),
                str(item.get("belief_id", "")),
                str(item.get("action_type", "")),
                str(item.get("action_uid", "")),
            ),
        )

        remaining_pending = [item for item in state["pending_execute_requests"] if int(item.get("tick", -1)) != tick]
        applied = list(state["applied_action_uids"])
        applied_set = set(applied)
        emitted = 0

        for item in pending_for_tick:
            action_uid = str(item.get("action_uid", ""))
            if not action_uid or action_uid in applied_set:
                continue

            if emitted >= MAX_FACTION_BEHAVIOR_EXECUTE_REQUESTS_PER_TICK:
                sim.schedule_event_at(
                    tick=tick + 1,
                    event_type=FACTION_BEHAVIOR_ACTION_EXECUTE_BUDGET_EXHAUSTED_EVENT_TYPE,
                    params={
                        "tick": tick,
                        "max_execute_requests_per_tick": MAX_FACTION_BEHAVIOR_EXECUTE_REQUESTS_PER_TICK,
                    },
                )
                break

            request_payload = {
                "tick": int(item["tick"]),
                "source_action_stub_event_id": str(item["source_action_stub_event_id"]),
                "action_uid": action_uid,
                "faction_id": str(item["faction_id"]),
                "action_type": str(item["action_type"]),
                "template_id": str(item["template_id"]),
                "belief_id": str(item["belief_id"]),
                "request_type": str(item["request_type"]),
                "reason": str(item["reason"]),
                "priority": int(item["priority"]),
            }

            is_supported = (
                request_payload["action_type"] == "investigate_belief"
                and request_payload["template_id"] == "belief_investigation"
            )
            if not is_supported:
                sim.schedule_event_at(
                    tick=tick + 1,
                    event_type=FACTION_BEHAVIOR_ACTION_EXECUTE_IGNORED_EVENT_TYPE,
                    params={
                        "tick": tick,
                        "action_uid": action_uid,
                        "faction_id": request_payload["faction_id"],
                        "action_type": request_payload["action_type"],
                        "template_id": request_payload["template_id"],
                        "reason": "unsupported_action",
                    },
                )
                applied.append(action_uid)
                applied_set.add(action_uid)
                continue

            sim.schedule_event_at(
                tick=tick + 1,
                event_type=FACTION_BEHAVIOR_ACTION_EXECUTE_REQUEST_EVENT_TYPE,
                params=request_payload,
            )
            emitted += 1
            applied.append(action_uid)
            applied_set.add(action_uid)

        if len(applied) > MAX_APPLIED_ACTION_UIDS:
            applied = applied[-MAX_APPLIED_ACTION_UIDS:]
        state["applied_action_uids"] = applied
        state["pending_execute_requests"] = remaining_pending
        state["last_processed_tick"] = tick
        sim.set_rules_state(self.name, state)

    def _normalized_state(self, *, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)

        applied_action_uids: list[str] = []
        raw_applied = state.get("applied_action_uids", [])
        if isinstance(raw_applied, list):
            for value in raw_applied:
                token = str(value)
                if token and token not in applied_action_uids:
                    applied_action_uids.append(token)
        if len(applied_action_uids) > MAX_APPLIED_ACTION_UIDS:
            applied_action_uids = applied_action_uids[-MAX_APPLIED_ACTION_UIDS:]

        pending_execute_requests: list[dict[str, Any]] = []
        raw_pending = state.get("pending_execute_requests", [])
        if isinstance(raw_pending, list):
            for item in raw_pending:
                if not isinstance(item, dict):
                    continue
                tick = item.get("tick")
                if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                    continue
                action_uid = str(item.get("action_uid", "")).strip()
                source_action_stub_event_id = str(item.get("source_action_stub_event_id", "")).strip()
                faction_id = str(item.get("faction_id", "")).strip().lower()
                if not action_uid or not source_action_stub_event_id or not faction_id:
                    continue

                raw_priority = item.get("priority", 1)
                priority = raw_priority if isinstance(raw_priority, int) and not isinstance(raw_priority, bool) else 1
                pending_execute_requests.append(
                    {
                        "tick": tick,
                        "source_action_stub_event_id": source_action_stub_event_id,
                        "action_uid": action_uid,
                        "faction_id": faction_id,
                        "action_type": str(item.get("action_type", "")).strip(),
                        "template_id": str(item.get("template_id", "")).strip(),
                        "belief_id": str(item.get("belief_id", "")).strip(),
                        "request_type": str(item.get("request_type", "")).strip(),
                        "reason": str(item.get("reason", "")).strip(),
                        "priority": priority,
                    }
                )

        return {
            "applied_action_uids": applied_action_uids,
            "pending_execute_requests": pending_execute_requests,
            "last_processed_tick": int(state.get("last_processed_tick", -1)) if isinstance(state.get("last_processed_tick", -1), int) else -1,
        }
