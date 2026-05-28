# Lag Capture Report

- reason: `environment_no_pygame`
- simulation_tick: `n/a`
- samples: `0`
- empty_records_reason: `pygame_not_installed_in_container`
- diagnosis: `runtime viewer commands could not execute in this container`

## Camera/Motion Diagnostics Added
Perf-sentinel samples now include `camera_diagnostics` with:
- active space id/role
- player simulation/interpolated/screen positions
- camera center/target and per-frame deltas
- zoom current/target and per-frame delta
- focus reason/mode
- player_view/debug flags
- interpolation alpha / ticks advanced
- target/zoom change booleans
- rounding/clamp-hysteresis metadata
