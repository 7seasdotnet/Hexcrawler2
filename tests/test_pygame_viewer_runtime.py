from hexcrawler.cli.pygame_viewer import _drain_sim_accumulator


def test_drain_sim_accumulator_handles_invalid_values() -> None:
    remaining, ticks = _drain_sim_accumulator(float('nan'), 0.1, paused=False)
    assert remaining == 0.0
    assert ticks == 0


def test_drain_sim_accumulator_running_batches_ticks() -> None:
    remaining, ticks = _drain_sim_accumulator(0.45, 0.1, paused=False)
    assert ticks == 4
    assert 0.049 <= remaining <= 0.051
