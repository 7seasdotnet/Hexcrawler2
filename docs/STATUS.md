## What changed in this commit
- Fixed Windows portability regression in `pygame_viewer` by removing the unconditional Unix-only `resource` import and moving memory sampling to a guarded cross-platform helper.
- Perf sentinel now records `memory_sampler` (`resource`/`psutil`/`tracemalloc`/`unavailable`) and keeps dumping metrics when RSS sampling is unavailable (`memory_rss_kb: null`).
- Added viewer tests proving import and perf sample capture remain safe when `resource` is unavailable.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/play.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_durability_audit.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "memory_sampler or resource_module_missing"`
- `python play.py --visual-audit` (fails in this environment if `pygame` is not installed)
- `python play.py --perf-sentinel --profile-on-lag --lag-frame-ms 50` (fails in this environment if `pygame` is not installed)

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Re-run the two `play.py` viewer commands on a Windows machine with `pygame` installed to confirm end-to-end launch succeeds without `resource`.

## What changed in this commit
- Added viewer-local lag sentinel toggles (`--perf-sentinel`, `--profile-on-lag`, `--lag-frame-ms`) with bounded ring-buffer sampling and deterministic-safe report dumps under `docs/ai_playtest/perf/`.
- Added first `CombatPresentationCue` viewer seam model (non-authoritative, non-serialized) for attack presentation scaffolding without combat outcome authority changes.
- Added hot-path audit notes and lag capture report templates for long-session runtime diagnosis.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/play.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_durability_audit.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --visual-audit` (fails in this environment when pygame is not installed)
- `python play.py --headless --perf-sentinel --lag-frame-ms 0` (requires pygame install before launcher can enter viewer path)

## What changed in this commit
- Visual-audit/player-view presentation pass in `pygame_viewer.py`: reduced player-view debug/HUD clutter, brighter campaign/local map readability, and state-sensitive title-card behavior so gameplay beats are not dominated by persistent center overlay text.
- Increased marker readability for player/hostile/site/extraction cues (larger radii and stronger icon/ring accents) and strengthened CONTACT modal contrast/button legibility without changing command routing.
- Preserved deterministic authority and beat sequencing; compile + targeted audit/contact/return tests pass, while `python play.py --visual-audit` remains blocked in this environment because `pygame` is unavailable.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_local_encounter_return.py tests/test_encounter_controller_smoke_slice.py tests/test_campaign_danger_contact_slice.py`
- `python play.py --visual-audit` (**fails in this environment: `ModuleNotFoundError: No module named pygame`**)

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Re-run `python play.py --visual-audit` in an environment with `pygame` installed to regenerate `docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png`, `docs/ai_playtest/AI_VISUAL_AUDIT_REPORT.md`, and `docs/ai_playtest/latest/audit_timeline.json`, then confirm all eight beats remain `ok`.
## What changed in this commit
- Fixed visual-audit extraction movement to use canonical local cell semantics for return admissibility (`_entity_location_ref(...).coord == return_exit_coord`) and corrected return-exit world conversion helper so bounded movement can actually path toward the authoritative target cell.
- Expanded `extraction_probe` diagnostics with before/after player position+cell, movement command/tick counts, command issuance state, and return evidence fields to make `not_at_return_exit_after_bounded_move` failures concrete and inspectable.
- Added focused `tests/test_visual_audit.py` coverage for canonical return-exit distance/cell semantics used by extraction movement checks.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_local_encounter_return.py tests/test_encounter_controller_smoke_slice.py tests/test_campaign_danger_contact_slice.py`
- `python play.py --visual-audit` (currently fails in this environment due to missing `pygame` dependency)

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run `python play.py --visual-audit` on a machine with `pygame` installed and confirm extraction reaches authoritative `local_encounter_return` evidence and campaign-role re-entry.

## What changed in this commit
- Fixed visual-audit extraction sequencing to use the authoritative return seam correctly: move to local `return_exit_coord` first, then issue `end_local_encounter_intent`, and only mark `extraction_return` OK when both `local_encounter_return` evidence and campaign-role re-entry are present.
- Added `extraction_probe` diagnostics in `audit_timeline.json` (active role/state, return affordance, distance to exit, command tick, recent return-event rows, and explicit failure reason).
- Added focused `tests/test_visual_audit.py` coverage for local return-context discovery and extraction-distance probe helpers used by the audit return flow.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_local_encounter_return.py tests/test_encounter_controller_smoke_slice.py tests/test_campaign_danger_contact_slice.py`
- `python play.py --visual-audit`

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Verify `core_playable_first_loop` visual audit now reaches authoritative extraction/return on local machine and confirm `extraction_return` beat is truthfully `ok/partial/failed` based on return evidence.

## What changed in this commit
- Reworked `src/hexcrawler/cli/visual_audit.py` to drive the core playable loop through authoritative command seams (`set_move_vector` -> `accept_encounter_offer` -> local `attack_intent` -> `end_local_encounter_intent`) with bounded waits and explicit failure reasons.
- Tightened visual-audit beat truth rules: `contact_modal` now requires a real pending offer, `local_entry` requires local-role/`in_local`, and `extraction_return` is no longer marked OK when local entry never happened.
- Added per-beat timeline diagnostics (space id/role, player position, encounter-control state, pending-offer count, command issued, and last event-trace rows) plus truthful failure labels on contact-sheet frames.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py tests/test_encounter_controller_smoke_slice.py`
- `python play.py --visual-audit` (currently fails in this environment due to missing `pygame` dependency)

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Validate the updated scripted visual-audit loop on a machine with `pygame` installed and confirm beats `contact_modal`/`local_entry`/`first_attack`/`combat_result` reach truthful OK states.

## What Exists (folders / entry points)
- `play.py`: canonical launcher including `--visual-audit`.
- `src/hexcrawler/cli/visual_audit.py`: scripted capture driver, beat status logic, report/contact-sheet/timeline writers.
- `src/hexcrawler/cli/pygame_viewer.py`: authoritative command emitters and viewer rendering path used by visual audit.
- `src/hexcrawler/cli/runtime_profiles.py`: `core_playable` runtime profile composition for playable-loop execution.


## What changed in this commit
- Fixed `visual_audit.py` space-role lookup to use canonical `SpaceState.role` via a tolerant helper, replacing invalid `.space_role` access that crashed audit capture.
- Hardened visual-audit failure handling so role-lookup runtime exceptions are captured into beat notes/blockers and timeline/report writing still completes whenever possible.
- Expanded `tests/test_visual_audit.py` coverage for canonical role lookup and failed-result blocker/report behavior.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "visual_audit or core_playable"`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --visual-audit`

# Hexcrawler2 — Current State

## Lock-out Review
- **Lock-out constraints reviewed: OK**

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run manual authored proving-ground melee verdict smoke (enter Old Stair local proving ground -> replay choke fight 3-5 times -> verify telegraph/recovery/hit-outcome readability -> record top-down verdict vs projection-risk criteria).
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
- Local dungeon authoring bridge intent currently executed through rule-module command/event seam: `local_dungeon_author_intent` (authored linked local-site spaces only; hostile spawner + transition point place/move/delete/use operations).
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
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "local_dungeon_authoring_spawner_and_points_create_move_delete_persist_save_load or local_dungeon_authored_spawner_materialization_and_return_to_origin or campaign_dungeon_authoring_create_move_delete_persists_save_load"`
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py tests/test_render_interpolation.py tests/test_pygame_viewer_runtime.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k player_feedback_lines_include_enemy_loop_line_in_local_space`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "greybridge_overlay or greybridge_hub_blocked_cells_stop_movement_but_doors_and_gate_path_remain_open or greybridge_gatehouse_round_trip_remains_traversable_and_exit_stable"`
- `PYTHONPATH=src pytest -q tests/test_reward_turn_in_loop_p5.py -k "overlay_compilation_is_deterministic_and_contains_gate_semantics or local_structure_authoring_create_edit_delete_persists_save_load or greybridge_hub_blocked_cells_stop_movement_but_doors_and_gate_path_remain_open or greybridge_gatehouse_round_trip_remains_traversable_and_exit_stable or greybridge_safe_hub_enter_exit_round_trip"`
- `PYTHONPATH=src pytest -q tests/test_local_combat_proving_ground.py`
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py tests/test_local_combat_proving_ground.py`
- `python play.py --headless`
- `python play.py --headless --runtime-profile experimental_world`
- `python play.py --headless --runtime-profile soak_audit`
- `python play.py`

## What changed in this commit
- Added bounded viewer-local floating combat feedback labels (for existing melee outcomes) anchored to local targets, with deterministic caps and lifetime windows that never serialize or mutate authoritative state.
- Tightened default HUD action hints for campaign vs contact vs local spaces while preserving existing command/event seams and keeping debug-heavy detail in existing inspector/debug panels.
- Added runtime tests for bounded combat feedback collection and headless-safe no-op sound hooks, and retained transition/hash non-mutation coverage.

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

- `PYTHONPATH=src pytest -q tests/test_render_interpolation.py tests/test_pygame_viewer_runtime.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "core_playable or feedback or local_contact or right_click"`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --headless`


## What changed in this commit
- Presentation Gate 1C verification hardening: headless pygame launch now sets dummy video+audio drivers in `--headless`, while sound hooks remain no-op and viewer-local.
- Added bounded duplicate-suppression for floating combat feedback via viewer-local seen-event keys (capped), preserving role/space filtering and non-mutation behavior.
- Narrow readability pass: clearer player marker silhouette, slightly higher floating feedback text placement, and shorter HUD/modal action wording for core_playable.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_render_interpolation.py tests/test_pygame_viewer_runtime.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "core_playable or feedback or local_contact or right_click"`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --headless`

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Execute local machine visual audit for default `core_playable` scene after installing `pygame`, then capture pass/fail against Presentation Gates 1A–1C checklist.

## What Exists (folders / entry points)
- `play.py`: canonical launcher (`python play.py`, `python play.py --headless`).
- `src/hexcrawler/cli/play.py`: startup/save bootstrap + runtime profile wiring.
- `src/hexcrawler/cli/pygame_viewer.py`: read-only viewer loop and headless/runtime diagnostics.
- `src/hexcrawler/cli/runtime_profiles.py`: `core_playable` default runtime profile composition.
- `requirements.txt`: runtime dependency declaration (`pygame`).
- `README.md`: dependency install, headless smoke, and manual visual-audit checklist.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `python play.py --headless` (returns explicit install guidance + non-zero if `pygame` is missing)
- `python -m pip install -r requirements.txt` (required before pygame/viewer tests; may fail in restricted CI with blocked package index)

## What changed in this commit
- Added explicit `ModuleNotFoundError` handling in viewer startup to fail with actionable dependency-install instructions instead of an unhandled traceback.
- Documented pygame dependency/runtime verification path and exact local install commands in `README.md`, including index-restricted environment fallback command.
- Added a minimal manual visual-audit workflow for default `core_playable` scene (what to inspect for first-minute presentation gates) and recorded this phase-aligned verification guidance in `STATUS.md`.

## What changed in this commit
- Added a new presentation helper module (`src/hexcrawler/cli/presentation_theme.py`) for an OSR-styled palette plus reusable panel/vignette drawing primitives to support a stronger default core_playable visual pass.
- Reworked core viewer framing in `pygame_viewer.py` to use themed top-bar presentation, darker campaign/local grounding, and stronger CONTACT modal direction (dimmer backdrop + sharper action language).
- Kept all presentation-only changes viewer-local (no simulation authority/state mutation), with pygame import binding for theme helpers.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run local visual audit with pygame installed and capture before/after screenshots for first-frame, CONTACT, and local combat readability.

## What changed in this commit
- Reworked the viewer presentation into a stronger vertical-slice framing with launch title card, compact player-facing HUD trimming, and stronger campaign major-site threat signaling (Old Stair pulse emphasis) to improve first 3–5 minute readability.
- Added viewer-local presentation effects substrate (`presentation_effects.py`) with bounded pulse-ring lifecycle for non-authoritative, non-serialized combat/map feedback scaffolding.
- Kept all additions presentation-only and deterministic-safe: no simulation authority mutation, no hash/input-log coupling, and no save-state schema changes.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --headless` (graceful dependency error when pygame missing)

## What changed in this commit
- Added a built-in visual audit CLI path (`python play.py --visual-audit`) plus script/output options, wired through `src/hexcrawler/cli/visual_audit.py`.
- Added stable AI visual audit report output at `docs/ai_playtest/AI_VISUAL_AUDIT_REPORT.md` and timeline output at `docs/ai_playtest/latest/audit_timeline.json` (graceful blocker reporting when pygame is unavailable).
- Added baseline tests for visual-audit CLI defaults and report writer, and documented upload artifact workflow in `README.md`.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py src/hexcrawler/cli/visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py tests/test_pygame_viewer_cli.py -k "visual_audit or core_playable"`
- `python play.py --headless` (returns non-zero with explicit dependency guidance if pygame is missing)
- `python play.py --visual-audit`

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Install pygame in local runtime, rerun `python play.py --visual-audit`, and verify full frame capture + contact sheet generation with reachable campaign/local beats.

## What changed in this commit
- Fixed visual audit runtime tick advancement to use the authoritative simulation API (`advance_ticks`) through a dedicated helper, removing the invalid `Simulation.step()` call path.
- Hardened visual audit failure reporting so pygame-unavailable vs runtime-exception vs unreachable-beat outcomes are recorded explicitly in both report and timeline outputs.
- Added regression tests for authoritative visual-audit tick advancement helper and blocker-aware report output.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "visual_audit or core_playable"`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --visual-audit`

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Validate the generated visual-audit contact sheet + report beat readability against Presentation Gates (campaign clarity, CONTACT event readability, local combat extraction clarity).

## What Exists (folders / entry points)
- `play.py`: visual-audit launcher entry point (`python play.py --visual-audit`).
- `src/hexcrawler/cli/visual_audit.py`: visual audit runner, report/timeline/contact-sheet generation.
- `src/hexcrawler/cli/pygame_viewer.py`: authoritative viewer simulation bootstrap and pygame runtime integration.
- `src/hexcrawler/cli/runtime_profiles.py`: default `core_playable` runtime profile composition used by visual audit.

## What changed in this commit
- Fixed visual audit capture to render screenshots via the actual pygame viewer frame pipeline (`render_viewer_frame_to_surface` -> `_draw_frame_layers`) instead of placeholder-filled surfaces.
- Added state-validated beat evaluation plus visual sanity diagnostics (unique colors, non-background ratio, blank-frame suspicion) and propagated them into both report/timeline outputs.
- Updated visual-audit result semantics to return `partial`/`failed` truthfully when contact/local/combat beats are not actually reached or frames appear blank.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k "visual_audit or core_playable"`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --visual-audit`

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Inspect generated visual-audit contact sheet for campaign/local readability and tune scripted action path only where needed to reach truthful beats.

## What Exists (folders / entry points)
- `src/hexcrawler/cli/visual_audit.py`: scripted visual audit orchestration, beat validation, report/timeline generation.
- `src/hexcrawler/cli/pygame_viewer.py`: canonical viewer frame drawing path now reusable for offscreen audit capture.
- `docs/ai_playtest/latest/audit_timeline.json`: per-beat diagnostic timeline including role/state/render-path/sanity metadata.
- `docs/ai_playtest/AI_VISUAL_AUDIT_REPORT.md`: truthful partial/fail success semantics and blocker reporting.

## What changed in this commit
- Updated `src/hexcrawler/cli/visual_audit.py` local-combat beat driving to select nearest local hostile, approach using authoritative `set_move_vector`, issue `attack_intent`, and evaluate combat outcome truth from authoritative combat results instead of screenshot-only timing.
- Added richer combat diagnostics in `audit_timeline.json` via `combat_probe` (target id/distance, attack tick, command issuance, observed event types, outcome reason/status).
- Updated visual audit contact-sheet generation to crop each screenshot to the main viewport rectangle so critique panels prioritize player-facing gameplay while preserving full screenshots and full diagnostics.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_local_hostile_behavior_slice.py tests/test_combat_execution_module.py tests/test_local_encounter_return.py tests/test_encounter_controller_smoke_slice.py`
- `python play.py --visual-audit` *(currently fails in this environment due to missing `pygame` dependency)*

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Re-run `python play.py --visual-audit` on a machine with `pygame` installed and validate truthful `first_attack`/`combat_result` beats plus viewport-focused contact-sheet output.

## What Exists (folders / entry points)
- `play.py`: entry point supporting `--visual-audit`.
- `src/hexcrawler/cli/visual_audit.py`: scripted visual-audit beat runner and report/timeline/contact-sheet writer.
- `src/hexcrawler/cli/pygame_viewer.py`: canonical draw path and viewport metadata used for audit captures.
- `docs/ai_playtest/latest/`: visual audit artifacts (full beat screenshots + `audit_timeline.json`).

## What changed in this commit
- Fixed visual-audit hostile target discovery to use canonical local hostile eligibility (template/faction + local-space + incapacitation filters) instead of brittle hostile-id prefix matching.
- Added per-beat `local_entity_probe` diagnostics to visual audit timeline/report metadata for `local_entry`, `first_attack`, and `combat_result`, including acceptance/rejection reasons for each local entity.
- Added visual-audit unit coverage for canonical hostile discovery and rejection-reason diagnostics to prevent regressions.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/visual_audit.py src/hexcrawler/cli/pygame_viewer.py src/hexcrawler/cli/runtime_profiles.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_local_hostile_behavior_slice.py tests/test_combat_execution_module.py tests/test_local_encounter_return.py tests/test_encounter_controller_smoke_slice.py tests/test_campaign_danger_contact_slice.py`
- `python play.py --visual-audit` *(fails in this container due to missing pygame dependency)*

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run `python play.py --visual-audit` in an environment with `pygame` installed to verify that `first_attack` and `combat_result` now resolve against authoritative local hostile/combat outcomes and inspect the new `local_entity_probe` timeline payload.

## What Exists (folders / entry points)
- `src/hexcrawler/cli/visual_audit.py`: visual-audit beat orchestration + canonical hostile targeting + local entity diagnostics.
- `tests/test_visual_audit.py`: visual-audit regression tests for hostile discovery and probe rejection reasons.
- `docs/ai_playtest/latest/audit_timeline.json`: generated timeline artifact now expected to include `local_entity_probe` records per local/combat beats.

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run/inspect the new Durability Gate 1 long-run audit outputs and isolate day-14 lag source from headless vs viewer-runtime metrics.

## What Exists (folders / entry points)
- `play.py`: supports `--durability-audit --days N --out <dir>` alongside `--visual-audit`.
- `src/hexcrawler/cli/durability_audit.py`: deterministic long-run audit runner + metrics/report/CSV writers.
- `tests/test_durability_audit.py`: coverage for durability artifact generation.

## What changed in this commit
- Added `run_durability_audit` command path with core_playable/experimental_world/soak_audit sampling for headless and viewer-runtime-style execution.
- Added interval durability metrics capture and artifact writers (`durability_metrics.json`, `durability_summary.csv`, `DURABILITY_REPORT.md`) including rules-state sizing and growth warnings.
- Added focused audit writer test and wired CLI flags in `play.py`.

## Current Verification Commands (known working)
- `python -m py_compile src/hexcrawler/cli/durability_audit.py src/hexcrawler/cli/play.py tests/test_durability_audit.py`
- `PYTHONPATH=src pytest -q tests/test_durability_audit.py`
- `PYTHONPATH=src pytest -q tests/test_visual_audit.py`
- `PYTHONPATH=src pytest -q tests/test_soak_bounds_slice.py tests/test_soak_audit_slice.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `python play.py --visual-audit`
- `python play.py --durability-audit --days 30 --out docs/ai_playtest/durability`
