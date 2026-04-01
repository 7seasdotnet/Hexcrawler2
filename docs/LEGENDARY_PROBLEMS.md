# Legendary Problems (Recurring Regressions)

## 1) Greybridge Return-to-Origin / Exit Regression
- **Problem name:** Greybridge hub exit can strand player in local hub.
- **Symptom:** Player is in `safe_hub:greybridge`, presses `Q/E`, and does not return to campaign origin.
- **Root cause:** Exit relied solely on `rules_state["exploration"]["safe_hub_active_by_entity"][entity_id]` origin context; if that context was absent/malformed, exit deterministically rejected (`not_in_safe_hub`) despite local-hub location.
- **Related architecture invariant/contract:**
  - Command/event mutation only (no viewer-side teleport).
  - Campaign/local role separation and authoritative return context.
  - Single authoritative simulation path for transitions.
- **Known-good fix path:**
  1. Keep enter/exit as `enter_safe_hub_intent` / `exit_safe_hub_intent` handled in simulation module.
  2. On exit, when context is missing but entity is in `safe_hub:greybridge`, resolve deterministic fallback origin from `home_greybridge` site location.
  3. Emit explicit forensic outcome reason (`exited_safe_hub_fallback_origin`).
- **Required regression tests:**
  - Safe-hub enter/exit round-trip.
  - Repeated round-trip stability.
  - Missing-context fallback still exits to campaign (`exited_safe_hub_fallback_origin`).
- **Do not regress by doing X:**
  - Do **not** patch exit via viewer/UI direct state mutation.
  - Do **not** add hidden in-memory-only return caches in rule modules.
  - Do **not** couple exit semantics to projection/camera behavior.

## 2) Replacement Patrol Spawns but Does Not Trigger Fight/Flee
- **Problem name:** Replacement patrol exists visually but no pending offer/Fight-Flee appears.
- **Symptom:** After successful token turn-in/recovery loop, player approaches the new patrol and no Fight/Flee menu appears; encounter loop stalls.
- **Root cause:** Replacement patrol respawn used a non-authoritative danger entity ID (`patrol:core_playable:respawn`) that did not re-enter the `CampaignDangerModule` single-source overlap/contact authority path (`DEFAULT_DANGER_ENTITY_ID`), so campaign contact did not emit a pending offer for that replacement instance.
- **Related architecture invariant/contract:**
  - `CampaignDangerModule` remains the single campaign encounter-control owner (`encounter_control_by_player` contract).
  - Replacement contacts must flow through the same pending-offer authority seam as the original patrol.
  - Viewer may surface offer state but must not synthesize/force encounter mutation.
- **Known-good fix path:**
  1. Keep turn-in-triggered patrol replacement inside authoritative simulation event handling (`greybridge_patrol_respawn`).
  2. Respawn replacement using the authoritative danger entity ID used by `CampaignDangerModule`.
  3. Preserve normal overlap edge behavior and pending-offer state transitions (`none -> pending_offer -> accepted_loading/in_local/...`).
  4. Validate that accepting replacement offer re-enters local encounter through existing request/begin events.
- **Required regression tests:**
  - Turn-in schedules replacement; authoritative danger entity is present.
  - Replacement overlap creates pending offer for player.
  - Accepting replacement offer emits local begin and maintains valid encounter-control state.
  - Repeat loop does not wedge `encounter_control_by_player`.
- **Do not regress by doing X:**
  - Do **not** spawn replacement patrol under a disconnected ID outside encounter authority.
  - Do **not** bypass pending-offer flow by directly forcing local encounter entry from UI.
  - Do **not** add viewer-side “fake Fight/Flee” state divorced from simulation rules_state.

## 3) Original Patrol Passes Through Player After Leave/Return Before Kill
- **Problem name:** Original patrol recontact wedge after local leave/return.
- **Symptom:** Player contacts patrol once, exits local without killing, returns to overlap, and receives no new Fight/Flee offer while patrol remains alive.
- **Root cause:** Contact offer creation was edge-triggered (`overlap && !prior_overlap`) only. If overlap stayed true across cooldown expiry/return context, encounter eligibility could recover while no new edge occurred, leaving contact permanently wedged until a later separation event.
- **Related architecture invariant/contract:**
  - `CampaignDangerModule` is authoritative for campaign contact and pending-offer ownership.
  - Encounter-control state (`none/pending_offer/in_local/returning/post_encounter_cooldown`) is serialized and deterministic.
  - Viewer/UI must remain read-only and must not synthesize offer state.
- **Known-good fix path:**
  1. Keep offer issuance in `CampaignDangerModule.on_tick_end`.
  2. Evaluate contact as `overlap && player_can_receive_offer(...)` instead of edge-only gating.
  3. Preserve explicit eligibility gates (`encounter_control`, active local state, flee-ignore windows).
  4. Ensure serialized cooldown pruning can naturally re-enable offers while overlap persists.
- **Required regression tests:**
  - Original patrol recontact after leave/return-before-kill.
  - Replacement patrol recontact after turn-in/recover.
  - Save/load across cooldown + persistent overlap still re-triggers pending offer.
  - Two-loop smoke without wedged `encounter_control_by_player`.
- **Do not regress by doing X:**
  - Do **not** require overlap edge transitions as the only retrigger condition.
  - Do **not** clear encounter-control via viewer-side mutation.
  - Do **not** bypass cooldown/flee-ignore semantics with ad-hoc command shortcuts.

## 4) Hex-Axial-Looking Facing Arrow Misrepresents Spatial Truth
- **Problem name:** Render heading appears hex-snapped/axial-coupled.
- **Symptom:** Direction wedge/arrow snaps back to shifted left/right axial-looking directions (especially on stop/start, idle frames, and interpolation reset/re-entry), implying campaign motion is hex-step based or local presentation is topology-snapped when it should read as continuous/display-smoothed.
- **Root cause:** Viewer-facing heading path fell back to authoritative discrete facing token (`entity.facing`) in common paths (zero-delta movement, missing/just-reset snapshots, local-role rendering), so presentation re-quantized to topology-style directions.
- **Related architecture invariant/contract:**
  - Continuous campaign plane remains authoritative; hex is derived indexing/presentation substrate.
  - Heading/facing/render-heading are distinct layers (campaign heading vs local tactical facing vs viewer display heading).
  - Viewer/UI remains read-only; projection/presentation must not mutate simulation truth.
- **Known-good fix path:**
  1. Preserve authoritative tactical facing semantics in simulation/combat unchanged.
  2. Use a viewer-only `display_heading` that derives from continuous motion deltas for both campaign and local render paths.
  3. On low-delta/zero-delta/missing-snapshot frames, hold last valid display heading instead of snapping to discrete facing.
  4. Keep display heading out of serialized/hash-covered simulation state.
- **Required regression tests:**
  - Campaign heading no longer appears hex-snapped in viewer heading helper paths.
  - Local heading no longer appears hex-snapped in viewer heading helper paths.
  - Zero-delta/idle frames preserve prior display heading.
  - Interpolation reset/re-entry uses hold fallback and does not quantize heading.
  - Simulation hash/save-load remains unchanged by display-heading logic.
- **Do not regress by doing X:**
  - Do **not** rebind display heading to axial/discrete facing tokens as default fallback during idle/re-entry paths.
  - Do **not** serialize viewer display/render heading into world/simulation state.
  - Do **not** patch perceived heading via simulation mutations from UI/render code.

## 5) Do Not Let Blocked-Cell Greybridge Patches Harden Into Final Local Building Substrate
- **Problem name:** Greybridge blocked-cell patch hardens into long-term local building truth.
- **Symptom:** Local building authoring keeps adding/adjusting raw blocked-cell tuples with ad hoc door holes, and future building semantics (walls/openings/rooms/gates) are inferred indirectly rather than authored explicitly.
- **Root cause:** Playable-loop urgency shipped coarse blocked occupancy first, but no enforced transition to overlay-authored structure truth was made.
- **Relevant architecture invariant / anti-lock-in rule:**
  - Local role simulation must remain deterministic and command/event authoritative.
  - Projection remains presentation-only; collision/pathing truth must not live only in viewer hacks.
  - Local-space contracts must preserve future topology/projection flexibility and must not encode “blocked cell list == final building model.”
- **Known-good fix path:**
  1. Author Greybridge/local buildings as structure-overlay source data (bounds/walls-openings/room labels/gate semantics).
  2. Deterministically compile overlay source to runtime blocked/passability cells while coarse movement lattice remains in use.
  3. Use overlay-derived data for both render readability and simulation collision/passability checks.
  4. Add deterministic tests for compile output, traversability at doors/gates/openings, and save/load/hash stability.
- **Required regression tests:**
  - Overlay compilation deterministic on repeated runs.
  - Gate/door/opening cells traversable while adjacent wall cells remain blocked.
  - Greybridge enter/exit + Watch Hall turn-in + Inn/Infirmary recovery + patrol recontact loop remain intact.
  - Save/load/hash stability for overlay-derived collision behavior.
- **Do not regress by doing X:**
  - Do **not** add new Greybridge building logic as raw blocked-cell-only truth.
  - Do **not** render fake wall/opening semantics in viewer that are not backed by authoritative overlay-derived collision truth.
  - Do **not** broaden this fix into a full editor/town/interior framework in the same bounded pass.
