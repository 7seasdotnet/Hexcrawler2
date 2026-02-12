# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 1 (deterministic sim + minimal viewer)
- **Next action:** Keep Phase 1 focused by validating and tightening deterministic movement input replay coverage.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, hashing.
- `src/hexcrawler/content/`
  - JSON schema + load/save helpers for world data.
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
- ✅ JSON schema validation and load/save support implemented.
- ✅ Deterministic fixed-tick simulation core implemented with sim-owned seeded RNG.
- ✅ Continuous sim-owned movement implemented with world-space float position.
- ✅ Hex coordinate is now derived from world position via axial conversion.
- ✅ Vector-based WASD movement (normalized; no diagonal speed boost).
- ✅ Right-click context menu implemented with one option: `Move Here`.
- ✅ World-bounds enforcement implemented (movement blocked outside defined world hexes).
- ✅ HUD shows `CURRENT HEX`, `ticks`, and `day` (`tick // TICKS_PER_DAY`).
- ✅ Mandatory tests implemented and passing:
  - determinism hash test
  - save/load world hash round-trip test
  - continuous movement + bounds tests

## Out of Scope Kept
- No pathfinding, terrain costs, factions, combat, rumors, wounds, or armor systems in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `PYTHONPATH=src pytest -q`

## What Changed in This Commit
- Replaced hex-step/offset motion with deterministic continuous world-space movement and derived hex state.
- Added normalized vector WASD input and right-click `Move Here` target command flow (viewer sends commands only).
- Enforced world hex bounds in simulation and updated docs/tests for new movement behavior.
