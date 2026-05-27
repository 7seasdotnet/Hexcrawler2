# Durability Report
- Days run: 30
- Tick time day-14 check: see durability_metrics.json
- Frame time day-14 check: see durability_metrics.json
- Monotonic growth containers: inspect event_trace_len/input_log_len/rules_state_sizes columns.
- Bounded containers: world.signals/world.tracks/world.spawn_descriptors are capped by substrate constants.
- Warning budgets: No warning budget breaches detected.
- Highest-confidence suspect: viewer_runtime debug/event aggregation loops over event trace under sustained growth.
- Lock-out constraints reviewed: OK