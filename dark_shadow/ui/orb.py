"""
DARK SHADOW® - Orb Controller and State Machine
Orchestrates the living visual orb entity, state transitions, hit-testing, and event hooks.
"""

import math
from typing import Optional, Tuple
from PySide6.QtCore import QObject, Signal, QPointF
from PySide6.QtGui import QPainter

from ..config import AppConfig, OrbState
from .particles import ParticleSystem


class DarkShadowOrb(QObject):
    """
    The living, interactive AI orb.
    Coordinates particle physics, state transitions, and user interactions.
    """
    # Signals
    state_changed = Signal(OrbState)
    activated = Signal()
    deactivated = Signal()
    clicked = Signal()
    listening_requested = Signal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.particles = ParticleSystem(config.visual, config.physics)

        # Internal state
        self._state = OrbState.IDLE
        self._is_dragged = False
        self._drag_start_pos: Optional[QPointF] = None

    @property
    def state(self) -> OrbState:
        return self._state

    def set_center(self, cx: float, cy: float):
        """Set screen/window anchor coordinates."""
        self.particles.set_center(cx, cy)

    def set_screen_bottom(self, bottom_y: float):
        """Set vertical coordinate for upward bottom emergence."""
        self.particles.set_screen_bottom(bottom_y)

    def activate(self):
        """Begin appearance animation: emerge from bottom and assemble into orb."""
        if self._state == OrbState.ACTIVATING:
            return
        self.set_state(OrbState.ACTIVATING)
        self.activated.emit()

    def deactivate(self):
        """Begin dissolving/falling exit animation into desktop."""
        if self._state in (OrbState.DEACTIVATING, OrbState.IDLE):
            return
        self.set_state(OrbState.DEACTIVATING)

    def set_state(self, new_state: OrbState):
        """Transition state machine."""
        if self._state == new_state:
            return

        self._state = new_state
        self.particles.set_state(new_state)
        self.state_changed.emit(new_state)

        if new_state == OrbState.IDLE:
            self.deactivated.emit()

    def on_click(self, local_x: float, local_y: float):
        """Trigger click shockwave ripple and listening state."""
        self.particles.trigger_click_shockwave(local_x, local_y)
        self.clicked.emit()

        # If orb is in normal interacting state, clicking activates listening
        if self._state in (OrbState.INTERACTING, OrbState.IDLE):
            if self._state == OrbState.IDLE:
                self.activate()
            else:
                self.set_state(OrbState.LISTENING)
                self.listening_requested.emit()
        elif self._state == OrbState.LISTENING:
            # Clicking while listening toggles back to interacting/thinking
            self.set_state(OrbState.INTERACTING)

    def on_scroll(self, delta: int):
        """Handle scroll wheel ripples."""
        self.particles.trigger_scroll_ripple(delta)

    def on_mouse_move(self, mx: float, my: float):
        """Update cursor position for particle repulsion and tendrils."""
        self.particles.mouse_pos = (mx, my)

    def on_mouse_leave(self):
        """Clear cursor proximity."""
        self.particles.mouse_pos = None

    def set_audio_amplitude(self, amplitude: float):
        """Forward real-time voice amplitude to particles."""
        self.particles.set_audio_amplitude(amplitude)

    def hit_test(self, px: float, py: float) -> bool:
        """
        Check if point (px, py) is within the interactive radius of the orb.
        Allows click-through transparency for everything outside this zone!
        """
        if self._state == OrbState.IDLE:
            return False

        cx = self.particles.center_x + self.particles.floating_offset_x
        cy = self.particles.center_y + self.particles.floating_offset_y

        dx = px - cx
        dy = py - cy
        dist = math.sqrt(dx * dx + dy * dy)

        # Interactive radius includes base radius + margin for outer aura & mouse field
        interactive_radius = self.particles.current_radius * 1.55
        return dist <= interactive_radius

    def update(self, dt: float):
        """Physics clock tick."""
        self.particles.update(dt)

        # Check if particle system finished activating or deactivating
        if self._state != self.particles.state:
            self._state = self.particles.state
            self.state_changed.emit(self._state)
            if self._state == OrbState.IDLE:
                self.deactivated.emit()

    def render(self, painter: QPainter):
        """Draw the living orb."""
        self.particles.render(painter)
