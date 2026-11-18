"""
DARK SHADOW® - Scroll Interaction Controller
Translates mouse scroll events into circular shockwaves, kinetic spin, and subtle expansions.
"""

from PySide6.QtGui import QWheelEvent
from ..ui.orb import DarkShadowOrb


class ScrollInteractionController:
    """
    Handles mouse scroll gestures over the orb:
    - Generates circular particle ripples expanding outward/inward
    - Imparts rotational momentum to orbital particles
    """

    def __init__(self, orb: DarkShadowOrb):
        self.orb = orb

    def handle_wheel_event(self, event: QWheelEvent) -> bool:
        """Process QWheelEvent."""
        pos = event.position()
        if not self.orb.hit_test(pos.x(), pos.y()):
            return False

        # Extract vertical scroll delta
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()

        if delta != 0:
            self.orb.on_scroll(delta)
            return True

        return False
