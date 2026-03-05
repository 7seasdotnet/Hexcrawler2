from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BASE_TRANSMISSION_DELAY_TICKS,
    BELIEF_FANOUT_SKIPPED_EVENT_TYPE,
    BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
    MAX_FANOUT_RECIPIENTS,
    MAX_TRANSMISSION_QUEUE,
    BeliefJobQueueModule,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.world import WorldState


def _claim_subject() -> dict[str, str]:
    return {"kind": "player", "id": "player"}


def _seed_factions(sim: Simulation, faction_ids: list[str]) -> None:
    sim.state.world.faction_beliefs = {
        faction_id: {"belief_records": {}}
        for faction_id in faction_ids
    }
    sim.state.world.faction_registry = sorted(faction_ids)
    sim.state.world.activated_factions = sorted(faction_ids)


def _outbound_params(*, source_faction_id: str, confidence: int = 25, **extra: object) -> dict[str, object]:
    params: dict[str, object] = {
        "source_faction_id": source_faction_id,
        "subject": _claim_subject(),
        "claim_key": "violence",
        "confidence": confidence,
    }
    params.update(extra)
    return params


def test_slice1e_deterministic_recipient_selection_lexical_and_bounded() -> None:
    sim = Simulation(world=WorldState(), seed=11)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed_factions(sim, ["delta", "gamma", "alpha", "beta", "source"])

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params=_outbound_params(source_faction_id="source"),
    )
    sim.advance_ticks(1)

    expected_recipients = ["alpha", "beta", "delta"][:MAX_FANOUT_RECIPIENTS]
    for faction_id in expected_recipients:
        queue = sim.state.world.faction_beliefs[faction_id]["transmission_queue"]
        assert len(queue) == 1

    assert "transmission_queue" not in sim.state.world.faction_beliefs["gamma"]


def test_slice1e_fanout_never_exceeds_max_recipients() -> None:
    sim = Simulation(world=WorldState(), seed=13)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed_factions(sim, ["source", "a", "b", "c", "d", "e", "f"])

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params=_outbound_params(source_faction_id="source"),
    )
    sim.advance_ticks(1)

    enqueued_count = sum(
        1
        for faction_id, faction_state in sim.state.world.faction_beliefs.items()
        if faction_id != "source" and isinstance(faction_state.get("transmission_queue"), list)
    )
    assert enqueued_count == MAX_FANOUT_RECIPIENTS


def test_slice1e_queue_full_emits_deterministic_skip_and_continues() -> None:
    sim = Simulation(world=WorldState(), seed=17)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed_factions(sim, ["source", "alpha", "beta", "gamma"])

    sim.state.world.faction_beliefs["alpha"]["transmission_queue"] = [
        {
            "job_id": f"existing-{index}",
            "created_tick": 0,
            "not_before_tick": 10_000,
            "faction_id": "alpha",
            "claim": {
                "subject": _claim_subject(),
                "claim_key": "violence",
                "confidence": 1,
            },
        }
        for index in range(MAX_TRANSMISSION_QUEUE)
    ]

    sim.schedule_event_at(
        tick=0,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params=_outbound_params(source_faction_id="source"),
    )
    sim.advance_ticks(1)

    assert len(sim.state.world.faction_beliefs["alpha"]["transmission_queue"]) == MAX_TRANSMISSION_QUEUE
    assert len(sim.state.world.faction_beliefs["beta"]["transmission_queue"]) == 1
    assert len(sim.state.world.faction_beliefs["gamma"]["transmission_queue"]) == 1

    skip_events = [
        row
        for row in sim.get_event_trace()
        if row["event_type"] == BELIEF_FANOUT_SKIPPED_EVENT_TYPE
    ]
    assert len(skip_events) == 1
    assert skip_events[0]["params"]["recipient_faction_id"] == "alpha"
    assert skip_events[0]["params"]["reason"] == "queue_full"


def test_slice1e_uses_slice1d_enqueue_modifiers_for_context() -> None:
    world = WorldState(
        belief_enqueue_config={
            "delay_mod_by_site_template": {"town_a": 4},
            "confidence_mod_by_site_template": {"town_a": 6},
            "delay_mod_by_region": {"north": 99},
            "confidence_mod_by_region": {"north": 50},
        }
    )
    sim = Simulation(world=world, seed=19)
    sim.register_rule_module(BeliefJobQueueModule())
    _seed_factions(sim, ["source", "alpha", "beta", "gamma"])

    sim.schedule_event_at(
        tick=3,
        event_type=BELIEF_OUTBOUND_CLAIM_AVAILABLE_EVENT_TYPE,
        params=_outbound_params(
            source_faction_id="source",
            confidence=20,
            site_template_id="town_a",
            region_id="north",
        ),
    )
    sim.advance_ticks(4)

    queued = sim.state.world.faction_beliefs["alpha"]["transmission_queue"][0]
    assert queued["created_tick"] == 3
    assert queued["not_before_tick"] == 3 + BASE_TRANSMISSION_DELAY_TICKS + 4
    assert queued["claim"]["confidence"] == 26
