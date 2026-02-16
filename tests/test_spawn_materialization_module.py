from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import SpawnMaterializationModule
from hexcrawler.sim.hash import simulation_hash


def _spawn_descriptor(*, action_uid: str, quantity: int, q: int, r: int, template_id: str = "bandit_scouts") -> dict[str, object]:
    return {
        "created_tick": 0,
        "location": {"topology_type": "overworld_hex", "coord": {"q": q, "r": r}},
        "template_id": template_id,
        "quantity": quantity,
        "expires_tick": None,
        "source_event_id": "evt-source",
        "action_uid": action_uid,
        "params": {},
    }


def _build_materialization_sim(seed: int = 123) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(SpawnMaterializationModule())
    return sim


def _spawn_entity_ids(sim: Simulation) -> list[str]:
    return sorted(entity_id for entity_id in sim.state.entities if entity_id.startswith("spawn:"))


def test_materialization_creates_expected_entities_with_deterministic_ids() -> None:
    sim = _build_materialization_sim()
    sim.state.world.append_spawn_descriptor(_spawn_descriptor(action_uid="evt-spawn:0", quantity=2, q=2, r=-1))

    sim.advance_ticks(1)

    assert _spawn_entity_ids(sim) == ["spawn:evt-spawn:0:0", "spawn:evt-spawn:0:1"]
    assert sim.state.entities["spawn:evt-spawn:0:0"].hex_coord.to_dict() == {"q": 2, "r": -1}
    assert sim.state.entities["spawn:evt-spawn:0:0"].template_id == "bandit_scouts"
    assert sim.state.entities["spawn:evt-spawn:0:0"].source_action_uid == "evt-spawn:0"


def test_materialization_is_idempotent_when_re_run() -> None:
    sim = _build_materialization_sim()
    sim.state.world.append_spawn_descriptor(_spawn_descriptor(action_uid="evt-spawn:0", quantity=2, q=0, r=0))

    sim.advance_ticks(1)
    first_ids = _spawn_entity_ids(sim)
    sim.advance_ticks(3)

    assert _spawn_entity_ids(sim) == first_ids
    assert len(first_ids) == 2


def test_materialization_save_load_round_trip_preserves_entities_and_linkage(tmp_path: Path) -> None:
    sim = _build_materialization_sim(seed=999)
    sim.state.world.append_spawn_descriptor(_spawn_descriptor(action_uid="evt-spawn:0", quantity=2, q=1, r=1))
    sim.advance_ticks(2)

    save_path = tmp_path / "spawn_materialization_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)

    assert _spawn_entity_ids(loaded) == _spawn_entity_ids(sim)
    assert loaded.state.entities["spawn:evt-spawn:0:0"].hex_coord == sim.state.entities["spawn:evt-spawn:0:0"].hex_coord
    assert loaded.state.entities["spawn:evt-spawn:0:0"].template_id == "bandit_scouts"
    assert loaded.state.entities["spawn:evt-spawn:0:0"].source_action_uid == "evt-spawn:0"


def test_materialization_replay_stability_keeps_hash_and_spawn_ids_identical() -> None:
    sim_a = _build_materialization_sim(seed=2024)
    sim_b = _build_materialization_sim(seed=2024)

    descriptor = _spawn_descriptor(action_uid="evt-spawn:0", quantity=2, q=-2, r=3, template_id="wolf_pack")
    sim_a.state.world.append_spawn_descriptor(descriptor)
    sim_b.state.world.append_spawn_descriptor(descriptor)

    sim_a.advance_ticks(5)
    sim_b.advance_ticks(5)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert _spawn_entity_ids(sim_a) == _spawn_entity_ids(sim_b)
