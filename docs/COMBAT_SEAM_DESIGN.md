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

Canonical target cell reference type used by this seam:

- `CellRef`
  - `space_id` (string)
  - `coord` (topology-dependent payload)

`CellRef.coord` encoding is owned by topology rules for the referenced `space_id`.
- Hex spaces may use axial `(q,r)` or another canonical hex encoding selected by topology rules.
- Square spaces may use `(x,y)`.
- The seam does not require `coord` to be a fixed 2-tuple; alternative coordinate schemes (including nested/z-aware forms) remain topology-owned.
- Engine validates `CellRef` against the referenced space topology at tick `T`.

Minimal JSON-safe payload:

```json
{
  "intent": "attack_intent",
  "attacker_id": "entity:...",
  "target_id": "entity:...",
  "target_cell": {"space_id": "overworld", "coord": [0, 0]},
  "mode": "melee",
  "weapon_ref": "item:...",
  "target_region": null,
  "tags": ["example"]
}
```

Required fields:
- `attacker_id`
- `mode` (string enum owned by rules/content, e.g. `melee`, `ranged`)

Optional fields:
- `target_id` (nullable only when `target_cell` is provided)
- `target_cell` (nullable `CellRef`; seam supports cell-only and combined targeting)
- `weapon_ref`
- `target_region` (nullable called-shot request; defaults to `torso`/center-mass when omitted)
- `tags` (array of strings)

Targeting forms accepted by seam:
- `A)` entity target only (`target_id` set, `target_cell` null)
- `B)` cell target only (`target_cell` set, `target_id` null)
- `C)` both entity + cell (`target_id` and `target_cell` set)

Validation contract at intake (deterministic pass/fail):
- Attacker entity exists.
- At least one targeting discriminator is present (`target_id` or `target_cell`).
- If `target_id` is present, target entity exists.
- If `target_cell` is present, cell payload is structurally valid for the space/topology.
- If both `target_id` and `target_cell` are present, they must be consistent at tick `T` (target entity occupies target cell) or the intent is rejected deterministically.
- If `target_id` is present, attacker and target are in the same `space_id`.
- If only `target_cell` is present, attacker and target cell must be in the same `space_id`.
- For melee-tagged modes, adjacency/topology reach check passes.
- Selected target discriminator (entity and/or cell) is admissible for the deterministic attack shape contract at tick `T` (attacker position + facing + weapon/mode + topology rules).
- Actor eligibility check passes (alive/present/not otherwise disqualified by serialized state).
- Unknown optional fields are ignored deterministically or rejected via schema policy (decision deferred to command schema policy, not combat logic).

Validation vs resolution boundary:
- Validation checks admissibility of the player-selected discriminator(s) at intake.
- Resolution deterministically determines actual affected entity/entities and records results in outcomes.
- Engine seam does not require precomputing the full affected set at intake; it enforces admissibility and records results.

Called-shot contract:
- `target_region` is a requested called-shot region, not a guaranteed outcome.
- If `target_region` is omitted/null, called shot defaults to `torso` (center-mass label).
- Region taxonomy remains content/rules-owned and deferred at seam level.

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
  "target_cell": {"space_id": "overworld", "coord": [0, 0]},
  "mode": "melee",
  "called_region": "torso",
  "region_hit": "arm",
  "applied": true,
  "reason": "resolved",
  "affected": [
    {
      "entity_id": "entity:...",
      "cell": {"space_id": "overworld", "coord": [0, 0]},
      "called_region": "torso",
      "region_hit": "arm",
      "wound_deltas": [],
      "applied": true,
      "reason": "resolved"
    }
  ],
  "wound_deltas": [],
  "roll_trace": [],
  "tags": []
}
```

- `wound_deltas` is a structural payload for future wound application evidence.
- `roll_trace` is a forensic list of deterministic random outputs (when RNG is used).
- `reason` includes deterministic non-apply outcomes (`invalid_target`, `out_of_range`, `ineligible`, `cooldown_blocked`, etc.).
- `called_region` records requested region after defaulting logic (`torso` when omitted/null).
- `region_hit` records deterministic actual impacted region (nullable when no hit is applied).
- Optional deterministic redirect rationale may be included via outcome metadata (e.g., `redirected_by_rules`), with taxonomy deferred.
- `target_id`/`target_cell` remain the selected/aimed target for UI correlation with the submitted intent.
- `affected` is optional and records actual applied consequences for multi-target resolution paths (sweeps/AoE/cell effects) while preserving primary selected-target fields.
- Each `affected` entry is JSON-safe and may include:
  - `entity_id` (nullable when effect is purely on a cell),
  - `cell` (optional `CellRef`),
  - `called_region` (optional/nullable),
  - `region_hit` (optional/nullable),
  - `wound_deltas` (array, may be empty),
  - `applied` (bool) and optional `reason` (string).
- If `affected` is introduced in implementation, it must be bounded by a fixed constant (e.g., `MAX_AFFECTED_PER_ACTION`) with deterministic overflow policy.

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

### Authoritative facing state (required for arcs)
- Each entity carries authoritative `facing` state as part of serialized entity state.
- Facing is hash-covered by standard canonical serialization of entity payloads.
- Facing updates are accepted only through authoritative simulation commands/intents (same authority class as movement mutations).
- Representation is topology-dependent:
  - `overworld_hex`: 6 discrete directions.
  - `square_grid`: represented as an integer direction token whose 4-way vs 8-way interpretation is deferred to topology rules.
- Facing is required input for directional attacks, weapon arcs, and attack-shape validation.

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
- Combat outcomes must preserve called-shot forensic fields: requested `called_region` and actual `region_hit` (both nullable strings in schema), with deterministic redirection reason optional.

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

### Weapon arc / attack-shape seam contract
- Weapons may define deterministic attack shapes in content/rules (`arc`, `cone`, `line`, `sweep`, etc.; taxonomy deferred).
- At tick `T`, legal affected targets are derived deterministically from attacker position + authoritative facing + weapon/mode reference + topology rules.
- Validation step: engine seam enforces deterministic admissibility checks that chosen entity/cell discriminator is legal for that computed attack shape at tick `T`.
- Resolution step: rules deterministically resolve actual affected entity/entities (e.g., first-in-line, all in cone, etc.) and outcome records what was affected.
- Engine seam does not require precomputing the full affected set at intake; it enforces admissibility and records results.
- Cell-only targeting is permitted; resolution may deterministically affect an entity in that cell or none, and outcome records what was affected.
- LOS/cover coupling is explicitly deferred, but seam choices here must not lock out future LOS/cover integration.

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
- Square-grid facing interpretation (4-way vs 8-way).
- Exact wound taxonomy.
- Armor math and threshold formulas.
- Damage math and penetration formulas.
- Healing/treatment/recovery model.
- Shock/stamina model.
- AI behavior and target-selection policy.
- Friendly-fire policy.
- Multi-attacker coordination details.
- Ranged LOS/cover algorithm.
- Weapon attack-shape taxonomy and per-weapon parameterization details (owned by content/rules).
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
