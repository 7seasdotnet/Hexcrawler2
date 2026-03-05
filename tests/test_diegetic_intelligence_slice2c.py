from __future__ import annotations

from hexcrawler.sim.beliefs import (
    FACTION_CONTACT_ADDED_EVENT_TYPE,
    FACTION_CONTACT_ADD_NOOP_EVENT_TYPE,
    FACTION_CONTACT_ADD_REJECTED_EVENT_TYPE,
    FACTION_CONTACT_REMOVED_EVENT_TYPE,
    FACTION_CONTACT_REMOVE_NOOP_EVENT_TYPE,
    FACTION_CONTACT_REMOVE_REJECTED_EVENT_TYPE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import MAX_CONTACTS_PER_FACTION, WorldState


def _setup_sim(*, world: WorldState | None = None, seed: int = 71) -> Simulation:
    sim = Simulation(world=world if world is not None else WorldState(), seed=seed)
    sim.register_rule_module(BeliefJobQueueModule())
    return sim


def _schedule_contact_event(
    sim: Simulation,
    *,
    event_type: str,
    source_faction_id: str,
    target_faction_id: str,
) -> None:
    sim.schedule_event_at(
        tick=0,
        event_type=event_type,
        params={
            "source_faction_id": source_faction_id,
            "target_faction_id": target_faction_id,
        },
    )


def test_slice2c_add_contact_success_and_hash_stability() -> None:
    world = WorldState(faction_registry=["wolves", "hawks", "boars"])
    sim = _setup_sim(world=world)

    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    sim.advance_ticks(1)

    assert sim.state.world.faction_contacts["wolves"] == ["hawks"]

    sim.schedule_event_at(
        tick=1,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        params={"source_faction_id": "wolves", "target_faction_id": "boars"},
    )
    sim.advance_ticks(1)
    assert sim.state.world.faction_contacts["wolves"] == ["boars", "hawks"]

    sim_loaded = Simulation.from_simulation_payload(sim.simulation_payload())
    assert sim_loaded.state.world.faction_contacts == sim.state.world.faction_contacts
    assert world_hash(sim_loaded.state.world) == world_hash(sim.state.world)
    assert simulation_hash(sim_loaded) == simulation_hash(sim)


def test_slice2c_add_contact_noop_is_deterministic() -> None:
    sim = _setup_sim(world=WorldState(faction_registry=["wolves", "hawks"]))

    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    sim.advance_ticks(1)

    assert sim.state.world.faction_contacts["wolves"] == ["hawks"]
    noops = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_ADD_NOOP_EVENT_TYPE]
    assert len(noops) == 1


def test_slice2c_add_contact_rejects_when_source_cap_is_full() -> None:
    recipients = [f"f{index:03d}" for index in range(MAX_CONTACTS_PER_FACTION)]
    world = WorldState(
        faction_registry=["source", "overflow", *recipients],
        faction_contacts={"source": recipients},
    )
    sim = _setup_sim(world=world)

    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        source_faction_id="source",
        target_faction_id="overflow",
    )
    before = sim.state.world.to_dict()
    sim.advance_ticks(1)

    assert sim.state.world.faction_contacts["source"] == sorted(recipients)
    assert sim.state.world.to_dict() == before
    rejected = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_ADD_REJECTED_EVENT_TYPE]
    assert len(rejected) == 1
    assert rejected[0]["params"]["reason"] == "cap_full"


def test_slice2c_remove_contact_success_and_default_omission() -> None:
    world = WorldState(
        faction_registry=["wolves", "hawks"],
        faction_contacts={"wolves": ["hawks"]},
    )
    sim = _setup_sim(world=world)

    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_REMOVED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    sim.advance_ticks(1)

    assert "wolves" not in sim.state.world.faction_contacts
    assert "faction_contacts" not in sim.state.world.to_dict()


def test_slice2c_remove_contact_noop_keeps_state_unchanged() -> None:
    world = WorldState(faction_registry=["wolves", "hawks"])
    sim = _setup_sim(world=world)
    before = sim.state.world.to_dict()

    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_REMOVED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    sim.advance_ticks(1)

    assert sim.state.world.to_dict() == before
    noops = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_REMOVE_NOOP_EVENT_TYPE]
    assert len(noops) == 1


def test_slice2c_validation_rejections_leave_world_unchanged() -> None:
    world = WorldState(faction_registry=["wolves", "hawks"])
    sim = _setup_sim(world=world)

    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        params={"source_faction_id": "wolves", "target_faction_id": "unknown"},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        params={"source_faction_id": "wolves", "target_faction_id": "wolves"},
    )
    sim.schedule_event_at(
        tick=0,
        event_type=FACTION_CONTACT_REMOVED_EVENT_TYPE,
        params={"source_faction_id": "wolves", "target_faction_id": "unknown"},
    )
    baseline = sim.state.world.to_dict()
    sim.advance_ticks(1)

    assert sim.state.world.to_dict() == baseline
    add_rejected = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_ADD_REJECTED_EVENT_TYPE]
    remove_rejected = [row for row in sim.get_event_trace() if row["event_type"] == FACTION_CONTACT_REMOVE_REJECTED_EVENT_TYPE]
    assert len(add_rejected) == 2
    assert len(remove_rejected) == 1


def test_slice2c_save_load_and_hash_stability() -> None:
    sim = _setup_sim(world=WorldState(faction_registry=["wolves", "hawks", "boars"]), seed=72)
    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_ADDED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="boars",
    )
    _schedule_contact_event(
        sim,
        event_type=FACTION_CONTACT_REMOVED_EVENT_TYPE,
        source_faction_id="wolves",
        target_faction_id="hawks",
    )
    sim.advance_ticks(1)

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    assert loaded.simulation_payload() == payload
    assert world_hash(loaded.state.world) == world_hash(sim.state.world)
    assert simulation_hash(loaded) == simulation_hash(sim)
