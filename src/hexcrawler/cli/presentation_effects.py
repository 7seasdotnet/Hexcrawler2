from __future__ import annotations

import math
from dataclasses import dataclass, field

@dataclass
class PulseRing:
    x: int
    y: int
    color: tuple[int,int,int]
    age: float = 0.0
    ttl: float = 0.55

@dataclass
class PresentationEffects:
    pulse_rings: list[PulseRing] = field(default_factory=list)

    def add_pulse(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if len(self.pulse_rings) >= 24:
            self.pulse_rings = self.pulse_rings[-23:]
        self.pulse_rings.append(PulseRing(x=x, y=y, color=color))

    def step(self, dt: float) -> None:
        keep=[]
        for ring in self.pulse_rings:
            ring.age += max(0.0, dt)
            if ring.age <= ring.ttl:
                keep.append(ring)
        self.pulse_rings = keep

    def draw(self, pygame, screen) -> None:
        for ring in self.pulse_rings:
            t = ring.age / max(0.001, ring.ttl)
            radius = int(10 + t * 34)
            alpha = max(0, int(180 * (1.0 - t)))
            if alpha <= 0:
                continue
            surf = pygame.Surface((radius*2+4, radius*2+4), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*ring.color, alpha), (radius+2, radius+2), radius, width=2)
            screen.blit(surf, (ring.x-radius-2, ring.y-radius-2))

def pulse_intensity(tick: int, period: float = 42.0) -> float:
    return 0.5 + 0.5 * math.sin((tick / period) * math.tau)
