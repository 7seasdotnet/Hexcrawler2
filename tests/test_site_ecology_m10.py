from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    FORTIFICATION_PENDING_EFFECT_TYPE,
    LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX,
    LocalEncounterInstanceModule,
    REINHABITATION_PENDING_EFFECT_TYPE,
    SITE_ECOLOGY_MAX_PROCESSED_PER_TICK,
    SITE_ECOLOGY_TICK_EVENT_TYPE,
    SiteEcologyModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import GroupRecord, SiteRecord, WorldState


def _build_sim(seed: int = 910) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.sites["ecology_site"] = SiteRecord(
        site_id="ecology_site",
        site_type="dungeon",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        tags=[],
    )
    world.groups["seeders"] = GroupRecord(
        group_id="seeders",
        group_type="goblin_troupe",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
        strength=5,
        tags=["seed"],
    )
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(SiteEcologyModule())
    return sim


def _site_state(sim: Simulation, *, site_id: str = "ecology_site") -> tuple[str, dict]:
    module = LocalEncounterInstanceModule()
    site_key = {
        "origin_space_id": "overworld",
        "origin_coord": {"q": 0, "r": 0},
        "template_id": site_id,
    }
    site_key_json = module._site_key_json(site_key)  # noqa: SLF001
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    by_key = dict(state.get(LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY, {}))  # noqa: SLF001
    if site_key_json not in by_key:
        by_key[site_key_json] = {
            "site_key": site_key,
            "status": "inactive",
            "last_active_tick": 0,
            "next_check_tick": 10**9,
            "tags": [],
            "pending_effects": [],
            "rehab_generation": 0,
            "fortified": False,
            "rehab_policy": "replace",
            "claimed_by_group_id": "seeders",
            "claimed_tick": 0,
            "growth_applied_steps": [],
        }
        state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY] = by_key  # noqa: SLF001
        sim.set_rules_state(LocalEncounterInstanceModule.name, state)
    return site_key_json, by_key[site_key_json]


def test_world_groups_and_site_state_defaults() -> None:
    world = load_world_json("content/examples/basic_map.json")
    payload = world.to_dict()
    payload.pop("groups", None)
    restored = WorldState.from_dict(payload)
    assert restored.groups == {}

    sim = _build_sim(seed=911)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    assert isinstance(state.get("processed_request_ids", []), list)

    _, site_state = _site_state(sim)
    normalized = LocalEncounterInstanceModule()._normalize_site_state_payload(site_state)  # noqa: SLF001
    assert normalized is not None
    assert normalized["claimed_by_group_id"] == "seeders"
    assert normalized["claimed_tick"] == 0
    assert normalized["growth_applied_steps"] == []


def test_ecology_growth_idempotent_and_priority_ordered() -> None:
    sim = _build_sim(seed=912)
    site_key_json, _ = _site_state(sim)

    sim.advance_ticks(sim.state.time.ticks_per_day * 8)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    effects = site_state["pending_effects"]
    fortify_effects = [entry for entry in effects if entry.get("effect_type") == FORTIFICATION_PENDING_EFFECT_TYPE]
    assert len(fortify_effects) == 1
    assert fortify_effects[0]["priority"] == 0
    assert site_state["growth_applied_steps"].count("fortify_1") == 1

    sim.advance_ticks(sim.state.time.ticks_per_day * 40)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    effects = site_state["pending_effects"]
    reinforce_effects = [entry for entry in effects if entry.get("effect_type") == REINHABITATION_PENDING_EFFECT_TYPE]
    assert len(reinforce_effects) == 1
    assert reinforce_effects[0]["priority"] == 10
    assert site_state["growth_applied_steps"].count("reinforce_1") == 1


def test_ecology_save_load_hash_stability(tmp_path: Path) -> None:
    path = tmp_path / "ecology_save.json"

    sim_a = _build_sim(seed=913)
    _site_state(sim_a)
    sim_a.advance_ticks(sim_a.state.time.ticks_per_day * 5)
    save_game_json(path, sim_a.state.world, sim_a)

    _, loaded = load_game_json(path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())

    sim_b = _build_sim(seed=913)
    _site_state(sim_b)
    sim_b.advance_ticks(sim_b.state.time.ticks_per_day * 5)

    loaded.advance_ticks(loaded.state.time.ticks_per_day * 40)
    sim_b.advance_ticks(sim_b.state.time.ticks_per_day * 40)
    assert simulation_hash(loaded) == simulation_hash(sim_b)


def test_ecology_processing_cap_is_deterministic() -> None:
    sim = _build_sim(seed=914)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    by_key = {}
    for index in range(SITE_ECOLOGY_MAX_PROCESSED_PER_TICK + 4):
        site_key = {
            "origin_space_id": "overworld",
            "origin_coord": {"q": index, "r": 0},
            "template_id": f"site_{index:03d}",
        }
        key = LocalEncounterInstanceModule._site_key_json(site_key)  # noqa: SLF001
        by_key[key] = {
            "site_key": site_key,
            "status": "inactive",
            "last_active_tick": 0,
            "next_check_tick": 10**9,
            "tags": [],
            "pending_effects": [],
            "rehab_generation": 0,
            "fortified": False,
            "rehab_policy": "replace",
            "claimed_by_group_id": "seeders",
            "claimed_tick": -sim.state.time.ticks_per_day * 8,
            "growth_applied_steps": [],
        }
    state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY] = by_key  # noqa: SLF001
    state["processed_request_ids"] = state.get("processed_request_ids", [])[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    sim.advance_ticks(2)
    first_tick_events = [
        row for row in sim.get_event_trace() if row["event_type"] == SITE_ECOLOGY_TICK_EVENT_TYPE
    ]
    assert first_tick_events
    assert first_tick_events[0]["params"]["processed_sites"] == SITE_ECOLOGY_MAX_PROCESSED_PER_TICK

    sim.advance_ticks(sim.state.time.ticks_per_day + 2)
    tick_events = [
        row for row in sim.get_event_trace() if row["event_type"] == SITE_ECOLOGY_TICK_EVENT_TYPE
    ]
    assert len(tick_events) >= 2
    assert tick_events[1]["params"]["processed_sites"] == SITE_ECOLOGY_MAX_PROCESSED_PER_TICK
