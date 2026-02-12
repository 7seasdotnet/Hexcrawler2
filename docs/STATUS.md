# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 1 (deterministic sim + minimal viewer)
- **Next action:** Extend serialization coverage for future schema migrations (v2+) while keeping deterministic replay guarantees.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, hashing.
- `src/hexcrawler/content/`
  - JSON schema validation + deterministic load/save helpers for world data.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller.
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical Phase 1 viewer with vector WASD input and right-click move command.
- `src/hexcrawler/__main__.py`
  - Package entrypoint routing to pygame viewer.
- `run_game.py`
  - Simple launch script that injects `src/` into `sys.path` and runs the pygame viewer.

## Progress
- ✅ Axial-coordinate hex world model implemented and keyed by `HexCoord`.
- ✅ Per-hex editable records implemented (`terrain_type`, `site_type`, `metadata`).
- ✅ Serialization contract (v1) implemented:
  - top-level `schema_version` required and validated,
  - top-level `world_hash` stored and fail-fast verified on load,
  - canonical JSON output (`sort_keys`, explicit `indent` + `separators`),
  - atomic save via same-directory temp file + `os.replace`.
- ✅ Deterministic fixed-tick simulation core implemented with sim-owned seeded RNG.
- ✅ Continuous sim-owned movement implemented with world-space float position.
- ✅ Viewer/controller separation preserved (viewer issues commands only).
- ✅ Mandatory tests implemented and passing, including serialization stability/verification checks.

## Out of Scope Kept
- No pathfinding, terrain costs, factions, combat, rumors, wounds, or armor systems in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `PYTHONPATH=src pytest -q`

## What Changed in This Commit
- Added schema-versioned save payloads with authoritative `world_hash` and strict load-time hash verification.
- Added canonical deterministic JSON and atomic save writes with temp-file cleanup on failure.
- Expanded save/load tests (schema_version, hash mismatch fail-fast, canonical stability, atomic write, metadata forward-compat preservation) and updated verification docs.
