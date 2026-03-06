from __future__ import annotations

from hexcrawler.cli.pygame_viewer import (
    PLAYER_ID,
    DebugPanelRenderCache,
    EncounterPanelScrollState,
    RumorPanelState,
    SimulationController,
    _clamp_scroll_offset,
    _compute_viewer_layout,
    _scroll_page_size,
    _wrap_text_to_pixel_width,
    _build_viewer_simulation,
    _ensure_pygame_imported,
    build_debug_panel_render_cache,
    compute_interpolation_alpha,
)


class StubFont:
    def size(self, text: str) -> tuple[int, int]:
        return (len(text) * 8, 16)


def _overlaps(a: object, b: object) -> bool:
    return not (
        a.right <= b.left
        or b.right <= a.left
        or a.bottom <= b.top
        or b.bottom <= a.top
    )


def test_layout_geometry_regions_do_not_overlap() -> None:
    _ensure_pygame_imported()
    layout = _compute_viewer_layout((1440, 900))

    assert layout.control_bar.width == 1440
    assert not _overlaps(layout.world_view, layout.inspector_panel)
    assert not _overlaps(layout.world_view, layout.debug_panel)
    assert not _overlaps(layout.inspector_panel, layout.debug_panel)
    assert layout.world_view.width > 0
    assert layout.world_view.height > 0


def test_layout_recomputes_for_multiple_window_sizes() -> None:
    _ensure_pygame_imported()
    large = _compute_viewer_layout((1600, 1000))
    compact = _compute_viewer_layout((1100, 760))

    for layout in (large, compact):
        for rect in (layout.control_bar, layout.world_view, layout.inspector_panel, layout.debug_panel):
            assert rect.width >= 1
            assert rect.height >= 1
            assert rect.left >= 0
            assert rect.top >= 0
            assert rect.right <= layout.window[0]
            assert rect.bottom <= layout.window[1]

    assert compact.world_view.width < large.world_view.width
    assert compact.inspector_panel.height < large.inspector_panel.height


def test_wrapped_text_respects_width_boundaries() -> None:
    font = StubFont()
    lines = _wrap_text_to_pixel_width("alpha beta gamma deltalongtoken", font, 64)

    assert lines
    assert all(font.size(line)[0] <= 64 for line in lines)


def test_scroll_states_are_independent() -> None:
    scroll = EncounterPanelScrollState()
    scroll.scroll("encounters", delta=3, total_count=20, page_size=5)
    scroll.scroll("rumors", delta=1, total_count=10, page_size=4)

    assert scroll.offset_for("encounters") == 3
    assert scroll.offset_for("rumors") == 1
    assert scroll.offset_for("supplies") == 0


def test_scroll_page_size_and_clamp_are_bounded() -> None:
    _ensure_pygame_imported()
    layout = _compute_viewer_layout((1280, 800))
    page = _scroll_page_size(layout.debug_panel)

    assert page >= 1
    assert _clamp_scroll_offset(0, 999, total_count=8, page_size=page) <= max(0, 8 - page)


def test_control_adapter_still_advances_tick_after_layout_refactor() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    tick_before = sim.state.tick
    controller.tick_once()

    assert sim.state.tick == tick_before + 1


def test_compute_interpolation_alpha_is_clamped_and_stable() -> None:
    assert compute_interpolation_alpha(elapsed_seconds=-1.0, tick_duration_seconds=0.1) == 0.0
    assert compute_interpolation_alpha(elapsed_seconds=0.05, tick_duration_seconds=0.1) == 0.5
    assert compute_interpolation_alpha(elapsed_seconds=0.2, tick_duration_seconds=0.1) == 1.0


def test_debug_panel_render_cache_reuses_rows_when_inputs_unchanged() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    rumor_state = RumorPanelState()
    cache = DebugPanelRenderCache()

    rows_first = build_debug_panel_render_cache(sim, rumor_state, cache)
    rows_second = build_debug_panel_render_cache(sim, rumor_state, cache)

    assert rows_first is rows_second

    sim.advance_ticks(1)
    rows_third = build_debug_panel_render_cache(sim, rumor_state, cache)
    assert rows_third is not rows_second
