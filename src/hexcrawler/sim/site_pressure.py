from __future__ import annotations

from typing import Any

from hexcrawler.sim.encounters import CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE
from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.rules import RuleModule

SITE_PRESSURE_APPLY_EVENT_TYPE = "site_pressure_apply"
SITE_PRESSURE_OUTCOME_EVENT_TYPE = "site_pressure_outcome"
SITE_PRESSURE_BRIDGE_OUTCOME_EVENT_TYPE = "site_pressure_bridge_outcome"
SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE = "site_pressure_summary_check"
SITE_PRESSURE_SUMMARY_OUTCOME_EVENT_TYPE = "site_pressure_summary_outcome"

SITE_PRESSURE_SUMMARY_THRESHOLD = 5

MAX_SITE_PRESSURE_BRIDGE_LEDGER = 512


class SitePressureBridgeModule(RuleModule):
    """Minimal deterministic bridge from explicit site claim events into site pressure."""

    name = "site_pressure_bridge"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE:
            return

        state = self._rules_state(sim)
        processed = set(state["processed_source_event_ids"])
        if event.event_id in processed:
            self._schedule_bridge_outcome(
                sim,
                tick=event.tick,
                source_event_id=event.event_id,
                outcome="skipped_duplicate",
                details={},
            )
            return

        site_id = self._site_id_from_site_key(event.params.get("site_key"))
        group_id = self._optional_non_empty_string(event.params.get("group_id"))
        if site_id is None or group_id is None:
            self._schedule_bridge_outcome(
                sim,
                tick=event.tick,
                source_event_id=event.event_id,
                outcome="skipped_invalid_context",
                details={
                    "site_id": site_id,
                    "group_id": group_id,
                },
            )
            return

        processed.add(event.event_id)
        ordered = sorted(processed)
        if len(ordered) > MAX_SITE_PRESSURE_BRIDGE_LEDGER:
            ordered = ordered[-MAX_SITE_PRESSURE_BRIDGE_LEDGER:]
        sim.set_rules_state(self.name, {"processed_source_event_ids": ordered})

        sim.schedule_event_at(
            tick=event.tick,
            event_type=SITE_PRESSURE_APPLY_EVENT_TYPE,
            params={
                "site_id": site_id,
                "faction_id": f"group:{group_id}",
                "pressure_type": "claim_activity",
                "strength": 1,
                "source_event_id": event.event_id,
                "tick": event.tick,
            },
        )
        self._schedule_bridge_outcome(
            sim,
            tick=event.tick,
            source_event_id=event.event_id,
            outcome="emitted",
            details={"site_id": site_id, "faction_id": f"group:{group_id}"},
        )

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw = state.get("processed_source_event_ids", [])
        if not isinstance(raw, list):
            raise ValueError("site_pressure_bridge.processed_source_event_ids must be a list")
        normalized = sorted({str(item) for item in raw if isinstance(item, str) and item})
        if len(normalized) > MAX_SITE_PRESSURE_BRIDGE_LEDGER:
            normalized = normalized[-MAX_SITE_PRESSURE_BRIDGE_LEDGER:]
        state["processed_source_event_ids"] = normalized
        sim.set_rules_state(self.name, state)
        return state

    def _schedule_bridge_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        source_event_id: str,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=SITE_PRESSURE_BRIDGE_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "source_event_id": source_event_id,
                "outcome": outcome,
                "details": dict(details),
            },
        )

    @staticmethod
    def _optional_non_empty_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped if stripped else None

    def _site_id_from_site_key(self, value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        template_id = self._optional_non_empty_string(value.get("template_id"))
        if template_id is None or not template_id.startswith("site:"):
            return None
        site_id = template_id[len("site:") :]
        return site_id if site_id else None


class SitePressureMutationModule(RuleModule):
    """Deterministic campaign-role substrate seam for site pressure mutation events."""

    name = "site_pressure_mutation"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != SITE_PRESSURE_APPLY_EVENT_TYPE:
            return

        normalized_payload, invalid_reason = self._normalize_apply_payload(event)
        if invalid_reason is not None:
            self._schedule_outcome(
                sim,
                tick=event.tick,
                source_event_id=event.event_id,
                outcome="invalid_payload" if invalid_reason != "invalid_strength" else "invalid_strength",
                details={"reason": invalid_reason},
                payload=normalized_payload,
            )
            return

        site_id = str(normalized_payload["site_id"])
        if site_id not in sim.state.world.sites:
            self._schedule_outcome(
                sim,
                tick=event.tick,
                source_event_id=event.event_id,
                outcome="unknown_site",
                details={},
                payload=normalized_payload,
            )
            return

        sim.state.world.add_site_pressure(
            site_id=site_id,
            faction_id=str(normalized_payload["faction_id"]),
            pressure_type=str(normalized_payload["pressure_type"]),
            strength=int(normalized_payload["strength"]),
            source_event_id=(
                str(normalized_payload["source_event_id"])
                if normalized_payload.get("source_event_id") is not None
                else event.event_id
            ),
            tick=int(normalized_payload["tick"]),
        )
        self._schedule_outcome(
            sim,
            tick=event.tick,
            source_event_id=event.event_id,
            outcome="applied",
            details={},
            payload=normalized_payload,
        )

    def _schedule_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        source_event_id: str,
        outcome: str,
        details: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=SITE_PRESSURE_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "source_event_id": source_event_id,
                "site_id": payload.get("site_id"),
                "faction_id": payload.get("faction_id"),
                "pressure_type": payload.get("pressure_type"),
                "strength": payload.get("strength"),
                "outcome": outcome,
                "details": dict(details),
            },
        )

    def _normalize_apply_payload(self, event: SimEvent) -> tuple[dict[str, Any], str | None]:
        params = event.params
        payload: dict[str, Any] = {
            "site_id": params.get("site_id"),
            "faction_id": params.get("faction_id"),
            "pressure_type": params.get("pressure_type"),
            "strength": params.get("strength"),
            "source_event_id": params.get("source_event_id"),
            "tick": params.get("tick", event.tick),
        }

        for key in ("site_id", "faction_id", "pressure_type"):
            value = payload[key]
            if not isinstance(value, str) or not value:
                return payload, f"invalid_{key}"

        strength = payload["strength"]
        if isinstance(strength, bool) or not isinstance(strength, int):
            return payload, "invalid_strength"
        if strength <= 0:
            return payload, "invalid_strength"

        source_event_id = payload.get("source_event_id")
        if source_event_id is not None and (not isinstance(source_event_id, str) or not source_event_id):
            return payload, "invalid_source_event_id"

        record_tick = payload["tick"]
        if isinstance(record_tick, bool) or not isinstance(record_tick, int) or record_tick < 0:
            return payload, "invalid_tick"

        return payload, None


class SitePressureSummaryConsumerModule(RuleModule):
    """Deterministic downstream seam that evaluates a single-site pressure summary on explicit checks."""

    name = "site_pressure_summary_consumer"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != SITE_PRESSURE_SUMMARY_CHECK_EVENT_TYPE:
            return

        site_id = event.params.get("site_id")
        if not isinstance(site_id, str) or not site_id:
            self._schedule_outcome(
                sim,
                tick=event.tick,
                source_event_id=event.event_id,
                status="invalid_site_id",
                summary={},
            )
            return

        if site_id not in sim.state.world.sites:
            self._schedule_outcome(
                sim,
                tick=event.tick,
                source_event_id=event.event_id,
                status="unknown_site",
                summary={"site_id": site_id},
            )
            return

        summary = sim.state.world.get_site_pressure_summary(site_id)
        status = "threshold_met" if summary.total_pressure >= SITE_PRESSURE_SUMMARY_THRESHOLD else "below_threshold"

        self._schedule_outcome(
            sim,
            tick=event.tick,
            source_event_id=event.event_id,
            status=status,
            summary={
                "site_id": site_id,
                "threshold": SITE_PRESSURE_SUMMARY_THRESHOLD,
                "total_pressure": summary.total_pressure,
                "dominant_faction_id": summary.dominant_faction_id,
                "dominant_strength": summary.dominant_strength,
                "record_count": summary.record_count,
            },
        )

    def _schedule_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        source_event_id: str,
        status: str,
        summary: dict[str, Any],
    ) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=SITE_PRESSURE_SUMMARY_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "source_event_id": source_event_id,
                "status": status,
                "summary": dict(summary),
            },
        )
