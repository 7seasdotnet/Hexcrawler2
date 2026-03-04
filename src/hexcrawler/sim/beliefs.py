from __future__ import annotations

import hashlib
import json
from typing import Any

from hexcrawler.sim.rules import RuleModule

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hexcrawler.sim.core import SimEvent, Simulation

BELIEF_CLAIM_EMITTED_EVENT_TYPE = "belief_claim_emitted"
BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE = "belief_transmission_job_enqueued"
BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE = "belief_investigation_job_enqueued"
BELIEF_TRANSMISSION_JOB_ENQUEUE_RESULT_EVENT_TYPE = "belief_transmission_job_enqueue_result"
BELIEF_INVESTIGATION_JOB_ENQUEUE_RESULT_EVENT_TYPE = "belief_investigation_job_enqueue_result"
BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE = "belief_transmission_job_completed"
BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE = "belief_investigation_job_completed"
BELIEF_SUBJECT_KINDS = {"player", "faction", "group", "unknown_actor"}
MAX_BELIEF_RECORDS_PER_FACTION = 512
MAX_BELIEF_CLAIM_KEY_LEN = 64
MAX_BELIEF_SUBJECT_ID_LEN = 64
MAX_BELIEF_EVIDENCE_COUNT = 1_000_000
MIN_BELIEF_CONFIDENCE = 0
MAX_BELIEF_CONFIDENCE = 100
MAX_TRANSMISSION_QUEUE = 256
MAX_INVESTIGATION_QUEUE = 256
MAX_JOBS_PER_TICK = 8


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


def compute_belief_job_id(
    *,
    queue_kind: str,
    faction_id: str,
    subject: dict[str, str | None],
    claim_key: str,
    created_tick: int,
    not_before_tick: int,
) -> str:
    if queue_kind not in {"transmission", "investigation"}:
        raise ValueError("queue_kind must be transmission or investigation")
    if isinstance(created_tick, bool) or not isinstance(created_tick, int) or created_tick < 0:
        raise ValueError("created_tick must be an integer >= 0")
    if isinstance(not_before_tick, bool) or not isinstance(not_before_tick, int) or not_before_tick < 0:
        raise ValueError("not_before_tick must be an integer >= 0")
    payload = {
        "queue_kind": queue_kind,
        "faction_id": normalize_faction_id(faction_id),
        "subject": normalize_belief_subject(subject),
        "claim_key": normalize_claim_key(claim_key),
        "created_tick": int(created_tick),
        "not_before_tick": int(not_before_tick),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"belief_job:{digest[:32]}"


def _normalize_claim_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("belief job claim must be an object")
    unknown = set(value) - {"subject", "claim_key", "confidence"}
    if unknown:
        raise ValueError(f"belief job claim has unknown fields: {sorted(unknown)}")
    return {
        "subject": normalize_belief_subject(value.get("subject")),
        "claim_key": normalize_claim_key(value.get("claim_key")),
        "confidence": clamp_confidence(value.get("confidence")),
    }


def _normalize_belief_job(value: Any, *, expected_kind: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("belief job must be an object")
    allowed = {"job_id", "created_tick", "not_before_tick", "faction_id", "claim"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"belief job has unknown fields: {sorted(unknown)}")

    faction_id = normalize_faction_id(value.get("faction_id"))
    created_tick = value.get("created_tick")
    if isinstance(created_tick, bool) or not isinstance(created_tick, int) or created_tick < 0:
        raise ValueError("belief job created_tick must be integer >= 0")
    not_before_tick = value.get("not_before_tick")
    if isinstance(not_before_tick, bool) or not isinstance(not_before_tick, int) or not_before_tick < 0:
        raise ValueError("belief job not_before_tick must be integer >= 0")
    if not_before_tick < created_tick:
        raise ValueError("belief job not_before_tick must be >= created_tick")

    claim = _normalize_claim_payload(value.get("claim"))
    expected_job_id = compute_belief_job_id(
        queue_kind=expected_kind,
        faction_id=faction_id,
        subject=dict(claim["subject"]),
        claim_key=str(claim["claim_key"]),
        created_tick=int(created_tick),
        not_before_tick=int(not_before_tick),
    )
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("belief job job_id must be a non-empty string")
    if job_id != expected_job_id:
        raise ValueError("belief job job_id mismatch")

    return {
        "job_id": job_id,
        "created_tick": int(created_tick),
        "not_before_tick": int(not_before_tick),
        "faction_id": faction_id,
        "claim": claim,
    }


def _normalize_transmission_queue(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("transmission_queue must be a list")
    queue = [_normalize_belief_job(row, expected_kind="transmission") for row in value]
    if len(queue) > MAX_TRANSMISSION_QUEUE:
        raise ValueError("transmission_queue exceeds maximum")
    return queue


def _normalize_investigation_queue(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("investigation_queue must be a list")
    queue = [_normalize_belief_job(row, expected_kind="investigation") for row in value]
    if len(queue) > MAX_INVESTIGATION_QUEUE:
        raise ValueError("investigation_queue exceeds maximum")
    return queue


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
    unknown = set(value) - {"belief_records", "transmission_queue", "investigation_queue"}
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

    transmission_queue = _normalize_transmission_queue(value.get("transmission_queue", []))
    investigation_queue = _normalize_investigation_queue(value.get("investigation_queue", []))

    result: dict[str, Any] = {"belief_records": belief_records}
    if transmission_queue:
        result["transmission_queue"] = transmission_queue
    if investigation_queue:
        result["investigation_queue"] = investigation_queue
    return result


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
        state = normalize_faction_belief_state(value[faction_id])
        if state.get("belief_records") or state.get("transmission_queue") or state.get("investigation_queue"):
            normalized[normalized_faction_id] = state
    return normalized


def _build_job(
    *,
    queue_kind: str,
    faction_id: str,
    created_tick: int,
    not_before_tick: int,
    claim: dict[str, Any],
) -> dict[str, Any]:
    normalized_claim = _normalize_claim_payload(claim)
    job_id = compute_belief_job_id(
        queue_kind=queue_kind,
        faction_id=faction_id,
        subject=dict(normalized_claim["subject"]),
        claim_key=str(normalized_claim["claim_key"]),
        created_tick=created_tick,
        not_before_tick=not_before_tick,
    )
    return {
        "job_id": job_id,
        "created_tick": int(created_tick),
        "not_before_tick": int(not_before_tick),
        "faction_id": normalize_faction_id(faction_id),
        "claim": normalized_claim,
    }


def _emit_job_enqueue_forensic(
    *,
    sim: Simulation,
    tick: int,
    event_type: str,
    faction_id: str,
    job_id: str,
    outcome: str,
) -> None:
    sim.schedule_event_at(
        tick=tick,
        event_type=event_type,
        params={
            "faction_id": faction_id,
            "job_id": job_id,
            "outcome": outcome,
            "tick": tick,
        },
    )


def _enqueue_job(
    *,
    faction_beliefs: dict[str, dict[str, Any]],
    faction_id: str,
    queue_key: str,
    queue_cap: int,
    job: dict[str, Any],
) -> bool:
    faction_state = faction_beliefs.setdefault(normalize_faction_id(faction_id), {"belief_records": {}})
    queue = faction_state.setdefault(queue_key, [])
    if len(queue) >= queue_cap:
        return False
    queue.append(job)
    return True


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


class BeliefJobQueueModule(RuleModule):
    """Slice 1B: deterministic transmission/investigation queue substrates and bounded processing."""

    name = "belief_job_queue"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == BELIEF_TRANSMISSION_JOB_ENQUEUED_EVENT_TYPE:
            self._handle_enqueue(sim=sim, event=event, queue_kind="transmission")
            return
        if event.event_type == BELIEF_INVESTIGATION_JOB_ENQUEUED_EVENT_TYPE:
            self._handle_enqueue(sim=sim, event=event, queue_kind="investigation")

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        for faction_id in sorted(sim.state.world.faction_beliefs):
            completed = 0
            completed += self._process_queue(
                sim=sim,
                tick=tick,
                faction_id=faction_id,
                queue_key="transmission_queue",
                completion_event_type=BELIEF_TRANSMISSION_JOB_COMPLETED_EVENT_TYPE,
                remaining_budget=MAX_JOBS_PER_TICK - completed,
            )
            self._process_queue(
                sim=sim,
                tick=tick,
                faction_id=faction_id,
                queue_key="investigation_queue",
                completion_event_type=BELIEF_INVESTIGATION_JOB_COMPLETED_EVENT_TYPE,
                remaining_budget=MAX_JOBS_PER_TICK - completed,
            )

    def _process_queue(
        self,
        *,
        sim: Simulation,
        tick: int,
        faction_id: str,
        queue_key: str,
        completion_event_type: str,
        remaining_budget: int,
    ) -> int:
        if remaining_budget <= 0:
            return 0
        faction_state = sim.state.world.faction_beliefs.get(faction_id)
        if faction_state is None:
            return 0
        queue = faction_state.get(queue_key)
        if not isinstance(queue, list) or not queue:
            return 0

        completed = 0
        while queue and completed < remaining_budget:
            job = queue[0]
            if int(job["not_before_tick"]) > tick:
                break
            completed += 1
            completed_job = queue.pop(0)
            sim.schedule_event_at(
                tick=tick + 1,
                event_type=completion_event_type,
                params={
                    "job_id": str(completed_job["job_id"]),
                    "faction_id": faction_id,
                    "tick": tick + 1,
                },
            )
        if not queue:
            faction_state.pop(queue_key, None)
        if (
            not faction_state.get("belief_records")
            and not faction_state.get("transmission_queue")
            and not faction_state.get("investigation_queue")
        ):
            sim.state.world.faction_beliefs.pop(faction_id, None)
        return completed

    def _handle_enqueue(self, *, sim: Simulation, event: SimEvent, queue_kind: str) -> None:
        params = event.params
        try:
            faction_id = normalize_faction_id(params.get("faction_id"))
            not_before_tick_raw = params.get("not_before_tick", event.tick)
            if isinstance(not_before_tick_raw, bool) or not isinstance(not_before_tick_raw, int):
                raise ValueError("not_before_tick must be integer")
            not_before_tick = max(event.tick, int(not_before_tick_raw))
            claim = _normalize_claim_payload(params.get("claim"))
        except (TypeError, ValueError):
            return

        job = _build_job(
            queue_kind=queue_kind,
            faction_id=faction_id,
            created_tick=event.tick,
            not_before_tick=not_before_tick,
            claim=claim,
        )

        if queue_kind == "transmission":
            accepted = _enqueue_job(
                faction_beliefs=sim.state.world.faction_beliefs,
                faction_id=faction_id,
                queue_key="transmission_queue",
                queue_cap=MAX_TRANSMISSION_QUEUE,
                job=job,
            )
            forensic_event_type = BELIEF_TRANSMISSION_JOB_ENQUEUE_RESULT_EVENT_TYPE
        else:
            accepted = _enqueue_job(
                faction_beliefs=sim.state.world.faction_beliefs,
                faction_id=faction_id,
                queue_key="investigation_queue",
                queue_cap=MAX_INVESTIGATION_QUEUE,
                job=job,
            )
            forensic_event_type = BELIEF_INVESTIGATION_JOB_ENQUEUE_RESULT_EVENT_TYPE

        _emit_job_enqueue_forensic(
            sim=sim,
            tick=event.tick,
            event_type=forensic_event_type,
            faction_id=faction_id,
            job_id=str(job["job_id"]),
            outcome=("enqueued" if accepted else "queue_full"),
        )
