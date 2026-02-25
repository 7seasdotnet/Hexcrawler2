from __future__ import annotations

from pathlib import Path

import pytest

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.encounters import (
    CLAIM_OPPORTUNITY_CREATED_EVENT_TYPE,
    CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
    CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
    LocalEncounterInstanceModule,
    RumorPipelineModule,
    SiteEcologyModule,
)
from hexcrawler.sim.groups import GroupMovementModule
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import MAX_RUMORS, GroupRecord, SiteRecord, WorldState


def _build_sim(seed: int = 1337) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.groups["caravan"] = GroupRecord(
        group_id="caravan",
        group_type="traders",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        strength=3,
    )
    world.sites["camp_01"] = SiteRecord(
        site_id="camp_01",
        site_type="dungeon",
        location={"space_id": "overworld", "coord": {"q": 1, "r": 0}},
    )

    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(SiteEcologyModule())
    sim.register_rule_module(GroupMovementModule())
    sim.register_rule_module(RumorPipelineModule())
    return sim


def _move_to_site(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=0,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                "travel_ticks": 2,
            },
        )
    )
    sim.advance_ticks(5)


def test_m15_replay_hash_stability_for_arrival_rumor_generation() -> None:
    sim_a = _build_sim(seed=808)
    sim_b = _build_sim(seed=808)

    _move_to_site(sim_a)
    _move_to_site(sim_b)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert any(row["kind"] == "group_arrival" for row in sim_a.state.world.rumors)


def test_m15_save_load_no_duplicate_rumor_entries(tmp_path: Path) -> None:
    contiguous = _build_sim(seed=909)
    _move_to_site(contiguous)
    contiguous.advance_ticks(3)

    split = _build_sim(seed=909)
    _move_to_site(split)
    save_path = tmp_path / "rumor_m15_save.json"
    save_game_json(save_path, split.state.world, split)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())
    loaded.register_rule_module(GroupMovementModule())
    loaded.register_rule_module(RumorPipelineModule())
    loaded.advance_ticks(3)

    rumor_ids = [record["rumor_id"] for record in loaded.state.world.rumors]
    assert len(rumor_ids) == len(set(rumor_ids))
    assert simulation_hash(loaded) == simulation_hash(contiguous)


def test_m15_deduplication_keeps_single_claim_opportunity_rumor() -> None:
    sim = _build_sim(seed=111)
    _move_to_site(sim)

    # duplicate seam event must not emit duplicate rumor
    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=CLAIM_OPPORTUNITY_CREATED_EVENT_TYPE,
        params={
            "tick": sim.state.tick,
            "opportunity_id": "dup",
            "group_id": "caravan",
            "site_key": sim.state.world.claim_opportunities[0]["site_key"],
        },
    )
    sim.advance_ticks(2)

    claim_rumors = [r for r in sim.state.world.rumors if r.get("kind") == "claim_opportunity"]
    assert len(claim_rumors) == 1


def test_m15_fifo_eviction_removes_oldest_first() -> None:
    sim = _build_sim(seed=222)

    for index in range(MAX_RUMORS + 8):
        sim.schedule_event_at(
            tick=0,
            event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
            params={
                "group_id": "caravan",
                "site_key": {
                    "origin_space_id": "overworld",
                    "origin_coord": {"q": 1, "r": 0},
                    "template_id": f"site:{index:04d}",
                },
            },
        )
    sim.advance_ticks(1)

    assert len(sim.state.world.rumors) == MAX_RUMORS
    ids = [row["site_key"] for row in sim.state.world.rumors]
    assert "template_id\":\"site:0000" not in ids[0]
    assert "template_id\":\"site:0008" in ids[0]


def test_m15_malformed_load_rejects_invalid_rumor_entry() -> None:
    world = load_world_json("content/examples/basic_map.json")
    payload = world.to_dict()
    payload["rumors"] = [
        {
            "rumor_id": "bad",
            "kind": "group_arrival",
            "created_tick": 1,
            "consumed": "nope",
        }
    ]

    with pytest.raises(ValueError, match="consumed must be a boolean"):
        WorldState.from_dict(payload)


def test_m15_claim_events_emit_site_claim_rumor() -> None:
    sim = _build_sim(seed=333)
    _move_to_site(sim)
    opportunity_id = str(sim.state.world.claim_opportunities[0]["opportunity_id"])

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            command_type=CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
            params={"opportunity_id": opportunity_id},
        )
    )
    sim.advance_ticks(3)

    assert any(row.get("kind") == "site_claim" for row in sim.state.world.rumors)


def test_m15_rumor_id_suffix_uses_canonical_sha_components() -> None:
    sim = _build_sim(seed=334)
    module = sim.get_rule_module(RumorPipelineModule.name)
    assert isinstance(module, RumorPipelineModule)

    event = SimEvent(
        tick=12,
        event_id="evt-17",
        event_type="dummy",
        params={},
    )
    site_key_a = '{"origin_coord":{"q":1,"r":0},"origin_space_id":"overworld","template_id":"site:camp_01"}'

    first = module._rumor_id(
        event=event,
        kind="group_arrival",
        site_key_json=site_key_a,
        group_id="caravan",
    )
    second = module._rumor_id(
        event=event,
        kind="group_arrival",
        site_key_json=site_key_a,
        group_id="caravan",
    )
    reordered_input = module._rumor_id(
        event=event,
        kind="group_arrival",
        site_key_json=LocalEncounterInstanceModule._site_key_json(
            {
                "template_id": "site:camp_01",
                "origin_space_id": "overworld",
                "origin_coord": {"r": 0, "q": 1},
            }
        ),
        group_id="caravan",
    )

    assert first == second
    assert first == reordered_input
