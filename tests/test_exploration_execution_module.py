from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.exploration import EXPLORATION_OUTCOME_EVENT_TYPE, ExplorationExecutionModule
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


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
