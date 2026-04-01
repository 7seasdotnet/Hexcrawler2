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
