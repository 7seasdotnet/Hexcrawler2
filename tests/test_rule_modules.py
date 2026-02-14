from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.rules import RuleModule


class RecordingModule(RuleModule):
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def on_simulation_start(self, sim: Simulation) -> None:
        self.calls.append(f"{self.name}:simulation_start")

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        self.calls.append(f"{self.name}:tick_start:{tick}")

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        self.calls.append(f"{self.name}:tick_end:{tick}")

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        self.calls.append(f"{self.name}:event:{event.event_id}")


class RngCaptureModule(RuleModule):
    def __init__(self, name: str, outputs: list[float]) -> None:
        self.name = name
        self.outputs = outputs

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        self.outputs.append(sim.rng_stream("test").random())



def _build_sim(seed: int) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    return Simulation(world=world, seed=seed)



def test_module_tick_ordering() -> None:
    sim = _build_sim(seed=100)
    calls: list[str] = []

    sim.register_rule_module(RecordingModule(name="A", calls=calls))
    sim.register_rule_module(RecordingModule(name="B", calls=calls))

    sim.advance_ticks(1)

    assert calls == [
        "A:simulation_start",
        "B:simulation_start",
        "A:tick_start:0",
        "B:tick_start:0",
        "A:tick_end:0",
        "B:tick_end:0",
    ]



def test_module_event_hook() -> None:
    sim = _build_sim(seed=101)
    calls: list[str] = []

    sim.register_rule_module(RecordingModule(name="A", calls=calls))
    sim.register_rule_module(RecordingModule(name="B", calls=calls))
    marker_id = sim.schedule_event_at(0, "debug_marker", {"label": "x"})

    sim.advance_ticks(1)

    assert calls == [
        "A:simulation_start",
        "B:simulation_start",
        "A:tick_start:0",
        "B:tick_start:0",
        f"A:event:{marker_id}",
        f"B:event:{marker_id}",
        "A:tick_end:0",
        "B:tick_end:0",
    ]



def test_rng_stream_determinism() -> None:
    outputs_a: list[float] = []
    outputs_b: list[float] = []

    sim_a = _build_sim(seed=202)
    sim_b = _build_sim(seed=202)

    sim_a.register_rule_module(RngCaptureModule(name="rng", outputs=outputs_a))
    sim_b.register_rule_module(RngCaptureModule(name="rng", outputs=outputs_b))

    sim_a.advance_ticks(4)
    sim_b.advance_ticks(4)

    assert outputs_a == outputs_b



def test_duplicate_module_name_rejected() -> None:
    sim = _build_sim(seed=303)

    sim.register_rule_module(RecordingModule(name="dup", calls=[]))

    try:
        sim.register_rule_module(RecordingModule(name="dup", calls=[]))
        assert False, "expected duplicate module name registration to fail"
    except ValueError:
        pass
