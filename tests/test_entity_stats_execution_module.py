from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.entity_stats import ENTITY_STAT_OUTCOME_EVENT_TYPE, EntityStatsExecutionModule
from hexcrawler.sim.world import HexCoord
from hexcrawler.sim.hash import simulation_hash


def _make_sim(seed: int = 55) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0)))
    sim.register_rule_module(EntityStatsExecutionModule())
    return sim


def _outcomes(sim: Simulation) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == ENTITY_STAT_OUTCOME_EVENT_TYPE]


def test_entity_stat_set_deterministic_mutation() -> None:
    sim = _make_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "set", "key": "str", "value": 10, "duration_ticks": 0},
        )
    )

    sim.advance_ticks(1)

    assert sim.get_entity_stats("scout") == {"str": 10}
    assert sim.get_entity_stat("scout", "str") == 10
    assert _outcomes(sim)[0]["params"]["outcome"] == "applied"


def test_entity_stat_save_load_mid_action_applies_once() -> None:
    sim = _make_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "set", "key": "dex", "value": 12, "duration_ticks": 3},
        )
    )

    sim.advance_ticks(1)
    loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    loaded.register_rule_module(EntityStatsExecutionModule())

    loaded.advance_ticks(4)

    assert loaded.get_entity_stats("scout") == {"dex": 12}
    loaded.schedule_event_at(
        tick=loaded.state.tick,
        event_type="entity_stat_execute",
        params={"action_uid": "0:0", "entity_id": "scout", "op": "set", "key": "dex", "value": 12},
    )
    loaded.advance_ticks(1)
    outcomes = _outcomes(loaded)
    assert len([o for o in outcomes if o["params"]["action_uid"] == "0:0" and o["params"]["outcome"] == "applied"]) == 1


def test_entity_stat_replay_and_hash_identity() -> None:
    sim_a = _make_sim(seed=91)
    sim_b = _make_sim(seed=91)
    command = SimCommand(
        tick=1,
        entity_id="scout",
        command_type="entity_stat_intent",
        params={"op": "set", "key": "tag:undead", "value": True, "duration_ticks": 2},
    )
    sim_a.append_command(command)
    sim_b.append_command(command)

    sim_a.advance_ticks(6)
    sim_b.advance_ticks(6)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_entity_stat_invalid_params_no_mutation() -> None:
    sim = _make_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "set", "key": "bad", "duration_ticks": 0},
        )
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "bogus", "key": "str", "value": 9, "duration_ticks": 0},
        )
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "set", "key": "str", "value": 9, "duration_ticks": -1},
        )
    )

    sim.advance_ticks(1)

    assert sim.get_entity_stats("scout") == {}
    outcomes = _outcomes(sim)
    assert len(outcomes) == 3
    assert all(entry["params"]["outcome"] == "invalid_params" for entry in outcomes)


def test_entity_stat_remove_operation() -> None:
    sim = _make_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "set", "key": "faction", "value": "wolves", "duration_ticks": 0},
        )
    )
    sim.append_command(
        SimCommand(
            tick=1,
            entity_id="scout",
            command_type="entity_stat_intent",
            params={"op": "remove", "key": "faction", "duration_ticks": 0},
        )
    )

    sim.advance_ticks(3)

    assert "faction" not in sim.get_entity_stats("scout")


def test_entity_stats_hash_equivalence_missing_vs_empty_payload() -> None:
    base_sim = _make_sim(seed=1337)
    payload = base_sim.simulation_payload()

    payload_missing = dict(payload)
    payload_missing["entities"] = [dict(row) for row in payload["entities"]]
    payload_missing["entities"][0].pop("stats", None)

    payload_empty = dict(payload)
    payload_empty["entities"] = [dict(row) for row in payload["entities"]]
    payload_empty["entities"][0]["stats"] = {}

    sim_missing = Simulation.from_simulation_payload(payload_missing)
    sim_empty = Simulation.from_simulation_payload(payload_empty)

    assert sim_missing.get_entity_stats("scout") == {}
    assert sim_empty.get_entity_stats("scout") == {}
    assert simulation_hash(sim_missing) == simulation_hash(sim_empty)


def test_entity_stats_empty_dict_persists_across_save_load() -> None:
    sim = _make_sim(seed=204)
    payload = sim.simulation_payload()

    assert payload["entities"][0]["stats"] == {}

    loaded = Simulation.from_simulation_payload(payload)
    loaded_payload = loaded.simulation_payload()

    assert loaded.get_entity_stats("scout") == {}
    assert loaded_payload["entities"][0]["stats"] == {}
