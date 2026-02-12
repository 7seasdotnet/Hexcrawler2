# Hexcrawler2 — Current State

## Progress
- ✅ Axial-coordinate hex world model implemented and keyed by `HexCoord`.
- ✅ Per-hex editable records implemented (`terrain_type`, `site_type`, `metadata`).
- ✅ JSON schema validation and load/save support implemented.
- ✅ Deterministic fixed-tick simulation core implemented with sim-owned seeded RNG.
- ✅ `advance_ticks(n)` and `advance_days(n)` implemented (`TICKS_PER_DAY=240`).
- ✅ Deterministic smooth entity movement implemented (hex + sub-hex offsets).
- ✅ Minimal CLI viewer/controller implemented (viewer reads state, controller sends commands).
- ✅ Mandatory tests implemented and passing:
  - determinism hash test
  - save/load world hash round-trip test

## Out of Scope Kept
- No rumors/wounds/armor/factions/combat/gameplay-loop systems in this phase.
