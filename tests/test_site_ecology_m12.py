from __future__ import annotations

from pathlib import Path

import pytest

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    FORTIFICATION_PENDING_EFFECT_TYPE,
    LocalEncounterInstanceModule,
    REINHABITATION_PENDING_EFFECT_TYPE,
    SITE_ECOLOGY_DECISION_EVENT_TYPE,
    SiteEcologyModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import GroupRecord, SiteRecord


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


def _with_ecology_config(sim: Simulation, config: dict) -> str:
    site_key_json, _ = _site_state(sim)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]["ecology_config"] = config  # noqa: SLF001
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)
    return site_key_json


def test_m12_default_compatibility_hash_matches_m11_baseline() -> None:
    sim = _build_sim(seed=912)
    _site_state(sim)
    sim.advance_ticks(sim.state.time.ticks_per_day * 45)
    assert simulation_hash(sim) == "94d20ec8617dae6e840b21eca2a126a8b11669b1fce85003cba99fcb7940bad8"


def test_m12_config_driven_rule_schedules_only_selected_marker() -> None:
    sim = _build_sim(seed=920)
    site_key_json = _with_ecology_config(
        sim,
        {
            "enabled": True,
            "tick_interval": 1,
            "max_steps_per_tick": 1,
            "rules": [
                {
                    "id": "only_fortify",
                    "kind": "chance_marker",
                    "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                    "chance_percent": 100,
                }
            ],
        },
    )
    sim.advance_ticks(sim.state.time.ticks_per_day * 2)

    site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    marker_types = {row["effect_type"] for row in site_state["pending_effects"]}
    assert marker_types == {FORTIFICATION_PENDING_EFFECT_TYPE}

    events = [
        row for row in sim.get_event_trace() if row["event_type"] == SITE_ECOLOGY_DECISION_EVENT_TYPE
    ]
    assert events
    assert any(event["params"].get("rule_id") == "only_fortify" for event in events)


def test_m12_config_rule_order_invariance() -> None:
    rules_a = [
        {
            "id": "b_rule",
            "kind": "chance_marker",
            "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
            "chance_percent": 100,
            "priority": -2,
        },
        {
            "id": "a_rule",
            "kind": "chance_marker",
            "marker_type": REINHABITATION_PENDING_EFFECT_TYPE,
            "chance_percent": 100,
            "priority": 4,
            "d20_payload": True,
        },
    ]
    rules_b = [rules_a[1], rules_a[0]]

    sim_a = _build_sim(seed=921)
    key_a = _with_ecology_config(sim_a, {"enabled": True, "tick_interval": 1, "max_steps_per_tick": 2, "rules": rules_a})
    sim_a.advance_ticks(sim_a.state.time.ticks_per_day * 3)

    sim_b = _build_sim(seed=921)
    key_b = _with_ecology_config(sim_b, {"enabled": True, "tick_interval": 1, "max_steps_per_tick": 2, "rules": rules_b})
    sim_b.advance_ticks(sim_b.state.time.ticks_per_day * 3)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    state_a = sim_a.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][key_a]  # noqa: SLF001
    state_b = sim_b.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][key_b]  # noqa: SLF001
    assert state_a["ecology_decisions"] == state_b["ecology_decisions"]
    assert state_a["pending_effects"] == state_b["pending_effects"]


def test_m12_max_steps_per_tick_applies_after_canonical_sort() -> None:
    sim = _build_sim(seed=924)
    site_key_json = _with_ecology_config(
        sim,
        {
            "enabled": True,
            "tick_interval": 1,
            "max_steps_per_tick": 1,
            "rules": [
                {
                    "id": "z_last",
                    "kind": "chance_marker",
                    "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                    "chance_percent": 100,
                },
                {
                    "id": "a_first",
                    "kind": "chance_marker",
                    "marker_type": REINHABITATION_PENDING_EFFECT_TYPE,
                    "chance_percent": 100,
                },
            ],
        },
    )
    sim.advance_ticks(sim.state.time.ticks_per_day * 2)

    site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    assert {row["effect_type"] for row in site_state["pending_effects"]} == {REINHABITATION_PENDING_EFFECT_TYPE}
    decision_keys = list(site_state["ecology_decisions"]["order"])
    assert len(decision_keys) == 1
    assert "rule:a_first" in decision_keys[0]


def test_m12_legacy_and_config_decisions_use_distinct_key_namespaces() -> None:
    sim = _build_sim(seed=925)
    site_key_json, _ = _site_state(sim)
    sim.advance_ticks(sim.state.time.ticks_per_day * 45)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    legacy_order = list(site_state["ecology_decisions"]["order"])
    assert legacy_order
    assert all(not key.startswith("site:") for key in legacy_order)

    site_state["ecology_config"] = {
        "enabled": True,
        "tick_interval": 1,
        "max_steps_per_tick": 1,
        "rules": [
            {
                "id": "config_only_rule",
                "kind": "chance_marker",
                "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                "chance_percent": 100,
            }
        ],
    }
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)
    sim.advance_ticks(sim.state.time.ticks_per_day * 2)

    updated_site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    final_order = updated_site_state["ecology_decisions"]["order"]
    assert all(key in final_order for key in legacy_order)
    assert any(key.startswith("site:") and "rule:config_only_rule" in key for key in final_order)


def test_m12_mixed_mode_config_can_be_disabled_without_keyspace_collision() -> None:
    sim = _build_sim(seed=927)
    site_key_json, _ = _site_state(sim)
    sim.advance_ticks(sim.state.time.ticks_per_day * 45)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    legacy_order = list(site_state["ecology_decisions"]["order"])

    site_state["ecology_config"] = {
        "enabled": True,
        "tick_interval": 1,
        "max_steps_per_tick": 1,
        "rules": [
            {
                "id": "toggle_rule",
                "kind": "chance_marker",
                "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                "chance_percent": 100,
            }
        ],
    }
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)
    sim.advance_ticks(sim.state.time.ticks_per_day * 2)

    state_after_enabled = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state_after_enabled = state_after_enabled[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    with_config_keys = list(site_state_after_enabled["ecology_decisions"]["order"])
    assert any(key.startswith("site:") and "rule:toggle_rule" in key for key in with_config_keys)

    site_state_after_enabled["ecology_config"] = {
        "enabled": False,
        "tick_interval": 1,
        "max_steps_per_tick": 1,
        "rules": [
            {
                "id": "toggle_rule",
                "kind": "chance_marker",
                "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                "chance_percent": 100,
            }
        ],
    }
    sim.set_rules_state(LocalEncounterInstanceModule.name, state_after_enabled)
    frozen_decisions = sim.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]["ecology_decisions"]  # noqa: SLF001
    sim.advance_ticks(sim.state.time.ticks_per_day * 3)
    final_site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][site_key_json]  # noqa: SLF001
    assert all(key in final_site_state["ecology_decisions"]["order"] for key in legacy_order)
    assert final_site_state["ecology_decisions"] == frozen_decisions


def test_m12_config_save_load_idempotence(tmp_path: Path) -> None:
    path = tmp_path / "ecology_m12_save.json"

    baseline = _build_sim(seed=922)
    key = _with_ecology_config(
        baseline,
        {
            "enabled": True,
            "tick_interval": 1,
            "max_steps_per_tick": 2,
            "rules": [
                {
                    "id": "x",
                    "kind": "chance_marker",
                    "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                    "chance_percent": 50,
                }
            ],
        },
    )
    baseline.advance_ticks(baseline.state.time.ticks_per_day * 2)
    save_game_json(path, baseline.state.world, baseline)

    _, loaded = load_game_json(path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())

    baseline.advance_ticks(baseline.state.time.ticks_per_day * 2)
    loaded.advance_ticks(loaded.state.time.ticks_per_day * 2)
    assert simulation_hash(loaded) == simulation_hash(baseline)
    assert (
        loaded.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][key]["ecology_decisions"]  # noqa: SLF001
        == baseline.get_rules_state(LocalEncounterInstanceModule.name)[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY][key]["ecology_decisions"]  # noqa: SLF001
    )


@pytest.mark.parametrize(
    "bad_config",
    [
        {
            "enabled": True,
            "rules": [
                {"id": "dup", "kind": "chance_marker", "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE, "chance_percent": 1},
                {"id": "dup", "kind": "chance_marker", "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE, "chance_percent": 2},
            ],
        },
        {
            "enabled": True,
            "rules": [{"id": "chance", "kind": "chance_marker", "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE, "chance_percent": 150}],
        },
        {
            "enabled": True,
            "rules": [{"id": "marker", "kind": "chance_marker", "marker_type": "unknown_marker", "chance_percent": 10}],
        },
        {
            "enabled": True,
            "rules": [
                {"id": f"r{i}", "kind": "chance_marker", "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE, "chance_percent": 10}
                for i in range(17)
            ],
        },
    ],
)
def test_m12_malformed_ecology_config_is_rejected(bad_config: dict) -> None:
    sim = _build_sim(seed=923)
    site_key_json = _with_ecology_config(sim, bad_config)
    payload = sim.simulation_payload()

    restored = Simulation.from_simulation_payload(payload)
    try:
        restored.register_rule_module(LocalEncounterInstanceModule())
    except ValueError as exc:
        assert "ecology_config" in str(exc)
    else:
        raise AssertionError(f"expected malformed ecology_config for {site_key_json} to raise ValueError")


def test_m12_malformed_ecology_config_rejection_is_atomic() -> None:
    sim = _build_sim(seed=926)
    site_key_json, _ = _site_state(sim)
    payload = sim.simulation_payload()
    payload["rules_state"][LocalEncounterInstanceModule.name]["site_state_by_key"][site_key_json]["ecology_config"] = {
        "enabled": True,
        "rules": [{"id": "bad", "kind": "chance_marker", "marker_type": "unknown_marker", "chance_percent": 50}],
    }

    restored = Simulation.from_simulation_payload(payload)
    baseline_hash = simulation_hash(restored)
    before_rules_state = restored.simulation_payload()["rules_state"]
    before_site_state = restored.simulation_payload()["rules_state"][LocalEncounterInstanceModule.name]["site_state_by_key"][site_key_json]
    try:
        restored.register_rule_module(LocalEncounterInstanceModule())
    except ValueError as exc:
        assert "ecology_config" in str(exc)
    else:
        raise AssertionError("expected malformed ecology_config to raise ValueError")
    after_payload = restored.simulation_payload()
    assert simulation_hash(restored) == baseline_hash
    assert after_payload["rules_state"] == before_rules_state
    assert after_payload["rules_state"][LocalEncounterInstanceModule.name]["site_state_by_key"][site_key_json] == before_site_state
