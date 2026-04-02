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
- **2026-04-01 bounded bridge status update:**
  - Greybridge now persists local `structure_primitives` as authored truth and compiles blocked collision from that source.
  - A minimal authoritative authoring intent seam (`local_structure_author_intent`) now supports create/edit/delete proof operations in local space.
  - This remains a bounded Part 1 bridge only; campaign city/patrol/dungeon authoring is still out of scope.
- **Required regression tests:**
  - Overlay compilation deterministic on repeated runs.
  - Gate/door/opening cells traversable while adjacent wall cells remain blocked.
  - Greybridge enter/exit + Watch Hall turn-in + Inn/Infirmary recovery + patrol recontact loop remain intact.
  - Save/load/hash stability for overlay-derived collision behavior.
- **Do not regress by doing X:**
  - Do **not** add new Greybridge building logic as raw blocked-cell-only truth.
  - Do **not** render fake wall/opening semantics in viewer that are not backed by authoritative overlay-derived collision truth.
  - Do **not** broaden this fix into a full editor/town/interior framework in the same bounded pass.

## 6) Authoring Exists but Is Effectively Unusable Behind Hotkeys
- **Problem name:** Campaign authoring hidden behind hotkeys instead of discoverable right-click spatial actions.
- **Symptom:** Users cannot discover how to place towns, dungeon entrances, or patrols during normal play; feature appears missing unless they already know debug keys.
- **Root cause:** Authoritative backend intents existed, but primary interaction path was key-driven demo actions (`B/O/P/M/Delete`) with no contextual right-click placement/edit affordance.
- **Relevant architecture / UX invariant:**
  - Viewer remains read-only; it may only emit authoritative command/event intents.
  - Campaign authoring workflow must be campaign-role spatial/contextual, not memorized hotkey trivia.
  - Existing deterministic authoring seam (`campaign_author_intent`) should be reused, not bypassed.
- **Known-good fix path:**
  1. Make right-click context menu the canonical campaign authoring surface.
  2. On empty campaign space, expose placement actions (town, dungeon entrance, patrol).
  3. On existing authored site/patrol, expose edit actions (move, delete).
  4. Keep move bounded and obvious: pick Move, choose destination with next right-click, Esc cancels.
  5. Keep hotkeys as debug-only fallback and avoid advertising them as primary UX.
- **Required regression tests:**
  - Right-click empty campaign space exposes place-town/place-dungeon/place-patrol actions.
  - Right-click existing authored site/patrol exposes move/delete actions.
  - Town/dungeon/patrol create-move-delete persists save/load and preserves hash stability.
  - Core `core_playable` launch loop still runs after authoring UX changes.
- **Do not regress by doing X:**
  - Do **not** reintroduce hotkeys as the only or advertised authoring path.
  - Do **not** mutate simulation state directly from viewer widgets.
  - Do **not** rebuild authoring backend seams when existing intents already satisfy mutation needs.

## 7) Hotkey-Authored and Right-Click-Authored Campaign Objects Behave Differently
- **Problem name:** Split campaign object behavior by creation path.
- **Symptom:** Some seeded/hotkey-created objects can be moved/deleted, while right-click-created objects fail hit detection, fail delete, or fail to materialize as usable patrols.
- **Root cause:** Authoring semantics diverged across object identity/registration paths (authored record vs runtime entity presence), and context-menu targeting depended on inconsistent marker/hit branches.
- **Relevant architecture / UX invariant:**
  - Campaign authoring must be right-click/context-menu first for player-facing spatial workflows.
  - Viewer remains read-only and emits authoritative `campaign_author_intent` mutations only.
  - Seeded defaults and newly authored objects must share one object identity/selection/edit/delete path.
- **Known-good fix path:**
  1. Keep one authoritative mutation seam (`campaign_author_intent`) for create/move/delete/path operations.
  2. Ensure right-click target resolution checks authored campaign truth (sites + patrol primitives) regardless of marker branch.
  3. On patrol create/update, keep authored patrol record and runtime patrol entity synchronized so new patrols are visible/selectable/editable/deletable.
  4. Keep delete semantics uniform in authoring mode (no protected seeded defaults).
  5. Keep patrol path editing bounded (anchor add/delete) and serialized via authoritative intents.
- **Required regression tests:**
  - Right-click Place Patrol Here creates patrol primitive and runtime patrol entity.
  - Move/delete works for seeded default town/dungeon/patrol and right-click-created town/dungeon/patrol.
  - Save/load/hash stability for patrol anchor operations (add/delete/move via intents).
  - `core_playable` headless launch remains healthy with default scene present.
- **Do not regress by doing X:**
  - Do **not** keep one behavior path for seeded/hotkey objects and another for right-click-created objects.
  - Do **not** rely on in-memory-only UI state for patrol path correctness.
  - Do **not** special-case seeded defaults as undeletable in authoring mode.

## 8) Patrol Can Be Placed but Does Not Move / Path Editor Exists but Is Undiscoverable
- **Problem name:** Patrol authoring appears present but is not usable in live play.
- **Symptom:** User can place patrol records but patrol does not visibly move, and path editing is hard to discover unless debug controls are remembered.
- **Root cause:** Two gaps combined:
  1. runtime patrol movement did not consume authored patrol route anchors as authoritative route truth;
  2. path workflow required extra discovery steps (no automatic entry, no explicit “path needed” feedback, anchor move action missing from right-click flow).
- **Relevant architecture / UX invariant:**
  - Campaign authoring must be right-click/context-menu first.
  - Authoring mutation remains `campaign_author_intent` only (viewer read-only for mutation).
  - Campaign movement semantics are continuous-plane, not hex-step cadence.
  - Authored patrol primitive and live patrol entity must remain one truth path.
- **Known-good fix path:**
  1. Keep patrol route truth in serialized `world.campaign_patrols[patrol_id].route_anchors`.
  2. Add deterministic runtime patrol route-follow sync in simulation module (`ExplorationExecutionModule`) so live patrol entity follows authored anchors.
  3. Auto-enter path edit mode after `Place Patrol Here`.
  4. In path edit mode, right-click anchor exposes both move and delete; right-click space adds anchor.
  5. If `route_anchors` is empty, patrol idles and UI explicitly reports `path needed`.
- **Required regression tests:**
  - Right-click patrol placement creates authored patrol/runtime patrol and enters obvious path workflow (`Edit Path` available and placement path-mode messaging present).
  - Path editing supports add/move/delete anchor operations through right-click actions.
  - Patrol movement follows authored route anchors continuously on campaign plane.
  - Save/load keeps patrol route and movement determinism stable (hash-stable at load point).
- **Do not regress by doing X:**
  - Do **not** reintroduce path editing as hidden hotkey-only behavior.
  - Do **not** maintain a dead authored patrol route record that runtime movement ignores.
  - Do **not** define patrol movement cadence as hex stepping.

## 9) Patrol Route Exists but Loop Semantics Are Ambiguous (Does Not Clearly Wrap to Start)
- **Problem name:** Placed patrol path exists but loop semantics are ambiguous / patrol fails to loop clearly.
- **Symptom:** Patrol can be placed and anchors can be authored, but live movement appears non-intuitive (for example appears to stop at end, or user cannot tell whether spawn is part of the route/loop).
- **Root cause:** Canonical semantics were not explicit in both runtime and UX:
  - route-follow targeted authored anchors only, while spawn participation in route cycle remained implicit/unclear;
  - campaign rendering did not provide clear route ordering/closure visibility (spawn, anchor order, explicit loop closure cue).
- **Relevant architecture / UX invariant:**
  - Campaign movement remains continuous-plane authoritative; hex remains derived indexing.
  - Viewer stays read-only and emits authoring intents only (`campaign_author_intent`).
  - Patrol route truth is serialized in `world.campaign_patrols` and progression state is serialized/hash-covered in rules state.
  - Right-click/context-menu remains canonical player-facing spatial authoring UX.
- **Known-good fix path:**
  1. Canonicalize route semantics: implicit anchor `0 = spawn_position`, authored anchors append after spawn, route wraps cyclically to anchor `0`.
  2. Keep zero-authored-anchor behavior explicit: patrol idles with status text `Add at least 1 route anchor to start loop.`
  3. Render patrol route visibly in campaign view: route line/polyline, ordered anchor markers, and explicit closure cue.
  4. Preserve deterministic route progression via serialized rules state and verify save/load continuation/hash stability.
- **Required regression tests:**
  - Zero-anchor patrol remains idle and target stays `None`.
  - One-anchor patrol loops between spawn and that anchor (both targets observed).
  - Multi-anchor patrol loops across anchors and back to spawn (spawn + anchors observed in route targets).
  - Route point compilation/order includes spawn first, then authored anchors in order.
  - Save/load mid-route progression matches uninterrupted hash outcome.
- **Do not regress by doing X:**
  - Do **not** treat authored anchors as the only loop set while hiding spawn route participation.
  - Do **not** leave patrol loop semantics undocumented/implicit in UX copy.
  - Do **not** move patrol routes via viewer-only mutation or non-serialized module memory.
