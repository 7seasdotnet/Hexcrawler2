from __future__ import annotations

import copy
from pathlib import Path

import pytest

from hexcrawler.content.io import load_simulation_json, load_world_json, save_simulation_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import MAX_RUMOR_DECAY_PROCESSED_PER_TICK, RumorDecayModule, RumorQueryModule, SELECT_RUMORS_INTENT
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import RumorRecord, WorldState


def _build_sim() -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=55)
    sim.register_rule_module(RumorDecayModule())
    sim.register_rule_module(RumorQueryModule())
    return sim


def test_m20_expiration_removal_is_deterministic() -> None:
    sim_a = _build_sim()
    sim_b = _build_sim()
    records = [
        RumorRecord(rumor_id="r-never", kind="group_arrival", created_tick=0, expires_tick=None),
        RumorRecord(rumor_id="r-1", kind="claim_opportunity", created_tick=0, expires_tick=1),
        RumorRecord(rumor_id="r-2", kind="site_claim", created_tick=0, expires_tick=2),
    ]
    for sim in (sim_a, sim_b):
        for row in records:
            sim.state.world.append_rumor(copy.deepcopy(row))

    sim_a.advance_ticks(3)
    sim_b.advance_ticks(3)

    assert sim_a.state.world.rumors == sim_b.state.world.rumors
    assert [row["rumor_id"] for row in sim_a.state.world.rumors] == ["r-never"]
    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_m20_save_load_idempotence_mid_decay_cursor(tmp_path: Path) -> None:
    baseline = _build_sim()
    resumed = _build_sim()
    total = MAX_RUMOR_DECAY_PROCESSED_PER_TICK + 9
    for index in range(total):
        record = RumorRecord(
            rumor_id=f"r-{index}",
            kind="group_arrival",
            created_tick=0,
            expires_tick=0,
        )
        baseline.state.world.append_rumor(copy.deepcopy(record))
        resumed.state.world.append_rumor(copy.deepcopy(record))

    baseline.advance_ticks(3)

    resumed.advance_ticks(1)
    save_path = tmp_path / "m20_mid_decay.json"
    save_simulation_json(save_path, resumed)
    loaded = load_simulation_json(save_path)
    loaded.register_rule_module(RumorDecayModule())
    loaded.register_rule_module(RumorQueryModule())
    loaded.advance_ticks(2)

    assert loaded.state.world.rumors == baseline.state.world.rumors
    assert simulation_hash(loaded) == simulation_hash(baseline)


def test_m20_bounded_processing_defers_deterministically() -> None:
    sim = _build_sim()
    total = MAX_RUMOR_DECAY_PROCESSED_PER_TICK + 5
    for index in range(total):
        sim.state.world.append_rumor(
            RumorRecord(rumor_id=f"r-{index}", kind="site_claim", created_tick=0, expires_tick=0)
        )

    sim.advance_ticks(1)
    assert len(sim.state.world.rumors) == 5
    assert sim.state.world.rumor_decay_cursor == 0

    sim.advance_ticks(1)
    assert sim.state.world.rumors == []
    assert sim.state.world.rumor_decay_cursor == 0


def test_m20_schema_rejects_invalid_expires_tick_type() -> None:
    payload = {
        "topology_type": "custom",
        "topology_params": {},
        "hexes": [],
        "rumors": [
            {
                "rumor_id": "bad",
                "kind": "group_arrival",
                "created_tick": 0,
                "consumed": False,
                "expires_tick": "10",
            }
        ],
    }
    with pytest.raises(ValueError, match="expires_tick"):
        _ = WorldState.from_dict(payload)

    payload["rumors"][0]["expires_tick"] = True
    with pytest.raises(ValueError, match="expires_tick"):
        _ = WorldState.from_dict(payload)


def test_m20_selection_outcome_drops_expired_rumor_ids_without_mutating_decision() -> None:
    sim = _build_sim()
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-live", kind="site_claim", created_tick=0, expires_tick=None))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-exp", kind="site_claim", created_tick=0, expires_tick=1))

    command = SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 10, "seed_tag": "m20-expiry"})
    sim._execute_command(command, command_index=0)
    outcome_before = sim.get_command_outcomes()[-1]
    decision_key = str(outcome_before["decision_key"])
    selected_ids = list(sim.state.world.rumor_selection_decisions[decision_key]["selected_rumor_ids"])
    assert "r-exp" in selected_ids

    sim.advance_ticks(2)

    sim._execute_command(command, command_index=1)
    outcome_after = sim.get_command_outcomes()[-1]
    returned_ids = [row["rumor_id"] for row in outcome_after["selection"]]

    assert outcome_after["decision_reused"] is True
    assert "r-exp" not in returned_ids
    assert sim.state.world.rumor_selection_decisions[decision_key]["selected_rumor_ids"] == selected_ids
