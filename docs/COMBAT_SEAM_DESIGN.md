# Combat Seam Design Memo (Wound-Ledger First, Continuous Tick)

## 1) Purpose and Constraints

This memo defines the **combat seam contract** for future implementation in the deterministic simulation engine.

### Goals
- Preserve a **continuous tick-based combat flow** inside the existing authoritative simulation loop.
- Support a combat feel where **information quality, positioning, and preparation** dominate outcomes over reflex speed.
- Establish a substrate that is **wound-ledger native** from day one.

### Hard constraints
- No initiative rounds.
- No modal simulation switch into a separate “combat mode.”
- No hidden mutable state in rule modules.
- All combat state and outcomes must remain JSON-safe, canonical-serializable, bounded, and hash-covered.
- Determinism contract remains strict: same seed + same input log + same code/content produces identical outcomes.

### Foundational model statement
- **Wound ledger is foundational.**
- Scalar HP depletion (if present for secondary systems) must not be assumed as the primary injury model.

---

## 2) Core Combat Intents

This section defines minimal command seams only. It does **not** define combat math.

### `attack_intent` (required seam)

Minimal JSON-safe payload:

```json
{
  "intent": "attack_intent",
  "attacker_id": "entity:...",
  "target_id": "entity:...",
  "mode": "melee",
  "weapon_ref": "item:...",
  "target_region": null,
  "tags": ["example"]
}
```

Required fields:
- `attacker_id`
- `target_id`
- `mode` (string enum owned by rules/content, e.g. `melee`, `ranged`)

Optional fields:
- `weapon_ref`
- `target_region` (nullable; seam support only)
- `tags` (array of strings)

Validation contract at intake (deterministic pass/fail):
- Attacker entity exists.
- Target entity exists.
- Both entities are in the same `space_id`.
- For melee-tagged modes, adjacency/topology reach check passes.
- Actor eligibility check passes (alive/present/not otherwise disqualified by serialized state).
- Unknown optional fields are ignored deterministically or rejected via schema policy (decision deferred to command schema policy, not combat logic).

Execution contract:
- Intent is accepted/rejected deterministically at ingest.
- Accepted intent resolves at authoritative tick `T` using only serialized world/sim state plus approved deterministic RNG stream usage.

Forensic `combat_outcome` record (minimum):

```json
{
  "event_type": "combat_outcome",
  "intent": "attack_intent",
  "action_uid": "...",
  "tick": 123,
  "attacker_id": "entity:...",
  "target_id": "entity:...",
  "mode": "melee",
  "applied": true,
  "reason": "resolved",
  "wound_deltas": [],
  "roll_trace": [],
  "tags": []
}
```

- `wound_deltas` is a structural payload for future wound application evidence.
- `roll_trace` is a forensic list of deterministic random outputs (when RNG is used).
- `reason` includes deterministic non-apply outcomes (`invalid_target`, `out_of_range`, `ineligible`, `cooldown_blocked`, etc.).

### `defend_intent` (optional seam, deferred)

Status:
- Seam reserved; concrete acceptance path may be deferred.

Minimum intended payload shape:
- `actor_id` (required)
- `mode` (required; stance/type)
- `duration_hint` (optional)
- `tags` (optional)

Validation contract (when enabled):
- Actor exists, same-space constraints where applicable, action eligibility passes.

Execution contract:
- Resolve at authoritative tick `T`.
- Emit `combat_outcome` with deterministic reasoning even when rejected/no-op.

### `disengage_intent` (optional seam, deferred)

Status:
- Seam reserved; concrete acceptance path may be deferred.

Minimum intended payload shape:
- `actor_id` (required)
- `from_entity_id` (optional)
- `tags` (optional)

Validation contract (when enabled):
- Actor exists and can legally disengage per topology/proximity constraints.

Execution contract:
- Resolve at authoritative tick `T`.
- Emit deterministic `combat_outcome` with applied/rejected reason.

---

## 3) Continuous Tick-Based Flow

### Authoritative timing
- Any entity may submit/attempt `attack_intent` on any tick.
- No initiative queue is introduced.
- No alternating actor phases are introduced.

### Minimal action timing primitive (design-only)
- Add per-entity serialized timing gate:
  - `next_action_tick` **or** `cooldown_until_tick`.
- The gate is read/written only through deterministic simulation execution.
- Eligibility at tick `T` uses this gate (`T >= gate_value` semantics, exact comparator deferred but fixed in implementation contract).

### Impairment interaction
- Wounds and related impairments may:
  - increase cooldown duration,
  - block specific intent families,
  - add deterministic penalties used by rule resolution.
- All such effects derive exclusively from serialized state and deterministic rules.

---

## 4) Wound-Ledger Substrate (Design Contract)

### Entity-level contract

Each entity must support a bounded wound ledger:

```json
{
  "wounds": [
    {
      "region": "...",
      "severity": "...",
      "tags": ["bleeding"],
      "inflicted_tick": 123,
      "source": "entity:attacker"
    }
  ]
}
```

- Field location is expected as `entity.wounds`.
- Ledger is bounded by constant `MAX_WOUNDS`.

### `WoundRecord` minimal fields
- `region` (enum/string; taxonomy deferred)
- `severity` (integer or enum; rules-defined)
- `tags` (rules-defined string tags)
- `inflicted_tick` (integer tick)
- `source` (optional attacker/source id)

### Contract statements
- Wounds are canonical-serialized and hash-covered.
- Wound mutations are deterministic and replay/save-load stable.
- Wounds persist until explicit deterministic healing/removal logic mutates ledger state.
- Overflow handling at `MAX_WOUNDS` is deterministic and explicit (e.g., FIFO eviction, merge, or rejection; policy deferred but must be fixed and tested once chosen).

### Primary injury model statement
- HP (if present) is not the primary injury model.
- Combat resolution seams must be able to produce direct wound outcomes without passing through HP-only depletion assumptions.

---

## 5) Resolution Model (Pluggable)

- Combat math and hit/penetration/injury computation live in rule modules.
- Engine core provides:
  - schema intake,
  - deterministic validation boundary,
  - deterministic mutation point,
  - deterministic forensic outcome emission.

### RNG contract
- If combat resolution requires RNG:
  - consume from a named deterministic stream (e.g., `combat`),
  - never consume ambient/global randomness,
  - include forensic roll values in `combat_outcome.roll_trace`.

### Replay contract
- Same seed + same input log => identical combat outcomes, wound ledger results, and forensic roll traces.

### Explicit non-choice
- No hit/damage/armor formulas are chosen in this memo.

---

## 6) Interaction With Existing Substrates

### Stats substrate
- Combat seams read stat inputs (strength/dexterity/etc.) through existing serialized entity stat surfaces.
- This memo does not define stat semantics.

### Signals / occlusion substrate
- Combat outcomes may emit signal events (sound/alert) through existing deterministic signal pathways.
- Awareness/perception and AI responses remain deferred; seam compatibility is preserved.

### Time substrate
- Cooldowns are tick-indexed and deterministic.
- Bleeding-over-time and other periodic wound effects are future periodic/event-queue consumers, not special loops.

### Multi-space topology
- Base validity requires same-space attacker/target.
- Cross-space combat is invalid unless future explicit bridge semantics are added.
- LOS specifics are deferred.

### Doors/interactions
- Combat does not bypass deterministic door/interactable constraints.
- No privileged combat path may mutate door/interactable state outside command/event seams.

---

## 7) Boundedness and Determinism Guarantees

The combat seam must include explicit bounded ledgers:
- `MAX_WOUNDS` per entity (required constant).
- `MAX_COMBAT_LOG` for combat forensic history if maintained as dedicated ledger (required constant if introduced).

Required behavior:
- All bounded ledgers use deterministic FIFO (or other explicitly fixed deterministic policy).
- No unbounded append paths in world/simulation payloads.
- All acceptance/rejection outcomes are deterministic and forensically visible.

---

## 8) Must-Not-Lock-Out Guarantees

This seam design preserves feasibility for:
- Armor coverage/threshold systems.
- Body-region targeting.
- Stealth/surprise mechanics.
- Lighting/visibility integration.
- AI tactical behavior.
- Ranged LOS and cover resolution.
- Interrupt/opportunity systems.

No current seam choice blocks these additions because:
- intent payloads include optional targeting metadata,
- timing uses per-entity tick gates rather than initiative rounds,
- outcomes are forensic and rule-pluggable,
- injury is ledger-based and structural.

Lock-out constraints reviewed: OK.

---

## 9) Deferred Decisions

Explicitly deferred in this memo:
- Exact wound taxonomy.
- Armor math and threshold formulas.
- Damage math and penetration formulas.
- Healing/treatment/recovery model.
- Shock/stamina model.
- AI behavior and target-selection policy.
- Friendly-fire policy.
- Multi-attacker coordination details.
- Ranged LOS/cover algorithm.
- Exact overflow policy at `MAX_WOUNDS`.
- Exact schema behavior for unknown optional intent fields (ignore vs strict reject), subject to global schema policy.

---

## 10) Minimal Future Implementation Plan

Smallest follow-on coding phase:
1. Add command/event schemas for `attack_intent` and `combat_outcome`.
2. Add per-entity serialized action timing gate (`next_action_tick` or `cooldown_until_tick`).
3. Add canonicalized empty `wounds` list to entity payload schema/state.
4. Add deterministic attack-resolution stub that validates, emits `combat_outcome`, and performs no advanced combat math.
5. Add regression tests:
   - replay identity (same seed/input => same outcomes),
   - save/load + hash stability with combat artifacts,
   - boundedness enforcement for wound/combat ledgers,
   - deterministic rejection paths for invalid intents.
