from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import (
    CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
    CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
    LocalEncounterInstanceModule,
    SiteEcologyModule,
    MAX_CLAIM_SITES_PROCESSED_PER_ARRIVAL,
)
from hexcrawler.sim.groups import GroupMovementModule
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import MAX_CLAIM_OPPORTUNITIES, GroupRecord, SiteRecord


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


def _first_opportunity_id(sim: Simulation) -> str:
    return str(sim.state.world.claim_opportunities[0]["opportunity_id"])


def test_m14_replay_hash_stability_for_arrival_opportunity_creation() -> None:
    sim_a = _build_sim(seed=4100)
    sim_b = _build_sim(seed=4100)

    _move_to_site(sim_a)
    _move_to_site(sim_b)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert len(sim_a.state.world.claim_opportunities) == 1


def test_m14_save_load_no_duplicate_opportunity_generation(tmp_path: Path) -> None:
    contiguous = _build_sim(seed=4200)
    _move_to_site(contiguous)
    contiguous.advance_ticks(3)

    split = _build_sim(seed=4200)
    _move_to_site(split)
    save_path = tmp_path / "m14_claim_opportunity.json"
    save_game_json(save_path, split.state.world, split)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())
    loaded.register_rule_module(GroupMovementModule())
    loaded.advance_ticks(3)

    assert len(loaded.state.world.claim_opportunities) == 1
    assert simulation_hash(loaded) == simulation_hash(contiguous)


def test_m14_dedup_same_group_same_site_when_unconsumed() -> None:
    sim = _build_sim(seed=4300)
    _move_to_site(sim)
    first = list(sim.state.world.claim_opportunities)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                "travel_ticks": 1,
            },
        )
    )
    sim.advance_ticks(3)

    assert len(sim.state.world.claim_opportunities) == 1
    assert sim.state.world.claim_opportunities == first


def test_m14_consume_happy_path_claims_site_and_marks_consumed() -> None:
    sim = _build_sim(seed=4400)
    _move_to_site(sim)
    opportunity_id = _first_opportunity_id(sim)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            command_type=CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
            params={"opportunity_id": opportunity_id},
        )
    )
    sim.advance_ticks(3)

    assert sim.state.world.claim_opportunities[0]["consumed_tick"] is not None
    local_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = next(iter(local_state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY].values()))
    assert site_state["claimed_by_group_id"] == "caravan"
    outcomes = [e for e in sim.get_event_trace() if e.get("event_type") == CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE]
    assert outcomes


def test_m14_consume_rejections_are_atomic() -> None:
    cases = [
        {"name": "unknown", "opportunity_id": "missing", "expected": "unknown_opportunity"},
        {"name": "already_consumed", "expected": "opportunity_already_consumed"},
        {"name": "group_moved_away", "expected": "group_not_at_opportunity_cell"},
        {"name": "site_already_claimed", "expected": "already_claimed"},
    ]

    for case in cases:
        sim = _build_sim(seed=4500)
        _move_to_site(sim)
        opportunity_id = _first_opportunity_id(sim)
        if case["name"] == "already_consumed":
            sim.append_command(
                SimCommand(
                    tick=sim.state.tick,
                    command_type=CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
                    params={"opportunity_id": opportunity_id},
                )
            )
            sim.advance_ticks(2)
        elif case["name"] == "group_moved_away":
            sim.state.world.groups["caravan"].location = {"space_id": "overworld", "coord": {"q": 0, "r": 0}}
            sim.state.world.groups["caravan"].cell = {"q": 0, "r": 0}
        elif case["name"] == "site_already_claimed":
            site_key = sim.state.world.claim_opportunities[0]["site_key"]
            local_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
            site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
            site_state_by_key = dict(local_state.get(LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY, {}))
            site_state_by_key[site_key_json] = {
                "site_key": site_key,
                "status": "inactive",
                "last_active_tick": 0,
                "next_check_tick": 0,
                "tags": [],
                "pending_effects": [],
                "rehab_generation": 0,
                "fortified": False,
                "rehab_policy": "replace",
                "claimed_by_group_id": "other",
                "claimed_tick": 0,
                "growth_applied_steps": [],
                "ecology_decisions": {"order": [], "by_key": {}},
            }
            local_state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY] = site_state_by_key
            sim.set_rules_state(LocalEncounterInstanceModule.name, local_state)

        before_hash = world_hash(sim.state.world)
        sim.append_command(
            SimCommand(
                tick=sim.state.tick,
                command_type=CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
                params={"opportunity_id": case.get("opportunity_id", opportunity_id)},
            )
        )
        sim.advance_ticks(2)

        outcomes = [e for e in sim.get_event_trace() if e.get("event_type") == "site_claim_outcome"]
        assert outcomes[-1]["params"]["outcome"] == case["expected"]
        if case["name"] in {"unknown", "group_moved_away", "site_already_claimed"}:
            assert world_hash(sim.state.world) == before_hash
            assert sim.state.world.claim_opportunities[0]["consumed_tick"] is None




def test_m14_multi_site_cell_order_dedupe_and_bounded_arrival_processing() -> None:
    sim = _build_sim(seed=4700)
    # Add many sites at one campaign-role cell; processing must be bounded and deterministic.
    for i in range(60):
        sim.state.world.sites[f"camp_bulk_{i:02d}"] = SiteRecord(
            site_id=f"camp_bulk_{i:02d}",
            site_type="dungeon",
            location={"space_id": "overworld", "coord": {"q": 1, "r": 0}},
        )

    _move_to_site(sim)

    # Existing camp_01 + bulk sites share same cell but arrival processing is bounded.
    assert len(sim.state.world.claim_opportunities) == MAX_CLAIM_SITES_PROCESSED_PER_ARRIVAL

    all_site_key_jsons = sorted(
        LocalEncounterInstanceModule._site_key_json(
            {
                "origin_space_id": str(site.location.get("space_id", "")),
                "origin_coord": dict(site.location.get("coord", {})),
                "template_id": f"site:{site.site_id}",
            }
        )
        for site in sim.state.world.get_sites_at_location({"space_id": "overworld", "coord": {"q": 1, "r": 0}})
    )
    expected_processed = all_site_key_jsons[:MAX_CLAIM_SITES_PROCESSED_PER_ARRIVAL]
    expected_skipped = all_site_key_jsons[MAX_CLAIM_SITES_PROCESSED_PER_ARRIVAL:]

    site_key_jsons = [
        LocalEncounterInstanceModule._site_key_json(dict(row["site_key"]))
        for row in sim.state.world.claim_opportunities
    ]
    assert site_key_jsons == expected_processed
    assert all(key not in site_key_jsons for key in expected_skipped)

    # Re-arrival at same cell must not duplicate unconsumed opportunities per (group_id, site_key).
    before = list(sim.state.world.claim_opportunities)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            command_type="move_group_intent",
            params={
                "group_id": "caravan",
                "dest_cell": {"space_id": "overworld", "coord": {"q": 1, "r": 0}},
                "travel_ticks": 1,
            },
        )
    )
    sim.advance_ticks(3)
    assert sim.state.world.claim_opportunities == before

def test_m14_bounded_fifo_eviction_is_deterministic() -> None:
    sim = _build_sim(seed=4600)
    module = sim.get_rule_module(SiteEcologyModule.name)
    assert isinstance(module, SiteEcologyModule)
    cell = {"space_id": "overworld", "coord": {"q": 1, "r": 0}}

    for i in range(MAX_CLAIM_OPPORTUNITIES):
        module._create_claim_opportunity(
            sim=sim,
            tick=i,
            group_id="caravan",
            site_key={"origin_space_id": "overworld", "origin_coord": {"q": 1, "r": 0}, "template_id": f"site:seed-{i}"},
            cell=cell,
        )

    # FIFO policy is unconditional (consumed and unconsumed entries are treated the same).
    sim.state.world.claim_opportunities[0]["consumed_tick"] = 999

    module._create_claim_opportunity(
        sim=sim,
        tick=MAX_CLAIM_OPPORTUNITIES + 1,
        group_id="caravan",
        site_key={"origin_space_id": "overworld", "origin_coord": {"q": 1, "r": 0}, "template_id": "site:new"},
        cell=cell,
    )

    assert len(sim.state.world.claim_opportunities) == MAX_CLAIM_OPPORTUNITIES
    first_id = str(sim.state.world.claim_opportunities[0]["opportunity_id"])
    assert 'site:seed-0' not in first_id
