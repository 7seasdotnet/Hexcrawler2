from __future__ import annotations

GREYBRIDGE_SAFE_HUB_SPACE_ID = "safe_hub:greybridge"

GREYBRIDGE_BLOCKED_CELLS: tuple[tuple[int, int], ...] = (
    # Watch Hall shell (door opening at 8,3).
    (8, 1), (9, 1), (10, 1), (11, 1), (12, 1), (13, 1),
    (8, 2), (13, 2),
    (8, 4), (9, 4), (10, 4), (11, 4), (12, 4), (13, 4),
    # Inn/Infirmary shell (door opening at 8,7).
    (8, 5), (9, 5), (10, 5), (11, 5), (12, 5), (13, 5),
    (8, 6), (13, 6),
    (8, 8), (13, 8),
    (8, 9), (9, 9), (10, 9), (11, 9), (12, 9), (13, 9),
    # Gate walls (openings at 1,5 for campaign exit and 3,5 for interior traversal).
    (0, 4), (1, 4), (2, 4), (3, 4),
    (0, 5),
    (0, 6), (1, 6), (2, 6), (3, 6),
)

GREYBRIDGE_DOOR_CELLS: tuple[tuple[int, int], ...] = ((8, 3), (8, 7), (1, 5), (3, 5))
