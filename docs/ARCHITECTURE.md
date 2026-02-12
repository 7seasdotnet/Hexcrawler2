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

## Movement Model
- Entity state: `hex_coord` + continuous `offset_x/offset_y`.
- Each tick moves toward destination world coordinates by `speed_per_tick`.
- Hex stepping uses deterministic nearest-neighbor axial stepping.
- Pathing strategy is isolated in `movement.py` for easy replacement later.

## Viewer/Controller Separation
- `AsciiViewer` only renders existing simulation state.
- `SimulationController` issues commands (`goto`, tick/day advancement) to sim.
- Simulation remains authoritative and headless-testable.
