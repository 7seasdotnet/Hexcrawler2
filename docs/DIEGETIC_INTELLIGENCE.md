# DIEGETIC_INTELLIGENCE.md

## Status
Authoritative Contract – Political Epistemology Substrate

This document defines the engine-level contracts for faction belief, information propagation, investigation, and disposition.

If any other document conflicts with this file regarding intelligence, belief, propagation, or reputation semantics, **this document governs**.

If implementation code conflicts with this document, either:
1) The code must be changed, or
2) A temporary deviation must be explicitly documented with justification.

This file is mandatory pre-implementation review material.

---

# 0. Non-Negotiable Principles

1. Determinism: Same seed + same command log ⇒ identical world_hash.
2. Atomicity: Rejection ⇒ zero mutation.
3. Serialization Discipline: All persistent state is serialized and hash-covered. Derived values are never serialized.
4. Boundedness: All collections and queues are hard-capped with deterministic eviction.
5. Event-Driven Only: No per-tick global graph scanning.
6. Diegetic UI Only: No quest logs, no objective trackers, no confidence numbers.
7. Editor-First with Safety Clamps: Content may tune within engine-enforced hard bounds.

---

# 1. Conceptual Model

The engine distinguishes:

- Objective Event (what occurred)
- Belief (what a faction thinks occurred)
- Disposition (behavior tier derived from belief)
- Transmission (belief spread)
- Investigation (belief correction)

Factions act on belief, not truth.

---

# 2. Entities and Identity

## 2.1 BeliefSubject

Beliefs may reference:

- Player
- Faction (faction_id)
- Group (group_id)
- UnknownActor (explicit subject type)

UnknownActor is a valid subject with bounded metadata.
It must not be represented as null/None.

## 2.2 Stable Identity Contract

All subject identifiers must be stable and deterministic.
No runtime memory addresses.
No random UUIDs.
No ephemeral keys.

---

# 3. Claim Categories (Launch Set)

1. Violence
2. Theft
3. Aid
4. Betrayal
5. Alliance
6. TerritorialViolation
7. LeadershipImpact

Each category defines:

- default_weight
- decay_profile
- propaganda_susceptibility
- transmission_multiplier
- disposition_contribution_profile
- economic_effect_profile
- aggregation_semantics (required for extensibility)

New categories MUST define all parameters above.

---

# 4. BeliefRecord (Merged Structure)

Keyed by:

(believer_faction_id, subject_ref, category, optional target_ref)

Fields:

- active_confidence (fixed-point integer)
- recollection_tier (None | Historical | Legendary)
- last_update_tick
- source_summary (bounded list)
- notables (bounded list)
- contradiction_state (None | Uncertain | Investigating)

## 4.1 Notables

Bounded, deterministically evicted.

Each notable must have:

- deterministic notable_id (e.g., sha256 of canonical event tuple)
- event_id
- summary_tag
- tick

---

# 5. Confidence Model

Fixed-point integer only (e.g., 0–100).

No floats.
No probabilistic math stored as floats.

Belief is continuous.
Behavior is discrete.

---

# 6. Decay and Recollection

Active confidence decays deterministically per category.

When crossing below threshold:

- record transitions into recollection_tier.
- recollection affects tone and bias only.
- recollection cannot escalate hostility tier by itself.

Recollection is bounded and subject to deterministic eviction.

---

# 7. Disposition (Derived Only)

Disposition tiers are derived from BeliefRecords.

They are NEVER serialized.

Example tiers:

- Unaware
- Suspicious
- Convinced
- Hostile

Thresholds are configurable but clamped.

---

# 8. Attribution and Scapegoating

When an event occurs:

1) Identified actor ⇒ attribute directly.
2) Unknown actor ⇒ attribute to UnknownActor.
3) Biased inference ⇒ may attribute to plausible scapegoat.

Scapegoat inference must be deterministic:

- Candidate set must be bounded.
- Scoring inputs limited to:
  - prior disposition tier
  - propaganda bias
  - rivalry adjacency
- Tie-breaking deterministic (stable ordering).

No automatic blame assignment.

---

# 9. Transmission Model

Propagation eligibility depends on:

- Geographic radius / region adjacency
- Diplomatic links
- Intelligence network strength
- Geological modifiers

Transmission is executed via queued jobs only.

No synchronous cascading.

---

# 9A. Authoritative Faction Registry and Activation Gate

- `world.faction_registry` is authoritative for what counts as a faction in simulation space (campaign/local role-agnostic identity substrate).
- `world.activated_factions` is the diegetic activation gate for information fan-out and propagation work queues.
- Propagation recipients are selected from activated factions only (excluding source), with deterministic lexical ordering and existing bounded caps.
- Belief state remains lazy: registry membership does not pre-allocate belief graphs. Faction belief state is created only on first use (activation side effects may be forensic only).
- Backward compatibility: saves lacking `faction_registry` derive it deterministically from existing `faction_beliefs` keys (sorted); if no beliefs exist, registry defaults to empty.
- Canonical serialization discipline: a registry derived only for backward compatibility/runtime use is default-omitted on save. `faction_registry` is emitted only when it was explicitly authored in input/content.

# 9B. Geography Gating (Region/Site Template)

- Geography gating is an explicit deterministic allow/deny policy over existing event context fields only: `region_id` and `site_template_id`.
- It is role-compatible for campaign/local routing metadata, but does **not** introduce distance/pathfinding/travel-time semantics.
- No inference/derivation is permitted: if context fields are absent, gating decisions operate strictly on configured policy (including optional `require_context`).
- Fan-out and enqueue gating are both deterministic and bounded: deny-lists override allow-lists, and when both region/site context are present, both dimensions are evaluated conservatively.

# 9C. Contact Lists (Structural Propagation)

- `world.faction_contacts` is an authored structural propagation constraint, not a relationship score and not a diplomacy graph.
- For fan-out recipient universe selection: recipients are drawn from `activated_factions ∩ faction_contacts[source_faction_id]` when a source-specific contact list exists.
- If a source has no authored contact list, fan-out remains backward-compatible open-network behavior over `activated_factions` (subject to existing caps and exclusion of source).
- Contact lists are deterministic substrate data only; they do not force disposition changes, diplomacy state, or direct behavior overrides.

# 9D. Contact Updates (Diegetic)

- Contact updates are processed through deterministic simulation events only:
  - `faction_contact_added`
  - `faction_contact_removed`
- Both ids are canonicalized (`strip().lower()`), validated against `world.faction_registry`, and self-contact is deterministically rejected.
- Add behavior is bounded:
  - existing edge => no-op forensic (`faction_contact_add_noop`),
  - source at `MAX_CONTACTS_PER_FACTION` => deterministic reject (`faction_contact_add_rejected`, `reason="cap_full"`),
  - otherwise add edge and lexically sort recipient list.
- Remove behavior is bounded:
  - absent edge => no-op forensic (`faction_contact_remove_noop`),
  - present edge => remove and keep lexical ordering.
- Canonical omission remains in effect: when a source has zero contacts after removal, that source key is omitted from `world.faction_contacts`.
- These updates are structural propagation constraints only and remain out of scope for relationship scoring, diplomacy graphs, and TTL/decay.

# 9E. Contact TTL / Decay (Deterministic, Bounded)

- Contact decay remains optional and fully deterministic via `world.contact_ttl_config`:
  - `enabled` (default `false`)
  - `contact_ttl_ticks` (required `>0` when enabled)
  - `max_decay_per_tick` (bounded per-tick cleanup cap)
- Contact touch metadata is serialized/hash-covered in `world.faction_contact_meta[source][target].last_touch_tick` and is omitted when empty.
- Touch semantics are diegetic and event-driven (`faction_contact_touched`):
  - contact add success schedules a touch,
  - successful fan-out enqueue emission (`belief_fanout_emitted`) schedules a touch,
  - touch against a missing edge is deterministic no-op forensic with `reason="touch_no_edge"`.
- Decay ordering is fixed and deterministic (not configurable): lexical source order, lexical target order.
- Decay processing is bounded per tick by `max_decay_per_tick` and emits `faction_contact_decayed` per removed edge; optional `faction_contact_decay_budget_exhausted` forensic is emitted when expired contacts remain after budget cap is hit.
- Legacy compatibility policy for old saves with contacts but no meta: first decay pass assigns `last_touch_tick=current_tick` for missing meta entries before evaluation, preventing immediate decay while preserving deterministic replay/save-load behavior.

# 10. Carrier Model

The engine must not require physical courier simulation.

Optional flavor:

- When groups arrive at sites, they may emit transmission events derived from faction beliefs.

Groups are carriers only.
Groups do not store belief graphs.

---

# 11. Investigation Jobs

Investigation is event-driven and queued.

Each job contains:

- belief_record_key
- scheduled_tick
- evidence_hook_tags
- deterministic_rng_seed

Randomness is permitted only during job creation or resolution and must be:

- deterministically seeded
- ledgered
- serialized

No rerolls on save/load.

Investigation may:

- increase confidence
- decrease confidence
- change contradiction_state
- emit secondary rumor tokens

---

# 12. Processing Discipline

All jobs processed via:

- deterministic ordering
- bounded per-tick caps
- deferral cursor

Queues must have hard maximum length.

No recursive propagation within a single tick.

---

# 13. Forensics Requirement

When:

- Disposition tier changes
- Investigation resolves contradiction
- Scapegoat inference occurs

Emit a concise forensic event token for testing and debugging.

---

# 14. Boundedness Constants

Engine must define hard caps for:

- MAX_BELIEF_RECORDS_PER_FACTION
- MAX_NOTABLES_PER_RECORD
- MAX_SOURCE_TOKENS_PER_RECORD
- MAX_RECOLLECTION_RECORDS_PER_FACTION
- MAX_TRANSMISSION_JOBS_PER_TICK
- MAX_INVESTIGATION_JOBS_PER_TICK
- MAX_DIPLOMACY_LINKS_PER_FACTION
- MAX_JOB_QUEUE_LENGTH

World configs may override within clamped limits.

---

# 15. Authored Stimulus Integration Rule

Authored content (editor/world design) may introduce political “initial conditions” and “shocks” for storytelling.

Contract:

- Authored stimuli MUST enter the simulation only as standard claim-bearing events (i.e., the same ClaimCategory/BeliefRecord pathway used by emergent simulation events).
- Authored stimuli MUST be enqueued into the same deterministic, bounded processing system (TransmissionJob / InvestigationJob where applicable).
- Authored stimuli MUST respect delay, geography/topology gating, decay, recollection, contradiction handling, and derived-only disposition.

Prohibited shortcuts:

- No direct mutation of disposition tiers (disposition is derived-only).
- No bypass of transmission/investigation queues (no synchronous global propagation).
- No hidden objective/quest completion flags or non-diegetic tracking state.
- No “force hostile/friendly” switches outside belief thresholds.

Rationale:

- Enables OSR-compatible storytelling via world-authored political setup while preserving the engine’s simulation physics and invariants.

---

# 16. Forbidden Anti-Patterns

- Global reputation meter as authority
- Direct disposition forcing or tier mutation
- Quest tracking
- Objective completion flags
- Instant global knowledge
- Unbounded belief growth
- UI display of internal math
- Floating-point confidence

---

# 17. OSR Alignment Statement

This system enforces:

- Local, fragmented politics
- Delayed information
- Fallible institutions
- Emergent consequences
- Player inference over UI exposition

The world produces incentives.
The player chooses.

No narrative rail.
No quest log.
No invisible hand.

---
END
