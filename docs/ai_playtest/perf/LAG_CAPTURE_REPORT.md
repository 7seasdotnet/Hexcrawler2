# LAG_CAPTURE_REPORT

## Scope
- Space role: campaign + local viewer presentation/runtime path only.
- Sentinel is viewer-local, read-only, bounded, and non-serialized.

## Frame Pacing Gate 1 Findings (Windows live capture)
- Captured frame band: ~50–65ms around in-game day 15/16.
- World load indicators remained bounded in the same capture: ~5 entities, ~4–5 pending events, `event_trace_len` capped at 256, `combat_log_len` ~87, `input_log_len` ~900, `debug_rows_rendered` ~55–56.
- Viewer frame cap configuration found in runtime loop: `clock.tick(target_fps)` with `target_fps=60` when running and `30` when paused.
- Fixed simulation tick remains `SIM_TICK_SECONDS` (authoritative sim unchanged).
- Rendering is not hard-coupled to one sim tick per rendered frame; render frames can occur with `ticks_advanced=0` and interpolation alpha is viewer-only.

## Instrumentation Added
Per-sample timing now includes:
- `input_ms`
- `command_ms`
- `simulation_advance_ms`
- `draw_world_ms` (currently coarse fallback)
- `draw_entities_ms` (currently coarse fallback)
- `draw_hud_debug_ms` (currently coarse fallback)
- `draw_modals_overlays_ms` (currently coarse fallback)
- `flip_ms`
- `throttle_ms`
- `update_ms`
- `draw_ms`
- `debug_draw_ms`
- `total_frame_ms`

And frame pacing config fields:
- `target_fps`
- `observed_fps`
- `tick_cap_fps`
- `sim_tick_seconds`
- `frame_cap_near_20fps`
- `render_coupled_to_sim_tick`

## Current Diagnosis
- Based on low canonical-state pressure plus 50–65ms frame times, the issue is likely frame pacing / throttle behavior (or platform display pacing) rather than runaway authoritative simulation growth.
- Gate-1 summary field `frame_time_diagnosis` now emits either `mostly_sleep_or_throttle` or `mostly_compute` from captured timing averages.

## Narrow fix applied
- No simulation mechanics changed.
- No canonical-state pruning applied.
- Added bounded, low-cost timing/pacing instrumentation and report summaries only.
