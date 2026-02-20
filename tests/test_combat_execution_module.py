from hexcrawler.content.io import load_world_json
from hexcrawler.sim.combat import (
    ATTACK_INTENT_COMMAND_TYPE,
    TURN_INTENT_COMMAND_TYPE,
    TURN_OUTCOME_EVENT_TYPE,
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

    sim.advance_ticks(3)

    accepted = sim.state.combat_log[0]
    rejected = sim.state.combat_log[1]
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
            "inflicted_tick": 0,
            "source": "attacker",
        }
    ]

    assert rejected["applied"] is False
    assert rejected["reason"] == "out_of_range"
    assert "affected" not in rejected


def test_applied_attack_populates_affected_target_fields() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": LOCAL_SPACE_ID, "coord": {"q": 1, "r": 0}}))
    sim.advance_ticks(2)

    outcome = sim.state.combat_log[0]
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
                "inflicted_tick": 0,
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
    sim.advance_ticks(2)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is False
    assert outcome["reason"] == "no_target_in_cell"
    assert "affected" not in outcome
    assert sim.state.entities["target"].wounds == []

    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.combat_log[0] == outcome
    assert "affected" not in restored.state.combat_log[0]


def test_cooldown_gate_blocks_repeat_attack_in_same_tick() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.append_command(_attack_command(tick=0))
    sim.append_command(_attack_command(tick=1))

    sim.advance_ticks(3)

    reasons = [entry["reason"] for entry in sim.state.combat_log]
    assert reasons == ["resolved", "cooldown_blocked", "resolved"]


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
    for tick in range(MAX_COMBAT_LOG + 3):
        sim.append_command(_attack_command(tick=tick))
    sim.advance_ticks(MAX_COMBAT_LOG + 4)

    assert len(sim.state.combat_log) == MAX_COMBAT_LOG
    assert sim.state.combat_log[0]["tick"] == 3
    assert sim.state.combat_log[-1]["tick"] == MAX_COMBAT_LOG + 2


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
    explicit_null = _attack_command(tick=1)
    explicit_null.params["target_region"] = None

    sim.append_command(omitted)
    sim.append_command(explicit_null)
    sim.advance_ticks(3)

    first, second = sim.state.combat_log
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

    sim.advance_ticks(2)

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
    sim.advance_ticks(2)

    assert len(target.wounds) == MAX_WOUNDS
    assert target.wounds[0]["region"] == "old_1"
    assert target.wounds[-1]["region"] == "torso"
    assert target.wounds[-1]["inflicted_tick"] == 0


def test_wound_application_save_load_preserves_hash_and_ledger() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0))
    sim.advance_ticks(2)

    before_hash = simulation_hash(sim)
    before_wounds = list(sim.state.entities["target"].wounds)

    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.entities["target"].wounds == before_wounds
    assert simulation_hash(restored) == before_hash


def test_turn_intent_applies_facing_and_records_outcome_with_hash_stability() -> None:
    sim = _build_sim()
    sim.append_command(_turn_command(tick=0, facing=4, tags=["test"]))

    sim.advance_ticks(2)

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

    sim.advance_ticks(2)

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
    front.advance_ticks(2)

    front_outcome = front.state.combat_log[0]
    assert front_outcome["applied"] is True
    assert front_outcome["reason"] == "resolved"
    assert "affected" in front_outcome
    assert front.state.entities["target"].wounds

    behind = _build_sim()
    behind.state.entities["attacker"].facing = 3
    behind.append_command(_attack_command(tick=0, target_id="target"))
    behind.advance_ticks(2)

    behind_outcome = behind.state.combat_log[0]
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
    sim.advance_ticks(2)

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
    sim.advance_ticks(2)

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
    replay.advance_ticks(2)
    assert simulation_hash(replay) == simulation_hash(sim)


def test_turn_intent_rejected_in_campaign_space_without_mutation() -> None:
    sim = _build_sim()
    sim.state.entities["attacker"].space_id = "overworld"
    sim.state.entities["attacker"].facing = 2
    sim.append_command(_turn_command(tick=0, facing=4))

    sim.advance_ticks(2)

    assert sim.state.entities["attacker"].facing == 2
    outcomes = _turn_outcomes(sim)
    assert len(outcomes) == 1
    assert outcomes[0]["params"]["applied"] is False
    assert outcomes[0]["params"]["reason"] == "tactical_not_allowed_in_campaign_space"


def test_tactical_permission_depends_on_space_role_not_topology() -> None:
    local_hex = _build_sim()
    local_hex.append_command(_attack_command(tick=0, target_id="target"))
    local_hex.advance_ticks(2)
    assert local_hex.state.combat_log[0]["applied"] is True

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
    local_square.advance_ticks(2)
    assert local_square.state.combat_log[0]["applied"] is True

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
    campaign_square.advance_ticks(2)
    assert campaign_square.state.combat_log[0]["applied"] is False
    assert campaign_square.state.combat_log[0]["reason"] == "tactical_not_allowed_in_campaign_space"


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
