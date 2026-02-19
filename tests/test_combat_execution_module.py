from hexcrawler.content.io import load_world_json
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, CombatExecutionModule
from hexcrawler.sim.core import MAX_AFFECTED_PER_ACTION, MAX_COMBAT_LOG, EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def _build_sim() -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=17)
    sim.register_rule_module(CombatExecutionModule())
    sim.add_entity(EntityState.from_hex(entity_id="attacker", hex_coord=HexCoord(0, 0), speed_per_tick=0.0))
    sim.add_entity(EntityState.from_hex(entity_id="target", hex_coord=HexCoord(1, 0), speed_per_tick=0.0))
    return sim


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
    sim.append_command(_attack_command(tick=0, target_cell={"space_id": "overworld", "coord": {"q": 1, "r": 0}}))
    sim.append_command(_attack_command(tick=1, target_id=None, target_cell={"space_id": "overworld", "coord": {"q": 0, "r": 0}}))

    sim.advance_ticks(3)

    accepted = sim.state.combat_log[0]
    rejected = sim.state.combat_log[1]
    assert accepted["applied"] is True
    assert accepted["reason"] == "resolved"
    assert accepted["called_region"] == "torso"
    assert accepted["region_hit"] == "torso"
    assert accepted["wound_deltas"] == []

    assert rejected["applied"] is False
    assert rejected["reason"] == "out_of_range"


def test_applied_attack_populates_affected_target_fields() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": "overworld", "coord": {"q": 1, "r": 0}}))
    sim.advance_ticks(2)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is True
    assert outcome["reason"] == "resolved"
    assert outcome["called_region"] == "torso"
    assert outcome["region_hit"] == "torso"

    affected = outcome["affected"]
    assert len(affected) == 1
    assert affected[0]["entity_id"] == "target"
    assert affected[0]["cell"] == {"space_id": "overworld", "coord": {"q": 1, "r": 0}}
    assert affected[0]["called_region"] == "torso"
    assert affected[0]["region_hit"] == "torso"
    assert affected[0]["wound_deltas"] == []
    assert affected[0]["applied"] is True
    assert affected[0]["reason"] == "resolved"


def test_cell_only_targeting_without_occupant_is_rejected_and_omits_affected() -> None:
    sim = _build_sim()
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": "overworld", "coord": {"q": 1, "r": -1}}))
    sim.advance_ticks(2)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is False
    assert outcome["reason"] == "no_target_in_cell"
    assert "affected" not in outcome

    restored = Simulation.from_simulation_payload(sim.simulation_payload())
    assert restored.state.combat_log[0] == outcome


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
        _attack_command(tick=1, target_cell={"space_id": "overworld", "coord": {"q": 0, "r": 0}}),
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
    assert restored.state.entities["attacker"].wounds == []
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
                    "target_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
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
    sim.append_command(_attack_command(tick=0, target_id=None, target_cell={"space_id": "overworld", "coord": [0, 0, 0]}))

    sim.advance_ticks(2)

    outcome = sim.state.combat_log[0]
    assert outcome["applied"] is False
    assert outcome["reason"] == "invalid_target_cell_coord_for_space"
