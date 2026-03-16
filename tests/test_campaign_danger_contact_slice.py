from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.campaign_danger import (
    ACCEPT_ENCOUNTER_OFFER_INTENT,
    CAMPAIGN_DANGER_CONTACT_EVENT_TYPE,
    FLEE_ENCOUNTER_OFFER_INTENT,
    CampaignDangerModule,
    DEFAULT_DANGER_ENTITY_ID,
)
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord, SpaceState

MAP_PATH = "content/examples/viewer_map.json"


def _build_sim(seed: int = 77) -> Simulation:
    world = load_world_json(MAP_PATH)
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(LocalEncounterRequestModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(CampaignDangerModule())
    sim.add_entity(EntityState.from_hex(entity_id=DEFAULT_PLAYER_ENTITY_ID, hex_coord=HexCoord(0, 0)))
    return sim


def _events(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_campaign_danger_visible_and_movement_is_deterministic() -> None:
    sim_a = _build_sim(seed=101)
    sim_b = _build_sim(seed=101)

    sim_a.advance_ticks(60)
    sim_b.advance_ticks(60)

    danger_a = sim_a.state.entities[DEFAULT_DANGER_ENTITY_ID]
    danger_b = sim_b.state.entities[DEFAULT_DANGER_ENTITY_ID]
    assert (danger_a.position_x, danger_a.position_y) == (danger_b.position_x, danger_b.position_y)
    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_campaign_contact_triggers_single_handoff_during_overlap() -> None:
    sim = _build_sim(seed=202)

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y

    sim.advance_ticks(30)

    assert len(_events(sim, CAMPAIGN_DANGER_CONTACT_EVENT_TYPE)) == 1
    assert len(_events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 0
    assert len(_events(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE)) == 0
    pending_offer = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID)
    assert isinstance(pending_offer, dict)


def test_campaign_contact_fight_accepts_offer_and_handoffs_once() -> None:
    sim = _build_sim(seed=222)

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
    sim.advance_ticks(3)

    assert len(_events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 1
    assert len(_events(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE)) == 1
    assert sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID) is None


def test_campaign_contact_flee_dismisses_offer_and_prevents_immediate_retrigger() -> None:
    sim = _build_sim(seed=223)

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)
    assert isinstance(sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID), dict)


def test_campaign_offer_state_is_player_scoped_for_command_handling() -> None:
    sim = _build_sim(seed=224)
    sim.add_entity(EntityState(entity_id="hireling", position_x=0.0, position_y=0.0, space_id="overworld"))

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)
    assert isinstance(sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID), dict)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="hireling",
            command_type=FLEE_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": "hireling"},
        )
    )
    sim.advance_ticks(1)

    # Wrong actor should not consume scout's offer.
    assert isinstance(sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID), dict)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type=FLEE_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": DEFAULT_PLAYER_ENTITY_ID},
        )
    )
    sim.advance_ticks(4)

    state = sim.get_rules_state(CampaignDangerModule.name)
    assert state.get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID) is None
    assert len(_events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 0

    # Move out and back into overlap before ignore window expires.
    player.position_x += 5.0
    player.position_y += 5.0
    sim.advance_ticks(1)
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(5)
    assert sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID) is None

    sim.advance_ticks(30)
    # Cooldown elapsed; offer can appear again.
    player.position_x += 5.0
    player.position_y += 5.0
    sim.advance_ticks(1)
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)
    assert isinstance(sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID), dict)


def test_campaign_contact_overlap_state_survives_save_load_without_spam() -> None:
    sim = _build_sim(seed=303)
    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y

    sim.advance_ticks(3)
    assert len(_events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 0

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(CampaignDangerModule())

    loaded.advance_ticks(10)
    assert len(_events(loaded, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 0


def test_campaign_contact_not_emitted_when_player_not_in_campaign_role() -> None:
    sim = _build_sim(seed=404)
    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.space_id = "local_encounter:test"
    sim.state.world.spaces[player.space_id] = SpaceState(
        space_id=player.space_id,
        topology_type="square_grid",
        role="local",
        topology_params={"width": 3, "height": 3, "origin": {"x": 0, "y": 0}},
    )
    player.position_x = danger.position_x
    player.position_y = danger.position_y

    sim.advance_ticks(5)
    assert _events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE) == []


def test_campaign_danger_contact_replay_hash_stability() -> None:
    def _run(seed: int) -> str:
        sim = _build_sim(seed=seed)
        danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
        sim.append_command(
            SimCommand(
                tick=0,
                entity_id=DEFAULT_PLAYER_ENTITY_ID,
                command_type="set_target_position",
                params={"x": danger.position_x, "y": danger.position_y},
            )
        )
        sim.advance_ticks(80)
        payload = sim.simulation_payload()
        loaded = Simulation.from_simulation_payload(payload)
        loaded.register_rule_module(LocalEncounterRequestModule())
        loaded.register_rule_module(LocalEncounterInstanceModule())
        loaded.register_rule_module(CampaignDangerModule())
        loaded.advance_ticks(20)
        return simulation_hash(loaded)

    assert _run(seed=5150) == _run(seed=5150)


def test_campaign_contact_uses_existing_bridge_module_not_direct_local_shortcut() -> None:
    sim = Simulation(world=load_world_json(MAP_PATH), seed=909)
    sim.register_rule_module(CampaignDangerModule())
    sim.add_entity(EntityState.from_hex(entity_id=DEFAULT_PLAYER_ENTITY_ID, hex_coord=HexCoord(0, 0)))

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y

    sim.advance_ticks(10)

    assert len(_events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 0
    assert _events(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE) == []

    sim.register_rule_module(LocalEncounterRequestModule())
    sim.advance_ticks(5)

    # No retroactive conversion of the already-emitted resolve request should occur.
    assert len(_events(sim, ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE)) == 0
    assert _events(sim, LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE) == []


def test_campaign_contact_does_not_create_offer_when_already_in_local_role() -> None:
    sim = _build_sim(seed=9091)
    local_space_id = "local_encounter:test"
    sim.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type="square_grid",
        role="local",
        topology_params={"width": 3, "height": 3, "origin": {"x": 0, "y": 0}},
    )

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    player.space_id = local_space_id
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(4)

    state = sim.get_rules_state(CampaignDangerModule.name)
    assert state.get("pending_offer_by_player", {}).get(DEFAULT_PLAYER_ENTITY_ID) is None
