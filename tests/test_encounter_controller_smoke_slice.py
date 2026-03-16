from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.campaign_danger import (
    ACCEPT_ENCOUNTER_OFFER_INTENT,
    FLEE_ENCOUNTER_OFFER_INTENT,
    CampaignDangerModule,
    DEFAULT_DANGER_ENTITY_ID,
)
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    EncounterCheckModule,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)

MAP_PATH = "content/examples/viewer_map.json"


def _build_sim(*, with_encounter_checks: bool = False, seed: int = 77) -> Simulation:
    sim = Simulation(world=load_world_json(MAP_PATH), seed=seed)
    sim.register_rule_module(LocalEncounterRequestModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(CampaignDangerModule())
    if with_encounter_checks:
        sim.register_rule_module(EncounterCheckModule())
    sim.add_entity(EntityState.from_hex(entity_id=DEFAULT_PLAYER_ENTITY_ID, hex_coord=sim.state.world.hexes.keys().__iter__().__next__()))
    return sim


def _events(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_smoke_dynamic_contact_stays_pending_until_fight_or_flee() -> None:
    sim = _build_sim(seed=901)

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)

    pending = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID)
    assert isinstance(pending, dict)
    assert _events(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE) == []


def test_smoke_static_and_dynamic_sources_share_pending_offer_flow() -> None:
    sim = _build_sim(with_encounter_checks=True, seed=17)
    sim.advance_ticks(250)

    pending = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID)
    assert isinstance(pending, dict)
    assert _events(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE) == []


def test_smoke_flee_clears_offer_resumes_control_and_no_immediate_retrigger() -> None:
    sim = _build_sim(seed=902)

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)

    frozen_x = player.position_x
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type="set_move_vector",
            params={"x": 1.0, "y": 0.0},
        )
    )
    sim.advance_ticks(1)
    assert player.position_x == frozen_x

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type=FLEE_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": DEFAULT_PLAYER_ENTITY_ID},
        )
    )
    sim.advance_ticks(10)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type="set_move_vector",
            params={"x": 1.0, "y": 0.0},
        )
    )
    sim.advance_ticks(1)
    assert player.position_x > frozen_x

    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(4)
    pending = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID)
    assert pending is None


def test_smoke_fight_enters_local_once_without_nested_begin() -> None:
    sim = _build_sim(seed=903)

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": DEFAULT_PLAYER_ENTITY_ID},
        )
    )
    sim.advance_ticks(8)

    begin_events = _events(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    assert len(begin_events) == 1
    sim.advance_ticks(20)
    assert len(_events(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)) == 1
    assert sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID) is None
