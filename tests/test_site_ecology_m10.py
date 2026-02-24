from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    FORTIFICATION_PENDING_EFFECT_TYPE,
    LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX,
    LocalEncounterInstanceModule,
    MAX_SITE_ECOLOGY_DECISIONS,
    REINHABITATION_PENDING_EFFECT_TYPE,
    SITE_ECOLOGY_DECISION_EVENT_TYPE,
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
            "ecology_decisions": {"order": [], "by_key": {}},
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
    assert normalized["ecology_decisions"] == {"order": [], "by_key": {}}


def test_ecology_rng_decisions_are_replay_stable() -> None:
    sim_a = _build_sim(seed=912)
    site_key_json, _ = _site_state(sim_a)
    sim_a.advance_ticks(sim_a.state.time.ticks_per_day * 45)

    sim_b = _build_sim(seed=912)
    _site_state(sim_b)
    sim_b.advance_ticks(sim_b.state.time.ticks_per_day * 45)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    state = sim_a.get_rules_state(LocalEncounterInstanceModule.name)
    decisions = state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]["ecology_decisions"]  # noqa: SLF001
    assert len(decisions["order"]) >= 2


def test_ecology_save_load_idempotence_reuses_existing_decisions(tmp_path: Path) -> None:
    path = tmp_path / "ecology_save.json"

    baseline = _build_sim(seed=913)
    site_key_json, _ = _site_state(baseline)
    baseline.advance_ticks(baseline.state.time.ticks_per_day * 45)
    baseline_pre = baseline.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]["ecology_decisions"]  # noqa: SLF001

    split = _build_sim(seed=913)
    _site_state(split)
    split.advance_ticks(split.state.time.ticks_per_day * 45)
    save_game_json(path, split.state.world, split)

    _, loaded = load_game_json(path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())

    loaded.advance_ticks(loaded.state.time.ticks_per_day * 5)
    baseline.advance_ticks(baseline.state.time.ticks_per_day * 5)

    loaded_state = loaded.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    baseline_state = baseline.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    assert loaded_state["ecology_decisions"] == baseline_state["ecology_decisions"]
    assert loaded_state["ecology_decisions"] == baseline_pre
    assert simulation_hash(loaded) == simulation_hash(baseline)


def test_ecology_noop_decision_is_recorded_and_not_rerolled(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setattr("hexcrawler.sim.encounters.SITE_ECOLOGY_FORTIFY_CHANCE_PERCENT", 0)
    monkeypatch.setattr("hexcrawler.sim.encounters.SITE_ECOLOGY_REINFORCE_CHANCE_PERCENT", 0)

    sim = _build_sim(seed=914)
    site_key_json, _ = _site_state(sim)
    sim.advance_ticks(sim.state.time.ticks_per_day * 40)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    decisions = site_state["ecology_decisions"]
    assert decisions["order"]
    for key in decisions["order"]:
        assert decisions["by_key"][key]["result"].startswith("no-op:")

    assert [e for e in site_state["pending_effects"] if e["effect_type"] in {FORTIFICATION_PENDING_EFFECT_TYPE, REINHABITATION_PENDING_EFFECT_TYPE}] == []

    path = tmp_path / "noop_save.json"
    save_game_json(path, sim.state.world, sim)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())

    loaded.advance_ticks(loaded.state.time.ticks_per_day * 5)
    reloaded_decisions = loaded.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]["ecology_decisions"]  # noqa: SLF001
    assert reloaded_decisions == decisions


def test_ecology_decision_ledger_is_fifo_bounded_and_deterministic() -> None:
    sim_a = _build_sim(seed=915)
    site_key_json, _ = _site_state(sim_a)
    module = SiteEcologyModule()
    decisions = {"order": [], "by_key": {}}
    for index in range(MAX_SITE_ECOLOGY_DECISIONS + 32):
        _, decisions, _ = module._resolve_ecology_decision(  # noqa: SLF001
            sim=sim_a,
            site_key_json=site_key_json,
            decisions=decisions,
            decision_key=f"synthetic_{index}",
            threshold=100,
            effect_type=FORTIFICATION_PENDING_EFFECT_TYPE,
        )

    assert len(decisions["order"]) == MAX_SITE_ECOLOGY_DECISIONS
    assert decisions["order"][0] == "synthetic_32"
    assert decisions["order"][-1] == f"synthetic_{MAX_SITE_ECOLOGY_DECISIONS + 31}"

    sim_b = _build_sim(seed=915)
    site_key_json_b, _ = _site_state(sim_b)
    decisions_b = {"order": [], "by_key": {}}
    for index in range(MAX_SITE_ECOLOGY_DECISIONS + 32):
        _, decisions_b, _ = module._resolve_ecology_decision(  # noqa: SLF001
            sim=sim_b,
            site_key_json=site_key_json_b,
            decisions=decisions_b,
            decision_key=f"synthetic_{index}",
            threshold=100,
            effect_type=FORTIFICATION_PENDING_EFFECT_TYPE,
        )
    assert decisions_b == decisions


def test_ecology_processing_cap_is_deterministic() -> None:
    sim = _build_sim(seed=916)
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
            "ecology_decisions": {"order": [], "by_key": {}},
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


def test_ecology_deferral_save_load_idempotence() -> None:
    def _build_large_site_state(sim: Simulation) -> None:
        state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        by_key = {}
        for index in range(SITE_ECOLOGY_MAX_PROCESSED_PER_TICK + 9):
            site_key = {
                "origin_space_id": "overworld",
                "origin_coord": {"q": index, "r": 1},
                "template_id": f"deferral_site_{index:03d}",
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
                "ecology_decisions": {"order": [], "by_key": {}},
            }
        state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY] = by_key  # noqa: SLF001
        sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    baseline = _build_sim(seed=918)
    _build_large_site_state(baseline)
    baseline.advance_ticks(2)
    baseline_snapshot = baseline.simulation_payload()
    baseline.advance_ticks(baseline.state.time.ticks_per_day + 2)

    split = Simulation.from_simulation_payload(baseline_snapshot)
    split.register_rule_module(LocalEncounterInstanceModule())
    split.register_rule_module(SiteEcologyModule())
    split.advance_ticks(split.state.time.ticks_per_day + 2)

    assert simulation_hash(split) == simulation_hash(baseline)

    baseline_state = baseline.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY]  # noqa: SLF001
    split_state = split.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY]  # noqa: SLF001
    assert split_state == baseline_state
    for site_payload in split_state.values():
        decisions = site_payload["ecology_decisions"]
        assert len(decisions["order"]) == len(set(decisions["order"]))


def test_invalid_ecology_decisions_payload_is_rejected() -> None:
    sim = _build_sim(seed=917)
    site_key_json, _ = _site_state(sim)
    payload = sim.simulation_payload()
    payload["rules_state"][LocalEncounterInstanceModule.name]["site_state_by_key"][site_key_json]["ecology_decisions"] = {
        "order": ["k1"],
        "by_key": {"k1": {"pct_roll": 10}},
    }

    restored = Simulation.from_simulation_payload(payload)
    try:
        restored.register_rule_module(LocalEncounterInstanceModule())
    except ValueError as exc:
        assert "ecology_decisions" in str(exc)
    else:
        raise AssertionError("expected malformed ecology_decisions to raise ValueError")
