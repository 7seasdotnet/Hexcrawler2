from pathlib import Path

import pytest

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.exploration import EXPLORATION_OUTCOME_EVENT_TYPE, ExplorationExecutionModule, MAX_RECOVERY_ACTION_UIDS
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord, SiteRecord, SpaceState


def _build_sim(seed: int = 101) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))
    sim.register_rule_module(ExplorationExecutionModule())
    return sim


def _outcomes(sim: Simulation) -> list[dict[str, object]]:
    return [entry for entry in sim.get_event_trace() if entry.get("event_type") == EXPLORATION_OUTCOME_EVENT_TYPE]


def test_exploration_replay_hash_identity_same_seed_same_inputs() -> None:
    sim_a = _build_sim(seed=555)
    sim_b = _build_sim(seed=555)

    for sim in (sim_a, sim_b):
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="scout",
                command_type="explore_intent",
                params={"action": "search", "duration_ticks": 60},
            )
        )
        sim.append_command(
            SimCommand(
                tick=5,
                entity_id="scout",
                command_type="explore_intent",
                params={"action": "listen", "duration_ticks": 30},
            )
        )

    sim_a.advance_ticks(120)
    sim_b.advance_ticks(120)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_save_load_mid_exploration_does_not_double_complete(tmp_path: Path) -> None:
    sim = _build_sim(seed=202)
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="explore_intent",
            params={"action": "rest", "duration_ticks": 20},
        )
    )

    sim.advance_ticks(10)
    save_path = tmp_path / "exploration_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(ExplorationExecutionModule())
    loaded.advance_ticks(20)

    completed = [entry for entry in _outcomes(loaded) if entry.get("params", {}).get("outcome") == "completed"]
    assert len(completed) == 1


def test_exploration_outcome_emitted_once_per_intent_even_if_execute_event_requeued() -> None:
    sim = _build_sim(seed=303)
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="explore_intent",
            params={"action": "search", "duration_ticks": 5},
        )
    )
    sim.advance_ticks(6)

    completed = [entry for entry in _outcomes(sim) if entry.get("params", {}).get("outcome") == "completed"]
    assert len(completed) == 1
    params = completed[0]["params"]
    action_uid = params["action_uid"]
    sim.schedule_event_at(tick=sim.state.tick, event_type="explore_execute", params={"entity_id": "scout", "action": "search", "action_uid": action_uid})

    sim.advance_ticks(2)

    completed = [entry for entry in _outcomes(sim) if entry.get("params", {}).get("outcome") == "completed"]
    assert len(completed) == 1


def test_exploration_duration_ticks_respected() -> None:
    sim = _build_sim(seed=404)
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="explore_intent",
            params={"action": "listen", "duration_ticks": 7},
        )
    )

    sim.advance_ticks(10)

    outcomes = [entry for entry in _outcomes(sim) if entry.get("params", {}).get("outcome") == "completed"]
    assert len(outcomes) == 1
    assert outcomes[0]["tick"] == 7


def test_invalid_exploration_action_emits_deterministic_failure_outcome() -> None:
    sim = _build_sim(seed=505)
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="explore_intent",
            params={"action": "dig", "duration_ticks": 5},
        )
    )

    sim.advance_ticks(2)

    outcomes = _outcomes(sim)
    assert len(outcomes) == 1
    assert outcomes[0]["params"]["outcome"] == "invalid_action"


def test_safe_recovery_succeeds_at_town_site_and_recovers_one_light_wound() -> None:
    sim = _build_sim(seed=606)
    sim.state.world.sites["town_safe"] = sim.state.world.sites.get("town_safe") or SiteRecord(
        site_id="town_safe",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        tags=[],
    )
    sim.state.entities["scout"].wounds = [{"severity": 1, "region": "leg"}, {"severity": 2, "region": "torso"}]

    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="safe_recovery_intent",
            params={},
        )
    )

    sim.advance_ticks(70)

    recovery_events = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == "recovery_outcome"
    ]
    assert recovery_events[0]["params"]["outcome"] == "scheduled"
    assert recovery_events[-1]["params"]["reason"] == "light_wound_recovered"
    assert sim.state.entities["scout"].wounds == [{"severity": 2, "region": "torso"}]


def test_safe_recovery_rejected_away_from_safe_site() -> None:
    sim = _build_sim(seed=607)
    sim.state.entities["scout"].position_x = 1.0
    sim.state.entities["scout"].position_y = 0.0
    sim.state.entities["scout"].wounds = [{"severity": 1, "region": "arm"}]

    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="safe_recovery_intent",
            params={},
        )
    )
    sim.advance_ticks(2)

    recovery_events = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == "recovery_outcome"
    ]
    assert recovery_events[0]["params"]["reason"] == "safe_site_required"
    assert sim.state.entities["scout"].wounds == [{"severity": 1, "region": "arm"}]


def test_safe_recovery_rejected_when_no_recoverable_wound() -> None:
    sim = _build_sim(seed=608)
    sim.state.world.sites["town_safe"] = sim.state.world.sites.get("town_safe") or SiteRecord(
        site_id="town_safe",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        tags=[],
    )
    sim.state.entities["scout"].wounds = [{"severity": 2, "region": "torso"}]

    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="safe_recovery_intent", params={}))
    sim.advance_ticks(2)

    recovery_events = [entry for entry in sim.get_event_trace() if entry.get("event_type") == "recovery_outcome"]
    assert recovery_events[0]["params"]["reason"] == "no_recoverable_wound"


def test_safe_recovery_save_load_and_hash_stability_with_pending_recovery(tmp_path: Path) -> None:
    sim_a = _build_sim(seed=609)
    sim_b = _build_sim(seed=609)
    for sim in (sim_a, sim_b):
        sim.state.world.sites["town_safe"] = sim.state.world.sites.get("town_safe") or SiteRecord(
            site_id="town_safe",
            site_type="town",
            location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
            tags=[],
        )
        sim.state.entities["scout"].wounds = [{"severity": 1, "region": "leg"}, {"severity": 2, "region": "torso"}]
        sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="safe_recovery_intent", params={}))

    sim_a.advance_ticks(20)
    save_path = tmp_path / "recovery_pending.json"
    save_game_json(save_path, sim_a.state.world, sim_a)
    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(ExplorationExecutionModule())

    sim_b.advance_ticks(80)
    loaded.advance_ticks(60)

    assert simulation_hash(loaded) == simulation_hash(sim_b)


def test_safe_recovery_role_gating_rejects_local_space() -> None:
    sim = _build_sim(seed=610)
    sim.state.world.spaces["local:test"] = SpaceState(
        space_id="local:test",
        topology_type="square_grid",
        role="local",
        topology_params={"width": 4, "height": 4, "origin": {"x": 0, "y": 0}},
    )
    sim.state.entities["scout"].space_id = "local:test"
    sim.state.entities["scout"].position_x = 0.0
    sim.state.entities["scout"].position_y = 0.0
    sim.state.entities["scout"].wounds = [{"severity": 1, "region": "arm"}]

    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="safe_recovery_intent", params={}))
    sim.advance_ticks(2)

    recovery_events = [entry for entry in sim.get_event_trace() if entry.get("event_type") == "recovery_outcome"]
    assert recovery_events[0]["params"]["reason"] == "campaign_space_required"


def test_safe_recovery_execute_requeue_is_idempotent_for_same_action_uid() -> None:
    sim = _build_sim(seed=611)
    sim.state.world.sites["town_safe"] = SiteRecord(
        site_id="town_safe",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        tags=[],
    )
    sim.state.entities["scout"].wounds = [{"severity": 1, "region": "leg"}, {"severity": 2, "region": "torso"}]

    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="safe_recovery_intent", params={}))
    sim.advance_ticks(70)

    first_completion = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == "recovery_outcome" and entry.get("params", {}).get("outcome") == "completed"
    ]
    assert len(first_completion) == 1
    action_uid = first_completion[0]["params"]["action_uid"]

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="recovery_execute",
        params={"entity_id": "scout", "action_uid": action_uid, "site_id": "town_safe"},
    )
    sim.advance_ticks(2)

    completions = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == "recovery_outcome" and entry.get("params", {}).get("outcome") == "completed"
    ]
    assert len(completions) == 1
    assert sim.state.entities["scout"].wounds == [{"severity": 2, "region": "torso"}]


def test_safe_recovery_uid_ledgers_are_bounded_with_deterministic_eviction() -> None:
    sim = _build_sim(seed=612)
    sim.state.world.sites["town_safe"] = SiteRecord(
        site_id="town_safe",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        tags=[],
    )
    sim.state.entities["scout"].wounds = [{"severity": 1, "region": "leg"}]

    scheduled_seed = [f"scheduled:{index}" for index in range(MAX_RECOVERY_ACTION_UIDS + 5)]
    completed_seed = [f"completed:{index}" for index in range(MAX_RECOVERY_ACTION_UIDS + 5)]
    sim.set_rules_state(
        "exploration",
        {
            "recovery_scheduled_action_uids": scheduled_seed,
            "recovery_completed_action_uids": completed_seed,
        },
    )

    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="safe_recovery_intent", params={}))
    sim.advance_ticks(1)

    state = sim.get_rules_state("exploration")
    scheduled = state["recovery_scheduled_action_uids"]
    completed = state["recovery_completed_action_uids"]

    assert len(scheduled) == MAX_RECOVERY_ACTION_UIDS
    assert len(completed) == MAX_RECOVERY_ACTION_UIDS
    assert scheduled[0] == "scheduled:6"
    assert completed[0] == "completed:5"
    assert any(uid.startswith("recovery:0:") for uid in scheduled)


def test_safe_recovery_uid_ledger_invalid_type_raises() -> None:
    sim = _build_sim(seed=613)
    sim.state.world.sites["town_safe"] = SiteRecord(
        site_id="town_safe",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        tags=[],
    )
    sim.state.entities["scout"].wounds = [{"severity": 1, "region": "leg"}]
    sim.set_rules_state("exploration", {"recovery_scheduled_action_uids": {"bad": "type"}})

    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="safe_recovery_intent", params={}))

    with pytest.raises(ValueError, match="recovery action uid state must be a list"):
        sim.advance_ticks(1)
