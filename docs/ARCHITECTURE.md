# Architecture (Engine Substrate MVP)

## Coordinate System
- **Axial coordinates** `(q, r)` are used for the map key space.
- World state is a dictionary keyed by `HexCoord(q, r)`.
- Each hex stores a `HexRecord` with:
  - `terrain_type: str`
  - `site_type: "none" | "town" | "dungeon"`
  - `metadata: dict`

## Serialization
- World maps are persisted as JSON (`hexes[]` rows containing `coord` + `record`).
- Schema validation is run on both load and save.
- The format is hand-editable and deterministic when re-serialized.

## Simulation Timing
- Fixed tick loop in `Simulation`.
- Constant: `TICKS_PER_DAY = 240`.
- `advance_ticks(n)` steps exactly `n` ticks.
- `advance_days(n)` steps `n * TICKS_PER_DAY` ticks.

## Determinism
- RNG is owned by simulation core (`random.Random(seed)`) and not exposed to viewers.
- Entity updates run in stable sorted-id order per tick.
- Hash helpers (`world_hash`, `simulation_hash`) provide regression-friendly fingerprints.
- Movement uses fixed per-tick increments only (no frame-delta movement in simulation).

## Movement Model
- Entity state stores continuous world-space position (`position_x`, `position_y`).
- Hex coordinate is derived from world-space each read using deterministic axial conversion.
- Each tick applies either:
  - normalized WASD input vector, or
  - autonomous movement toward `target_position` when no WASD input is active.
- World bounds are simulation-enforced: movement is blocked when resulting position maps to a non-existent hex.
- Right-click `Move Here` sets a world-space target only if inside bounds; no pathfinding is performed.

## Viewer/Controller Separation
- `AsciiViewer` and pygame viewer only render existing simulation state.
- Viewer/controller sends movement commands (`set_entity_move_vector`, `set_entity_target_position`) to simulation.
- Simulation remains authoritative and headless-testable.
