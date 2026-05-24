from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

pygame: Any

@dataclass(frozen=True)
class Palette:
    bg: tuple[int, int, int] = (20, 18, 16)
    parchment: tuple[int, int, int] = (52, 46, 40)
    iron: tuple[int, int, int] = (86, 90, 98)
    bone: tuple[int, int, int] = (218, 208, 186)
    blood: tuple[int, int, int] = (164, 44, 46)
    moss: tuple[int, int, int] = (74, 96, 70)
    safe: tuple[int, int, int] = (132, 182, 156)
    hostile: tuple[int, int, int] = (205, 76, 72)

PALETTE = Palette()


def bind(pg: Any) -> None:
    global pygame
    pygame = pg


def draw_panel(surface: Any, rect: Any, title: str, font: Any) -> Any:
    pygame.draw.rect(surface, PALETTE.parchment, rect, border_radius=8)
    pygame.draw.rect(surface, PALETTE.iron, rect, 2, border_radius=8)
    if title:
        txt = font.render(title, True, PALETTE.bone)
        surface.blit(txt, (rect.x + 10, rect.y + 8))
    return pygame.Rect(rect.x + 10, rect.y + 30, rect.width - 20, rect.height - 40)


def draw_vignette(surface: Any, rect: Any, intensity: float) -> None:
    alpha = max(0, min(160, int(160 * intensity)))
    if alpha <= 0:
        return
    overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    cx, cy = rect.width / 2.0, rect.height / 2.0
    max_d = math.hypot(cx, cy)
    for r in range(int(max_d), 0, -30):
        a = int(alpha * (1.0 - (r / max_d)))
        pygame.draw.circle(overlay, (0, 0, 0, a), (int(cx), int(cy)), r, width=30)
    surface.blit(overlay, (rect.x, rect.y))
