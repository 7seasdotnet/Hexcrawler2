from __future__ import annotations

import random
import json
import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.beliefs import (
    normalize_belief_enqueue_config,
    normalize_belief_geo_gating_config,
    normalize_faction_id,
    normalize_world_faction_beliefs,
)
from hexcrawler.sim.rng import derive_stream_seed

SITE_TYPES = {"none", "town", "dungeon"}
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"
DEFAULT_TERRAIN_OPTIONS = ("plains", "forest", "hills")
DEFAULT_OVERWORLD_SPACE_ID = "overworld"
SQUARE_GRID_TOPOLOGY = "square_grid"
CAMPAIGN_SPACE_ROLE = "campaign"
LOCAL_SPACE_ROLE = "local"
SPACE_ROLES = {CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE}
MAX_SIGNALS = 256
MAX_OCCLUSION_EDGES = 2048
MAX_CLAIM_OPPORTUNITIES = 256
MAX_RUMORS = 512
MAX_RUMOR_SELECTION_DECISIONS = 256
MAX_ACTIVATED_FACTIONS = 128
MAX_CONTACTS_PER_FACTION = 64
MAX_CONTACT_TTL_TICKS = 1_000_000
MAX_CONTACT_DECAY_PER_TICK = 128
MAX_SITE_PRESSURE_RECORDS = 32
MAX_SITE_CONDITION_MARKERS = 32
DEFAULT_CONTACT_TTL_CONFIG = {
    "enabled": False,
    "contact_ttl_ticks": 0,
    "max_decay_per_tick": 16,
}
MAX_BELIEF_REACTIONS_PER_TICK = 64
DEFAULT_BELIEF_REACTION_CONFIG = {
    "enabled": False,
    "max_reactions_per_tick": 8,
    "contested_investigation_threshold": 60,
    "contested_min_age_ticks": 50,
    "unknown_actor_investigation_threshold": 60,
    "max_investigation_jobs_enqueued_per_tick": 4,
}
RUMOR_KINDS = {"group_arrival", "claim_opportunity", "site_claim"}
MAX_RUMOR_TTL_TICKS = 1_000_000
DEFAULT_RUMOR_TTL_BY_KIND = {
    "group_arrival": 2000,
    "claim_opportunity": 4000,
    "site_claim": 10000,
}
DEFAULT_RUMOR_TTL_CONFIG = {
    "enabled": True,
    "ttl_by_kind": dict(DEFAULT_RUMOR_TTL_BY_KIND),
    "ttl_by_site_template": {},
    "ttl_by_region": {},
    "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
}


def _normalize_rumor_ttl_override_id(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} keys must be strings")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} keys must be non-empty strings")
    return normalized


def _normalize_rumor_ttl_by_kind(
    value: Any,
    *,
    field_name: str,
    max_ttl_ticks: int,
) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    ttl_by_kind: dict[str, int] = {}
    for raw_kind in sorted(value):
        if raw_kind not in RUMOR_KINDS:
            raise ValueError(f"{field_name} has unknown rumor kind")
        ttl_ticks = value[raw_kind]
        if isinstance(ttl_ticks, bool) or not isinstance(ttl_ticks, int):
            raise ValueError(f"{field_name} values must be integers")
        if ttl_ticks < 0:
            raise ValueError(f"{field_name} values must be >= 0")
        if ttl_ticks > max_ttl_ticks:
            raise ValueError(f"{field_name} value exceeds max_ttl_ticks")
        ttl_by_kind[str(raw_kind)] = ttl_ticks
    return ttl_by_kind


def _normalize_rumor_ttl_overrides(
    value: Any,
    *,
    field_name: str,
    max_ttl_ticks: int,
) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    overrides: dict[str, dict[str, int]] = {}
    for raw_key in sorted(value):
        normalized_key = _normalize_rumor_ttl_override_id(raw_key, field_name=field_name)
        if normalized_key in overrides:
            raise ValueError(f"{field_name} keys must be unique after normalization")
        overrides[normalized_key] = _normalize_rumor_ttl_by_kind(
            value[raw_key],
            field_name=f"{field_name}[{normalized_key}]",
            max_ttl_ticks=max_ttl_ticks,
        )
    return overrides


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _validate_json_value(value: Any, *, field_name: str) -> None:
    if _is_json_primitive(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name=field_name)
        return
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} keys must be strings")
            _validate_json_value(nested_value, field_name=field_name)
        return
    raise ValueError(f"{field_name} must contain only canonical JSON primitives")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _legacy_rumor_kind(value: dict[str, Any]) -> str | None:
    template_id = value.get("template_id")
    if isinstance(template_id, str) and template_id in RUMOR_KINDS:
        return template_id
    for key in ("kind", "category", "rumor_kind"):
        raw = value.get(key)
        if isinstance(raw, str) and raw in RUMOR_KINDS:
            return raw
    return None


def _legacy_rumor_created_tick(value: dict[str, Any]) -> int:
    for key in ("created_tick", "tick", "at_tick"):
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw if raw >= 0 else 0
    return 0


def _legacy_rumor_id(value: dict[str, Any]) -> str:
    rumor_id = value.get("rumor_id")
    if isinstance(rumor_id, str) and rumor_id:
        return rumor_id
    digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:16]
    return f"legacy:{digest}"


def _normalize_rumor_records(raw_rumors: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}

    for index, raw in enumerate(raw_rumors):
        if not isinstance(raw, dict):
            raise ValueError("rumor record must be an object")

        candidate: dict[str, Any] | None
        modern_fields = {"rumor_id", "kind", "site_key", "group_id", "created_tick", "consumed", "expires_tick"}
        unknown_fields = set(raw) - modern_fields
        try:
            candidate = RumorRecord.from_dict(dict(raw)).to_dict()
        except ValueError:
            if not unknown_fields:
                raise
            kind = _legacy_rumor_kind(raw)
            if kind is None:
                candidate = None
            else:
                migrated: dict[str, Any] = {
                    "rumor_id": _legacy_rumor_id(raw),
                    "kind": kind,
                    "created_tick": _legacy_rumor_created_tick(raw),
                    "consumed": bool(raw.get("consumed", False)),
                }
                site_key = raw.get("site_key")
                if isinstance(site_key, str) and site_key:
                    migrated["site_key"] = site_key
                group_id = raw.get("group_id")
                if isinstance(group_id, str) and group_id:
                    migrated["group_id"] = group_id
                try:
                    candidate = RumorRecord.from_dict(migrated).to_dict()
                except ValueError:
                    candidate = None

        if candidate is None:
            continue

        rumor_id = str(candidate["rumor_id"])
        occurrence = seen_ids.get(rumor_id, 0)
        if occurrence:
            digest = hashlib.sha256(f"{rumor_id}:{index}".encode("utf-8")).hexdigest()[:8]
            candidate["rumor_id"] = f"{rumor_id}~{digest}"
        seen_ids[rumor_id] = occurrence + 1
        normalized.append(candidate)

    if len(normalized) > MAX_RUMORS:
        normalized = normalized[-MAX_RUMORS:]
    return normalized


def normalize_faction_registry(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("faction_registry must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_faction_id in value:
        faction_id = normalize_faction_id(raw_faction_id)
        if faction_id in seen:
            raise ValueError("faction_registry ids must be unique after normalization")
        seen.add(faction_id)
        normalized.append(faction_id)
    return sorted(normalized)


def normalize_activated_factions(value: Any, *, faction_registry: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("activated_factions must be a list")
    registry_set = set(faction_registry)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_faction_id in value:
        faction_id = normalize_faction_id(raw_faction_id)
        if faction_id not in registry_set:
            raise ValueError("activated_factions must be a subset of faction_registry")
        if faction_id in seen:
            raise ValueError("activated_factions ids must be unique after normalization")
        seen.add(faction_id)
        normalized.append(faction_id)
    if len(normalized) > MAX_ACTIVATED_FACTIONS:
        raise ValueError("activated_factions exceeds maximum")
    return sorted(normalized)


def normalize_faction_contacts(value: Any, *, faction_registry: list[str]) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("faction_contacts must be an object")

    registry_set = set(faction_registry)
    normalized_contacts: dict[str, list[str]] = {}
    for raw_source_id in sorted(value):
        source_id = normalize_faction_id(raw_source_id)
        if source_id in normalized_contacts:
            raise ValueError("faction_contacts source ids must be unique after normalization")
        if source_id not in registry_set:
            raise ValueError("faction_contacts source ids must exist in faction_registry")

        raw_contacts = value[raw_source_id]
        if not isinstance(raw_contacts, list):
            raise ValueError("faction_contacts recipient lists must be lists")

        recipients: list[str] = []
        seen_recipients: set[str] = set()
        for raw_recipient_id in raw_contacts:
            recipient_id = normalize_faction_id(raw_recipient_id)
            if recipient_id not in registry_set:
                raise ValueError("faction_contacts recipient ids must exist in faction_registry")
            if recipient_id == source_id:
                raise ValueError("faction_contacts must not include self-contact")
            if recipient_id in seen_recipients:
                raise ValueError("faction_contacts recipient ids must be unique after normalization")
            seen_recipients.add(recipient_id)
            recipients.append(recipient_id)

        if len(recipients) > MAX_CONTACTS_PER_FACTION:
            raise ValueError("faction_contacts exceeds maximum per faction")

        if recipients:
            normalized_contacts[source_id] = sorted(recipients)

    return normalized_contacts


def normalize_faction_contact_meta(
    value: Any,
    *,
    faction_registry: list[str],
    faction_contacts: dict[str, list[str]],
) -> dict[str, dict[str, dict[str, int]]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("faction_contact_meta must be an object")

    registry_set = set(faction_registry)
    normalized_meta: dict[str, dict[str, dict[str, int]]] = {}
    for raw_source_id in sorted(value):
        source_id = normalize_faction_id(raw_source_id)
        if source_id in normalized_meta:
            raise ValueError("faction_contact_meta source ids must be unique after normalization")
        if source_id not in registry_set:
            raise ValueError("faction_contact_meta source ids must exist in faction_registry")

        raw_targets = value[raw_source_id]
        if not isinstance(raw_targets, dict):
            raise ValueError("faction_contact_meta target maps must be objects")

        normalized_targets: dict[str, dict[str, int]] = {}
        contact_targets = set(faction_contacts.get(source_id, []))
        for raw_target_id in sorted(raw_targets):
            target_id = normalize_faction_id(raw_target_id)
            if target_id in normalized_targets:
                raise ValueError("faction_contact_meta target ids must be unique after normalization")
            if target_id not in registry_set:
                raise ValueError("faction_contact_meta target ids must exist in faction_registry")
            if target_id not in contact_targets:
                raise ValueError("faction_contact_meta entries must reference existing faction_contacts edges")

            raw_meta = raw_targets[raw_target_id]
            if not isinstance(raw_meta, dict):
                raise ValueError("faction_contact_meta entries must be objects")
            allowed = {"last_touch_tick"}
            unknown = set(raw_meta) - allowed
            if unknown:
                raise ValueError("faction_contact_meta entries have unknown fields")
            last_touch_tick = raw_meta.get("last_touch_tick")
            if isinstance(last_touch_tick, bool) or not isinstance(last_touch_tick, int):
                raise ValueError("faction_contact_meta.last_touch_tick must be an integer")
            if last_touch_tick < 0:
                raise ValueError("faction_contact_meta.last_touch_tick must be >= 0")

            normalized_targets[target_id] = {"last_touch_tick": int(last_touch_tick)}

        if normalized_targets:
            normalized_meta[source_id] = normalized_targets

    return normalized_meta


def normalize_contact_ttl_config(value: Any) -> dict[str, Any]:
    if value is None:
        return dict(DEFAULT_CONTACT_TTL_CONFIG)
    if not isinstance(value, dict):
        raise ValueError("contact_ttl_config must be an object")

    allowed = {"enabled", "contact_ttl_ticks", "max_decay_per_tick"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("contact_ttl_config has unknown fields")

    enabled = value.get("enabled", DEFAULT_CONTACT_TTL_CONFIG["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("contact_ttl_config.enabled must be a boolean")

    raw_ttl = value.get("contact_ttl_ticks", DEFAULT_CONTACT_TTL_CONFIG["contact_ttl_ticks"])
    if isinstance(raw_ttl, bool) or not isinstance(raw_ttl, int):
        raise ValueError("contact_ttl_config.contact_ttl_ticks must be an integer")
    if raw_ttl < 0:
        raise ValueError("contact_ttl_config.contact_ttl_ticks must be >= 0")
    if raw_ttl > MAX_CONTACT_TTL_TICKS:
        raise ValueError("contact_ttl_config.contact_ttl_ticks exceeds maximum")

    raw_decay = value.get("max_decay_per_tick", DEFAULT_CONTACT_TTL_CONFIG["max_decay_per_tick"])
    if isinstance(raw_decay, bool) or not isinstance(raw_decay, int):
        raise ValueError("contact_ttl_config.max_decay_per_tick must be an integer")
    if raw_decay < 1:
        raise ValueError("contact_ttl_config.max_decay_per_tick must be >= 1")
    if raw_decay > MAX_CONTACT_DECAY_PER_TICK:
        raise ValueError("contact_ttl_config.max_decay_per_tick exceeds maximum")

    if enabled and raw_ttl <= 0:
        raise ValueError("contact_ttl_config.contact_ttl_ticks must be > 0 when enabled")

    return {
        "enabled": enabled,
        "contact_ttl_ticks": int(raw_ttl),
        "max_decay_per_tick": int(raw_decay),
    }


def normalize_belief_reaction_config(value: Any) -> dict[str, Any]:
    if value is None:
        return dict(DEFAULT_BELIEF_REACTION_CONFIG)
    if not isinstance(value, dict):
        raise ValueError("belief_reaction_config must be an object")

    allowed = {
        "enabled",
        "max_reactions_per_tick",
        "contested_investigation_threshold",
        "contested_min_age_ticks",
        "unknown_actor_investigation_threshold",
        "max_investigation_jobs_enqueued_per_tick",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("belief_reaction_config has unknown fields")

    enabled = value.get("enabled", DEFAULT_BELIEF_REACTION_CONFIG["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("belief_reaction_config.enabled must be a boolean")

    max_reactions = value.get(
        "max_reactions_per_tick",
        DEFAULT_BELIEF_REACTION_CONFIG["max_reactions_per_tick"],
    )
    if isinstance(max_reactions, bool) or not isinstance(max_reactions, int):
        raise ValueError("belief_reaction_config.max_reactions_per_tick must be an integer")
    if max_reactions < 0:
        raise ValueError("belief_reaction_config.max_reactions_per_tick must be >= 0")
    if max_reactions > MAX_BELIEF_REACTIONS_PER_TICK:
        raise ValueError("belief_reaction_config.max_reactions_per_tick exceeds maximum")

    contested_threshold = value.get(
        "contested_investigation_threshold",
        DEFAULT_BELIEF_REACTION_CONFIG["contested_investigation_threshold"],
    )
    if isinstance(contested_threshold, bool) or not isinstance(contested_threshold, int):
        raise ValueError("belief_reaction_config.contested_investigation_threshold must be an integer")
    if contested_threshold < 0 or contested_threshold > 100:
        raise ValueError("belief_reaction_config.contested_investigation_threshold must be in [0,100]")

    contested_min_age = value.get(
        "contested_min_age_ticks",
        DEFAULT_BELIEF_REACTION_CONFIG["contested_min_age_ticks"],
    )
    if isinstance(contested_min_age, bool) or not isinstance(contested_min_age, int):
        raise ValueError("belief_reaction_config.contested_min_age_ticks must be an integer")
    if contested_min_age < 0:
        raise ValueError("belief_reaction_config.contested_min_age_ticks must be >= 0")
    if contested_min_age > MAX_CONTACT_TTL_TICKS:
        raise ValueError("belief_reaction_config.contested_min_age_ticks exceeds maximum")

    unknown_threshold = value.get(
        "unknown_actor_investigation_threshold",
        DEFAULT_BELIEF_REACTION_CONFIG["unknown_actor_investigation_threshold"],
    )
    if isinstance(unknown_threshold, bool) or not isinstance(unknown_threshold, int):
        raise ValueError("belief_reaction_config.unknown_actor_investigation_threshold must be an integer")
    if unknown_threshold < 0 or unknown_threshold > 100:
        raise ValueError("belief_reaction_config.unknown_actor_investigation_threshold must be in [0,100]")

    max_jobs = value.get(
        "max_investigation_jobs_enqueued_per_tick",
        DEFAULT_BELIEF_REACTION_CONFIG["max_investigation_jobs_enqueued_per_tick"],
    )
    if isinstance(max_jobs, bool) or not isinstance(max_jobs, int):
        raise ValueError("belief_reaction_config.max_investigation_jobs_enqueued_per_tick must be an integer")
    if max_jobs < 0:
        raise ValueError("belief_reaction_config.max_investigation_jobs_enqueued_per_tick must be >= 0")
    if max_jobs > MAX_BELIEF_REACTIONS_PER_TICK:
        raise ValueError("belief_reaction_config.max_investigation_jobs_enqueued_per_tick exceeds maximum")

    return {
        "enabled": enabled,
        "max_reactions_per_tick": int(max_reactions),
        "contested_investigation_threshold": int(contested_threshold),
        "contested_min_age_ticks": int(contested_min_age),
        "unknown_actor_investigation_threshold": int(unknown_threshold),
        "max_investigation_jobs_enqueued_per_tick": int(max_jobs),
    }


def _normalize_rumor_ttl_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("rumor_ttl_config must be an object")
    allowed = {"enabled", "ttl_by_kind", "ttl_by_site_template", "ttl_by_region", "max_ttl_ticks"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("rumor_ttl_config has unknown fields")

    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("rumor_ttl_config.enabled must be a boolean")

    max_ttl_ticks_raw = value.get("max_ttl_ticks", MAX_RUMOR_TTL_TICKS)
    if isinstance(max_ttl_ticks_raw, bool) or not isinstance(max_ttl_ticks_raw, int):
        raise ValueError("rumor_ttl_config.max_ttl_ticks must be an integer")
    if max_ttl_ticks_raw < 0:
        raise ValueError("rumor_ttl_config.max_ttl_ticks must be >= 0")
    if max_ttl_ticks_raw > MAX_RUMOR_TTL_TICKS:
        raise ValueError("rumor_ttl_config.max_ttl_ticks exceeds MAX_RUMOR_TTL_TICKS")

    ttl_by_kind = _normalize_rumor_ttl_by_kind(
        value.get("ttl_by_kind", DEFAULT_RUMOR_TTL_BY_KIND),
        field_name="rumor_ttl_config.ttl_by_kind",
        max_ttl_ticks=max_ttl_ticks_raw,
    )
    ttl_by_site_template = _normalize_rumor_ttl_overrides(
        value.get("ttl_by_site_template", {}),
        field_name="rumor_ttl_config.ttl_by_site_template",
        max_ttl_ticks=max_ttl_ticks_raw,
    )
    ttl_by_region = _normalize_rumor_ttl_overrides(
        value.get("ttl_by_region", {}),
        field_name="rumor_ttl_config.ttl_by_region",
        max_ttl_ticks=max_ttl_ticks_raw,
    )

    return {
        "enabled": enabled,
        "ttl_by_kind": ttl_by_kind,
        "ttl_by_site_template": ttl_by_site_template,
        "ttl_by_region": ttl_by_region,
        "max_ttl_ticks": max_ttl_ticks_raw,
    }




def _require_non_negative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _normalize_signal_origin(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("signal.origin must be an object")
    space_id = value.get("space_id")
    topology_type = value.get("topology_type")
    coord = value.get("coord")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("signal.origin.space_id must be a non-empty string")
    if not isinstance(topology_type, str) or not topology_type:
        raise ValueError("signal.origin.topology_type must be a non-empty string")
    if not isinstance(coord, dict):
        raise ValueError("signal.origin.coord must be an object")
    normalized_coord: dict[str, int] = {}
    for key, raw in coord.items():
        if not isinstance(key, str):
            raise ValueError("signal.origin.coord keys must be strings")
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"signal.origin.coord[{key}] must be an integer")
        normalized_coord[key] = raw
    return {"space_id": space_id, "topology_type": topology_type, "coord": normalized_coord}


def _normalize_signal_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("signal record must be an object")

    if "signal_id" not in value:
        _validate_json_value(value, field_name="signal")
        return dict(value)

    signal_id = value.get("signal_id")
    space_id = value.get("space_id")
    channel = value.get("channel")
    falloff_model = value.get("falloff_model")
    if not isinstance(signal_id, str) or not signal_id:
        raise ValueError("signal.signal_id must be a non-empty string")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("signal.space_id must be a non-empty string")
    if not isinstance(channel, str) or not channel:
        raise ValueError("signal.channel must be a non-empty string")
    if not isinstance(falloff_model, str) or not falloff_model:
        raise ValueError("signal.falloff_model must be a non-empty string")
    metadata = value.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("signal.metadata must be an object")
    _validate_json_value(metadata, field_name="signal.metadata")
    return {
        "signal_id": signal_id,
        "tick_emitted": _require_non_negative_int(value.get("tick_emitted"), field_name="signal.tick_emitted"),
        "space_id": space_id,
        "origin": _normalize_signal_origin(value.get("origin")),
        "channel": channel,
        "base_intensity": _require_non_negative_int(value.get("base_intensity"), field_name="signal.base_intensity"),
        "falloff_model": falloff_model,
        "max_radius": _require_non_negative_int(value.get("max_radius"), field_name="signal.max_radius"),
        "ttl_ticks": _require_non_negative_int(value.get("ttl_ticks"), field_name="signal.ttl_ticks"),
        "metadata": dict(metadata),
    }


def _coord_sort_key(coord: dict[str, int]) -> tuple[int, int, int]:
    if "q" in coord and "r" in coord:
        return (0, int(coord["q"]), int(coord["r"]))
    if "x" in coord and "y" in coord:
        return (1, int(coord["x"]), int(coord["y"]))
    raise ValueError("coord must contain q/r or x/y")


def _canonicalize_edge_cells(cell_a: dict[str, Any], cell_b: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    normalized_a = _normalize_coord_dict(dict(cell_a), field_name="structure_occlusion.cell_a")
    normalized_b = _normalize_coord_dict(dict(cell_b), field_name="structure_occlusion.cell_b")
    if set(normalized_a.keys()) != set(normalized_b.keys()):
        raise ValueError("structure_occlusion edge coords must share the same topology keys")
    if _coord_sort_key(normalized_b) < _coord_sort_key(normalized_a):
        return normalized_b, normalized_a
    return normalized_a, normalized_b


def canonical_occlusion_edge_key(space_id: str, cell_a: dict[str, Any], cell_b: dict[str, Any]) -> str:
    normalized_a, normalized_b = _canonicalize_edge_cells(cell_a, cell_b)
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("structure_occlusion.space_id must be a non-empty string")
    payload = {"space_id": space_id, "cell_a": normalized_a, "cell_b": normalized_b}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _normalize_occlusion_edge_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("structure_occlusion entry must be an object")
    space_id = value.get("space_id")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("structure_occlusion.space_id must be a non-empty string")
    cell_a, cell_b = _canonicalize_edge_cells(value.get("cell_a", {}), value.get("cell_b", {}))
    occlusion_value = _require_non_negative_int(value.get("occlusion_value"), field_name="structure_occlusion.occlusion_value")
    return {
        "space_id": space_id,
        "cell_a": cell_a,
        "cell_b": cell_b,
        "occlusion_value": occlusion_value,
    }


def _normalize_claim_opportunity_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("claim opportunity entry must be an object")
    allowed = {"opportunity_id", "group_id", "site_key", "cell", "created_tick", "consumed_tick"}
    if set(value) - allowed:
        raise ValueError("claim opportunity entry has unknown fields")

    opportunity_id = value.get("opportunity_id")
    group_id = value.get("group_id")
    site_key = value.get("site_key")
    cell = value.get("cell")
    if not isinstance(opportunity_id, str) or not opportunity_id:
        raise ValueError("claim opportunity opportunity_id must be a non-empty string")
    if not isinstance(group_id, str) or not group_id:
        raise ValueError("claim opportunity group_id must be a non-empty string")
    if not isinstance(site_key, dict):
        raise ValueError("claim opportunity site_key must be an object")
    _validate_json_value(site_key, field_name="claim opportunity site_key")

    if not isinstance(cell, dict):
        raise ValueError("claim opportunity cell must be an object")
    if set(cell) != {"space_id", "coord"}:
        raise ValueError("claim opportunity cell must contain exactly: space_id, coord")
    if not isinstance(cell.get("space_id"), str) or not cell.get("space_id"):
        raise ValueError("claim opportunity cell.space_id must be a non-empty string")
    if not isinstance(cell.get("coord"), dict):
        raise ValueError("claim opportunity cell.coord must be an object")
    _validate_json_value(cell.get("coord"), field_name="claim opportunity cell.coord")

    created_tick = _require_non_negative_int(value.get("created_tick"), field_name="claim opportunity created_tick")
    consumed_tick_raw = value.get("consumed_tick")
    consumed_tick = None
    if consumed_tick_raw is not None:
        consumed_tick = _require_non_negative_int(consumed_tick_raw, field_name="claim opportunity consumed_tick")

    return {
        "opportunity_id": opportunity_id,
        "group_id": group_id,
        "site_key": copy.deepcopy(site_key),
        "cell": {"space_id": str(cell["space_id"]), "coord": copy.deepcopy(cell["coord"])},
        "created_tick": created_tick,
        "consumed_tick": consumed_tick,
    }

def _build_default_hex_record(rng_worldgen: random.Random) -> HexRecord:
    return HexRecord(terrain_type=rng_worldgen.choice(DEFAULT_TERRAIN_OPTIONS))


def generate_hex_disk(radius: int, rng_worldgen: random.Random) -> dict[HexCoord, HexRecord]:
    if radius < 0:
        raise ValueError("radius must be >= 0")

    hexes: dict[HexCoord, HexRecord] = {}
    for q in range(-radius, radius + 1):
        min_r = max(-radius, -q - radius)
        max_r = min(radius, -q + radius)
        for r in range(min_r, max_r + 1):
            coord = HexCoord(q=q, r=r)
            hexes[coord] = _build_default_hex_record(rng_worldgen)
    return hexes


def generate_hex_rectangle(width: int, height: int, rng_worldgen: random.Random) -> dict[HexCoord, HexRecord]:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be > 0")

    hexes: dict[HexCoord, HexRecord] = {}
    for q in range(width):
        for r in range(height):
            coord = HexCoord(q=q, r=r)
            hexes[coord] = _build_default_hex_record(rng_worldgen)
    return hexes


@dataclass(frozen=True, order=True)
class HexCoord:
    """Axial hex coordinate (q, r)."""

    q: int
    r: int

    def to_dict(self) -> dict[str, int]:
        return {"q": self.q, "r": self.r}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HexCoord":
        return cls(q=int(data["q"]), r=int(data["r"]))


@dataclass
class HexRecord:
    terrain_type: str
    site_type: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.site_type not in SITE_TYPES:
            raise ValueError(f"invalid site_type: {self.site_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "terrain_type": self.terrain_type,
            "site_type": self.site_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HexRecord":
        return cls(
            terrain_type=str(data["terrain_type"]),
            site_type=str(data.get("site_type", "none")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class RumorRecord:
    rumor_id: str
    kind: str
    created_tick: int
    site_key: str | None = None
    group_id: str | None = None
    consumed: bool = False
    expires_tick: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rumor_id, str) or not self.rumor_id:
            raise ValueError("rumor_id must be a non-empty string")
        if not isinstance(self.kind, str) or self.kind not in RUMOR_KINDS:
            raise ValueError(f"kind must be one of: {sorted(RUMOR_KINDS)}")
        if self.site_key is not None and (not isinstance(self.site_key, str) or not self.site_key):
            raise ValueError("site_key must be a non-empty string when present")
        if self.group_id is not None and (not isinstance(self.group_id, str) or not self.group_id):
            raise ValueError("group_id must be a non-empty string when present")
        if not isinstance(self.created_tick, int):
            raise ValueError("created_tick must be an integer")
        if not isinstance(self.consumed, bool):
            raise ValueError("consumed must be a boolean")
        if self.expires_tick is not None:
            if isinstance(self.expires_tick, bool) or not isinstance(self.expires_tick, int):
                raise ValueError("expires_tick must be an integer when present")
            if self.expires_tick < 0:
                raise ValueError("expires_tick must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        data = {
            "rumor_id": self.rumor_id,
            "kind": self.kind,
            "created_tick": self.created_tick,
            "consumed": self.consumed,
        }
        if self.site_key is not None:
            data["site_key"] = self.site_key
        if self.group_id is not None:
            data["group_id"] = self.group_id
        if self.expires_tick is not None:
            data["expires_tick"] = self.expires_tick
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RumorRecord":
        allowed = {"rumor_id", "kind", "site_key", "group_id", "created_tick", "consumed", "expires_tick"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"rumor record has unknown fields: {sorted(unknown)}")
        raw_expires_tick = data.get("expires_tick")
        if raw_expires_tick is not None and (isinstance(raw_expires_tick, bool) or not isinstance(raw_expires_tick, int)):
            raise ValueError("expires_tick must be an integer when present")
        return cls(
            rumor_id=str(data["rumor_id"]),
            kind=str(data["kind"]),
            site_key=(str(data["site_key"]) if data.get("site_key") is not None else None),
            group_id=(str(data["group_id"]) if data.get("group_id") is not None else None),
            created_tick=int(data["created_tick"]),
            consumed=(data.get("consumed", False) if data.get("consumed") is not None else False),
            expires_tick=raw_expires_tick,
        )


def _normalize_rumor_selection_decision_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("rumor selection decision record must be an object")
    allowed = {
        "selected_rumor_ids",
        "rng_rolls",
        "created_tick",
        "scope",
        "seed_tag",
        "k",
        "filters",
        "candidate_count",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"rumor selection decision has unknown fields: {sorted(unknown)}")

    created_tick = _require_non_negative_int(value.get("created_tick"), field_name="rumor_selection.created_tick")
    scope = value.get("scope")
    if not isinstance(scope, str) or not scope:
        raise ValueError("rumor_selection.scope must be a non-empty string")
    seed_tag = value.get("seed_tag")
    if not isinstance(seed_tag, str) or not seed_tag:
        raise ValueError("rumor_selection.seed_tag must be a non-empty string")
    k = _require_non_negative_int(value.get("k"), field_name="rumor_selection.k")
    candidate_count = _require_non_negative_int(value.get("candidate_count"), field_name="rumor_selection.candidate_count")

    selected_rumor_ids_raw = value.get("selected_rumor_ids")
    if not isinstance(selected_rumor_ids_raw, list):
        raise ValueError("rumor_selection.selected_rumor_ids must be a list")
    selected_rumor_ids: list[str] = []
    for row in selected_rumor_ids_raw:
        if not isinstance(row, str) or not row:
            raise ValueError("rumor_selection.selected_rumor_ids entries must be non-empty strings")
        selected_rumor_ids.append(row)

    rng_rolls_raw = value.get("rng_rolls", [])
    if not isinstance(rng_rolls_raw, list):
        raise ValueError("rumor_selection.rng_rolls must be a list")
    rng_rolls: list[int] = []
    for row in rng_rolls_raw:
        rng_rolls.append(_require_non_negative_int(row, field_name="rumor_selection.rng_rolls[]"))

    filters_raw = value.get("filters", {})
    if not isinstance(filters_raw, dict):
        raise ValueError("rumor_selection.filters must be an object")
    _validate_json_value(filters_raw, field_name="rumor_selection.filters")

    return {
        "selected_rumor_ids": selected_rumor_ids,
        "rng_rolls": rng_rolls,
        "created_tick": created_tick,
        "scope": scope,
        "seed_tag": seed_tag,
        "k": k,
        "filters": dict(filters_raw),
        "candidate_count": candidate_count,
    }


def _normalize_coord_dict(coord: dict[str, Any], *, field_name: str) -> dict[str, int]:
    if not isinstance(coord, dict):
        raise ValueError(f"{field_name} must be an object")
    if "x" in coord or "y" in coord:
        if "x" not in coord or "y" not in coord:
            raise ValueError(f"{field_name} requires x and y")
        return {"x": int(coord["x"]), "y": int(coord["y"])}
    if "q" in coord or "r" in coord:
        if "q" not in coord or "r" not in coord:
            raise ValueError(f"{field_name} requires q and r")
        return {"q": int(coord["q"]), "r": int(coord["r"])}
    raise ValueError(f"{field_name} requires either x/y or q/r")


@dataclass
class DoorRecord:
    door_id: str
    space_id: str
    a: dict[str, int]
    b: dict[str, int]
    state: str
    flags: dict[str, bool] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.door_id, str) or not self.door_id:
            raise ValueError("door_id must be a non-empty string")
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        self.a = _normalize_coord_dict(self.a, field_name="door.a")
        self.b = _normalize_coord_dict(self.b, field_name="door.b")
        if self.state not in {"open", "closed"}:
            raise ValueError("door state must be 'open' or 'closed'")
        self.flags = {
            "locked": bool(self.flags.get("locked", False)),
            "blocked": bool(self.flags.get("blocked", False)),
        }
        _validate_json_value(self.metadata, field_name="door.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "door_id": self.door_id,
            "space_id": self.space_id,
            "a": dict(self.a),
            "b": dict(self.b),
            "state": self.state,
            "flags": dict(self.flags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DoorRecord":
        return cls(
            door_id=str(data["door_id"]),
            space_id=str(data["space_id"]),
            a=dict(data["a"]),
            b=dict(data["b"]),
            state=str(data["state"]),
            flags=dict(data.get("flags", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AnchorRecord:
    anchor_id: str
    space_id: str
    coord: dict[str, int]
    kind: str
    target: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.anchor_id, str) or not self.anchor_id:
            raise ValueError("anchor_id must be a non-empty string")
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        self.coord = _normalize_coord_dict(self.coord, field_name="anchor.coord")
        if self.kind not in {"exit", "return", "transition"}:
            raise ValueError("anchor kind must be one of exit|return|transition")
        if not isinstance(self.target, dict):
            raise ValueError("anchor.target must be an object")
        target_type = str(self.target.get("type", ""))
        if target_type not in {"space", "site"}:
            raise ValueError("anchor.target.type must be space or site")
        normalized_target: dict[str, Any] = {"type": target_type}
        if target_type == "space":
            space_id = self.target.get("space_id")
            if not isinstance(space_id, str) or not space_id:
                raise ValueError("anchor.target.space_id must be a non-empty string")
            normalized_target["space_id"] = space_id
        else:
            site_id = self.target.get("site_id")
            if not isinstance(site_id, str) or not site_id:
                raise ValueError("anchor.target.site_id must be a non-empty string")
            normalized_target["site_id"] = site_id
            if isinstance(self.target.get("space_id"), str) and self.target.get("space_id"):
                normalized_target["space_id"] = str(self.target["space_id"])
        self.target = normalized_target
        _validate_json_value(self.metadata, field_name="anchor.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "space_id": self.space_id,
            "coord": dict(self.coord),
            "kind": self.kind,
            "target": dict(self.target),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnchorRecord":
        return cls(
            anchor_id=str(data["anchor_id"]),
            space_id=str(data["space_id"]),
            coord=dict(data["coord"]),
            kind=str(data["kind"]),
            target=dict(data["target"]),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class InteractableRecord:
    interactable_id: str
    space_id: str
    coord: dict[str, int]
    kind: str
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.interactable_id, str) or not self.interactable_id:
            raise ValueError("interactable_id must be a non-empty string")
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        self.coord = _normalize_coord_dict(self.coord, field_name="interactable.coord")
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("interactable kind must be a non-empty string")
        if not isinstance(self.state, dict):
            raise ValueError("interactable state must be an object")
        _validate_json_value(self.state, field_name="interactable.state")
        _validate_json_value(self.metadata, field_name="interactable.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "interactable_id": self.interactable_id,
            "space_id": self.space_id,
            "coord": dict(self.coord),
            "kind": self.kind,
            "state": dict(self.state),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InteractableRecord":
        return cls(
            interactable_id=str(data["interactable_id"]),
            space_id=str(data["space_id"]),
            coord=dict(data["coord"]),
            kind=str(data["kind"]),
            state=dict(data.get("state", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SpaceState:
    space_id: str
    topology_type: str
    role: str = LOCAL_SPACE_ROLE
    topology_params: dict[str, Any] = field(default_factory=dict)
    hexes: dict[HexCoord, HexRecord] = field(default_factory=dict)
    doors: dict[str, DoorRecord] = field(default_factory=dict)
    anchors: dict[str, AnchorRecord] = field(default_factory=dict)
    interactables: dict[str, InteractableRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.role = str(self.role)
        if self.role not in SPACE_ROLES:
            raise ValueError(f"space.role must be one of {sorted(SPACE_ROLES)}")
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            self.topology_params = self._normalized_square_topology_params(self.topology_params)
        self._normalize_space_records()

    def _normalize_space_records(self) -> None:
        normalized_doors: dict[str, DoorRecord] = {}
        for door_id, record in self.doors.items():
            normalized_id = str(door_id)
            normalized = record if isinstance(record, DoorRecord) else DoorRecord.from_dict(dict(record))
            if normalized.door_id != normalized_id:
                raise ValueError("door record id mismatch")
            if normalized.space_id != self.space_id:
                raise ValueError("door record space_id mismatch")
            if not self.is_valid_cell(normalized.a) or not self.is_valid_cell(normalized.b):
                raise ValueError("door endpoints must reference valid cells")
            normalized_doors[normalized_id] = normalized
        self.doors = normalized_doors

        normalized_anchors: dict[str, AnchorRecord] = {}
        for anchor_id, record in self.anchors.items():
            normalized_id = str(anchor_id)
            normalized = record if isinstance(record, AnchorRecord) else AnchorRecord.from_dict(dict(record))
            if normalized.anchor_id != normalized_id:
                raise ValueError("anchor record id mismatch")
            if normalized.space_id != self.space_id:
                raise ValueError("anchor record space_id mismatch")
            if not self.is_valid_cell(normalized.coord):
                raise ValueError("anchor coord must reference a valid cell")
            normalized_anchors[normalized_id] = normalized
        self.anchors = normalized_anchors

        normalized_interactables: dict[str, InteractableRecord] = {}
        for interactable_id, record in self.interactables.items():
            normalized_id = str(interactable_id)
            normalized = (
                record if isinstance(record, InteractableRecord) else InteractableRecord.from_dict(dict(record))
            )
            if normalized.interactable_id != normalized_id:
                raise ValueError("interactable record id mismatch")
            if normalized.space_id != self.space_id:
                raise ValueError("interactable record space_id mismatch")
            if not self.is_valid_cell(normalized.coord):
                raise ValueError("interactable coord must reference a valid cell")
            normalized_interactables[normalized_id] = normalized
        self.interactables = normalized_interactables

    @staticmethod
    def _normalized_square_topology_params(topology_params: dict[str, Any]) -> dict[str, Any]:
        width = int(topology_params.get("width", 0))
        height = int(topology_params.get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError("square_grid topology requires width > 0 and height > 0")
        origin = topology_params.get("origin", {"x": 0, "y": 0})
        if not isinstance(origin, dict):
            raise ValueError("square_grid origin must be an object")
        origin_x = int(origin.get("x", 0))
        origin_y = int(origin.get("y", 0))
        return {
            "width": width,
            "height": height,
            "origin": {"x": origin_x, "y": origin_y},
        }

    def is_valid_cell(self, coord: dict[str, Any]) -> bool:
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            try:
                x = int(coord["x"])
                y = int(coord["y"])
            except (KeyError, TypeError, ValueError):
                return False
            params = self._normalized_square_topology_params(self.topology_params)
            origin = params["origin"]
            return (
                origin["x"] <= x < origin["x"] + params["width"]
                and origin["y"] <= y < origin["y"] + params["height"]
            )
        try:
            return HexCoord.from_dict(coord) in self.hexes
        except (KeyError, TypeError, ValueError):
            return False

    def iter_cells(self) -> list[dict[str, int]]:
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            params = self._normalized_square_topology_params(self.topology_params)
            origin = params["origin"]
            return [
                {"x": x, "y": y}
                for y in range(origin["y"], origin["y"] + params["height"])
                for x in range(origin["x"], origin["x"] + params["width"])
            ]
        return [coord.to_dict() for coord in sorted(self.hexes)]

    def default_spawn_coord(self) -> dict[str, int]:
        spawn = self.topology_params.get("spawn") if isinstance(self.topology_params, dict) else None
        if isinstance(spawn, dict) and self.is_valid_cell(spawn):
            return dict(spawn)
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            params = self._normalized_square_topology_params(self.topology_params)
            origin = params["origin"]
            return {"x": origin["x"], "y": origin["y"]}
        return {"q": 0, "r": 0}

    def to_dict(self) -> dict[str, Any]:
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        payload = {
            "space_id": self.space_id,
            "topology_type": self.topology_type,
            "role": self.role,
            "topology_params": dict(self.topology_params),
            "hexes": hex_rows,
        }
        if self.doors:
            payload["doors"] = {record_id: self.doors[record_id].to_dict() for record_id in sorted(self.doors)}
        if self.anchors:
            payload["anchors"] = {record_id: self.anchors[record_id].to_dict() for record_id in sorted(self.anchors)}
        if self.interactables:
            payload["interactables"] = {
                record_id: self.interactables[record_id].to_dict() for record_id in sorted(self.interactables)
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpaceState":
        space_id = str(data["space_id"])
        role_raw = data.get("role")
        if role_raw is None:
            role = CAMPAIGN_SPACE_ROLE if space_id == DEFAULT_OVERWORLD_SPACE_ID else LOCAL_SPACE_ROLE
        else:
            role = str(role_raw)
        space = cls(
            space_id=space_id,
            topology_type=str(data.get("topology_type", "custom")),
            role=role,
            topology_params=dict(data.get("topology_params", {})),
        )
        for row in data.get("hexes", []):
            coord = HexCoord.from_dict(row["coord"])
            record = HexRecord.from_dict(row["record"])
            space.hexes[coord] = record
        space.doors = {
            str(door_id): DoorRecord.from_dict(dict(row)) for door_id, row in dict(data.get("doors", {})).items()
        }
        space.anchors = {
            str(anchor_id): AnchorRecord.from_dict(dict(row)) for anchor_id, row in dict(data.get("anchors", {})).items()
        }
        space.interactables = {
            str(interactable_id): InteractableRecord.from_dict(dict(row))
            for interactable_id, row in dict(data.get("interactables", {})).items()
        }
        space._normalize_space_records()
        return space


@dataclass
class ContainerState:
    container_id: str
    location: dict[str, Any] | None = None
    owner_entity_id: str | None = None
    items: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.container_id, str) or not self.container_id:
            raise ValueError("container_id must be a non-empty string")
        if self.location is not None and not isinstance(self.location, dict):
            raise ValueError("container location must be an object when present")
        if self.owner_entity_id is not None and (not isinstance(self.owner_entity_id, str) or not self.owner_entity_id):
            raise ValueError("owner_entity_id must be a non-empty string when present")

        normalized_items: dict[str, int] = {}
        for item_id, quantity in self.items.items():
            if not isinstance(item_id, str) or not item_id:
                raise ValueError("container item_id keys must be non-empty strings")
            if not isinstance(quantity, int):
                raise ValueError("container item quantities must be integers")
            if quantity < 0:
                raise ValueError("container item quantities must be >= 0")
            if quantity > 0:
                normalized_items[item_id] = quantity
        self.items = normalized_items

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "container_id": self.container_id,
            "items": {item_id: self.items[item_id] for item_id in sorted(self.items)},
        }
        if self.location is not None:
            payload["location"] = dict(self.location)
        if self.owner_entity_id is not None:
            payload["owner_entity_id"] = self.owner_entity_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContainerState":
        return cls(
            container_id=str(data["container_id"]),
            location=(dict(data["location"]) if data.get("location") is not None else None),
            owner_entity_id=(str(data["owner_entity_id"]) if data.get("owner_entity_id") is not None else None),
            items=dict(data.get("items", {})),
        )


@dataclass
class SiteRecord:
    site_id: str
    site_type: str
    location: dict[str, Any]
    name: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    entrance: dict[str, Any] | None = None
    site_state: "SiteWorldState" = field(default_factory=lambda: SiteWorldState())

    def __post_init__(self) -> None:
        if not isinstance(self.site_id, str) or not self.site_id:
            raise ValueError("site_id must be a non-empty string")
        if not isinstance(self.site_type, str) or not self.site_type:
            raise ValueError("site_type must be a non-empty string")
        if not isinstance(self.location, dict):
            raise ValueError("location must be an object")
        if not isinstance(self.location.get("space_id"), str) or not self.location.get("space_id"):
            raise ValueError("location.space_id must be a non-empty string")
        coord = self.location.get("coord")
        if not isinstance(coord, dict):
            raise ValueError("location.coord must be an object")
        if self.name is not None and not isinstance(self.name, str):
            raise ValueError("name must be a string when present")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("description must be a string when present")
        if not isinstance(self.tags, list):
            raise ValueError("tags must be a list")
        normalized_tags = sorted({str(tag) for tag in self.tags})
        self.tags = normalized_tags
        if self.entrance is not None:
            if not isinstance(self.entrance, dict):
                raise ValueError("entrance must be an object when present")
            target_space_id = self.entrance.get("target_space_id")
            if not isinstance(target_space_id, str) or not target_space_id:
                raise ValueError("entrance.target_space_id must be a non-empty string")
            spawn = self.entrance.get("spawn")
            if spawn is not None and not isinstance(spawn, dict):
                raise ValueError("entrance.spawn must be an object when present")
        if not isinstance(self.site_state, SiteWorldState):
            if isinstance(self.site_state, dict):
                self.site_state = SiteWorldState.from_dict(self.site_state)
            else:
                raise ValueError("site_state must be a SiteWorldState or object payload")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "site_id": self.site_id,
            "site_type": self.site_type,
            "location": dict(self.location),
            "tags": list(self.tags),
        }
        if self.name is not None:
            payload["name"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        if self.entrance is not None:
            payload["entrance"] = {
                "target_space_id": self.entrance["target_space_id"],
                "spawn": dict(self.entrance["spawn"]) if isinstance(self.entrance.get("spawn"), dict) else None,
            }
        if not self.site_state.is_default():
            payload["site_state"] = self.site_state.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SiteRecord":
        entrance_payload = data.get("entrance")
        entrance: dict[str, Any] | None
        if entrance_payload is None:
            entrance = None
        else:
            entrance = {
                "target_space_id": str(entrance_payload["target_space_id"]),
                "spawn": (
                    dict(entrance_payload["spawn"])
                    if isinstance(entrance_payload.get("spawn"), dict)
                    else None
                ),
            }
        return cls(
            site_id=str(data["site_id"]),
            site_type=str(data["site_type"]),
            location=dict(data["location"]),
            name=(str(data["name"]) if data.get("name") is not None else None),
            description=(str(data["description"]) if data.get("description") is not None else None),
            tags=[str(tag) for tag in data.get("tags", [])],
            entrance=entrance,
            site_state=SiteWorldState.from_dict(dict(data.get("site_state", {}))),
        )


@dataclass
class SitePressureRecord:
    faction_id: str
    pressure_type: str
    strength: int
    source_event_id: str | None = None
    tick: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.faction_id, str) or not self.faction_id:
            raise ValueError("faction_id must be a non-empty string")
        if not isinstance(self.pressure_type, str) or not self.pressure_type:
            raise ValueError("pressure_type must be a non-empty string")
        if isinstance(self.strength, bool) or not isinstance(self.strength, int):
            raise ValueError("strength must be an integer")
        if self.source_event_id is not None and (not isinstance(self.source_event_id, str) or not self.source_event_id):
            raise ValueError("source_event_id must be a non-empty string when present")
        if isinstance(self.tick, bool) or not isinstance(self.tick, int):
            raise ValueError("tick must be an integer")
        if self.tick < 0:
            raise ValueError("tick must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "faction_id": self.faction_id,
            "pressure_type": self.pressure_type,
            "strength": self.strength,
            "tick": self.tick,
        }
        if self.source_event_id is not None:
            payload["source_event_id"] = self.source_event_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SitePressureRecord":
        return cls(
            faction_id=str(data["faction_id"]),
            pressure_type=str(data["pressure_type"]),
            strength=int(data["strength"]),
            source_event_id=(str(data["source_event_id"]) if data.get("source_event_id") is not None else None),
            tick=int(data.get("tick", 0)),
        )


@dataclass
class SiteWorldState:
    owner_faction_id: str | None = None
    pressure_records: list[SitePressureRecord] = field(default_factory=list)
    condition_markers: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.owner_faction_id is not None and (
            not isinstance(self.owner_faction_id, str) or not self.owner_faction_id
        ):
            raise ValueError("owner_faction_id must be a non-empty string when present")

        normalized_pressure_records: list[SitePressureRecord] = []
        for record in self.pressure_records:
            normalized = record if isinstance(record, SitePressureRecord) else SitePressureRecord.from_dict(dict(record))
            normalized_pressure_records.append(normalized)
        if len(normalized_pressure_records) > MAX_SITE_PRESSURE_RECORDS:
            normalized_pressure_records = normalized_pressure_records[-MAX_SITE_PRESSURE_RECORDS:]
        self.pressure_records = normalized_pressure_records

        if not isinstance(self.condition_markers, list):
            raise ValueError("condition_markers must be a list")
        normalized_markers: list[str] = []
        for marker in self.condition_markers:
            marker_id = str(marker).strip()
            if not marker_id:
                raise ValueError("condition_markers values must be non-empty strings")
            normalized_markers.append(marker_id)
        if len(normalized_markers) > MAX_SITE_CONDITION_MARKERS:
            normalized_markers = normalized_markers[-MAX_SITE_CONDITION_MARKERS:]
        self.condition_markers = normalized_markers


    def is_default(self) -> bool:
        return (
            self.owner_faction_id is None
            and not self.pressure_records
            and not self.condition_markers
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pressure_records": [record.to_dict() for record in self.pressure_records],
            "condition_markers": list(self.condition_markers),
        }
        if self.owner_faction_id is not None:
            payload["owner_faction_id"] = self.owner_faction_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SiteWorldState":
        return cls(
            owner_faction_id=(str(data["owner_faction_id"]) if data.get("owner_faction_id") is not None else None),
            pressure_records=[
                SitePressureRecord.from_dict(dict(row))
                for row in list(data.get("pressure_records", []))
            ],
            condition_markers=[str(marker) for marker in list(data.get("condition_markers", []))],
        )


@dataclass
class GroupRecord:
    group_id: str
    group_type: str
    location: dict[str, Any]
    cell: dict[str, Any] | None = None
    moving: dict[str, Any] | None = None
    last_arrival_uid: str | None = None
    strength: int = 0
    tags: list[str] = field(default_factory=list)
    home_site_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id:
            raise ValueError("group_id must be a non-empty string")
        if not isinstance(self.group_type, str) or not self.group_type:
            raise ValueError("group_type must be a non-empty string")
        if not isinstance(self.location, dict):
            raise ValueError("location must be an object")
        if not isinstance(self.location.get("space_id"), str) or not self.location.get("space_id"):
            raise ValueError("location.space_id must be a non-empty string")
        coord = self.location.get("coord")
        if not isinstance(coord, dict):
            raise ValueError("location.coord must be an object")
        _validate_json_value(coord, field_name="group.location.coord")
        if self.cell is None:
            self.cell = copy.deepcopy(coord)
        if not isinstance(self.cell, dict):
            raise ValueError("cell must be an object")
        _validate_json_value(self.cell, field_name="group.cell")
        self.location["coord"] = copy.deepcopy(self.cell)
        if self.moving is not None:
            if not isinstance(self.moving, dict):
                raise ValueError("moving must be an object when present")
            if set(self.moving) != {"dest_cell", "depart_tick", "arrive_tick", "move_uid"}:
                raise ValueError("moving must contain exactly: dest_cell, depart_tick, arrive_tick, move_uid")
            dest_cell = self.moving["dest_cell"]
            if not isinstance(dest_cell, dict):
                raise ValueError("moving.dest_cell must be an object")
            if set(dest_cell) != {"space_id", "coord"}:
                raise ValueError("moving.dest_cell must contain exactly: space_id, coord")
            if not isinstance(dest_cell.get("space_id"), str) or not dest_cell.get("space_id"):
                raise ValueError("moving.dest_cell.space_id must be a non-empty string")
            _validate_json_value(dest_cell.get("coord"), field_name="group.moving.dest_cell.coord")
            if isinstance(self.moving["depart_tick"], bool) or not isinstance(self.moving["depart_tick"], int):
                raise ValueError("moving.depart_tick must be an integer")
            if isinstance(self.moving["arrive_tick"], bool) or not isinstance(self.moving["arrive_tick"], int):
                raise ValueError("moving.arrive_tick must be an integer")
            if self.moving["arrive_tick"] < self.moving["depart_tick"]:
                raise ValueError("moving.arrive_tick must be >= moving.depart_tick")
            if not isinstance(self.moving["move_uid"], str) or not self.moving["move_uid"]:
                raise ValueError("moving.move_uid must be a non-empty string")
            self.moving = {
                "dest_cell": {"space_id": str(dest_cell["space_id"]), "coord": copy.deepcopy(dest_cell["coord"])},
                "depart_tick": int(self.moving["depart_tick"]),
                "arrive_tick": int(self.moving["arrive_tick"]),
                "move_uid": str(self.moving["move_uid"]),
            }
        if self.last_arrival_uid is not None and (not isinstance(self.last_arrival_uid, str) or not self.last_arrival_uid):
            raise ValueError("last_arrival_uid must be a non-empty string when present")
        if isinstance(self.strength, bool) or not isinstance(self.strength, int):
            raise ValueError("strength must be an integer")
        if self.strength < 0:
            raise ValueError("strength must be >= 0")
        if not isinstance(self.tags, list):
            raise ValueError("tags must be a list")
        normalized_tags = sorted({str(tag) for tag in self.tags})
        self.tags = normalized_tags
        if self.home_site_key is not None and (not isinstance(self.home_site_key, str) or not self.home_site_key):
            raise ValueError("home_site_key must be a non-empty string when present")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "group_id": self.group_id,
            "group_type": self.group_type,
            "location": {
                "space_id": str(self.location["space_id"]),
                "coord": copy.deepcopy(self.cell),
            },
            "cell": copy.deepcopy(self.cell),
            "strength": int(self.strength),
            "tags": list(self.tags),
        }
        if self.moving is not None:
            payload["moving"] = copy.deepcopy(self.moving)
        if self.last_arrival_uid is not None:
            payload["last_arrival_uid"] = self.last_arrival_uid
        if self.home_site_key is not None:
            payload["home_site_key"] = self.home_site_key
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroupRecord":
        moving_raw = data.get("moving")
        if moving_raw is not None and not isinstance(moving_raw, dict):
            raise ValueError("moving must be an object when present")
        cell_raw = data.get("cell")
        if cell_raw is not None and not isinstance(cell_raw, dict):
            raise ValueError("cell must be an object when present")
        return cls(
            group_id=str(data.get("group_id", "")),
            group_type=str(data["group_type"]),
            location={
                "space_id": str(dict(data["location"])["space_id"]),
                "coord": copy.deepcopy(dict(data["location"])["coord"]),
            },
            cell=(copy.deepcopy(cell_raw) if isinstance(cell_raw, dict) else None),
            moving=(copy.deepcopy(moving_raw) if isinstance(moving_raw, dict) else None),
            last_arrival_uid=(
                str(data["last_arrival_uid"]) if data.get("last_arrival_uid") is not None else None
            ),
            strength=int(data.get("strength", 0)),
            tags=[str(tag) for tag in data.get("tags", [])],
            home_site_key=(str(data["home_site_key"]) if data.get("home_site_key") is not None else None),
        )


@dataclass
class WorldState:
    hexes: dict[HexCoord, HexRecord] = field(default_factory=dict)
    topology_type: str = "custom"
    topology_params: dict[str, int] = field(default_factory=dict)
    spaces: dict[str, SpaceState] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    structure_occlusion: list[dict[str, Any]] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)
    spawn_descriptors: list[dict[str, Any]] = field(default_factory=list)
    rumors: list[dict[str, Any]] = field(default_factory=list)
    containers: dict[str, ContainerState] = field(default_factory=dict)
    sites: dict[str, SiteRecord] = field(default_factory=dict)
    groups: dict[str, GroupRecord] = field(default_factory=dict)
    claim_opportunities: list[dict[str, Any]] = field(default_factory=list)
    rumor_ttl_config: dict[str, Any] = field(default_factory=lambda: _normalize_rumor_ttl_config(DEFAULT_RUMOR_TTL_CONFIG))
    rumor_selection_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    rumor_selection_decision_order: list[str] = field(default_factory=list)
    rumor_decay_cursor: int = 0
    faction_registry: list[str] = field(default_factory=list)
    activated_factions: list[str] = field(default_factory=list)
    faction_beliefs: dict[str, dict[str, Any]] = field(default_factory=dict)
    belief_enqueue_config: dict[str, dict[str, int]] = field(default_factory=dict)
    belief_geo_gating_config: dict[str, Any] = field(default_factory=dict)
    belief_reaction_config: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_BELIEF_REACTION_CONFIG))
    faction_contacts: dict[str, list[str]] = field(default_factory=dict)
    faction_contact_meta: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    contact_ttl_config: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONTACT_TTL_CONFIG))
    _faction_registry_authored: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.rumor_ttl_config = _normalize_rumor_ttl_config(self.rumor_ttl_config)
        self.faction_beliefs = normalize_world_faction_beliefs(self.faction_beliefs)
        self.faction_registry = normalize_faction_registry(self.faction_registry)
        if self.faction_registry:
            self._faction_registry_authored = True
        if not self.faction_registry and self.faction_beliefs:
            self.faction_registry = sorted(self.faction_beliefs)
        self.activated_factions = normalize_activated_factions(
            self.activated_factions,
            faction_registry=self.faction_registry,
        )
        self.belief_enqueue_config = normalize_belief_enqueue_config(self.belief_enqueue_config)
        self.belief_geo_gating_config = normalize_belief_geo_gating_config(self.belief_geo_gating_config)
        self.belief_reaction_config = normalize_belief_reaction_config(self.belief_reaction_config)
        self.faction_contacts = normalize_faction_contacts(
            self.faction_contacts,
            faction_registry=self.faction_registry,
        )
        self.faction_contact_meta = normalize_faction_contact_meta(
            self.faction_contact_meta,
            faction_registry=self.faction_registry,
            faction_contacts=self.faction_contacts,
        )
        self.contact_ttl_config = normalize_contact_ttl_config(self.contact_ttl_config)
        if self.spaces:
            overworld_space = self.spaces.get(DEFAULT_OVERWORLD_SPACE_ID)
            if overworld_space is None:
                raise ValueError(f"spaces must include default '{DEFAULT_OVERWORLD_SPACE_ID}' space")
            self.hexes = overworld_space.hexes
            self.topology_type = overworld_space.topology_type
            self.topology_params = dict(overworld_space.topology_params)
            self._ensure_closed_door_occlusion_defaults()
            return
        self.spaces[DEFAULT_OVERWORLD_SPACE_ID] = SpaceState(
            space_id=DEFAULT_OVERWORLD_SPACE_ID,
            topology_type=self.topology_type,
            role=CAMPAIGN_SPACE_ROLE,
            topology_params=dict(self.topology_params),
            hexes=self.hexes,
        )
        self._ensure_closed_door_occlusion_defaults()

    @classmethod
    def create_with_topology(
        cls,
        master_seed: int,
        topology_type: str,
        topology_params: dict[str, int],
    ) -> "WorldState":
        rng_worldgen = random.Random(
            derive_stream_seed(master_seed=master_seed, stream_name=RNG_WORLDGEN_STREAM_NAME)
        )
        if topology_type == "hex_disk":
            radius = int(topology_params["radius"])
            hexes = generate_hex_disk(radius=radius, rng_worldgen=rng_worldgen)
        elif topology_type == "hex_rectangle":
            width = int(topology_params["width"])
            height = int(topology_params["height"])
            hexes = generate_hex_rectangle(width=width, height=height, rng_worldgen=rng_worldgen)
        else:
            raise ValueError(f"unsupported topology_type: {topology_type}")

        return cls(hexes=hexes, topology_type=topology_type, topology_params=dict(topology_params))

    def set_hex_record(self, coord: HexCoord, record: HexRecord) -> None:
        self.hexes[coord] = record

    def get_hex_record(self, coord: HexCoord) -> HexRecord | None:
        return self.hexes.get(coord)

    def to_legacy_dict(self) -> dict[str, Any]:
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        payload = {
            "topology_type": self.topology_type,
            "topology_params": self.topology_params,
            "hexes": hex_rows,
        }
        if self.signals:
            payload["signals"] = sorted(
                (dict(record) for record in self.signals),
                key=lambda record: str(record.get("signal_id", record.get("signal_uid", ""))),
            )
        if self.tracks:
            payload["tracks"] = sorted(
                (dict(record) for record in self.tracks),
                key=lambda record: str(record.get("track_uid", "")),
            )
        if self.spawn_descriptors:
            payload["spawn_descriptors"] = [dict(record) for record in self.spawn_descriptors]
        if self.rumors:
            payload["rumors"] = [RumorRecord.from_dict(record).to_dict() for record in self.rumors]
        if self.containers:
            payload["containers"] = {
                container_id: self.containers[container_id].to_dict()
                for container_id in sorted(self.containers)
            }
        if self.sites:
            payload["sites"] = {
                site_id: self.sites[site_id].to_dict()
                for site_id in sorted(self.sites)
            }
        if self.groups:
            payload["groups"] = {
                group_id: self.groups[group_id].to_dict()
                for group_id in sorted(self.groups)
            }
        if self.claim_opportunities:
            payload["claim_opportunities"] = [
                _normalize_claim_opportunity_record(row)
                for row in self.claim_opportunities
            ]
        normalized_rumor_ttl_config = _normalize_rumor_ttl_config(self.rumor_ttl_config)
        if normalized_rumor_ttl_config != _normalize_rumor_ttl_config(DEFAULT_RUMOR_TTL_CONFIG):
            payload["rumor_ttl_config"] = normalized_rumor_ttl_config
        if self.rumor_selection_decision_order:
            payload["rumor_selection_decision_order"] = list(self.rumor_selection_decision_order)
        if self.rumor_selection_decisions:
            payload["rumor_selection_decisions"] = {
                decision_key: _normalize_rumor_selection_decision_record(self.rumor_selection_decisions[decision_key])
                for decision_key in sorted(self.rumor_selection_decisions)
            }
        if self.rumor_decay_cursor > 0:
            payload["rumor_decay_cursor"] = int(self.rumor_decay_cursor)
        if self.faction_beliefs:
            payload["faction_beliefs"] = {
                faction_id: dict(self.faction_beliefs[faction_id])
                for faction_id in sorted(self.faction_beliefs)
            }
        if self._faction_registry_authored:
            payload["faction_registry"] = list(self.faction_registry)
        if self.activated_factions:
            payload["activated_factions"] = list(self.activated_factions)
        if self.belief_enqueue_config:
            payload["belief_enqueue_config"] = normalize_belief_enqueue_config(self.belief_enqueue_config)
        if self.belief_geo_gating_config:
            payload["belief_geo_gating_config"] = normalize_belief_geo_gating_config(self.belief_geo_gating_config)
        normalized_belief_reaction_config = normalize_belief_reaction_config(self.belief_reaction_config)
        if normalized_belief_reaction_config != DEFAULT_BELIEF_REACTION_CONFIG:
            payload["belief_reaction_config"] = normalized_belief_reaction_config
        if self.faction_contacts:
            payload["faction_contacts"] = {
                source_faction_id: list(self.faction_contacts[source_faction_id])
                for source_faction_id in sorted(self.faction_contacts)
            }
        if self.faction_contact_meta:
            payload["faction_contact_meta"] = {
                source_faction_id: {
                    target_faction_id: dict(self.faction_contact_meta[source_faction_id][target_faction_id])
                    for target_faction_id in sorted(self.faction_contact_meta[source_faction_id])
                }
                for source_faction_id in sorted(self.faction_contact_meta)
            }
        normalized_contact_ttl_config = normalize_contact_ttl_config(self.contact_ttl_config)
        if normalized_contact_ttl_config != DEFAULT_CONTACT_TTL_CONFIG:
            payload["contact_ttl_config"] = normalized_contact_ttl_config
        return payload

    def to_dict(self) -> dict[str, Any]:
        spaces_payload = [
            self.spaces[space_id].to_dict()
            for space_id in sorted(self.spaces)
        ]
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        payload = {
            "topology_type": self.topology_type,
            "topology_params": self.topology_params,
            "hexes": hex_rows,
            "spaces": spaces_payload,
        }
        if self.signals:
            payload["signals"] = sorted(
                (dict(record) for record in self.signals),
                key=lambda record: str(record.get("signal_id", record.get("signal_uid", ""))),
            )
        if self.structure_occlusion:
            payload["structure_occlusion"] = sorted(
                (dict(record) for record in self.structure_occlusion),
                key=lambda record: canonical_occlusion_edge_key(
                    str(record.get("space_id", "")),
                    dict(record.get("cell_a", {})),
                    dict(record.get("cell_b", {})),
                ),
            )
        if self.tracks:
            payload["tracks"] = sorted(
                (dict(record) for record in self.tracks),
                key=lambda record: str(record.get("track_uid", "")),
            )
        if self.spawn_descriptors:
            payload["spawn_descriptors"] = [dict(record) for record in self.spawn_descriptors]
        if self.rumors:
            payload["rumors"] = [RumorRecord.from_dict(record).to_dict() for record in self.rumors]
        if self.containers:
            payload["containers"] = {
                container_id: self.containers[container_id].to_dict()
                for container_id in sorted(self.containers)
            }
        if self.sites:
            payload["sites"] = {
                site_id: self.sites[site_id].to_dict()
                for site_id in sorted(self.sites)
            }
        if self.groups:
            payload["groups"] = {
                group_id: self.groups[group_id].to_dict()
                for group_id in sorted(self.groups)
            }
        if self.claim_opportunities:
            payload["claim_opportunities"] = [
                _normalize_claim_opportunity_record(row)
                for row in self.claim_opportunities
            ]
        normalized_rumor_ttl_config = _normalize_rumor_ttl_config(self.rumor_ttl_config)
        if normalized_rumor_ttl_config != _normalize_rumor_ttl_config(DEFAULT_RUMOR_TTL_CONFIG):
            payload["rumor_ttl_config"] = normalized_rumor_ttl_config
        if self.rumor_selection_decision_order:
            payload["rumor_selection_decision_order"] = list(self.rumor_selection_decision_order)
        if self.rumor_selection_decisions:
            payload["rumor_selection_decisions"] = {
                decision_key: _normalize_rumor_selection_decision_record(self.rumor_selection_decisions[decision_key])
                for decision_key in sorted(self.rumor_selection_decisions)
            }
        if self.rumor_decay_cursor > 0:
            payload["rumor_decay_cursor"] = int(self.rumor_decay_cursor)
        if self.faction_beliefs:
            payload["faction_beliefs"] = {
                faction_id: dict(self.faction_beliefs[faction_id])
                for faction_id in sorted(self.faction_beliefs)
            }
        if self._faction_registry_authored:
            payload["faction_registry"] = list(self.faction_registry)
        if self.activated_factions:
            payload["activated_factions"] = list(self.activated_factions)
        if self.belief_enqueue_config:
            payload["belief_enqueue_config"] = normalize_belief_enqueue_config(self.belief_enqueue_config)
        if self.belief_geo_gating_config:
            payload["belief_geo_gating_config"] = normalize_belief_geo_gating_config(self.belief_geo_gating_config)
        normalized_belief_reaction_config = normalize_belief_reaction_config(self.belief_reaction_config)
        if normalized_belief_reaction_config != DEFAULT_BELIEF_REACTION_CONFIG:
            payload["belief_reaction_config"] = normalized_belief_reaction_config
        if self.faction_contacts:
            payload["faction_contacts"] = {
                source_faction_id: list(self.faction_contacts[source_faction_id])
                for source_faction_id in sorted(self.faction_contacts)
            }
        if self.faction_contact_meta:
            payload["faction_contact_meta"] = {
                source_faction_id: {
                    target_faction_id: dict(self.faction_contact_meta[source_faction_id][target_faction_id])
                    for target_faction_id in sorted(self.faction_contact_meta[source_faction_id])
                }
                for source_faction_id in sorted(self.faction_contact_meta)
            }
        normalized_contact_ttl_config = normalize_contact_ttl_config(self.contact_ttl_config)
        if normalized_contact_ttl_config != DEFAULT_CONTACT_TTL_CONFIG:
            payload["contact_ttl_config"] = normalized_contact_ttl_config
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldState":
        raw_spaces = data.get("spaces")
        if raw_spaces is None:
            world = cls(
                topology_type=str(data.get("topology_type", "custom")),
                topology_params=dict(data.get("topology_params", {})),
            )
            for row in data.get("hexes", []):
                coord = HexCoord.from_dict(row["coord"])
                record = HexRecord.from_dict(row["record"])
                world.set_hex_record(coord, record)
        else:
            if not isinstance(raw_spaces, list):
                raise ValueError("spaces must be a list")
            spaces: dict[str, SpaceState] = {}
            for entry in raw_spaces:
                if not isinstance(entry, dict):
                    raise ValueError("space entry must be an object")
                space = SpaceState.from_dict(entry)
                spaces[space.space_id] = space
            world = cls(spaces=spaces)
            legacy_hex_rows = data.get("hexes")
            if legacy_hex_rows is not None:
                legacy_world = cls(
                    topology_type=str(data.get("topology_type", world.topology_type)),
                    topology_params=dict(data.get("topology_params", world.topology_params)),
                )
                for row in legacy_hex_rows:
                    coord = HexCoord.from_dict(row["coord"])
                    record = HexRecord.from_dict(row["record"])
                    legacy_world.set_hex_record(coord, record)
                if legacy_world.to_legacy_dict() != world.to_legacy_dict():
                    raise ValueError("legacy overworld fields disagree with spaces.overworld payload")
        raw_signals = data.get("signals", [])
        if not isinstance(raw_signals, list):
            raise ValueError("signals must be a list")
        world.signals = [_normalize_signal_record(row) for row in raw_signals]
        if len(world.signals) > MAX_SIGNALS:
            world.signals = world.signals[-MAX_SIGNALS:]

        raw_structure_occlusion = data.get("structure_occlusion", [])
        if not isinstance(raw_structure_occlusion, list):
            raise ValueError("structure_occlusion must be a list")
        world.structure_occlusion = [_normalize_occlusion_edge_record(row) for row in raw_structure_occlusion]
        if len(world.structure_occlusion) > MAX_OCCLUSION_EDGES:
            world.structure_occlusion = world.structure_occlusion[-MAX_OCCLUSION_EDGES:]
        world._ensure_closed_door_occlusion_defaults()

        raw_tracks = data.get("tracks", [])
        if not isinstance(raw_tracks, list):
            raise ValueError("tracks must be a list")
        world.tracks = [dict(row) for row in raw_tracks]

        raw_spawn_descriptors = data.get("spawn_descriptors", [])
        if not isinstance(raw_spawn_descriptors, list):
            raise ValueError("spawn_descriptors must be a list")
        world.spawn_descriptors = [dict(row) for row in raw_spawn_descriptors]

        raw_rumors = data.get("rumors", [])
        if not isinstance(raw_rumors, list):
            raise ValueError("rumors must be a list")
        world.rumors = _normalize_rumor_records(raw_rumors)
        seen_rumor_ids: set[str] = set()
        for row in world.rumors:
            rumor_id = str(row["rumor_id"])
            if rumor_id in seen_rumor_ids:
                raise ValueError("rumor ids must be unique")
            seen_rumor_ids.add(rumor_id)

        raw_rumor_decay_cursor = data.get("rumor_decay_cursor", 0)
        if isinstance(raw_rumor_decay_cursor, bool) or not isinstance(raw_rumor_decay_cursor, int):
            raise ValueError("rumor_decay_cursor must be an integer")
        if raw_rumor_decay_cursor < 0:
            raise ValueError("rumor_decay_cursor must be >= 0")
        if world.rumors:
            world.rumor_decay_cursor = min(raw_rumor_decay_cursor, len(world.rumors) - 1)
        else:
            world.rumor_decay_cursor = 0

        raw_containers = data.get("containers", {})
        if not isinstance(raw_containers, dict):
            raise ValueError("containers must be an object")
        world.containers = {}
        for container_id in sorted(raw_containers):
            row = raw_containers[container_id]
            if not isinstance(row, dict):
                raise ValueError(f"container '{container_id}' must be an object")
            if "container_id" not in row:
                row = {**row, "container_id": container_id}
            container = ContainerState.from_dict(row)
            if container.container_id != container_id:
                raise ValueError(f"container key/id mismatch for '{container_id}'")
            world.containers[container_id] = container

        raw_sites = data.get("sites", {})
        if not isinstance(raw_sites, dict):
            raise ValueError("sites must be an object")
        world.sites = {}
        for site_id in sorted(raw_sites):
            row = raw_sites[site_id]
            if not isinstance(row, dict):
                raise ValueError(f"site '{site_id}' must be an object")
            if "site_id" not in row:
                row = {**row, "site_id": site_id}
            site = SiteRecord.from_dict(row)
            if site.site_id != site_id:
                raise ValueError(f"site key/id mismatch for '{site_id}'")
            world.sites[site_id] = site

        raw_groups = data.get("groups", {})
        if not isinstance(raw_groups, dict):
            raise ValueError("groups must be an object")
        world.groups = {}
        for group_id in sorted(raw_groups):
            row = raw_groups[group_id]
            if not isinstance(row, dict):
                raise ValueError(f"group '{group_id}' must be an object")
            if "group_id" not in row:
                row = {**row, "group_id": group_id}
            group = GroupRecord.from_dict(row)
            if group.group_id != group_id:
                raise ValueError(f"group key/id mismatch for '{group_id}'")
            world.groups[group_id] = group

        raw_claim_opportunities = data.get("claim_opportunities", [])
        if not isinstance(raw_claim_opportunities, list):
            raise ValueError("claim_opportunities must be a list")
        world.claim_opportunities = [
            _normalize_claim_opportunity_record(row)
            for row in raw_claim_opportunities
        ]
        if len(world.claim_opportunities) > MAX_CLAIM_OPPORTUNITIES:
            raise ValueError("claim_opportunities exceeds maximum")
        seen_opportunity_ids: set[str] = set()
        for row in world.claim_opportunities:
            opportunity_id = str(row["opportunity_id"])
            if opportunity_id in seen_opportunity_ids:
                raise ValueError("claim opportunity ids must be unique")
            seen_opportunity_ids.add(opportunity_id)

        world.rumor_ttl_config = _normalize_rumor_ttl_config(data.get("rumor_ttl_config", DEFAULT_RUMOR_TTL_CONFIG))

        world.faction_beliefs = normalize_world_faction_beliefs(data.get("faction_beliefs", {}))
        # Backward compatibility: old saves have no faction_registry. Derive from existing
        # faction_beliefs keys deterministically to preserve replay/save-load stability.
        faction_registry_authored = "faction_registry" in data
        raw_faction_registry = data.get("faction_registry")
        if raw_faction_registry is None:
            raw_faction_registry = sorted(world.faction_beliefs)
        world.faction_registry = normalize_faction_registry(raw_faction_registry)
        world._faction_registry_authored = faction_registry_authored
        world.activated_factions = normalize_activated_factions(
            data.get("activated_factions", []),
            faction_registry=world.faction_registry,
        )
        world.belief_enqueue_config = normalize_belief_enqueue_config(data.get("belief_enqueue_config", {}))
        world.belief_geo_gating_config = normalize_belief_geo_gating_config(data.get("belief_geo_gating_config", {}))
        world.belief_reaction_config = normalize_belief_reaction_config(data.get("belief_reaction_config", None))
        world.faction_contacts = normalize_faction_contacts(
            data.get("faction_contacts", {}),
            faction_registry=world.faction_registry,
        )
        world.faction_contact_meta = normalize_faction_contact_meta(
            data.get("faction_contact_meta", {}),
            faction_registry=world.faction_registry,
            faction_contacts=world.faction_contacts,
        )
        world.contact_ttl_config = normalize_contact_ttl_config(data.get("contact_ttl_config", None))

        raw_rumor_selection_decisions = data.get("rumor_selection_decisions", {})
        if not isinstance(raw_rumor_selection_decisions, dict):
            raise ValueError("rumor_selection_decisions must be an object")
        world.rumor_selection_decisions = {}
        for decision_key in sorted(raw_rumor_selection_decisions):
            row = raw_rumor_selection_decisions[decision_key]
            if not isinstance(decision_key, str) or not decision_key:
                raise ValueError("rumor_selection_decisions keys must be non-empty strings")
            world.rumor_selection_decisions[decision_key] = _normalize_rumor_selection_decision_record(row)
        if len(world.rumor_selection_decisions) > MAX_RUMOR_SELECTION_DECISIONS:
            raise ValueError("rumor_selection_decisions exceeds maximum")

        raw_decision_order = data.get("rumor_selection_decision_order")
        if raw_decision_order is None:
            world.rumor_selection_decision_order = sorted(world.rumor_selection_decisions)
        else:
            if not isinstance(raw_decision_order, list):
                raise ValueError("rumor_selection_decision_order must be a list")
            order: list[str] = []
            seen_order: set[str] = set()
            for decision_key in raw_decision_order:
                if not isinstance(decision_key, str) or not decision_key:
                    raise ValueError("rumor_selection_decision_order entries must be non-empty strings")
                if decision_key in seen_order:
                    raise ValueError("rumor_selection_decision_order entries must be unique")
                if decision_key not in world.rumor_selection_decisions:
                    raise ValueError("rumor_selection_decision_order references unknown decision key")
                seen_order.add(decision_key)
                order.append(decision_key)
            if len(order) != len(world.rumor_selection_decisions):
                raise ValueError("rumor_selection_decision_order must include every decision key")
            world.rumor_selection_decision_order = order
        return world

    def get_sites_at_location(self, location_ref: dict[str, Any]) -> list[SiteRecord]:
        space_id = str(location_ref.get("space_id", ""))
        coord = location_ref.get("coord")
        if not isinstance(coord, dict):
            return []
        matches = [
            site
            for site in self.sites.values()
            if site.location.get("space_id") == space_id and site.location.get("coord") == coord
        ]
        return sorted(matches, key=lambda site: site.site_id)

    def add_site_pressure(
        self,
        site_id: str,
        faction_id: str,
        pressure_type: str,
        strength: int,
        source_event_id: str | None = None,
        *,
        tick: int = 0,
    ) -> SitePressureRecord:
        if site_id not in self.sites:
            raise ValueError(f"unknown site_id '{site_id}'")
        record = SitePressureRecord(
            faction_id=faction_id,
            pressure_type=pressure_type,
            strength=strength,
            source_event_id=source_event_id,
            tick=tick,
        )
        site_state = self.sites[site_id].site_state
        site_state.pressure_records.append(record)
        if len(site_state.pressure_records) > MAX_SITE_PRESSURE_RECORDS:
            overflow = len(site_state.pressure_records) - MAX_SITE_PRESSURE_RECORDS
            del site_state.pressure_records[:overflow]
        return record

    def upsert_signal(self, record: dict[str, Any]) -> bool:
        signal_uid = str(record["signal_uid"])
        for existing in self.signals:
            if str(existing.get("signal_uid")) == signal_uid:
                return False
        self.signals.append(dict(record))
        return True

    def append_signal_record(self, record: dict[str, Any]) -> None:
        self.signals.append(_normalize_signal_record(record))
        if len(self.signals) > MAX_SIGNALS:
            del self.signals[: len(self.signals) - MAX_SIGNALS]

    def get_structure_occlusion_value(self, *, space_id: str, cell_a: dict[str, Any], cell_b: dict[str, Any]) -> int:
        edge_key = canonical_occlusion_edge_key(space_id, cell_a, cell_b)
        for record in self.structure_occlusion:
            if canonical_occlusion_edge_key(record["space_id"], record["cell_a"], record["cell_b"]) == edge_key:
                return int(record["occlusion_value"])
        return 0

    def set_structure_occlusion_edge(self, *, space_id: str, cell_a: dict[str, Any], cell_b: dict[str, Any], occlusion_value: int) -> None:
        normalized = _normalize_occlusion_edge_record(
            {
                "space_id": space_id,
                "cell_a": cell_a,
                "cell_b": cell_b,
                "occlusion_value": occlusion_value,
            }
        )
        edge_key = canonical_occlusion_edge_key(normalized["space_id"], normalized["cell_a"], normalized["cell_b"])
        for index, record in enumerate(self.structure_occlusion):
            existing_key = canonical_occlusion_edge_key(record["space_id"], record["cell_a"], record["cell_b"])
            if existing_key != edge_key:
                continue
            if normalized["occlusion_value"] <= 0:
                del self.structure_occlusion[index]
                return
            self.structure_occlusion[index] = normalized
            return
        if normalized["occlusion_value"] <= 0:
            return
        self.structure_occlusion.append(normalized)
        if len(self.structure_occlusion) > MAX_OCCLUSION_EDGES:
            del self.structure_occlusion[: len(self.structure_occlusion) - MAX_OCCLUSION_EDGES]

    def _ensure_closed_door_occlusion_defaults(self) -> None:
        for space_id in sorted(self.spaces):
            space = self.spaces[space_id]
            for door_id in sorted(space.doors):
                door = space.doors[door_id]
                if door.state != "closed":
                    continue
                edge_value = self.get_structure_occlusion_value(space_id=space_id, cell_a=door.a, cell_b=door.b)
                if edge_value > 0:
                    continue
                self.set_structure_occlusion_edge(
                    space_id=space_id,
                    cell_a=door.a,
                    cell_b=door.b,
                    occlusion_value=1,
                )

    def upsert_track(self, record: dict[str, Any]) -> bool:
        track_uid = str(record["track_uid"])
        for existing in self.tracks:
            if str(existing.get("track_uid")) == track_uid:
                return False
        self.tracks.append(dict(record))
        return True

    def append_spawn_descriptor(self, record: dict[str, Any]) -> None:
        self.spawn_descriptors.append(dict(record))

    def append_rumor(self, record: RumorRecord | dict[str, Any]) -> None:
        normalized = record if isinstance(record, RumorRecord) else RumorRecord.from_dict(record)
        rumor_id = normalized.rumor_id
        for existing in self.rumors:
            if str(existing.get("rumor_id", "")) == rumor_id:
                return
        self.rumors.append(normalized.to_dict())
        if len(self.rumors) > MAX_RUMORS:
            overflow = len(self.rumors) - MAX_RUMORS
            del self.rumors[:overflow]
            self.rumor_decay_cursor = max(0, self.rumor_decay_cursor - overflow)
        if self.rumors:
            self.rumor_decay_cursor = min(self.rumor_decay_cursor, len(self.rumors) - 1)
        else:
            self.rumor_decay_cursor = 0

    def upsert_rumor_selection_decision(self, *, decision_key: str, record: dict[str, Any]) -> bool:
        if not isinstance(decision_key, str) or not decision_key:
            raise ValueError("decision_key must be a non-empty string")
        normalized = _normalize_rumor_selection_decision_record(record)
        if decision_key in self.rumor_selection_decisions:
            self.rumor_selection_decisions[decision_key] = normalized
            return False
        self.rumor_selection_decisions[decision_key] = normalized
        self.rumor_selection_decision_order.append(decision_key)
        if len(self.rumor_selection_decision_order) > MAX_RUMOR_SELECTION_DECISIONS:
            overflow = len(self.rumor_selection_decision_order) - MAX_RUMOR_SELECTION_DECISIONS
            evicted = self.rumor_selection_decision_order[:overflow]
            del self.rumor_selection_decision_order[:overflow]
            for key in evicted:
                self.rumor_selection_decisions.pop(key, None)
        return True
