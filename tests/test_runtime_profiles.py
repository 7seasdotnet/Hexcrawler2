from pathlib import Path

from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE, EXPERIMENTAL_WORLD, SOAK_AUDIT, module_names_for_profile
from hexcrawler.cli.pygame_viewer import _build_viewer_simulation, _load_viewer_simulation, _save_viewer_simulation


def test_core_playable_profile_excludes_quarantined_modules() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", runtime_profile=CORE_PLAYABLE)

    assert sim.get_rule_module("site_ecology") is None
    assert sim.get_rule_module("rumor_pipeline") is None
    assert sim.get_rule_module("rumor_decay") is None
    assert sim.get_rule_module("rumor_query") is None
    assert sim.get_rule_module("interaction_execution") is None
    assert sim.get_rule_module("signal_propagation") is None


def test_experimental_world_profile_includes_quarantined_modules() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", runtime_profile=EXPERIMENTAL_WORLD)

    assert sim.get_rule_module("site_ecology") is not None
    assert sim.get_rule_module("rumor_pipeline") is not None
    assert sim.get_rule_module("rumor_decay") is not None
    assert sim.get_rule_module("rumor_query") is not None


def test_soak_audit_profile_is_selectable() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", runtime_profile=SOAK_AUDIT)

    for module_name in module_names_for_profile(SOAK_AUDIT):
        assert sim.get_rule_module(module_name) is not None


def test_load_path_registers_core_playable_profile(tmp_path: Path) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", runtime_profile=CORE_PLAYABLE, seed=21)
    save_path = tmp_path / "profile_save.json"
    _save_viewer_simulation(sim, str(save_path))

    loaded = _load_viewer_simulation(str(save_path), runtime_profile=CORE_PLAYABLE)

    assert loaded.get_rule_module("encounter_check") is not None
    assert loaded.get_rule_module("site_ecology") is None


def test_soak_audit_is_distinct_from_experimental_world() -> None:
    soak_modules = set(module_names_for_profile(SOAK_AUDIT))
    experimental_modules = set(module_names_for_profile(EXPERIMENTAL_WORLD))

    assert soak_modules < experimental_modules
    assert "site_ecology" not in soak_modules
    assert "rumor_pipeline" not in soak_modules
    assert "rumor_decay" not in soak_modules
    assert "interaction_execution" not in soak_modules
    assert "signal_propagation" in soak_modules
    assert "rumor_query" in soak_modules
