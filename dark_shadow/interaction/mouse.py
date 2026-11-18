"""
DARK SHADOW® - Mouse Interaction Controller
Handles cursor hover dynamics, drag-to-reposition, and click-to-activate events.
"""

import time
from typing import Optional, Tuple
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from ..ui.orb import DarkShadowOrb


class MouseInteractionController:
    """
    Manages mouse events over the living orb:
    - Cursor proximity repulsion and magnetic tendrils
    - Drag threshold detection for repositioning
    - Click detection for voice activation
    """

    def __init__(self, orb: DarkShadowOrb, drag_threshold: float = 6.0):
        self.orb = orb
        self.drag_threshold = drag_threshold

        # Drag tracking
        self.is_mouse_down = False
        self.is_dragging = False
        self.press_pos: Optional[QPointF] = None
        self.last_pos: Optional[QPointF] = None
        self.last_time = 0.0

        # Cursor velocity
        self.cursor_velocity = (0.0, 0.0)

    def handle_mouse_press(self, event: QMouseEvent) -> bool:
        """Record press position for click vs drag discrimination."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            # Verify hit inside interactive radius
            if self.orb.hit_test(pos.x(), pos.y()):
                self.is_mouse_down = True
                self.is_dragging = False
                self.press_pos = QPointF(pos)
                self.last_pos = QPointF(pos)
                self.last_time = time.perf_counter()
                return True
        return False

    def handle_mouse_move(self, event: QMouseEvent, update_center_callback=None) -> bool:
        """Handle hover dynamics or active reposition dragging."""
        pos = event.position()
        curr_time = time.perf_counter()
        dt = max(0.001, curr_time - self.last_time) if self.last_time > 0 else 0.016

        # Calculate cursor velocity for fluid physics
        if self.last_pos is not None:
            vx = (pos.x() - self.last_pos.x()) / dt
            vy = (pos.y() - self.last_pos.y()) / dt
            self.cursor_velocity = (vx * 0.2 + self.cursor_velocity[0] * 0.8,
                                    vy * 0.2 + self.cursor_velocity[1] * 0.8)

        self.last_pos = QPointF(pos)
        self.last_time = curr_time

        # If left mouse button is held down: check drag threshold
        if self.is_mouse_down and self.press_pos is not None:
            dx = pos.x() - self.press_pos.x()
            dy = pos.y() - self.press_pos.y()
            dist = (dx * dx + dy * dy) ** 0.5

            if dist > self.drag_threshold:
                self.is_dragging = True

            if self.is_dragging and update_center_callback is not None:
                # Reposition the orb center
                update_center_callback(pos.x(), pos.y())
                return True

        # Forward hover position to orb particles
        self.orb.on_mouse_move(pos.x(), pos.y())
        return self.orb.hit_test(pos.x(), pos.y())

    def handle_mouse_release(self, event: QMouseEvent) -> bool:
        """Differentiate between click and drag termination."""
        if event.button() == Qt.MouseButton.LeftButton:
            was_down = self.is_mouse_down
            was_dragging = self.is_dragging
            pos = event.position()

            self.is_mouse_down = False
            self.is_dragging = False
            self.press_pos = None

            if was_down and not was_dragging:
                # Genuine click detected!
                if self.orb.hit_test(pos.x(), pos.y()):
                    self.orb.on_click(pos.x(), pos.y())
                    return True
        return False

    def handle_mouse_leave(self):
        """Cursor left the window region."""
        self.is_mouse_down = False
        self.is_dragging = False
        self.press_pos = None
        self.orb.on_mouse_leave()
