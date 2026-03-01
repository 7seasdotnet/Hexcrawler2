from __future__ import annotations

import copy

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import LIST_RUMORS_INTENT, RumorQueryModule
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import RumorRecord


def _build_sim() -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.append_rumor(RumorRecord(rumor_id="r-03", kind="group_arrival", created_tick=5, group_id="alpha", consumed=False))
    world.append_rumor(
        RumorRecord(
            rumor_id="r-01",
            kind="claim_opportunity",
            created_tick=7,
            site_key='{"origin_space_id":"overworld","origin_coord":{"q":1,"r":0},"template_id":"site:a"}',
            group_id="alpha",
            consumed=False,
        )
    )
    world.append_rumor(
        RumorRecord(
            rumor_id="r-02",
            kind="claim_opportunity",
            created_tick=7,
            site_key='{"origin_space_id":"overworld","origin_coord":{"q":2,"r":0},"template_id":"site:b"}',
            group_id="beta",
            consumed=True,
        )
    )
    world.append_rumor(RumorRecord(rumor_id="r-00", kind="site_claim", created_tick=9, group_id="beta", consumed=True))

    sim = Simulation(world=world, seed=11)
    sim.register_rule_module(RumorQueryModule())
    return sim


def _last_outcome(sim: Simulation) -> dict[str, object]:
    outcomes = sim.get_command_outcomes()
    assert outcomes
    return outcomes[-1]


def test_m16_list_rumors_deterministic_ordering() -> None:
    sim = _build_sim()
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"limit": 10}))

    sim.advance_ticks(1)

    outcome = _last_outcome(sim)
    ids = [row["rumor_id"] for row in outcome["rumors"]]
    assert ids == ["r-00", "r-01", "r-02", "r-03"]


def test_m16_list_rumors_filtering_by_fields() -> None:
    sim = _build_sim()
    site_key = '{"origin_space_id":"overworld","origin_coord":{"q":1,"r":0},"template_id":"site:a"}'
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"kind": "claim_opportunity", "limit": 10}))
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"site_key": site_key, "limit": 10}))
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"group_id": "beta", "limit": 10}))
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"consumed": False, "limit": 10}))

    sim.advance_ticks(1)

    outcomes = sim.get_command_outcomes()[-4:]
    assert [row["kind"] for row in outcomes[0]["rumors"]] == ["claim_opportunity", "claim_opportunity"]
    assert [row["rumor_id"] for row in outcomes[1]["rumors"]] == ["r-01"]
    assert [row["rumor_id"] for row in outcomes[2]["rumors"]] == ["r-00", "r-02"]
    assert [row["rumor_id"] for row in outcomes[3]["rumors"]] == ["r-01", "r-03"]


def test_m16_list_rumors_pagination_is_stable() -> None:
    sim = _build_sim()
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"limit": 2}))
    sim.advance_ticks(1)

    first_page = _last_outcome(sim)
    assert [row["rumor_id"] for row in first_page["rumors"]] == ["r-00", "r-01"]
    next_cursor = first_page["next_cursor"]
    assert isinstance(next_cursor, str)

    sim.append_command(SimCommand(tick=1, command_type=LIST_RUMORS_INTENT, params={"limit": 2, "cursor": next_cursor}))
    sim.advance_ticks(1)

    second_page = _last_outcome(sim)
    assert [row["rumor_id"] for row in second_page["rumors"]] == ["r-02", "r-03"]

    sim.append_command(SimCommand(tick=2, command_type=LIST_RUMORS_INTENT, params={"limit": 2, "cursor": "8:not-present"}))
    sim.advance_ticks(1)
    tolerant = _last_outcome(sim)
    assert tolerant["outcome"] == "ok"
    assert [row["rumor_id"] for row in tolerant["rumors"]] == ["r-01", "r-02"]


def test_m16_list_rumors_read_only_keeps_hash_and_world_stable() -> None:
    sim = _build_sim()
    command = SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"kind": "site_claim", "limit": 3})

    hash_before = simulation_hash(sim)
    rumors_before = copy.deepcopy(sim.state.world.rumors)
    rules_before = copy.deepcopy(sim.state.rules_state)

    sim._execute_command(command, command_index=0)

    assert simulation_hash(sim) == hash_before
    assert sim.state.world.rumors == rumors_before
    assert sim.state.rules_state == rules_before


def test_m16_list_rumors_cursor_validation_rejects_malformed_cursor() -> None:
    sim = _build_sim()
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"cursor": "abc", "kind": "group_arrival"}))

    sim.advance_ticks(1)

    outcome = _last_outcome(sim)
    assert outcome["outcome"] == "invalid_params"
    assert outcome["diagnostic"] == "invalid_cursor"
    assert outcome["rumors"] == []


def test_m16_list_rumors_outcome_buffer_clears_each_tick() -> None:
    sim = _build_sim()
    sim.append_command(SimCommand(tick=0, command_type=LIST_RUMORS_INTENT, params={"limit": 1}))

    sim.advance_ticks(1)
    assert len(sim.get_command_outcomes()) == 1

    sim.advance_ticks(1)
    assert sim.get_command_outcomes() == []
