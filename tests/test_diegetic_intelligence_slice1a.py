from __future__ import annotations

from hexcrawler.sim.beliefs import (
    BELIEF_CLAIM_EMITTED_EVENT_TYPE,
    MAX_BELIEF_RECORDS_PER_FACTION,
    BeliefClaimIngestionModule,
    compute_belief_id,
    normalize_faction_belief_state,
    upsert_player_claim_belief,
)
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import WorldState


def test_slice1a_world_defaults_omit_beliefs_and_hash_stable() -> None:
    world = WorldState()
    payload = world.to_dict()

    assert "faction_beliefs" not in payload

    loaded = WorldState.from_dict(payload)
    assert loaded.to_dict() == payload
    assert world_hash(loaded) == world_hash(world)


def test_slice1a_world_with_belief_serializes_and_changes_hash() -> None:
    world_default = WorldState()
    world_with_belief = WorldState()
    upsert_player_claim_belief(
        faction_beliefs=world_with_belief.faction_beliefs,
        faction_id="wolves",
        claim_key="violence",
        confidence_delta=20,
        tick=5,
        evidence_increment=1,
    )

    payload = world_with_belief.to_dict()
    assert "faction_beliefs" in payload

    loaded = WorldState.from_dict(payload)
    assert loaded.to_dict() == payload
    assert world_hash(loaded) == world_hash(world_with_belief)
    assert world_hash(world_with_belief) != world_hash(world_default)


def test_slice1a_belief_id_is_deterministic_and_distinguishes_inputs() -> None:
    subject = {"kind": "player", "id": "player"}
    belief_a1 = compute_belief_id(faction_id="wolves", subject=subject, claim_key="violence")
    belief_a2 = compute_belief_id(faction_id="wolves", subject=subject, claim_key="violence")
    belief_b = compute_belief_id(faction_id="wolves", subject=subject, claim_key="aid")
    belief_c = compute_belief_id(faction_id="hawks", subject=subject, claim_key="violence")

    assert belief_a1 == belief_a2
    assert belief_a1 != belief_b
    assert belief_a1 != belief_c


def test_slice1a_deterministic_bounded_eviction_tie_breaks_by_belief_id() -> None:
    records: dict[str, dict[str, object]] = {}
    total = MAX_BELIEF_RECORDS_PER_FACTION + 2
    for index in range(total):
        belief_id = f"belief:{index:04d}"
        records[belief_id] = {
            "belief_id": belief_id,
            "subject": {"kind": "player", "id": "player"},
            "claim_key": f"claim_{index}",
            "confidence": 10,
            "first_seen_tick": 2,
            "last_updated_tick": 7,
            "evidence_count": 1,
        }

    normalized = normalize_faction_belief_state({"belief_records": records})
    remaining = sorted(normalized["belief_records"])

    assert len(remaining) == MAX_BELIEF_RECORDS_PER_FACTION
    assert "belief:0000" not in normalized["belief_records"]
    assert "belief:0001" not in normalized["belief_records"]
    assert remaining[0] == "belief:0002"


def test_slice1a_player_only_claim_ingestion_merges_deterministically_and_is_hash_stable() -> None:
    sim_a = Simulation(world=WorldState(), seed=12)
    sim_b = Simulation(world=WorldState(), seed=12)
    sim_a.register_rule_module(BeliefClaimIngestionModule())
    sim_b.register_rule_module(BeliefClaimIngestionModule())

    for sim in (sim_a, sim_b):
        sim.schedule_event_at(
            tick=1,
            event_type=BELIEF_CLAIM_EMITTED_EVENT_TYPE,
            params={"faction_id": "wolves", "claim_key": "violence", "confidence_delta": 15, "evidence_increment": 1},
        )
        sim.schedule_event_at(
            tick=3,
            event_type=BELIEF_CLAIM_EMITTED_EVENT_TYPE,
            params={"faction_id": "wolves", "claim_key": "violence", "confidence_delta": 40, "evidence_increment": 1},
        )
        sim.advance_ticks(5)

    beliefs = sim_a.state.world.faction_beliefs["wolves"]["belief_records"]
    assert len(beliefs) == 1
    record = next(iter(beliefs.values()))
    assert record["first_seen_tick"] == 1
    assert record["last_updated_tick"] == 3
    assert record["evidence_count"] == 2
    assert record["confidence"] == 55

    assert simulation_hash(sim_a) == simulation_hash(sim_b)

    loaded = Simulation.from_simulation_payload(sim_a.simulation_payload())
    loaded.register_rule_module(BeliefClaimIngestionModule())
    assert simulation_hash(loaded) == simulation_hash(sim_a)


def test_slice1a_claim_key_canonicalization_is_stable() -> None:
    subject = {"kind": "player", "id": "player"}
    raw_a = compute_belief_id(faction_id="wolves", subject=subject, claim_key="  violence  ")
    raw_b = compute_belief_id(faction_id="wolves", subject=subject, claim_key="violence")
    assert raw_a == raw_b


def test_slice1a_ingestion_mutates_only_via_event_pipeline() -> None:
    sim = Simulation(world=WorldState(), seed=33)
    sim.register_rule_module(BeliefClaimIngestionModule())

    # No event yet: world remains unchanged.
    before_hash = world_hash(sim.state.world)
    sim.advance_ticks(1)
    assert world_hash(sim.state.world) == before_hash

    # Scheduling event through Simulation queue is the only mutation path for this slice.
    sim.schedule_event_at(
        tick=2,
        event_type=BELIEF_CLAIM_EMITTED_EVENT_TYPE,
        params={"faction_id": "wolves", "claim_key": "  violence  ", "confidence_delta": 10, "evidence_increment": 1},
    )
    sim.advance_ticks(3)

    beliefs = sim.state.world.faction_beliefs["wolves"]["belief_records"]
    assert len(beliefs) == 1
    record = next(iter(beliefs.values()))
    assert record["claim_key"] == "violence"
    assert record["confidence"] == 10
