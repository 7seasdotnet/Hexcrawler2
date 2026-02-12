# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 1 (deterministic sim + minimal viewer)
- **Next action:** Wire deterministic RNG streams into upcoming world-generation entrypoints while preserving strict sim-owned RNG boundaries.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, RNG stream derivation, hashing.
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
- ✅ Deterministic master-seed RNG stream separation implemented (`rng_worldgen`, `rng_sim`) via SHA-256 child seed derivation.
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
- Added deterministic stream-seed derivation helper using SHA-256 over `"{master_seed}:{stream_name}"` and wired simulation-owned `rng_sim` + `rng_worldgen` streams.
- Extended simulation hashing/state payload to include master seed and both RNG stream states.
- Added RNG stream tests for stable derivation, stream-name differentiation, and stream-separation butterfly-effect protection.
