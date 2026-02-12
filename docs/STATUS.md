# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 1 (deterministic sim + minimal viewer)
- **Next action:** Validate the pygame viewer loop on a local desktop display and keep extending Phase 1 only with deterministic, sim-owned input handling.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement, world model, hashing.
- `src/hexcrawler/content/`
  - JSON schema + load/save helpers for world data.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller.
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical Phase 1 hex-grid viewer with HUD and keyboard movement commands.
- `src/hexcrawler/__main__.py`
  - Package entrypoint routing to pygame viewer.
- `run_game.py`
  - Simple launch script that injects `src/` into `sys.path` and runs the pygame viewer.

## Progress
- ✅ Axial-coordinate hex world model implemented and keyed by `HexCoord`.
- ✅ Per-hex editable records implemented (`terrain_type`, `site_type`, `metadata`).
- ✅ JSON schema validation and load/save support implemented.
- ✅ Deterministic fixed-tick simulation core implemented with sim-owned seeded RNG.
- ✅ `advance_ticks(n)` and `advance_days(n)` implemented (`TICKS_PER_DAY=240`).
- ✅ Deterministic smooth entity movement implemented (hex + sub-hex offsets).
- ✅ Graphical pygame viewer renders a visible pointy-top axial hex grid (radius 8).
- ✅ Terrain colors + minimal site markers rendered in the grid.
- ✅ One entity icon is spawned and shown in the viewer.
- ✅ WASD movement works by sending destination commands to simulation (viewer does not mutate state directly).
- ✅ HUD shows `CURRENT HEX`, `ticks`, and `day` (`tick // TICKS_PER_DAY`).
- ✅ Mandatory tests implemented and passing:
  - determinism hash test
  - save/load world hash round-trip test

## Out of Scope Kept
- No rumors/wounds/armor/factions/combat/gameplay-loop systems in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `PYTHONPATH=src pytest -q`

## What Changed in This Commit
- Added `pygame` viewer module with deterministic fixed-step tick driving and sim-command-only movement input.
- Added easy launcher (`run_game.py`) and package `__main__` to run viewer without manual `PYTHONPATH`.
- Updated verification docs for pygame launch + tests.
