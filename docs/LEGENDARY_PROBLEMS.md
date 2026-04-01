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
