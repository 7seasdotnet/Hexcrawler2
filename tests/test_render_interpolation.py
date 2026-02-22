from hexcrawler.cli.pygame_viewer import (
    RenderEntitySnapshot,
    clamp01,
    extract_render_snapshot,
    interpolate_entity_position,
    lerp,
    _clamp_scroll_offset,
    _get_return_context_for_space,
    _section_entries,
    _truncate_text_to_pixel_width,
    _truncate_label,
)
from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.encounters import LocalEncounterInstanceModule
from hexcrawler.sim.world import HexCoord


def test_clamp01_and_lerp() -> None:
    assert clamp01(-0.5) == 0.0
    assert clamp01(0.25) == 0.25
    assert clamp01(1.5) == 1.0
    assert lerp(2.0, 10.0, 0.25) == 4.0


def test_extract_render_snapshot_is_immutable_copy_of_positions() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=3)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))

    snapshot = extract_render_snapshot(sim)
    assert snapshot["runner"].x == 0.0
    assert snapshot["runner"].y == 0.0

    sim.set_entity_move_vector("runner", 1.0, 0.0)
    sim.advance_ticks(1)

    # Existing snapshots must not be mutated by later simulation ticks.
    assert snapshot["runner"].x == 0.0
    assert snapshot["runner"].y == 0.0


def test_interpolate_entity_position_missing_entity_cases() -> None:
    prev_snapshot = {"runner": RenderEntitySnapshot(x=0.0, y=0.0)}
    curr_snapshot = {"runner": RenderEntitySnapshot(x=1.0, y=1.0)}

    assert interpolate_entity_position(prev_snapshot, curr_snapshot, "runner", 0.5) == (0.5, 0.5)
    assert interpolate_entity_position({}, curr_snapshot, "runner", 0.5) == (1.0, 1.0)
    assert interpolate_entity_position(prev_snapshot, {}, "runner", 0.5) == (0.0, 0.0)
    assert interpolate_entity_position({}, {}, "runner", 0.5) is None


def test_truncate_label_is_deterministic_and_bounded() -> None:
    assert _truncate_label("  watchtower  ", max_length=8) == "watchto…"
    assert _truncate_label("sig", max_length=8) == "sig"
    assert _truncate_label("", max_length=8) == "?"


def test_section_entries_newest_first_with_cap() -> None:
    rows = [f"row-{idx}" for idx in range(40)]
    selected = _section_entries(rows)

    assert len(selected) == 30
    assert selected[0] == "row-39"
    assert selected[-1] == "row-10"


def test_clamp_scroll_offset_clamps_to_page_bounds() -> None:
    assert _clamp_scroll_offset(current=0, delta=-1, total_count=8, page_size=6) == 0
    assert _clamp_scroll_offset(current=0, delta=1, total_count=8, page_size=6) == 1
    assert _clamp_scroll_offset(current=1, delta=10, total_count=8, page_size=6) == 2


def test_get_return_context_for_space_reads_serialized_rules_state() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=9)
    sim.set_rules_state(
        LocalEncounterInstanceModule.name,
        {
            "active_by_local_space": {
                "local_encounter:test": {
                    "from_space_id": "overworld",
                    "request_event_id": "evt-1",
                    "from_location": {"topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                }
            }
        },
    )

    context = _get_return_context_for_space(sim, "local_encounter:test")

    assert context is not None
    assert context["from_space_id"] == "overworld"
    assert _get_return_context_for_space(sim, "local_encounter:missing") is None


class _StubFont:
    def size(self, text: str) -> tuple[int, int]:
        return (len(text) * 7, 10)


def test_truncate_text_to_pixel_width_is_deterministic() -> None:
    font = _StubFont()
    assert _truncate_text_to_pixel_width("abcdefghijk", font, max_width=49) == "abcd..."
    assert _truncate_text_to_pixel_width(" short ", font, max_width=70) == "short"
    assert _truncate_text_to_pixel_width("", font, max_width=70) == "?"
