# LAG_CAPTURE_REPORT

## Scope
- Space role: campaign + local viewer presentation/runtime path only.
- Sentinel is viewer-local, read-only, bounded, and non-serialized.

## Live Sentinel
- Added optional `--perf-sentinel` toggle in normal `play.py` flow.
- Dump triggers:
  - `F10` hotkey (when sentinel enabled).
  - threshold mode: `frame_ms >= --lag-frame-ms` for 3 consecutive frames.
- Bounded buffer cap: 180 samples.

## Metrics Captured
- frame_ms
- tick_ms
- ticks_advanced
- simulation_tick
- in_game_day
- entity_count
- pending_event_count
- event_trace_len
- combat_log_len
- input_log_len
- rules_state_sizes (JSON-serialized size by module)
- visible_cells_drawn (currently null if unavailable)
- visible_entities_drawn
- debug_rows_rendered
- debug_panel_active
- memory_rss_kb (best-effort via `resource.getrusage`)

## Hot-path scan findings
- `pygame_viewer._draw_world`: iterates all `world.hexes` every frame in campaign mode.
- `pygame_viewer._draw_frame_layers`: iterates sorted `sim.state.entities` each frame.
- Debug path already has bounded/cached rows via `DebugPanelRenderCache` keying on tick/filter signature.
- Event/combat/input logs are length-queried every frame but no full unbounded list render in top HUD.

## Narrow fix applied
- No broad pruning/system rewrite applied.
- Implemented sentinel-only sampling and bounded dump path, with default off.

## Notes
- `profile_snapshot.txt` is written only when `--profile-on-lag` is set and dump triggers.
