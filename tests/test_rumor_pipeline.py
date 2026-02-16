from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, EncounterActionExecutionModule, RumorPipelineModule
from hexcrawler.sim.hash import simulation_hash


def _build_sim(seed: int = 123) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(EncounterActionExecutionModule())
    sim.register_rule_module(RumorPipelineModule())
    return sim


def _enqueue_executed_action(sim: Simulation, *, source_event_id: str, q: int = 0, r: int = 0) -> None:
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
        params={
            "source_event_id": source_event_id,
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": q, "r": r}},
            "actions": [{"action_type": "signal_intent", "template_id": "omens.crows", "params": {}}],
        },
    )


def test_rumor_pipeline_determinism_same_seed_same_inputs() -> None:
    sim_a = _build_sim(seed=808)
    sim_b = _build_sim(seed=808)

    for sim in (sim_a, sim_b):
        _enqueue_executed_action(sim, source_event_id="evt-alpha")
        sim.advance_ticks(220)

    rumors_a = [record["rumor_id"] for record in sim_a.state.world.rumors]
    rumors_b = [record["rumor_id"] for record in sim_b.state.world.rumors]

    assert rumors_a == rumors_b
    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_rumor_pipeline_no_duplicates_across_save_load_resume(tmp_path: Path) -> None:
    sim = _build_sim(seed=909)
    _enqueue_executed_action(sim, source_event_id="evt-alpha")
    sim.advance_ticks(60)

    save_path = tmp_path / "rumors_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.register_rule_module(RumorPipelineModule())
    loaded.advance_ticks(220)

    rumor_ids = [record["rumor_id"] for record in loaded.state.world.rumors]
    assert len(rumor_ids) == len(set(rumor_ids))


def test_rumor_id_stability_independent_of_platform_order() -> None:
    sim = _build_sim(seed=1)
    module = sim.get_rule_module(RumorPipelineModule.name)
    assert isinstance(module, RumorPipelineModule)

    identities = [
        "base:evt-source:0",
        "base:evt-source:1",
        "prop:rumor-a:1:0:1",
        "prop:rumor-b:2:-1:0",
    ]
    first = [module._rumor_id_for_identity(identity) for identity in identities]
    second = [module._rumor_id_for_identity(identity) for identity in reversed(list(identities))]
    assert first == list(reversed(second))
