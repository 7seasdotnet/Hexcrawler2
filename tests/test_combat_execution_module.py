import pytest

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.combat import (
    ATTACK_INTENT_COMMAND_TYPE,
    TURN_INTENT_COMMAND_TYPE,
    TURN_OUTCOME_EVENT_TYPE,
    WEAPON_MOTION_PROFILES,
    CombatExecutionModule,
)
from hexcrawler.sim.core import MAX_AFFECTED_PER_ACTION, MAX_COMBAT_LOG, MAX_WOUNDS, EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord, HexRecord, SpaceState, WorldState


LOCAL_SPACE_ID = "local_arena"

def _build_sim() -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[LOCAL_SPACE_ID] = SpaceState(
        space_id=LOCAL_SPACE_ID,
        topology_type="hex_disk",
        role="local",
        hexes={
            HexCoord(0, 0): HexRecord(terrain_type="plains"),
            HexCoord(1, 0): HexRecord(terrain_type="plains"),
            HexCoord(1, -1): HexRecord(terrain_type="plains"),
            HexCoord(0, -1): HexRecord(terrain_type="plains"),
        },
    )
    sim = Simulation(world=world, seed=17)
    sim.register_rule_module(CombatExecutionModule())
    attacker = EntityState.from_hex(entity_id="attacker", hex_coord=HexCoord(0, 0), speed_per_tick=0.0)
    attacker.space_id = LOCAL_SPACE_ID
    target = EntityState.from_hex(entity_id="target", hex_coord=HexCoord(1, 0), speed_per_tick=0.0)
    target.space_id = LOCAL_SPACE_ID
    sim.add_entity(attacker)
    sim.add_entity(target)
    return sim




def _turn_command(*, tick: int, entity_id: str = "attacker", facing: object = 0, tags: list[str] | None = None) -> SimCommand:
    params: dict[str, object] = {"entity_id": entity_id, "facing": facing}
    if tags is not None:
        params["tags"] = tags
    return SimCommand(tick=tick, command_type=TURN_INTENT_COMMAND_TYPE, params=params)


def _turn_outcomes(sim: Simulation) -> list[dict[str, object]]:
    return [entry for entry in sim.get_event_trace() if entry.get("event_type") == TURN_OUTCOME_EVENT_TYPE]

def _attack_command(*, tick: int, target_id: str | None = "target", target_cell=None, attacker_id: str = "attacker") -> SimCommand:
    params = {
        "attacker_id": attacker_id,
        "mode": "melee",
        "tags": ["test"],
    }
    if target_id is not None:
        params["target_id"] = target_id
    if target_cell is not None:
        params["target_cell"] = target_cell
    return SimCommand(tick=tick, command_type=ATTACK_INTENT_COMMAND_TYPE, params=params)


def _first_outcome_with_reason(sim: Simulation, reason: str) -> dict[str, object]:
    return next(entry for entry in sim.state.combat_log if entry.get("reason") == reason)


def _first_applied_outcome(sim: Simulation) -> dict[str, object]:
    return next(entry for entry in sim.state.combat_log if entry.get("applied") is True)


def test_attack_intent_has_no_authoritative_effect_before_tick_executes() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=2))

    assert sim.state.entities["attacker"].cooldown_until_tick == 0
    assert sim.state.combat_log == []

    sim.advance_ticks(1)
    assert sim.state.tick == 1
    assert sim.state.entities["attacker"].cooldown_until_tick == 0
    assert sim.state.combat_log == []


def test_attack_outcomes_are_deterministic_for_acceptance_and_rejection() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}}))
    sim.append_command(_attack_command(tick=1, target_id=None, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 0, "r": 0}}))

    sim.advance_ticks(4)

    accepted = next(entry for entry in sim.state.combat_log if entry.get("applied") is True)
    rejected = next(entry for entry in sim.state.combat_log if entry.get("reason") == "out_of_range")
    assert accepted["applied"] is True
    assert "affected" in accepted
    assert len(accepted["affected"]) >= 1
    assert accepted["reason"] == "resolved"
    assert accepted["called_region"] == "torso"
    assert accepted["region_hit"] == "torso"
    assert accepted["wound_deltas"] == []
    assert sim.state.entities["target"].wounds == [
        {
            "region": "torso",
            "severity": 1,
            "tags": [],
            "inflicted_tick": 2,
            "source": "attacker",
        }
    ]

    assert rejected["applied"] is False
    assert rejected["reason"] == "out_of_range"
    assert "affected" not in rejected


def test_applied_attack_populates_affected_target_fields() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}}))
    sim.advance_ticks(3)

    outcome = _first_applied_outcome(sim)
    assert outcome["applied"] is True
    assert "affected" in outcome
    assert outcome["reason"] == "resolved"
    assert outcome["called_region"] == "torso"
    assert outcome["region_hit"] == "torso"

    affected = outcome["affected"]
    assert len(affected) == 1
    assert affected[0]["entity_id"] == "target"
    assert affected[0]["cell"] == {"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}}
    assert affected[0]["called_region"] == "torso"
    assert affected[0]["region_hit"] == "torso"
    assert affected[0]["wound_deltas"] == [
        {
            "op": "append",
            "wound": {
                "region": "torso",
                "severity": 1,
                "tags": [],
                "inflicted_tick": 2,
                "source": "attacker",
            },
        }
    ]
    assert affected[0]["applied"] is True
    assert affected[0]["reason"] == "resolved"
    assert sim.state.entities["target"].wounds[-1] == affected[0]["wound_deltas"][0]["wound"]


def test_cell_only_targeting_without_occupant_is_rejected_and_omits_affected() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": -1}}))
    sim.advance_ticks(3)

    windup = sim.state.combat_log[0]
    outcome = sim.state.combat_log[1]
    assert windup["reason"] == "windup_started"
    assert outcome["applied"] is False
    assert outcome["reason"] == "no_target_in_cell"
    assert "affected" not in outcome
    assert sim.state.entities["target"].wounds == []

    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.combat_log[1] == outcome
    assert "affected" not in restored.state.combat_log[1]


def test_not_ready_gate_blocks_repeat_attack_without_combat_log_spam() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.append_command(_attack_command(tick=0))
    sim.append_command(_attack_command(tick=1))

    sim.advance_ticks(8)

    reasons = [entry["reason"] for entry in sim.state.combat_log]
    assert reasons == ["windup_started", "resolved"]
    assert [entry["reason"] for entry in sim.get_command_outcomes()] == []


def test_repeated_attack_intents_during_cadence_do_not_create_extra_combat_outcomes() -> None:
    sim = _build_sim()
    for tick in range(0, 7):
        sim.append_command(_attack_command(tick=tick))

    sim.advance_ticks(10)

    outcome_reasons = [entry["reason"] for entry in sim.state.combat_log]
    assert outcome_reasons == ["windup_started", "resolved"]
    assert len([entry for entry in sim.state.combat_log if entry.get("applied") is True]) == 1
    assert sim.state.entities["target"].wounds == [
        {"region": "torso", "severity": 1, "tags": [], "inflicted_tick": 2, "source": "attacker"}
    ]


def test_attack_cadence_stores_committed_direction_and_normalized_weapon_profile() -> None:
    sim = _build_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={
                "attacker_id": "attacker",
                "target_id": "target",
                "mode": "melee",
                "weapon_profile_id": "thrust",
                "committed_aim": {"space_id": LOCAL_SPACE_ID, "x": 0.0, "y": 1.0, "facing": 0},
                "target_point": {"space_id": LOCAL_SPACE_ID, "x": 1.0, "y": 0.0},
                "tags": ["test"],
            },
        )
    )
    # Retarget the actor's facing before impact; event resolution must use the captured
    # facing/aim from acceptance, not cursor/facing drift afterward.
    sim.append_command(_turn_command(tick=1, facing=3))

    sim.advance_ticks(7)

    windup = _first_outcome_with_reason(sim, "windup_started")
    impact = _first_applied_outcome(sim)
    assert windup["committed_aim"] == {"space_id": LOCAL_SPACE_ID, "x": 0.0, "y": 1.0, "facing": 0}
    assert impact["committed_aim"] == windup["committed_aim"]
    assert impact["weapon_profile_id"] == "default_melee"
    assert impact["weapon_profile"] == {"profile_id": "default_melee", "motion_family": "slash", "windup_ticks": 2, "impact_tick": 2, "recovery_ticks": 5}
    assert sim.state.entities["target"].wounds[0]["inflicted_tick"] == 2


def test_spoofed_weapon_profile_id_is_normalized_and_cannot_change_timing() -> None:
    sim = _build_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={
                "attacker_id": "attacker",
                "target_id": "target",
                "mode": "melee",
                "weapon_profile_id": "chop",
                "weapon_ref": "war axe",
                "tags": ["test"],
            },
        )
    )

    sim.advance_ticks(4)

    windup = _first_outcome_with_reason(sim, "windup_started")
    impact = _first_applied_outcome(sim)
    assert windup["weapon_profile_id"] == "default_melee"
    assert windup["impact_tick"] == 2
    assert windup["recovery_until_tick"] == 8
    assert impact["tick"] == 2
    assert impact["weapon_profile"]["motion_family"] == "slash"


def test_weapon_motion_profile_seam_distinguishes_gate_one_families() -> None:
    assert set(WEAPON_MOTION_PROFILES) >= {"default_melee", "slash", "thrust", "chop", "stab", "bash"}
    assert WEAPON_MOTION_PROFILES["slash"].motion_family == "slash"
    assert WEAPON_MOTION_PROFILES["thrust"].reach > WEAPON_MOTION_PROFILES["stab"].reach
    assert WEAPON_MOTION_PROFILES["chop"].windup_ticks > WEAPON_MOTION_PROFILES["stab"].windup_ticks
    assert WEAPON_MOTION_PROFILES["bash"].arc_degrees != WEAPON_MOTION_PROFILES["thrust"].arc_degrees


def test_empty_space_directional_attack_accepts_cadence_and_whiffs_cleanly() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": -1}}))

    sim.advance_ticks(4)

    assert [entry["reason"] for entry in sim.state.combat_log] == ["windup_started", "no_target_in_cell"]
    assert sim.state.combat_log[0]["cadence_state"] == "WINDUP"
    assert sim.state.combat_log[1]["cadence_state"] == "IMPACT_MISS"
    assert sim.state.combat_log[1]["applied"] is False
    assert "affected" not in sim.state.combat_log[1]
    assert sim.state.entities["target"].wounds == []


def test_cadence_boundary_ready_resumes_on_exact_cooldown_until_tick() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.append_command(_attack_command(tick=7))
    sim.append_command(_attack_command(tick=8))

    sim.advance_ticks(12)

    # default_melee: windup ticks 0-1, impact at acceptance+2, recovery ticks 3-7, READY at tick 8.
    assert [entry["tick"] for entry in sim.state.combat_log if entry["reason"] == "windup_started"] == [0, 8]
    assert [entry["tick"] for entry in sim.state.combat_log if entry["applied"] is True] == [2, 10]
    assert sim.state.entities["attacker"].cooldown_until_tick == 16


def test_save_load_during_windup_emits_exactly_one_impact() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(1)
    assert [entry["reason"] for entry in sim.state.combat_log] == ["windup_started"]

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.advance_ticks(4)

    applied = [entry for entry in loaded.state.combat_log if entry.get("applied") is True]
    assert len(applied) == 1
    assert applied[0]["tick"] == 2
    assert [entry["reason"] for entry in loaded.state.combat_log] == ["windup_started", "resolved"]


def test_save_load_during_recovery_preserves_not_ready_until_boundary() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(3)
    assert sim.state.tick == 3
    assert sim.state.entities["attacker"].cooldown_until_tick == 8

    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.append_command(_attack_command(tick=3))
    loaded.append_command(_attack_command(tick=8))
    loaded.advance_ticks(9)

    assert [entry["tick"] for entry in loaded.state.combat_log if entry["reason"] == "windup_started"] == [0, 8]
    assert [entry["tick"] for entry in loaded.state.combat_log if entry.get("applied") is True] == [2, 10]


def test_save_load_continuation_matches_fresh_run_hash_and_no_duplicate_impact() -> None:
    commands = [_attack_command(tick=0), _attack_command(tick=8)]
    baseline = _build_sim()
    for command in commands:
        baseline.append_command(command)
    baseline.advance_ticks(12)

    interrupted = _build_sim()
    for command in commands:
        interrupted.append_command(command)
    interrupted.advance_ticks(1)
    loaded = Simulation.from_simulation_payload(interrupted.simulation_payload())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.advance_ticks(11)

    assert loaded.state.combat_log == baseline.state.combat_log
    assert simulation_hash(loaded) == simulation_hash(baseline)
    assert len([entry for entry in loaded.state.combat_log if entry.get("applied") is True]) == 2


def test_combat_save_payload_rejects_presentation_only_metadata() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(3)
    payload = sim.simulation_payload()
    forbidden_fragments = ("screen", "pixel", "camera", "zoom", "interpolation", "render", "bbox", "cursor", "arc_geometry", "presentation")
    serialized = str(payload).lower()
    assert not any(fragment in serialized for fragment in forbidden_fragments)
    assert "reach" not in payload["combat_log"][0]["weapon_profile"]
    assert "arc_degrees" not in payload["combat_log"][0]["weapon_profile"]

    poisoned = sim.simulation_payload()
    poisoned["combat_log"][0]["screen_x"] = 12
    with pytest.raises(ValueError, match="presentation-only"):
        Simulation.from_simulation_payload(poisoned)


def test_combat_state_round_trip_and_hash_is_stable() -> None:
    script = [
        _attack_command(tick=0),
        _attack_command(tick=1, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 0, "r": 0}}),
    ]

    sim_a = _build_sim()
    sim_b = _build_sim()
    for command in script:
        sim_a.append_command(command)
        sim_b.append_command(command)
    sim_a.advance_ticks(4)
    sim_b.advance_ticks(4)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)

    restored = Simulation.from_simulation_payload(sim_a.simulation_payload())
    assert restored.state.combat_log == sim_a.state.combat_log
    assert restored.state.entities["attacker"].cooldown_until_tick == sim_a.state.entities["attacker"].cooldown_until_tick
    assert restored.state.entities["target"].wounds == sim_a.state.entities["target"].wounds
    assert simulation_hash(restored) == simulation_hash(sim_a)


def test_combat_log_is_bounded_with_deterministic_fifo_eviction() -> None:
    sim = _build_sim()
    for index in range(MAX_COMBAT_LOG + 3):
        sim.append_command(_attack_command(tick=index * 8))
    sim.advance_ticks((MAX_COMBAT_LOG + 3) * 8 + 4)

    assert len(sim.state.combat_log) == MAX_COMBAT_LOG
    assert sim.state.combat_log[0]["tick"] >= 2
    assert sim.state.combat_log[-1]["tick"] >= MAX_COMBAT_LOG + 1


def test_affected_entries_are_truncated_to_max_bound() -> None:
    oversized = [{"entity_id": str(index), "wound_deltas": []} for index in range(MAX_AFFECTED_PER_ACTION + 3)]
    normalized = Simulation.from_simulation_payload(
        {
            **_build_sim().simulation_payload(),
            "combat_log": [
                {
                    "tick": 0,
                    "intent": ATTACK_INTENT_COMMAND_TYPE,
                    "action_uid": "0:0",
                    "attacker_id": "attacker",
                    "target_id": "target",
                    "target_cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}},
                    "mode": "melee",
                    "weapon_ref": None,
                    "called_region": "torso",
                    "region_hit": "torso",
                    "applied": True,
                    "reason": "resolved",
                    "wound_deltas": [],
                    "roll_trace": [],
                    "tags": [],
                    "affected": oversized,
                }
            ],
        }
    )

    affected = normalized.state.combat_log[0]["affected"]
    assert len(affected) == MAX_AFFECTED_PER_ACTION
    assert [row["entity_id"] for row in affected] == [str(index) for index in range(MAX_AFFECTED_PER_ACTION)]
    assert affected[0]["wound_deltas"] == []


def test_load_normalization_injects_default_wound_deltas_without_injecting_affected_on_rejected() -> None:
    normalized = Simulation.from_simulation_payload(
        {
            **_build_sim().simulation_payload(),
            "combat_log": [
                {
                    "tick": 0,
                    "intent": ATTACK_INTENT_COMMAND_TYPE,
                    "action_uid": "0:0",
                    "attacker_id": "attacker",
                    "target_id": "target",
                    "target_cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}},
                    "mode": "melee",
                    "weapon_ref": None,
                    "called_region": "torso",
                    "region_hit": "torso",
                    "applied": True,
                    "reason": "resolved",
                    "wound_deltas": [],
                    "roll_trace": [],
                    "tags": [],
                    "affected": [
                        {
                            "entity_id": "target",
                            "cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}},
                            "called_region": "torso",
                            "region_hit": "torso",
                            "applied": True,
                            "reason": "resolved",
                        }
                    ],
                },
                {
                    "tick": 1,
                    "intent": ATTACK_INTENT_COMMAND_TYPE,
                    "action_uid": "1:0",
                    "attacker_id": "attacker",
                    "target_id": None,
                    "target_cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 9, "r": 9}},
                    "mode": "melee",
                    "weapon_ref": None,
                    "called_region": "torso",
                    "region_hit": None,
                    "applied": False,
                    "reason": "no_target_in_cell",
                    "wound_deltas": [],
                    "roll_trace": [],
                    "tags": [],
                },
            ],
        }
    )

    applied, rejected = normalized.state.combat_log
    assert "affected" in applied
    assert len(applied["affected"]) >= 1
    assert applied["affected"][0]["wound_deltas"] == []
    assert "affected" not in rejected


def test_absent_vs_explicit_default_entity_fields_have_matching_hash() -> None:
    base = _build_sim()
    base.state.entities["attacker"].facing = 2
    payload = base.simulation_payload()

    implicit_payload = dict(payload)
    implicit_entities = []
    for row in payload["entities"]:
        cloned = dict(row)
        if cloned["entity_id"] == "attacker":
            cloned.pop("facing", None)
            cloned.pop("cooldown_until_tick", None)
            cloned.pop("wounds", None)
        implicit_entities.append(cloned)
    implicit_payload["entities"] = implicit_entities

    explicit_payload = dict(payload)
    explicit_entities = []
    for row in payload["entities"]:
        cloned = dict(row)
        if cloned["entity_id"] == "attacker":
            cloned["facing"] = 0
            cloned["cooldown_until_tick"] = 0
            cloned["wounds"] = []
        explicit_entities.append(cloned)
    explicit_payload["entities"] = explicit_entities

    implicit = Simulation.from_simulation_payload(implicit_payload)
    explicit = Simulation.from_simulation_payload(explicit_payload)
    assert implicit.state.entities["attacker"].facing == 0
    assert implicit.state.entities["attacker"].cooldown_until_tick == 0
    assert implicit.state.entities["attacker"].wounds == []
    assert simulation_hash(implicit) == simulation_hash(explicit)


def test_called_region_defaults_to_canonical_torso_for_omitted_and_null_target_region() -> None:
    sim = _build_sim()
    omitted = _attack_command(tick=0)
    explicit_null = _attack_command(tick=8)
    explicit_null.params["target_region"] = None

    sim.append_command(omitted)
    sim.append_command(explicit_null)
    sim.advance_ticks(12)

    resolved = [entry for entry in sim.state.combat_log if entry.get("applied") is True]
    first, second = resolved
    assert first["applied"] is True
    assert second["applied"] is True
    assert first["called_region"] == "torso"
    assert second["called_region"] == "torso"
    assert first["region_hit"] == "torso"
    assert second["region_hit"] == "torso"

    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.combat_log == sim.state.combat_log


def test_target_cell_coord_validation_is_topology_owned_not_generic_length_check() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": LOCAL_SPACE_ID, "coord": [0, 0, 0]}))

    sim.advance_ticks(3)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is False
    assert outcome["reason"] == "invalid_target_cell_coord_for_space"


def test_wound_region_falls_back_to_called_region_when_region_hit_missing() -> None:
    sim = _build_sim()

    affected = [
        {
            "entity_id": "target",
            "called_region": "arm",
            "region_hit": None,
            "wound_deltas": [],
            "applied": True,
            "reason": "resolved",
        }
    ]

    CombatExecutionModule._apply_wounds_from_affected(
        sim=sim,
        tick=4,
        attacker_id="attacker",
        called_region="torso",
        affected=affected,
    )

    assert sim.state.entities["target"].wounds == [
        {
            "region": "arm",
            "severity": 1,
            "tags": [],
            "inflicted_tick": 4,
            "source": "attacker",
        }
    ]


def test_wound_append_is_bounded_with_fifo_eviction() -> None:
    sim = _build_sim()
    target = sim.state.entities["target"]
    target.wounds = [
        {
            "region": f"old_{index}",
            "severity": 1,
            "tags": [],
            "inflicted_tick": index,
            "source": "setup",
        }
        for index in range(MAX_WOUNDS)
    ]

    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(3)

    assert len(target.wounds) == MAX_WOUNDS
    assert target.wounds[0]["region"] == "old_1"
    assert target.wounds[-1]["region"] == "torso"
    assert target.wounds[-1]["inflicted_tick"] == 2


def test_wound_application_save_load_preserves_hash_and_ledger() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(3)

    before_hash = simulation_hash(sim)
    before_wounds = list(sim.state.entities["target"].wounds)

    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.entities["target"].wounds == before_wounds
    assert simulation_hash(restored) == before_hash


def test_turn_intent_applies_facing_and_records_outcome_with_hash_stability() -> None:
    sim = _build_sim()
    sim.append_command(_turn_command(tick=0, facing=4, tags=["test"]))

    sim.advance_ticks(3)

    assert sim.state.entities["attacker"].facing == 4
    outcomes = _turn_outcomes(sim)
    assert len(outcomes) == 1
    params = outcomes[0]["params"]
    assert params["applied"] is True
    assert params["reason"] == "resolved"
    assert params["entity_id"] == "attacker"
    assert params["facing"] == 4

    before_hash = simulation_hash(sim)
    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.entities["attacker"].facing == 4
    assert _turn_outcomes(restored)[0]["params"] == params
    assert simulation_hash(restored) == before_hash


def test_turn_intent_invalid_facing_rejected_deterministically() -> None:
    sim = _build_sim()
    sim.append_command(_turn_command(tick=0, facing="bad"))

    sim.advance_ticks(3)

    assert sim.state.entities["attacker"].facing == 0
    outcomes = _turn_outcomes(sim)
    assert len(outcomes) == 1
    params = outcomes[0]["params"]
    assert params["applied"] is False
    assert params["reason"] == "invalid_facing"
    assert params["facing"] is None


def test_melee_arc_gate_allows_front_arc_and_rejects_behind() -> None:
    front = _build_sim()
    front.state.entities["attacker"].facing = 0
    front.append_command(_attack_command(tick=0, target_id="target"))
    front.advance_ticks(3)

    front_outcome = _first_applied_outcome(front)
    assert front_outcome["applied"] is True
    assert front_outcome["reason"] == "resolved"
    assert "affected" in front_outcome
    assert front.state.entities["target"].wounds

    behind = _build_sim()
    behind.state.entities["attacker"].facing = 3
    behind.append_command(_attack_command(tick=0, target_id="target"))
    behind.advance_ticks(3)

    behind_outcome = _first_outcome_with_reason(behind, "invalid_arc")
    assert behind_outcome["applied"] is False
    assert behind_outcome["reason"] == "invalid_arc"
    assert "affected" not in behind_outcome
    assert behind.state.entities["target"].wounds == []


def test_affected_ordering_helper_is_deterministic_and_non_mutating() -> None:
    entries = [
        {"entity_id": "z", "cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 2, "r": 0}}},
        {"entity_id": "a", "cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 0, "r": 0}}},
        {"entity_id": "m", "cell": {"space_id": LOCAL_SPACE_ID, "coord": {"q": 0, "r": -1}}},
    ]
    snapshot = [dict(row) for row in entries]

    first = CombatExecutionModule._sort_affected_entries(entries)
    second = CombatExecutionModule._sort_affected_entries(entries)

    assert [(row["cell"]["coord"]["q"], row["cell"]["coord"]["r"], row["entity_id"]) for row in first] == [
        (0, -1, "m"),
        (0, 0, "a"),
        (2, 0, "z"),
    ]
    assert first == second
    assert entries == snapshot


def test_attack_in_noncanonical_hex_topology_is_rejected_without_wildcard_topology_admission() -> None:
    sim = _build_sim()
    sim.state.world.spaces["hex_local"] = SpaceState(
        space_id="hex_local",
        topology_type="custom",
        role="local",
        hexes={
            HexCoord(0, 0): HexRecord(terrain_type="plains"),
            HexCoord(1, 0): HexRecord(terrain_type="plains"),
        },
    )
    sim.state.entities["attacker"].space_id = "hex_local"
    sim.state.entities["target"].space_id = "hex_local"

    sim.append_command(_attack_command(tick=0, target_id="target"))
    sim.advance_ticks(3)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is False
    assert outcome["reason"] == "invalid_target"
    assert "affected" not in outcome


def test_attack_intent_rejected_in_campaign_space_without_side_effects() -> None:
    sim = _build_sim()
    sim.state.entities["attacker"].space_id = "overworld"
    sim.state.entities["target"].space_id = "overworld"

    baseline_hash = simulation_hash(sim)
    sim.append_command(_attack_command(tick=0, target_id="target"))
    sim.advance_ticks(3)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is False
    assert outcome["reason"] == "tactical_not_allowed_in_campaign_space"
    assert "affected" not in outcome
    assert sim.state.entities["attacker"].cooldown_until_tick == 0
    assert sim.state.entities["target"].wounds == []

    replay = _build_sim()
    replay.state.entities["attacker"].space_id = "overworld"
    replay.state.entities["target"].space_id = "overworld"
    assert simulation_hash(replay) == baseline_hash
    replay.append_command(_attack_command(tick=0, target_id="target"))
    replay.advance_ticks(3)
    assert simulation_hash(replay) == simulation_hash(sim)


def test_turn_intent_rejected_in_campaign_space_without_mutation() -> None:
    sim = _build_sim()
    sim.state.entities["attacker"].space_id = "overworld"
    sim.state.entities["attacker"].facing = 2
    sim.append_command(_turn_command(tick=0, facing=4))

    sim.advance_ticks(3)

    assert sim.state.entities["attacker"].facing == 2
    outcomes = _turn_outcomes(sim)
    assert len(outcomes) == 1
    assert outcomes[0]["params"]["applied"] is False
    assert outcomes[0]["params"]["reason"] == "tactical_not_allowed_in_campaign_space"


def test_tactical_permission_depends_on_space_role_not_topology() -> None:
    local_hex = _build_sim()
    local_hex.append_command(_attack_command(tick=0, target_id="target"))
    local_hex.advance_ticks(3)
    assert _first_applied_outcome(local_hex)["applied"] is True

    local_square = _build_sim()
    local_square.state.world.spaces["local_square"] = SpaceState(
        space_id="local_square",
        topology_type="square_grid",
        role="local",
        topology_params={"width": 3, "height": 3, "origin": {"x": 0, "y": 0}},
    )
    local_square.state.entities["attacker"].space_id = "local_square"
    local_square.state.entities["target"].space_id = "local_square"
    local_square.state.entities["attacker"].position_x = 0.0
    local_square.state.entities["attacker"].position_y = 0.0
    local_square.state.entities["target"].position_x = 1.0
    local_square.state.entities["target"].position_y = 0.0
    local_square.append_command(_attack_command(tick=0, target_id="target"))
    local_square.advance_ticks(3)
    assert _first_applied_outcome(local_square)["applied"] is True

    campaign_square = _build_sim()
    campaign_square.state.world.spaces["campaign_square"] = SpaceState(
        space_id="campaign_square",
        topology_type="square_grid",
        role="campaign",
        topology_params={"width": 3, "height": 3, "origin": {"x": 0, "y": 0}},
    )
    campaign_square.state.entities["attacker"].space_id = "campaign_square"
    campaign_square.state.entities["target"].space_id = "campaign_square"
    campaign_square.state.entities["attacker"].position_x = 0.0
    campaign_square.state.entities["attacker"].position_y = 0.0
    campaign_square.state.entities["target"].position_x = 1.0
    campaign_square.state.entities["target"].position_y = 0.0
    campaign_square.append_command(_attack_command(tick=0, target_id="target"))
    campaign_square.advance_ticks(3)
    assert _first_outcome_with_reason(campaign_square, "tactical_not_allowed_in_campaign_space")["applied"] is False


def test_legacy_world_payload_defaults_space_roles_deterministically() -> None:
    legacy_world = {
        "topology_type": "hex_disk",
        "topology_params": {"radius": 1},
        "hexes": [
            {"coord": {"q": 0, "r": 0}, "record": {"terrain_type": "plains", "site_type": "none"}},
            {"coord": {"q": 1, "r": 0}, "record": {"terrain_type": "plains", "site_type": "none"}},
        ],
    }
    world = WorldState.from_dict(legacy_world)
    world.spaces["local_extra"] = SpaceState(
        space_id="local_extra",
        topology_type="square_grid",
        role="local",
        topology_params={"width": 2, "height": 2, "origin": {"x": 0, "y": 0}},
    )

    payload = world.to_dict()
    for space in payload["spaces"]:
        space.pop("role", None)

    restored = WorldState.from_dict(payload)
    assert restored.spaces["overworld"].role == "campaign"
    assert restored.spaces["local_extra"].role == "local"
    assert WorldState.from_dict(restored.to_dict()).to_dict() == restored.to_dict()


def test_combat_cadence_probe_records_acceptance_rejection_and_impact_source_paths() -> None:
    from hexcrawler.sim.combat import combat_cadence_probe

    sim = _build_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={"attacker_id": "attacker", "target_id": "target", "mode": "melee", "tags": ["viewer_lmb_directional_melee"]},
        )
    )
    sim.append_command(
        SimCommand(
            tick=1,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={"attacker_id": "attacker", "target_id": "target", "mode": "melee", "tags": ["viewer_lmb_directional_melee"]},
        )
    )
    sim.advance_ticks(2)

    probe = combat_cadence_probe(sim)
    rows = probe["rows"]
    assert any(row["source_path"] == "player_lmb" and row["accepted"] is True and row["windup_start_tick"] == 0 for row in rows)
    assert any(row["accepted"] is False and row["rejection_reason"] == "not_ready" and row["outcome_emitted"] is False for row in rows)

    sim.advance_ticks(1)
    rows = combat_cadence_probe(sim)["rows"]
    assert any(row["source_path"] == "scheduled_impact" and row["outcome_emitted"] is True and row["impact_tick"] == 2 for row in rows)


def test_every_applied_combat_outcome_has_preceding_accepted_cadence_evidence() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.append_command(_attack_command(tick=8))
    sim.advance_ticks(12)

    accepted = {row["action_uid"] for row in sim.state.combat_log if row.get("reason") == "windup_started"}
    applied = [row for row in sim.state.combat_log if row.get("applied") is True]
    assert applied
    assert all(row.get("action_uid") in accepted for row in applied)


def test_starter_hostile_durability_tuning_is_stat_gated_not_global() -> None:
    sim = _build_sim()
    sim.state.entities["target"].stats["starter_incoming_wound_severity_bonus"] = 1
    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(3)
    assert sim.state.entities["target"].wounds[-1]["severity"] == 2

    baseline = _build_sim()
    baseline.append_command(_attack_command(tick=0))
    baseline.advance_ticks(3)
    assert baseline.state.entities["target"].wounds[-1]["severity"] == 1
