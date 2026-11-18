"""
DARK SHADOW® - Animation Utilities and Easing Functions
Mathematical easing, shockwave ripple tracking, and harmonic oscillation helpers.
"""

import math
import time
from typing import List


def ease_out_cubic(t: float) -> float:
    """Fast cubic deceleration ease."""
    t = max(0.0, min(1.0, t))
    return 1.0 - math.pow(1.0 - t, 3)


def ease_in_out_cubic(t: float) -> float:
    """Smooth cubic acceleration and deceleration."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    else:
        return 1.0 - math.pow(-2.0 * t + 2.0, 3) / 2.0


def ease_out_quad(t: float) -> float:
    """Gentle quadratic deceleration."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_out_elastic(t: float) -> float:
    """Elastic bounce decay."""
    t = max(0.0, min(1.0, t))
    if t == 0.0 or t == 1.0:
        return t
    c4 = (2.0 * math.pi) / 3.0
    return math.pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0


class ShockwaveRipple:
    """
    Represents an expanding circular kinetic shockwave (e.g. from mouse clicks or scroll).
    Particles that intersect the ripple radius experience outward displacement.
    """
    def __init__(self, cx: float, cy: float, max_radius: float = 140.0, speed: float = 240.0,
                 amplitude: float = 16.0, width: float = 28.0):
        self.cx = cx
        self.cy = cy
        self.radius = 4.0
        self.max_radius = max_radius
        self.speed = speed
        self.amplitude = amplitude
        self.width = width
        self.start_time = time.perf_counter()
        self.alive = True

    def update(self, dt: float) -> bool:
        """Advance the ripple radius. Returns True if ripple remains active."""
        self.radius += self.speed * dt
        if self.radius > self.max_radius:
            self.alive = False
        return self.alive

    @property
    def intensity(self) -> float:
        """Normalized remaining intensity (1.0 at inception down to 0.0 at max_radius)."""
        if not self.alive:
            return 0.0
        prog = self.radius / self.max_radius
        return max(0.0, 1.0 - ease_out_cubic(prog))


class RippleManager:
    """Container managing active circular shockwaves."""
    def __init__(self):
        self.ripples: List[ShockwaveRipple] = []

    def spawn(self, cx: float, cy: float, max_radius: float = 150.0, speed: float = 240.0,
              amplitude: float = 18.0, width: float = 30.0):
        """Create a new shockwave."""
        # Limit concurrent ripples to prevent over-displacement
        if len(self.ripples) > 6:
            self.ripples.pop(0)
        self.ripples.append(ShockwaveRipple(cx, cy, max_radius, speed, amplitude, width))

    def update(self, dt: float):
        """Update all ripples and discard faded ones."""
        self.ripples = [r for r in self.ripples if r.update(dt)]

    def clear(self):
        """Reset all active ripples."""
        self.ripples.clear()
