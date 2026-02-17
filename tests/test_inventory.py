from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import INVENTORY_OUTCOME_EVENT_TYPE, EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord

import pytest


def _make_sim(seed: int = 11) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0)))
    return sim


def _latest_outcome(sim: Simulation) -> dict[str, object]:
    outcomes = [entry for entry in sim.get_event_trace() if entry.get("event_type") == INVENTORY_OUTCOME_EVENT_TYPE]
    assert outcomes
    return outcomes[-1]["params"]


def test_save_load_round_trip_preserves_containers_exactly(tmp_path: Path) -> None:
    sim = _make_sim()
    inv_id = sim.state.entities["runner"].inventory_container_id
    assert inv_id is not None
    sim.state.world.containers[inv_id].items["torch"] = 4

    path = tmp_path / "inventory_save.json"
    save_game_json(path, sim.state.world, sim)
    world_loaded, sim_loaded = load_game_json(path)

    assert world_loaded.to_dict()["containers"] == sim.state.world.to_dict()["containers"]
    assert sim_loaded.state.world.to_dict()["containers"] == sim.state.world.to_dict()["containers"]


def test_inventory_determinism_same_seed_same_commands_same_hash() -> None:
    def run_once() -> str:
        sim = _make_sim(seed=91)
        inv_id = sim.state.entities["runner"].inventory_container_id
        assert inv_id is not None
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id="runner",
                command_type="inventory_intent",
                params={
                    "src_container_id": None,
                    "dst_container_id": inv_id,
                    "item_id": "rations",
                    "quantity": 3,
                    "reason": "spawn",
                },
            )
        )
        sim.append_command(
            SimCommand(
                tick=1,
                entity_id="runner",
                command_type="inventory_intent",
                params={
                    "src_container_id": inv_id,
                    "dst_container_id": None,
                    "item_id": "rations",
                    "quantity": 1,
                    "reason": "consume",
                },
            )
        )
        sim.advance_ticks(3)
        return simulation_hash(sim)

    assert run_once() == run_once()


def test_idempotence_same_action_uid_does_not_double_apply() -> None:
    sim = _make_sim()
    inv_id = sim.state.entities["runner"].inventory_container_id
    assert inv_id is not None
    sim.state.world.containers[inv_id].items["torch"] = 5

    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": inv_id,
                "dst_container_id": None,
                "item_id": "torch",
                "quantity": 2,
                "reason": "consume",
            },
        )
    )

    sim.advance_ticks(1)
    assert sim.state.world.containers[inv_id].items["torch"] == 3

    sim.state.tick = 0
    sim._apply_commands_for_tick(0)
    assert sim.state.world.containers[inv_id].items["torch"] == 3
    assert _latest_outcome(sim)["outcome"] == "already_applied"


def test_insufficient_quantity_never_goes_negative() -> None:
    sim = _make_sim()
    inv_id = sim.state.entities["runner"].inventory_container_id
    assert inv_id is not None
    sim.state.world.containers[inv_id].items["torch"] = 1

    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": inv_id,
                "dst_container_id": None,
                "item_id": "torch",
                "quantity": 2,
                "reason": "consume",
            },
        )
    )

    sim.advance_ticks(1)
    assert sim.state.world.containers[inv_id].items["torch"] == 1
    assert _latest_outcome(sim)["outcome"] == "insufficient_quantity"


def test_transfer_conserves_quantity_between_containers() -> None:
    sim = _make_sim()
    sim.add_entity(EntityState.from_hex(entity_id="mule", hex_coord=HexCoord(0, 1)))

    src_id = sim.state.entities["runner"].inventory_container_id
    dst_id = sim.state.entities["mule"].inventory_container_id
    assert src_id is not None and dst_id is not None

    sim.state.world.containers[src_id].items["scrap_iron"] = 10
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": src_id,
                "dst_container_id": dst_id,
                "item_id": "scrap_iron",
                "quantity": 4,
                "reason": "transfer",
            },
        )
    )

    sim.advance_ticks(1)
    assert sim.state.world.containers[src_id].items["scrap_iron"] == 6
    assert sim.state.world.containers[dst_id].items["scrap_iron"] == 4


def test_drop_then_pickup_uses_deterministic_world_container() -> None:
    sim = _make_sim()
    inv_id = sim.state.entities["runner"].inventory_container_id
    assert inv_id is not None
    sim.state.world.containers[inv_id].items["rations"] = 5

    drop_container_id = "world_drop:overworld:0:0"
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": inv_id,
                "dst_container_id": None,
                "item_id": "rations",
                "quantity": 2,
                "reason": "drop",
            },
        )
    )
    sim.append_command(
        SimCommand(
            tick=1,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": drop_container_id,
                "dst_container_id": inv_id,
                "item_id": "rations",
                "quantity": 2,
                "reason": "pickup",
            },
        )
    )

    sim.advance_ticks(2)
    assert drop_container_id in sim.state.world.containers
    assert sim.state.world.containers[drop_container_id].items == {}
    assert sim.state.world.containers[inv_id].items["rations"] == 5


def test_unknown_item_and_unknown_container_are_rejected_deterministically() -> None:
    sim = _make_sim()
    inv_id = sim.state.entities["runner"].inventory_container_id
    assert inv_id is not None

    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": None,
                "dst_container_id": inv_id,
                "item_id": "does_not_exist",
                "quantity": 1,
                "reason": "spawn",
            },
        )
    )
    sim.append_command(
        SimCommand(
            tick=1,
            entity_id="runner",
            command_type="inventory_intent",
            params={
                "src_container_id": "missing_container",
                "dst_container_id": inv_id,
                "item_id": "torch",
                "quantity": 1,
                "reason": "transfer",
            },
        )
    )

    sim.advance_ticks(2)
    outcomes = [entry["params"]["outcome"] for entry in sim.get_event_trace() if entry.get("event_type") == INVENTORY_OUTCOME_EVENT_TYPE]
    assert outcomes == ["unknown_item", "unknown_container"]


def test_load_fails_when_entity_references_missing_container() -> None:
    sim = _make_sim()
    payload = sim.simulation_payload()
    payload["entities"][0]["inventory_container_id"] = "missing:container"

    with pytest.raises(ValueError, match="references missing inventory container"):
        Simulation.from_simulation_payload(payload)
