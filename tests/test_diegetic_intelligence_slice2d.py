from __future__ import annotations

from hexcrawler.sim.beliefs import (
    FACTION_CONTACT_ADDED_EVENT_TYPE,
    FACTION_CONTACT_DECAY_BUDGET_EXHAUSTED_EVENT_TYPE,
    FACTION_CONTACT_DECAYED_EVENT_TYPE,
    FACTION_CONTACT_TOUCHED_EVENT_TYPE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import WorldState


def _setup_sim(*, world: WorldState, seed: int = 72) -> Simulation:
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(BeliefJobQueueModule())
    return sim


def test_slice2d_ttl_disabled_keeps_contacts_and_hash_stable() -> None:
    sim = _setup_sim(
        world=WorldState(
            faction_registry=["wolves", "hawks"],
            faction_contacts={"wolves": ["hawks"]},
        )
    )
    before_hash = simulation_hash(sim)

    sim.advance_ticks(10)

    assert sim.state.world.faction_contacts == {"wolves": ["hawks"]}
    assert simulation_hash(sim) != before_hash


def test_slice2d_add_contact_touches_meta_and_prevents_immediate_decay() -> None:
    sim = _setup_sim(
        world=WorldState(
            faction_registry=["wolves", "hawks"],
            contact_ttl_config={"enabled": True, "contact_ttl_ticks": 5, "max_decay_per_tick": 16},
        )
    )

    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        params={"source_faction_id": "wolves", "target_faction_id": "hawks"},
    )
    sim.advance_ticks(5)

    assert sim.state.world.faction_contacts == {"wolves": ["hawks"]}
    assert sim.state.world.faction_contact_meta["wolves"]["hawks"]["last_touch_tick"] == 0


def test_slice2d_contact_decays_after_ttl() -> None:
    sim = _setup_sim(
        world=WorldState(
            faction_registry=["wolves", "hawks"],
            faction_contacts={"wolves": ["hawks"]},
            faction_contact_meta={"wolves": {"hawks": {"last_touch_tick": 0}}},
            contact_ttl_config={"enabled": True, "contact_ttl_ticks": 3, "max_decay_per_tick": 16},
        )
    )

    sim.advance_ticks(5)

    assert "wolves" not in sim.state.world.faction_contacts
    decayed = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_DECAYED_EVENT_TYPE]
    assert len(decayed) == 1


def test_slice2d_touch_refresh_prevents_decay() -> None:
    sim = _setup_sim(
        world=WorldState(
            faction_registry=["wolves", "hawks"],
            faction_contacts={"wolves": ["hawks"]},
            faction_contact_meta={"wolves": {"hawks": {"last_touch_tick": 0}}},
            contact_ttl_config={"enabled": True, "contact_ttl_ticks": 5, "max_decay_per_tick": 16},
        )
    )

    sim.advance_ticks(4)
    sim.schedule_event_at(
        tick=4,
        event_type=FACTION_CONTACT_TOUCHED_EVENT_TYPE,
        params={"source_faction_id": "wolves", "target_faction_id": "hawks"},
    )
    sim.advance_ticks(5)

    assert sim.state.world.faction_contacts == {"wolves": ["hawks"]}


def test_slice2d_decay_budget_is_bounded_and_deterministic() -> None:
    targets = [f"t{index}" for index in range(5)]
    sim = _setup_sim(
        world=WorldState(
            faction_registry=["source", *targets],
            faction_contacts={"source": list(targets)},
            faction_contact_meta={
                "source": {target: {"last_touch_tick": 0} for target in targets}
            },
            contact_ttl_config={"enabled": True, "contact_ttl_ticks": 1, "max_decay_per_tick": 2},
        )
    )

    sim.advance_ticks(2)
    assert sim.state.world.faction_contacts["source"] == ["t2", "t3", "t4"]

    sim.advance_ticks(1)
    assert sim.state.world.faction_contacts["source"] == ["t4"]

    budget_events = [
        row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_DECAY_BUDGET_EXHAUSTED_EVENT_TYPE
    ]
    assert budget_events


def test_slice2d_save_load_and_hash_stability() -> None:
    world_default = WorldState(faction_registry=["a", "b"], faction_contacts={"a": ["b"]})
    payload_default = world_default.to_dict()
    assert "contact_ttl_config" not in payload_default
    assert "faction_contact_meta" not in payload_default

    loaded_default = WorldState.from_dict(payload_default)
    assert loaded_default.to_dict() == payload_default
    assert world_hash(loaded_default) == world_hash(world_default)

    world_configured = WorldState(
        faction_registry=["a", "b"],
        faction_contacts={"a": ["b"]},
        faction_contact_meta={"a": {"b": {"last_touch_tick": 7}}},
        contact_ttl_config={"enabled": True, "contact_ttl_ticks": 9, "max_decay_per_tick": 3},
    )
    payload_configured = world_configured.to_dict()
    loaded_configured = WorldState.from_dict(payload_configured)
    assert loaded_configured.to_dict() == payload_configured
    assert world_hash(loaded_configured) == world_hash(world_configured)


def test_slice2d_legacy_contacts_without_meta_are_touched_at_runtime_tick() -> None:
    payload = {
        "topology_type": "custom",
        "topology_params": {},
        "spaces": [WorldState().spaces["overworld"].to_dict()],
        "hexes": [],
        "faction_registry": ["wolves", "hawks"],
        "faction_contacts": {"wolves": ["hawks"]},
        "contact_ttl_config": {"enabled": True, "contact_ttl_ticks": 2, "max_decay_per_tick": 16},
    }
    world = WorldState.from_dict(payload)
    sim = _setup_sim(world=world)

    sim.advance_ticks(1)
    assert sim.state.world.faction_contacts == {"wolves": ["hawks"]}
    assert sim.state.world.faction_contact_meta["wolves"]["hawks"]["last_touch_tick"] == 0

    sim.advance_ticks(2)
    assert sim.state.world.faction_contacts == {}
