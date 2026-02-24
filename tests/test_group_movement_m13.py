from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.groups import (
    GROUP_MOVE_ARRIVAL_EVENT_TYPE,
    GROUP_MOVE_ARRIVAL_IGNORED_EVENT_TYPE,
    GROUP_MOVE_ARRIVED_EVENT_TYPE,
    GROUP_MOVE_SCHEDULED_EVENT_TYPE,
    MAX_GROUP_TRAVEL_TICKS,
    GroupMovementModule,
)
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import LOCAL_SPACE_ROLE, GroupRecord, SpaceState


def _build_sim(seed: int = 1337) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.groups["caravan"] = GroupRecord(
        group_id="caravan",
        group_type="traders",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        strength=3,
        tags=["test"],
    )
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(GroupMovementModule())
    return sim


def _events(sim: Simulation, event_type: str) -> list[dict[str, object]]:
    return [entry for entry in sim.get_event_trace() if entry.get("event_type") == event_type]


def test_group_movement_replay_hash_identity_same_seed_same_inputs() -> None:
    sim_a = _build_sim(seed=4040)
    sim_b = _build_sim(seed=4040)

    for sim in (sim_a, sim_b):
        sim.append_command(
            SimCommand(
                tick=0,
                command_type="move_group_intent",
                params={
                    "group_id": "caravan",
                    "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                    "travel_ticks": 5,
                },
            )
        )

    sim_a.advance_ticks(8)
    sim_b.advance_ticks(8)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_group_movement_save_load_mid_travel_idempotent(tmp_path: Path) -> None:
    contiguous = _build_sim(seed=5050)
    contiguous.append_command(
        SimCommand(
            tick=0,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                "travel_ticks": 6,
            },
        )
    )
    contiguous.advance_ticks(10)

    split = _build_sim(seed=5050)
    split.append_command(
        SimCommand(
            tick=0,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                "travel_ticks": 6,
            },
        )
    )
    split.advance_ticks(4)
    save_path = tmp_path / "group_move_midtravel.json"
    save_game_json(save_path, split.state.world, split)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(GroupMovementModule())
    loaded.advance_ticks(6)

    assert simulation_hash(loaded) == simulation_hash(contiguous)
    assert loaded.state.world.groups["caravan"].to_dict() == contiguous.state.world.groups["caravan"].to_dict()
    assert loaded.state.world.groups["caravan"].moving is None


def test_group_movement_arrival_idempotence_and_stale_event_ignored_after_replan() -> None:
    sim = _build_sim(seed=6060)
    sim.append_command(
        SimCommand(
            tick=0,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": -1}},
                "travel_ticks": 3,
            },
        )
    )
    sim.append_command(
        SimCommand(
            tick=1,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                "travel_ticks": 5,
            },
        )
    )
    sim.schedule_event_at(
        tick=2,
        event_type=GROUP_MOVE_ARRIVAL_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "move_uid": "0:0",
            "from_cell": {"space_id": "overworld", "coord": {"q": 0, "r": 0}},
            "to_cell": {"space_id": "overworld", "coord": {"q": 1, "r": -1}},
            "arrive_tick": 3,
        },
    )
    sim.advance_ticks(7)

    arrived = _events(sim, GROUP_MOVE_ARRIVED_EVENT_TYPE)
    assert len(arrived) == 1
    move_uid = arrived[0]["params"]["move_uid"]
    assert move_uid == "1:0"
    assert sim.state.world.groups["caravan"].last_arrival_uid == move_uid
    assert sim.state.world.groups["caravan"].cell == {"q": 1, "r": 0}

    pre = sim.state.world.groups["caravan"].to_dict()
    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=GROUP_MOVE_ARRIVAL_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "move_uid": move_uid,
            "from_cell": {"space_id": "overworld", "coord": {"q": 0, "r": 0}},
            "to_cell": {"space_id": "overworld", "coord": {"q": 1, "r": -1}},
            "arrive_tick": 3,
        },
    )
    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=GROUP_MOVE_ARRIVAL_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "move_uid": "stale:uid",
            "from_cell": {"space_id": "overworld", "coord": {"q": 0, "r": 0}},
            "to_cell": {"space_id": "overworld", "coord": {"q": 3, "r": -3}},
            "arrive_tick": 3,
        },
    )
    sim.advance_ticks(2)

    assert sim.state.world.groups["caravan"].to_dict() == pre
    ignored = _events(sim, GROUP_MOVE_ARRIVAL_IGNORED_EVENT_TYPE)
    reasons = [entry["params"]["reason"] for entry in ignored]
    assert "no_plan" in reasons
    assert "stale_uid" in reasons


def test_group_movement_invalid_inputs_are_atomic() -> None:
    cases = [
        {
            "group_id": "missing",
            "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
            "travel_ticks": 2,
            "reason": "unknown_group",
        },
        {
            "group_id": "caravan",
            "dest_cell": {"space_id": "overworld"},
            "travel_ticks": 2,
            "reason": "invalid_target_cell",
        },
        {
            "group_id": "caravan",
            "dest_cell": {"space_id": "overworld", "coord": {"q": 999, "r": 999}},
            "travel_ticks": 2,
            "reason": "invalid_target_cell_coord_for_space",
        },
        {
            "group_id": "caravan",
            "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
            "travel_ticks": MAX_GROUP_TRAVEL_TICKS + 1,
            "reason": "invalid_travel_ticks",
        },
        {
            "group_id": "caravan",
            "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
            "travel_ticks": 2,
            "reason": "group_not_in_campaign_space",
            "group_space_id": "generated_local",
        },
    ]

    for case in cases:
        sim = _build_sim(seed=7070)
        if "group_space_id" in case:
            sim.state.world.spaces[case["group_space_id"]] = SpaceState(
                space_id=case["group_space_id"],
                topology_type="square_grid",
                role=LOCAL_SPACE_ROLE,
                topology_params={"width": 2, "height": 2, "origin": {"x": 0, "y": 0}},
            )
            sim.state.world.groups["caravan"].location["space_id"] = case["group_space_id"]
        before = sim.state.world.groups["caravan"].to_dict()
        before_world_hash = world_hash(sim.state.world)

        sim.append_command(
            SimCommand(
                tick=0,
                command_type="move_group_intent",
                params={
                    "group_id": case["group_id"],
                    "dest_cell": case["dest_cell"],
                    "travel_ticks": case["travel_ticks"],
                },
            )
        )
        sim.advance_ticks(2)

        after = sim.state.world.groups["caravan"].to_dict()
        assert after == before
        assert world_hash(sim.state.world) == before_world_hash
        ignored = _events(sim, GROUP_MOVE_ARRIVAL_IGNORED_EVENT_TYPE)
        assert ignored[-1]["params"]["reason"] == case["reason"]
        assert _events(sim, GROUP_MOVE_SCHEDULED_EVENT_TYPE) == []
