from pathlib import Path

import pytest

from hexcrawler.content.encounters import (
    DEFAULT_ENCOUNTER_TABLE_PATH,
    load_encounter_table_json,
    validate_encounter_table_payload,
)
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    ENCOUNTER_SELECTION_STUB_EVENT_TYPE,
    EncounterSelectionModule,
)
from hexcrawler.sim.hash import simulation_hash


def _resolve_request_params() -> dict[str, object]:
    return {
        "tick": 0,
        "context": "global",
        "trigger": "idle",
        "location": {"topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        "roll": 40,
        "category": "hostile",
    }


def _build_selection_sim(seed: int = 91) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(EncounterSelectionModule(load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)))
    return sim


def test_encounter_table_schema_validation_example_and_invalid_payload() -> None:
    table = load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)
    assert table.table_id == "basic_encounters"
    assert [entry.entry_id for entry in table.entries] == [
        "scavenger_patrol",
        "ominous_sign",
        "wayfarer_meeting",
    ]

    with pytest.raises(ValueError, match="weight >= 1"):
        validate_encounter_table_payload(
            {
                "schema_version": 1,
                "table_id": "broken",
                "entries": [
                    {
                        "entry_id": "bad_entry",
                        "weight": 0,
                        "payload": {"x": 1},
                    }
                ],
            }
        )


def test_selection_stub_emitted_once_and_passthrough_fields_stable() -> None:
    sim = _build_selection_sim(seed=17)
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params=_resolve_request_params(),
    )

    sim.advance_ticks(2)
    selection_entries = [
        entry for entry in sim.get_event_trace() if entry["event_type"] == ENCOUNTER_SELECTION_STUB_EVENT_TYPE
    ]

    assert len(selection_entries) == 1
    stub_params = selection_entries[0]["params"]
    assert stub_params["tick"] == 0
    assert stub_params["context"] == "global"
    assert stub_params["trigger"] == "idle"
    assert stub_params["location"] == {"topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}}
    assert stub_params["roll"] == 40
    assert stub_params["category"] == "hostile"
    assert stub_params["table_id"] == "basic_encounters"
    assert stub_params["entry_id"] == "ominous_sign"
    assert stub_params["entry_tags"] == ["environment", "omen"]
    assert stub_params["entry_payload"] == {
        "notes": "Descriptive only in 4H",
        "template": "ominous_sign",
    }


def test_selection_determinism_save_load_continuation_and_hash_identity(tmp_path: Path) -> None:
    contiguous = _build_selection_sim(seed=42)
    contiguous.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params=_resolve_request_params(),
    )
    contiguous.schedule_event_at(
        tick=8,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params={**_resolve_request_params(), "tick": 8, "roll": 75, "category": "neutral"},
    )
    contiguous.advance_ticks(20)

    split = _build_selection_sim(seed=42)
    split.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params=_resolve_request_params(),
    )
    split.schedule_event_at(
        tick=8,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params={**_resolve_request_params(), "tick": 8, "roll": 75, "category": "neutral"},
    )
    split.advance_ticks(5)

    save_path = tmp_path / "selection_save.json"
    save_game_json(save_path, split.state.world, split)
    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(EncounterSelectionModule(load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)))
    loaded.advance_ticks(15)

    assert simulation_hash(contiguous) == simulation_hash(loaded)


def test_selection_determinism_replay_hash_identity() -> None:
    sim_a = _build_selection_sim(seed=999)
    sim_b = _build_selection_sim(seed=999)

    for sim in (sim_a, sim_b):
        sim.schedule_event_at(
            tick=0,
            event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
            params=_resolve_request_params(),
        )
        sim.schedule_event_at(
            tick=2,
            event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
            params={**_resolve_request_params(), "tick": 2, "roll": 88, "category": "omen"},
        )

    sim_a.advance_ticks(12)
    sim_b.advance_ticks(12)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_selection_contract_regression_hash_is_stable() -> None:
    sim = _build_selection_sim(seed=17)
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params=_resolve_request_params(),
    )
    sim.schedule_event_at(
        tick=2,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params={**_resolve_request_params(), "tick": 2, "roll": 88, "category": "omen"},
    )

    sim.advance_ticks(12)

    assert (
        simulation_hash(sim)
        == "fdf586eedfc8cdc61e4d38eedecd3cf0db41c68152257cba149f69181ab5af8b"
    )
