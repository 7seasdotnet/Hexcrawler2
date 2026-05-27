# HOTPATH_NOTES

Viewer/runtime hot spots observed:
1. Campaign world draw scans all hexes each frame (`_draw_world`).
2. Entity draw scans all entities in current space each frame (`_draw_frame_layers`).
3. Debug panel avoids full rebuild via existing cache (`build_debug_panel_render_cache`).

Recommendation for next narrow pass:
- Add viewport-cell helper for campaign hex draw so `_draw_world` skips out-of-view hexes.
