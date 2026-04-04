# Hexcrawler2 — Current State

## Lock-out Review
- **Lock-out constraints reviewed: OK**

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run manual authored-site activation smoke (right-click place town/dungeon -> Enter linked local proof space -> author local structure -> delete cascade -> save/load), then proceed to bounded local population/spawner authoring inside linked spaces.
- **Phase status:** Active phase reset complete (documentation-only). Substrate expansion is no longer the default path unless directly required to ship this playable loop.

## Playable Milestone Definition (First Cash-Out Loop)
A milestone build is considered successful when a player can:
1) start from a safe site,
2) travel on the authoritative continuous **campaign** plane,
3) observe and choose to avoid/engage visible danger presence,
4) transition deterministically into a **local** encounter space,
5) survive brutal combat or die,
6) extract/return with persistent consequences still in effect.

## Immediate Priority Rule (Phase Discipline)
During this phase, new work is prioritized by all of the following:
1) direct player-facing payoff,
2) direct relevance to the playable loop above,
3) bounded complexity growth,
4) compatibility with architecture invariants and determinism contracts.

If a task does not materially advance the playable loop, defer it unless it is strictly required to unblock the loop.

## A4 Policy — Active Path vs Preserved-But-Not-Immediate-Critical-Path

### Active Path Systems (current playable slice)
Prefer implementation work in this set unless a justified dependency requires otherwise:
- campaign-role travel/movement visibility on the continuous campaign plane,
- visible campaign danger/contact,
- deterministic campaign → local encounter handoff,
- minimal hostile local behavior,
- fast brutal local combat resolution,
- wound application/persistence,
- extraction/return pressure with minimal supporting supplies/loot/recovery surfaces, including safe-site recovery rest.

### Preserved but Not Immediate Critical Path
These systems remain valid and preserved, but are **not immediate critical path** and should expand only when directly required by the playable slice:
- deeper belief/intelligence propagation,
- advanced diplomacy/political reaction depth,
- broader ecology/site evolution depth,
- nonessential observability expansion,
- editor expansion beyond slice-critical authoring/testing needs,
- higher-order rumor sophistication beyond immediate gameplay payoff.

### Decision Rule for Future Work
Select work in this order:
1) player-facing payoff,
2) direct relevance to the current playable loop,
3) bounded complexity/growth,
4) compatibility with locked architecture contracts.

### Anti-Drift Reminder
Robust/engine-first/do-not-lock-out requirements are architecture guardrails, not permission to expand noncritical systems ahead of playable-loop delivery.

## Invariants (Unchanged, Non-Negotiable)
- Deterministic simulation remains authoritative.
- Authoritative mutation remains command/event-driven only.
- Persistent state remains serialized and hash-covered.
- Queues/logs/containers remain bounded.
- Viewer/UI remains read-only with respect to simulation mutation.
- Campaign/local role separation remains mandatory.
- Multiplayer-safe architecture remains preserved (no lock-out).
- Editor-first extensibility remains preserved.
- Rule modules remain ephemeral behavioral shells (no correctness-critical in-memory state).
- Continuous campaign plane remains authoritative; hex membership remains derived.
- Local topology/projection flexibility remains preserved.

## Supported Action Intent Types (Current)
- Combat/tactical intents currently executed through the authoritative seam: `attack_intent`, `turn_intent` (local-role gated).
- Provisional deterministic encounter action intents currently executed: `signal_intent`, `track_intent`.
- Campaign encounter-control intents currently executed through the authoritative seam: `accept_encounter_offer`, `flee_encounter_offer`.
- Recovery intent currently executed through rule-module command/event seam: `safe_recovery_intent` (campaign safe-site context **or** Greybridge local-hub Inn/Infirmary context; deterministic context-gated admissibility).
- Reward turn-in intent currently executed through rule-module command/event seam: `turn_in_reward_token_intent` (Greybridge local-hub Watch Hall building context; deterministic context-gated admissibility).
- Safe-hub traversal intents currently executed through rule-module command/event seam: `enter_safe_hub_intent`, `exit_safe_hub_intent`.
- Local manual loot intent currently executed through rule-module command/event seam: `loot_local_proof_intent`.
- Local structure authoring proof intent currently executed through rule-module command/event seam: `local_structure_author_intent` (Greybridge local safe-hub only; create/move-opening/remove/delete bounded operations).
- Campaign authoring bridge intent currently executed through rule-module command/event seam: `campaign_author_intent` (campaign overworld only; create/move/delete town+dungeon sites and create/move/delete patrol primitives/anchors, including patrol anchor delete).
- Unknown/unsupported intents must continue to be ignored deterministically with recorded outcomes.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`: deterministic simulation core, event queue, command processing, encounter/event seams, world/state hashing, save/load substrate.
- `src/hexcrawler/content/`: content loaders/validators for encounter/supply and related data payloads.
- `src/hexcrawler/cli/pygame_viewer.py`: read-only viewer/editor-facing runtime controls and inspection surfaces.
- `play.py`: canonical launch entry point.

## Current Verification Commands (known working)
- `PYTHONPATH=src pytest -q`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k right_click_campaign_map_does_not_raise_name_error`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "campaign_authoring_patrol_edit_menu_exposes_edit_path_entry or campaign_patrol_anchor_hit_detection_enables_move_or_delete_actions or campaign_patrol_path_needed_count_detects_missing_route_anchor"`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "campaign_patrol_authoring_create_move_delete_persists_save_load or campaign_patrol_route_following_moves_and_persists_save_load_hash"`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "campaign_site_authoring_create_move_delete_persists_save_load or campaign_dungeon_authoring_create_move_delete_persists_save_load or local_structure_authoring_works_inside_authored_site_linked_local_space"`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "zero_added_anchors_stays_idle_with_no_target or one_anchor_loops_between_spawn_and_anchor or multi_anchor_route_wraps_back_to_spawn or route_progression_save_load_matches_uninterrupted_hash"`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "campaign_patrol_route_points_include_spawn_as_anchor_zero_then_authored_order or campaign_patrol_path_needed_count_detects_missing_route_anchor"`
- `PYTHONPATH=src pytest -q tests/test_play_launcher.py tests/test_pygame_viewer_cli.py -k "core_playable_default_scene_is_sparse_and_contains_single_patrol or play_launcher_default_core_playable_rebuilds_when_scene_is_missing or play_launcher_startup_truth_log_includes_scene_and_paths or viewer_runtime_controller_new_simulation_preserves_core_playable_patrol_and_sites"`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py tests/test_runtime_profiles.py tests/test_pygame_viewer_cli.py -k "reward_turn_in_loop_p5 or enter_or_e_generic_site_use_opens_town_services_via_generic_path or player_feedback_lines_show_proof_gain_turn_in_and_attack_resolution"`
- `PYTHONPATH=src python - <<'PY' ... core_playable visible-loop smoke (home visibility + local attack intent + hostile incapacitation + reward turn-in + calendar tie-to-tick) ... PY`
- `PYTHONPATH=src pytest -q tests/test_local_hostile_behavior_slice.py tests/test_pygame_viewer_cli.py tests/test_runtime_profiles.py tests/test_exploration_execution_module.py tests/test_reward_turn_in_loop_p5.py`
- `PYTHONPATH=src python - <<'PY' ... core_playable scripted smoke (patrol contact -> Fight -> local pressure -> return) ... PY`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `PYTHONPATH=src pytest -q tests/test_combat_execution_module.py -k "deterministic or hash or round_trip or cooldown_gate_blocks_repeat_attack_in_same_tick"`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_pygame_viewer_cli.py tests/test_pygame_viewer_runtime.py`
- `PYTHONPATH=src pytest -q tests/test_encounter_controller_smoke_slice.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k local_contact_and_return_smoke_slice`
- `PYTHONPATH=src pytest -q tests/test_soak_bounds_slice.py tests/test_soak_audit_slice.py`
- `PYTHONPATH=src python - <<'PY' ... collect_soak_metrics headless/viewer 20000-tick comparison ... PY`
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py src/hexcrawler/sim/exploration.py src/hexcrawler/sim/encounters.py tests/test_reward_turn_in_loop_p5.py tests/test_runtime_profiles.py tests/test_exploration_execution_module.py`
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py tests/test_render_interpolation.py tests/test_pygame_viewer_runtime.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k player_feedback_lines_include_enemy_loop_line_in_local_space`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "greybridge_overlay or greybridge_hub_blocked_cells_stop_movement_but_doors_and_gate_path_remain_open or greybridge_gatehouse_round_trip_remains_traversable_and_exit_stable"`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "overlay_compilation_is_deterministic_and_contains_gate_semantics or local_structure_authoring_create_edit_delete_persists_save_load or greybridge_hub_blocked_cells_stop_movement_but_doors_and_gate_path_remain_open or greybridge_gatehouse_round_trip_remains_traversable_and_exit_stable or greybridge_safe_hub_enter_exit_round_trip"`
- `python play.py --headless`
- `python play.py --headless --runtime-profile experimental_world`
- `python play.py --headless --runtime-profile soak_audit`
- `python play.py`

## What changed in this commit
- Authored campaign town/dungeon site placement now eagerly creates explicit deterministic linked local proof spaces (`local_site:{site_id}`), with serialized `SiteRecord.entrance` linkage used by `enter_site`.
- Right-click authored site menu now exposes `Enter / Move / Delete` (campaign canonical context flow), and linked local spaces accept existing `local_structure_author_intent` workflow for proof authoring.
- Site delete semantics are now explicit cascading delete for linked authored local spaces; added regression tests + updated bridge/problem docs for dead-marker prevention.

## Core-playable clarity note (this pass)
- Default `core_playable` startup now presents a sparse intentional campaign scene (Greybridge + Old Stair + one patrol + player) with clearer travel rhythm and reduced map-surface text clutter.
- Verbose diagnostics remain available through read-only bounded debug surfaces, preserving observability without crowding the main player map view.
- Full town/dungeon interiors and expanded in-game editor authoring remain later scope.
- This commit is a **local combat feel/readability pass in `core_playable`** (melee cadence + local HUD feedback + local visual readability), not a new combat architecture pass.
- Projectile/ranged combat remains explicitly out of scope for this pass; melee-only authoritative combat path remains unchanged.

## Runtime profile note (C1)
- Default play now uses `core_playable` (narrow playable-loop module set).
- Preserved second-order systems remain available via explicit opt-in: `--runtime-profile experimental_world`.
- Soak/audit composition remains explicit, bounded, and distinct via `--runtime-profile soak_audit`.

## Soak/Performance Diagnosis (this pass)
- **Main driver:** viewer/runtime overhead remains the dominant long-run slowdown source once caps are enforced, because viewer-coupled systems keep additional entities/events/encounter-control bookkeeping active; record containers are now bounded.
- **Simulation-side status:** headless run stayed bounded with no active entities/events growth (20k-tick diagnostic: `signals=256`, `tracks=256`, `spawn_descriptors=256`, `entities=0`, `pending_events=0`).
- **Viewer/runtime-side status:** 20k-tick diagnostic remained bounded on capped records but retained higher active-state load (`entities=258`, `event_trace=256`, `pending_events=6`, `pending_offers=1`), matching expected viewer+encounter module workload and confirming slowdown is now mostly runtime/viewer-coupled rather than unbounded container growth.
