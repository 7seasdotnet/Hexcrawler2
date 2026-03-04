from __future__ import annotations

from pathlib import Path

import pytest

from hexcrawler.content.io import load_simulation_json, load_world_json, save_simulation_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import (
    CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
    CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
    LocalEncounterInstanceModule,
    RumorDecayModule,
    RumorPipelineModule,
    SiteEcologyModule,
)
from hexcrawler.sim.groups import GroupMovementModule
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import MAX_RUMOR_TTL_TICKS, GroupRecord, SiteRecord, WorldState


def _build_sim(*, ttl_enabled: bool = True, ttl_overrides: dict[str, int] | None = None) -> Simulation:
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
    world.rumor_ttl_config = {
        "enabled": ttl_enabled,
        "ttl_by_kind": ttl_overrides or {
            "group_arrival": 300,
            "claim_opportunity": 400,
            "site_claim": 500,
        },
        "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
    }

    sim = Simulation(world=world, seed=4242)
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(SiteEcologyModule())
    sim.register_rule_module(GroupMovementModule())
    sim.register_rule_module(RumorPipelineModule())
    sim.register_rule_module(RumorDecayModule())
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


def _emit_site_claim(sim: Simulation) -> None:
    opportunity_id = str(sim.state.world.claim_opportunities[0]["opportunity_id"])
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            command_type=CLAIM_SITE_FROM_OPPORTUNITY_INTENT,
            params={"opportunity_id": opportunity_id},
        )
    )
    sim.advance_ticks(3)


def test_m21_applies_ttl_defaults_by_kind_on_creation() -> None:
    sim = _build_sim()
    _move_to_site(sim)
    _emit_site_claim(sim)

    by_kind = {row["kind"]: row for row in sim.state.world.rumors}
    assert by_kind["group_arrival"]["expires_tick"] == by_kind["group_arrival"]["created_tick"] + 300
    assert by_kind["claim_opportunity"]["expires_tick"] == by_kind["claim_opportunity"]["created_tick"] + 400
    assert by_kind["site_claim"]["expires_tick"] == by_kind["site_claim"]["created_tick"] + 500


def test_m21_ttl_not_applied_when_disabled() -> None:
    sim = _build_sim(ttl_enabled=False)
    _move_to_site(sim)

    assert all(row.get("expires_tick") is None for row in sim.state.world.rumors)


def test_m22_site_template_override_applies_with_precedence() -> None:
    sim = _build_sim()
    sim.state.world.rumor_ttl_config = {
        "enabled": True,
        "ttl_by_kind": {
            "group_arrival": 300,
            "claim_opportunity": 400,
            "site_claim": 500,
        },
        "ttl_by_region": {
            "frontier": {
                "group_arrival": 333,
            }
        },
        "ttl_by_site_template": {
            "dungeon": {
                "group_arrival": 111,
            }
        },
        "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
    }
    sim.state.world.sites["camp_01"].location["region_id"] = "frontier"

    _move_to_site(sim)

    arrival = next(row for row in sim.state.world.rumors if row["kind"] == "group_arrival")
    assert arrival["expires_tick"] == arrival["created_tick"] + 111


def test_m22_region_override_is_ignored_without_resolvable_region_context() -> None:
    sim = _build_sim()
    sim.state.world.rumor_ttl_config = {
        "enabled": True,
        "ttl_by_kind": {
            "group_arrival": 300,
            "claim_opportunity": 400,
            "site_claim": 500,
        },
        "ttl_by_region": {
            "frontier": {
                "site_claim": 123,
            }
        },
        "ttl_by_site_template": {},
        "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
    }

    sim.schedule_event_at(
        tick=0,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 9, "r": 9},
                "template_id": "site:missing_site",
            },
        },
    )
    sim.advance_ticks(1)

    rumor = sim.state.world.rumors[0]
    assert rumor["kind"] == "site_claim"
    assert rumor["expires_tick"] == rumor["created_tick"] + 500


def test_m22_expires_tick_is_not_recomputed_after_creation_when_config_changes() -> None:
    sim = _build_sim()
    sim.state.world.rumor_ttl_config = {
        "enabled": True,
        "ttl_by_kind": {
            "group_arrival": 3,
            "claim_opportunity": 4,
            "site_claim": 5,
        },
        "ttl_by_site_template": {},
        "ttl_by_region": {},
        "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
    }
    _move_to_site(sim)

    created = next(row for row in sim.state.world.rumors if row["kind"] == "group_arrival")
    original_expires_tick = int(created["expires_tick"])

    sim.state.world.rumor_ttl_config = {
        "enabled": True,
        "ttl_by_kind": {
            "group_arrival": 999,
            "claim_opportunity": 999,
            "site_claim": 999,
        },
        "ttl_by_site_template": {},
        "ttl_by_region": {},
        "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
    }
    same_rumor = next(row for row in sim.state.world.rumors if row["rumor_id"] == created["rumor_id"])
    assert same_rumor["expires_tick"] == original_expires_tick


def test_m22_override_key_normalization_is_trimmed_and_deterministic() -> None:
    world = WorldState.from_dict(
        {
            "topology_type": "custom",
            "topology_params": {},
            "hexes": [],
            "rumor_ttl_config": {
                "enabled": True,
                "ttl_by_kind": {
                    "group_arrival": 10,
                    "claim_opportunity": 11,
                    "site_claim": 12,
                },
                "ttl_by_site_template": {
                    "  dungeon  ": {"group_arrival": 9},
                },
                "ttl_by_region": {
                    "  frontier  ": {"group_arrival": 8},
                },
                "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
            },
        }
    )

    assert "dungeon" in world.rumor_ttl_config["ttl_by_site_template"]
    assert "frontier" in world.rumor_ttl_config["ttl_by_region"]


def test_m22_override_key_normalization_rejects_post_trim_duplicates() -> None:
    payload = {
        "topology_type": "custom",
        "topology_params": {},
        "hexes": [],
        "rumor_ttl_config": {
            "enabled": True,
            "ttl_by_kind": {
                "group_arrival": 10,
                "claim_opportunity": 11,
                "site_claim": 12,
            },
            "ttl_by_site_template": {
                "dungeon": {"group_arrival": 9},
                " dungeon ": {"group_arrival": 8},
            },
            "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
        },
    }
    with pytest.raises(ValueError, match="unique after normalization"):
        _ = WorldState.from_dict(payload)


@pytest.mark.parametrize(
    "config, error_match",
    [
        ({"enabled": True, "ttl_by_kind": {"group_arrival": True}}, "ttl_by_kind"),
        ({"enabled": True, "ttl_by_kind": {"group_arrival": -1}}, ">= 0"),
        ({"enabled": True, "ttl_by_kind": {"group_arrival": MAX_RUMOR_TTL_TICKS + 1}}, "max_ttl_ticks"),
        ({"enabled": True, "ttl_by_kind": {"unknown_kind": 10}}, "unknown rumor kind"),
    ],
)
def test_m21_rumor_ttl_config_validation_rejects_invalid_values(config: dict[str, object], error_match: str) -> None:
    payload = {
        "topology_type": "custom",
        "topology_params": {},
        "hexes": [],
        "rumor_ttl_config": config,
    }
    with pytest.raises(ValueError, match=error_match):
        _ = WorldState.from_dict(payload)


def test_m21_save_load_preserves_ttl_and_decay_state(tmp_path: Path) -> None:
    baseline = _build_sim()
    resumed = _build_sim()
    for sim in (baseline, resumed):
        _move_to_site(sim)
        _emit_site_claim(sim)

    baseline.advance_ticks(6)

    save_path = tmp_path / "m21_ttl_save.json"
    save_simulation_json(save_path, resumed)
    loaded = load_simulation_json(save_path)
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(SiteEcologyModule())
    loaded.register_rule_module(GroupMovementModule())
    loaded.register_rule_module(RumorPipelineModule())
    loaded.register_rule_module(RumorDecayModule())
    loaded.advance_ticks(6)

    assert loaded.state.world.rumors == baseline.state.world.rumors
    assert simulation_hash(loaded) == simulation_hash(baseline)


def test_m21_decay_module_removes_ttl_expired_rumors() -> None:
    sim = _build_sim(ttl_overrides={"group_arrival": 1, "claim_opportunity": 1, "site_claim": 1})
    sim.schedule_event_at(
        tick=0,
        event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
        params={
            "group_id": "caravan",
            "site_key": {
                "origin_space_id": "overworld",
                "origin_coord": {"q": 1, "r": 0},
                "template_id": "site:camp_01",
            },
        },
    )

    sim.advance_ticks(1)
    assert len(sim.state.world.rumors) == 1
    assert sim.state.world.rumors[0]["expires_tick"] == sim.state.world.rumors[0]["created_tick"] + 1

    sim.advance_ticks(1)
    assert sim.state.world.rumors == []

def test_m21_default_config_omission_and_hash_coverage_semantics() -> None:
    baseline_world = load_world_json("content/examples/basic_map.json")
    defaulted_world = WorldState.from_dict(baseline_world.to_dict())

    assert "rumor_ttl_config" not in baseline_world.to_dict()
    assert "rumor_ttl_config" not in defaulted_world.to_dict()
    assert world_hash(defaulted_world) == world_hash(baseline_world)

    defaulted_world.rumor_ttl_config = {
        "enabled": True,
        "ttl_by_kind": {
            "group_arrival": 2000,
            "claim_opportunity": 4000,
            "site_claim": 9999,
        },
        "ttl_by_site_template": {
            "dungeon": {
                "site_claim": 9998,
            }
        },
        "ttl_by_region": {
            "frontier": {
                "site_claim": 9997,
            }
        },
        "max_ttl_ticks": MAX_RUMOR_TTL_TICKS,
    }
    payload = defaulted_world.to_dict()
    assert "rumor_ttl_config" in payload
    assert payload["rumor_ttl_config"]["ttl_by_kind"]["site_claim"] == 9999
    assert payload["rumor_ttl_config"]["ttl_by_site_template"]["dungeon"]["site_claim"] == 9998
    assert payload["rumor_ttl_config"]["ttl_by_region"]["frontier"]["site_claim"] == 9997
    assert world_hash(defaulted_world) != world_hash(baseline_world)

    reloaded = WorldState.from_dict(payload)
    assert reloaded.rumor_ttl_config == defaulted_world.rumor_ttl_config
    assert world_hash(reloaded) == world_hash(defaulted_world)
