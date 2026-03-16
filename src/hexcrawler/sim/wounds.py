from __future__ import annotations

from typing import Any

WOUND_MOVE_PENALTY_PER_SEVERITY = 0.25
WOUND_MOVE_MIN_MULTIPLIER = 0.0
WOUND_INCAPACITATE_SEVERITY = 3


def recover_one_light_wound(wounds: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return a copy of ``wounds`` with at most one light wound removed.

    Space roles:
    - campaign: used by campaign-role safe-site recovery/rest.
    - local: no direct use currently; kept topology-agnostic for future reuse.
    """

    normalized = [dict(wound) for wound in wounds if isinstance(wound, dict)]
    for index, wound in enumerate(normalized):
        severity = wound.get("severity")
        if isinstance(severity, int) and severity == 1:
            recovered = normalized.pop(index)
            return normalized, recovered
    return normalized, None


def movement_multiplier_from_wounds(wounds: list[dict[str, Any]]) -> float:
    """Deterministic movement consequence derived from serialized wound ledger.

    Space roles:
    - campaign: applies during campaign-role traversal movement resolution.
    - local: applies during local-role tactical movement resolution.
    """

    severity_total = 0
    for wound in wounds:
        if not isinstance(wound, dict):
            continue
        severity = wound.get("severity")
        if isinstance(severity, int) and severity > 0:
            severity_total += severity

    if severity_total >= WOUND_INCAPACITATE_SEVERITY:
        return WOUND_MOVE_MIN_MULTIPLIER

    multiplier = 1.0 - (float(severity_total) * WOUND_MOVE_PENALTY_PER_SEVERITY)
    return max(WOUND_MOVE_MIN_MULTIPLIER, multiplier)
