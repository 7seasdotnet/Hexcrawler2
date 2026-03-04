from __future__ import annotations

import hashlib
import json
from typing import Any

from hexcrawler.sim.rules import RuleModule

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hexcrawler.sim.core import SimEvent, Simulation

BELIEF_CLAIM_EMITTED_EVENT_TYPE = "belief_claim_emitted"
BELIEF_SUBJECT_KINDS = {"player", "faction", "group", "unknown_actor"}
MAX_BELIEF_RECORDS_PER_FACTION = 512
MAX_BELIEF_CLAIM_KEY_LEN = 64
MAX_BELIEF_SUBJECT_ID_LEN = 64
MAX_BELIEF_EVIDENCE_COUNT = 1_000_000
MIN_BELIEF_CONFIDENCE = 0
MAX_BELIEF_CONFIDENCE = 100


def _normalize_string_id(value: Any, *, field_name: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(normalized) > max_len:
        raise ValueError(f"{field_name} exceeds max length {max_len}")
    return normalized


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def normalize_claim_key(value: Any) -> str:
    return _normalize_string_id(value, field_name="claim_key", max_len=MAX_BELIEF_CLAIM_KEY_LEN)


def normalize_faction_id(value: Any) -> str:
    return _normalize_string_id(value, field_name="faction_id", max_len=MAX_BELIEF_SUBJECT_ID_LEN)


def normalize_belief_subject(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise ValueError("belief subject must be an object")
    unknown = set(value) - {"kind", "id"}
    if unknown:
        raise ValueError(f"belief subject has unknown fields: {sorted(unknown)}")

    kind = value.get("kind")
    if kind not in BELIEF_SUBJECT_KINDS:
        raise ValueError(f"belief subject kind must be one of: {sorted(BELIEF_SUBJECT_KINDS)}")

    subject_id = value.get("id")
    if kind == "player":
        if subject_id is None:
            subject_id = "player"
        subject_id = _normalize_string_id(subject_id, field_name="belief subject.id", max_len=MAX_BELIEF_SUBJECT_ID_LEN)
    elif kind in {"faction", "group"}:
        subject_id = _normalize_string_id(subject_id, field_name="belief subject.id", max_len=MAX_BELIEF_SUBJECT_ID_LEN)
    else:
        if subject_id is None:
            subject_id = None
        else:
            subject_id = _normalize_string_id(subject_id, field_name="belief subject.id", max_len=MAX_BELIEF_SUBJECT_ID_LEN)

    return {"kind": str(kind), "id": subject_id}


def clamp_confidence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("belief confidence must be an integer")
    return _clamp_int(int(value), minimum=MIN_BELIEF_CONFIDENCE, maximum=MAX_BELIEF_CONFIDENCE)


def clamp_evidence_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("belief evidence_count must be an integer")
    return _clamp_int(int(value), minimum=0, maximum=MAX_BELIEF_EVIDENCE_COUNT)


def compute_belief_id(*, faction_id: str, subject: dict[str, str | None], claim_key: str) -> str:
    payload = {
        "faction_id": normalize_faction_id(faction_id),
        "subject": normalize_belief_subject(subject),
        "claim_key": normalize_claim_key(claim_key),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"belief:{digest[:32]}"


def normalize_belief_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("belief record must be an object")
    allowed = {
        "belief_id",
        "subject",
        "claim_key",
        "confidence",
        "first_seen_tick",
        "last_updated_tick",
        "evidence_count",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"belief record has unknown fields: {sorted(unknown)}")

    belief_id = value.get("belief_id")
    if not isinstance(belief_id, str) or not belief_id:
        raise ValueError("belief record belief_id must be a non-empty string")

    subject = normalize_belief_subject(value.get("subject"))
    claim_key = normalize_claim_key(value.get("claim_key"))

    first_seen_tick = value.get("first_seen_tick")
    if isinstance(first_seen_tick, bool) or not isinstance(first_seen_tick, int) or first_seen_tick < 0:
        raise ValueError("belief record first_seen_tick must be integer >= 0")

    last_updated_tick = value.get("last_updated_tick")
    if isinstance(last_updated_tick, bool) or not isinstance(last_updated_tick, int) or last_updated_tick < 0:
        raise ValueError("belief record last_updated_tick must be integer >= 0")
    if last_updated_tick < first_seen_tick:
        raise ValueError("belief record last_updated_tick must be >= first_seen_tick")

    confidence = clamp_confidence(value.get("confidence"))
    evidence_count = clamp_evidence_count(value.get("evidence_count"))

    return {
        "belief_id": belief_id,
        "subject": subject,
        "claim_key": claim_key,
        "confidence": confidence,
        "first_seen_tick": int(first_seen_tick),
        "last_updated_tick": int(last_updated_tick),
        "evidence_count": evidence_count,
    }


def _evict_excess_records(records: dict[str, dict[str, Any]]) -> None:
    if len(records) <= MAX_BELIEF_RECORDS_PER_FACTION:
        return
    ordered = sorted(
        records.values(),
        key=lambda row: (int(row["last_updated_tick"]), str(row["belief_id"])),
    )
    remove_count = len(records) - MAX_BELIEF_RECORDS_PER_FACTION
    for row in ordered[:remove_count]:
        records.pop(str(row["belief_id"]), None)


def normalize_faction_belief_state(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("faction belief state must be an object")
    unknown = set(value) - {"belief_records"}
    if unknown:
        raise ValueError(f"faction belief state has unknown fields: {sorted(unknown)}")
    raw_records = value.get("belief_records", {})
    if not isinstance(raw_records, dict):
        raise ValueError("faction belief state belief_records must be an object")

    belief_records: dict[str, dict[str, Any]] = {}
    for belief_id in sorted(raw_records):
        record = normalize_belief_record(raw_records[belief_id])
        if record["belief_id"] != belief_id:
            raise ValueError("faction belief state belief_id key mismatch")
        belief_records[belief_id] = record
    _evict_excess_records(belief_records)
    return {"belief_records": belief_records}


def normalize_world_faction_beliefs(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("faction_beliefs must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for faction_id in sorted(value):
        normalized_faction_id = normalize_faction_id(faction_id)
        if normalized_faction_id in normalized:
            raise ValueError("faction_beliefs keys must be unique after normalization")
        normalized[normalized_faction_id] = normalize_faction_belief_state(value[faction_id])
    return normalized


def upsert_player_claim_belief(
    *,
    faction_beliefs: dict[str, dict[str, Any]],
    faction_id: str,
    claim_key: str,
    confidence_delta: int,
    tick: int,
    evidence_increment: int,
) -> str:
    normalized_faction_id = normalize_faction_id(faction_id)
    normalized_claim_key = normalize_claim_key(claim_key)
    if isinstance(confidence_delta, bool) or not isinstance(confidence_delta, int):
        raise ValueError("confidence_delta must be an integer")
    if isinstance(evidence_increment, bool) or not isinstance(evidence_increment, int) or evidence_increment < 0:
        raise ValueError("evidence_increment must be an integer >= 0")
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise ValueError("tick must be an integer >= 0")

    subject: dict[str, str | None] = {"kind": "player", "id": "player"}
    belief_id = compute_belief_id(
        faction_id=normalized_faction_id,
        subject=subject,
        claim_key=normalized_claim_key,
    )
    faction_state = faction_beliefs.setdefault(normalized_faction_id, {"belief_records": {}})
    belief_records: dict[str, dict[str, Any]] = faction_state.setdefault("belief_records", {})
    existing = belief_records.get(belief_id)

    if existing is None:
        belief_records[belief_id] = {
            "belief_id": belief_id,
            "subject": subject,
            "claim_key": normalized_claim_key,
            "confidence": clamp_confidence(confidence_delta),
            "first_seen_tick": tick,
            "last_updated_tick": tick,
            "evidence_count": clamp_evidence_count(max(1, evidence_increment)),
        }
    else:
        updated_confidence = clamp_confidence(int(existing["confidence"]) + confidence_delta)
        updated_evidence = clamp_evidence_count(int(existing["evidence_count"]) + evidence_increment)
        belief_records[belief_id] = {
            **existing,
            "confidence": updated_confidence,
            "last_updated_tick": tick,
            "evidence_count": updated_evidence,
        }

    _evict_excess_records(belief_records)
    return belief_id


class BeliefClaimIngestionModule(RuleModule):
    """Slice 1A: deterministic player-only claim ingestion into faction belief substrate."""

    name = "belief_claim_ingestion"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != BELIEF_CLAIM_EMITTED_EVENT_TYPE:
            return
        params = event.params
        try:
            faction_id = normalize_faction_id(params.get("faction_id"))
            claim_key = normalize_claim_key(params.get("claim_key"))
            confidence_delta = int(params.get("confidence_delta", 0))
            if isinstance(params.get("confidence_delta", 0), bool):
                raise ValueError("confidence_delta must be an integer")
            evidence_increment_raw = params.get("evidence_increment", 1)
            if isinstance(evidence_increment_raw, bool) or not isinstance(evidence_increment_raw, int):
                raise ValueError("evidence_increment must be an integer")
            evidence_increment = max(0, int(evidence_increment_raw))
        except (TypeError, ValueError):
            return

        upsert_player_claim_belief(
            faction_beliefs=sim.state.world.faction_beliefs,
            faction_id=faction_id,
            claim_key=claim_key,
            confidence_delta=confidence_delta,
            tick=event.tick,
            evidence_increment=evidence_increment,
        )
