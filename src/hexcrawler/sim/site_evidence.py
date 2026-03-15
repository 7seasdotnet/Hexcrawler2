from __future__ import annotations

from typing import Any

from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.rules import RuleModule

SITE_EVIDENCE_APPLY_EVENT_TYPE = "site_evidence_apply"
SITE_EVIDENCE_OUTCOME_EVENT_TYPE = "site_evidence_outcome"


class SiteEvidenceMutationModule(RuleModule):
    """Deterministic campaign-role substrate seam for site evidence mutation events."""

    name = "site_evidence_mutation"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != SITE_EVIDENCE_APPLY_EVENT_TYPE:
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

        sim.state.world.add_site_evidence(
            site_id=site_id,
            evidence_type=str(normalized_payload["evidence_type"]),
            strength=int(normalized_payload["strength"]),
            faction_id=(
                str(normalized_payload["faction_id"])
                if normalized_payload.get("faction_id") is not None
                else None
            ),
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
            event_type=SITE_EVIDENCE_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "source_event_id": source_event_id,
                "site_id": payload.get("site_id"),
                "evidence_type": payload.get("evidence_type"),
                "strength": payload.get("strength"),
                "faction_id": payload.get("faction_id"),
                "outcome": outcome,
                "details": dict(details),
            },
        )

    def _normalize_apply_payload(self, event: SimEvent) -> tuple[dict[str, Any], str | None]:
        params = event.params
        payload: dict[str, Any] = {
            "site_id": params.get("site_id"),
            "evidence_type": params.get("evidence_type"),
            "strength": params.get("strength"),
            "faction_id": params.get("faction_id"),
            "source_event_id": params.get("source_event_id"),
            "tick": params.get("tick", event.tick),
        }

        for key in ("site_id", "evidence_type"):
            value = payload[key]
            if not isinstance(value, str) or not value:
                return payload, f"invalid_{key}"

        strength = payload["strength"]
        if isinstance(strength, bool) or not isinstance(strength, int):
            return payload, "invalid_strength"
        if strength <= 0:
            return payload, "invalid_strength"

        faction_id = payload.get("faction_id")
        if faction_id is not None and (not isinstance(faction_id, str) or not faction_id):
            return payload, "invalid_faction_id"

        source_event_id = payload.get("source_event_id")
        if source_event_id is not None and (not isinstance(source_event_id, str) or not source_event_id):
            return payload, "invalid_source_event_id"

        record_tick = payload["tick"]
        if isinstance(record_tick, bool) or not isinstance(record_tick, int) or record_tick < 0:
            return payload, "invalid_tick"

        return payload, None
