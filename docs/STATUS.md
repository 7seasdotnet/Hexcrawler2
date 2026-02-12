# Hexcrawler2 — Current State

## What Exists
- Repo initialized.
- AGENTS.md present.
- No engine code yet.

## Current Goal (Phase 1)
Implement deterministic hexmap engine:
- Hex coordinate system
- World state keyed to hex
- Per-hex editable table (terrain, site_type, metadata)
- Fixed tick loop
- Seeded RNG (unused but contained)
- Entity with smooth movement
- Determinism test

## Explicit Non-Goals (for now)
- No rumors
- No wounds
- No armor
- No factions
- No combat
- No gameplay loop
- No deep AI
- No multiplayer

## Definition of Done for Phase 1
When I can:
- Load a JSON hexmap
- Mark hexes as town/dungeon/open
- Spawn one entity
- Advance ticks
- Watch entity move smoothly
- Produce identical world hash under same seed
- Save and reload world without change

## Next Action
Implement sim core + determinism test only.
