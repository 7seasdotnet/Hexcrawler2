from __future__ import annotations

import copy
from pathlib import Path

import pytest

from hexcrawler.content.io import load_simulation_json, load_world_json, save_simulation_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import (
    RUMOR_SELECTION_DECISION_EVENT_TYPE,
    SELECT_RUMORS_INTENT,
    RumorQueryModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import MAX_RUMOR_SELECTION_DECISIONS, RumorRecord, WorldState


def _build_sim() -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.append_rumor(RumorRecord(rumor_id="r-a", kind="group_arrival", created_tick=10, consumed=False))
    world.append_rumor(RumorRecord(rumor_id="r-b", kind="claim_opportunity", created_tick=20, consumed=False))
    world.append_rumor(RumorRecord(rumor_id="r-c", kind="site_claim", created_tick=30, consumed=False))
    world.append_rumor(RumorRecord(rumor_id="r-d", kind="site_claim", created_tick=5, consumed=False))
    world.append_rumor(RumorRecord(rumor_id="r-z", kind="claim_opportunity", created_tick=25, consumed=True))
    sim = Simulation(world=world, seed=101)
    sim.register_rule_module(RumorQueryModule())
    return sim


def _last_outcome(sim: Simulation) -> dict[str, object]:
    outcomes = sim.get_command_outcomes()
    assert outcomes
    return outcomes[-1]


def _selection_ids(sim: Simulation) -> list[str]:
    return [str(row["rumor_id"]) for row in _last_outcome(sim)["selection"]]


def test_m18_replay_hash_stability_for_rumor_selection_decision_ledger() -> None:
    sim_a = _build_sim()
    sim_b = _build_sim()
    command = SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 3, "seed_tag": "alpha"})

    sim_a.append_command(command)
    sim_b.append_command(copy.deepcopy(command))
    sim_a.advance_ticks(1)
    sim_b.advance_ticks(1)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert sim_a.state.world.rumor_selection_decision_order == sim_b.state.world.rumor_selection_decision_order
    assert sim_a.state.world.rumor_selection_decisions == sim_b.state.world.rumor_selection_decisions


def test_m18_save_load_idempotence_reuses_decision_ledger(tmp_path: Path) -> None:
    sim = _build_sim()
    sim._execute_command(SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 3, "seed_tag": "persist"}), command_index=0)
    first_outcome = _last_outcome(sim)
    decision_key = str(first_outcome["decision_key"])
    assert first_outcome["decision_reused"] is False
    assert len(sim.state.world.rumor_selection_decision_order) == 1

    save_path = tmp_path / "rumor_selection_m18_save.json"
    save_simulation_json(save_path, sim)
    loaded = load_simulation_json(save_path)
    loaded.register_rule_module(RumorQueryModule())

    loaded._execute_command(SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 3, "seed_tag": "persist"}), command_index=0)

    second_outcome = _last_outcome(loaded)
    assert second_outcome["decision_reused"] is True
    assert second_outcome["decision_key"] == decision_key
    assert _selection_ids(loaded) == [str(row["rumor_id"]) for row in first_outcome["selection"]]
    assert len(loaded.state.world.rumor_selection_decision_order) == 1


def test_m18_duplicate_selection_key_does_not_reroll_or_emit_new_forensics() -> None:
    sim = _build_sim()
    sim._execute_command(SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 2, "seed_tag": "dedup"}), command_index=0)
    first_outcome = _last_outcome(sim)
    first_trace_count = len([row for row in sim.state.event_trace if row["event_type"] == RUMOR_SELECTION_DECISION_EVENT_TYPE])

    sim._execute_command(SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 2, "seed_tag": "dedup"}), command_index=1)
    second_outcome = _last_outcome(sim)
    second_trace_count = len([row for row in sim.state.event_trace if row["event_type"] == RUMOR_SELECTION_DECISION_EVENT_TYPE])

    assert first_outcome["decision_reused"] is False
    assert second_outcome["decision_reused"] is True
    assert second_outcome["decision_key"] == first_outcome["decision_key"]
    assert _selection_ids(sim) == [str(row["rumor_id"]) for row in first_outcome["selection"]]
    assert second_trace_count == first_trace_count




def test_m18_decision_key_changes_across_ticks_for_same_request() -> None:
    sim = _build_sim()

    sim._execute_command(SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 2, "seed_tag": "tick-scope"}), command_index=0)
    first = _last_outcome(sim)

    sim._execute_command(SimCommand(tick=1, command_type=SELECT_RUMORS_INTENT, params={"k": 2, "seed_tag": "tick-scope"}), command_index=0)
    second = _last_outcome(sim)

    assert first["decision_key"] != second["decision_key"]
    assert len(sim.state.world.rumor_selection_decision_order) == 2


def test_m18_cursor_is_view_only_and_does_not_create_new_decision() -> None:
    sim = _build_sim()

    sim._execute_command(SimCommand(tick=0, command_type=SELECT_RUMORS_INTENT, params={"k": 2, "seed_tag": "cursor-view"}), command_index=0)
    first = _last_outcome(sim)
    first_key = str(first["decision_key"])
    first_trace_count = len([row for row in sim.state.event_trace if row["event_type"] == RUMOR_SELECTION_DECISION_EVENT_TYPE])

    sim._execute_command(
        SimCommand(
            tick=0,
            command_type=SELECT_RUMORS_INTENT,
            params={"k": 2, "seed_tag": "cursor-view", "cursor": "1"},
        ),
        command_index=1,
    )
    paged = _last_outcome(sim)
    second_trace_count = len([row for row in sim.state.event_trace if row["event_type"] == RUMOR_SELECTION_DECISION_EVENT_TYPE])

    assert paged["decision_reused"] is True
    assert paged["decision_key"] == first_key
    assert len(sim.state.world.rumor_selection_decision_order) == 1
    assert second_trace_count == first_trace_count

def test_m18_fifo_eviction_for_selection_decisions_is_deterministic() -> None:
    sim = _build_sim()

    for index in range(MAX_RUMOR_SELECTION_DECISIONS + 3):
        sim.append_command(
            SimCommand(
                tick=index,
                command_type=SELECT_RUMORS_INTENT,
                params={"k": 1, "seed_tag": f"tag-{index}"},
            )
        )
        sim.advance_ticks(1)

    assert len(sim.state.world.rumor_selection_decision_order) == MAX_RUMOR_SELECTION_DECISIONS
    assert len(sim.state.world.rumor_selection_decisions) == MAX_RUMOR_SELECTION_DECISIONS
    assert sim.state.world.rumor_selection_decision_order[0].startswith("campaign|tag-3|3|")
    assert all(key in sim.state.world.rumor_selection_decisions for key in sim.state.world.rumor_selection_decision_order)


def test_m18_weight_scoring_prefers_kind_and_recency_deterministically() -> None:
    sim = _build_sim()
    module = RumorQueryModule()

    assert module._rumor_score(rumor={"kind": "site_claim", "created_tick": 50}, selection_tick=50) > module._rumor_score(
        rumor={"kind": "claim_opportunity", "created_tick": 50},
        selection_tick=50,
    )
    assert module._rumor_score(rumor={"kind": "claim_opportunity", "created_tick": 50}, selection_tick=50) > module._rumor_score(
        rumor={"kind": "group_arrival", "created_tick": 50},
        selection_tick=50,
    )
    assert module._rumor_score(rumor={"kind": "site_claim", "created_tick": 1}, selection_tick=5000) < module._rumor_score(
        rumor={"kind": "site_claim", "created_tick": 4999},
        selection_tick=5000,
    )

    sim.append_command(SimCommand(tick=sim.state.tick, command_type=SELECT_RUMORS_INTENT, params={"k": 2, "seed_tag": "weights"}))
    sim.advance_ticks(1)
    ids = _selection_ids(sim)
    assert "r-c" in ids


def test_m18_malformed_selection_ledger_rejected_on_load() -> None:
    sim = _build_sim()
    payload = sim.state.world.to_dict()
    payload["rumor_selection_decisions"] = {
        "campaign|default|0|bad": {
            "selected_rumor_ids": "not-a-list",
            "created_tick": 0,
            "scope": "campaign",
            "seed_tag": "default",
            "k": 1,
            "filters": {},
            "candidate_count": 1,
        }
    }
    payload["rumor_selection_decision_order"] = ["campaign|default|0|bad"]

    with pytest.raises(ValueError, match="selected_rumor_ids"):
        _ = WorldState.from_dict(payload)
