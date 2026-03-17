from hexcrawler.sim.wounds import movement_multiplier_from_wounds


def test_movement_multiplier_from_wounds_default_and_bounds() -> None:
    assert movement_multiplier_from_wounds([]) == 1.0
    assert movement_multiplier_from_wounds([{"severity": 1}]) == 0.75
    assert movement_multiplier_from_wounds([{"severity": 2}]) == 0.5
    assert movement_multiplier_from_wounds([{"severity": 3}]) == 0.25


def test_movement_multiplier_ignores_invalid_wound_payloads() -> None:
    wounds = [
        {"severity": 1},
        {"severity": -5},
        {"severity": "bad"},
        {},
    ]
    assert movement_multiplier_from_wounds(wounds) == 0.75


def test_movement_multiplier_allows_floor_until_explicit_incapacitation() -> None:
    assert movement_multiplier_from_wounds([{"severity": 2}]) == 0.5
    assert movement_multiplier_from_wounds([{"severity": 3}]) == 0.25
    assert movement_multiplier_from_wounds([{"severity": 4}]) == 0.0
