"""
DARK SHADOW® - Transparent Frameless Windows 11 Desktop Overlay
Renders the living particle orb, manages window masking for click-through pass-through,
handles high-DPI scaling, system tray integration, and mouse/scroll/keyboard dispatch.
"""

import sys
import time
from typing import Optional
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, Signal
from PySide6.QtGui import (
    QPainter, QColor, QRegion, QIcon, QPixmap,
    QMouseEvent, QWheelEvent, QKeyEvent, QAction
)
from PySide6.QtWidgets import (
    QWidget, QApplication, QSystemTrayIcon, QMenu
)

from ..config import AppConfig, OrbState
from .orb import DarkShadowOrb
from ..interaction.mouse import MouseInteractionController
from ..interaction.scroll import ScrollInteractionController
from ..interaction.keyboard import KeyboardController, WindowsGlobalHotkey


class DarkShadowOverlay(QWidget):
    """
    Transparent, frameless, always-on-top desktop overlay.
    Employs dynamic region masking so desktop clicks pass through outside the orb.
    """
    # Signals
    request_toggle_listen = Signal()
    request_toggle_activate = Signal()
    quit_requested = Signal()

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

        # Configure transparent frameless window attributes (No stays-on-top so it stays in background when other apps open)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        # Initialize Orb Entity
        self.orb = DarkShadowOrb(config, self)

        # Interaction Controllers
        self.mouse_ctrl = MouseInteractionController(self.orb)
        self.scroll_ctrl = ScrollInteractionController(self.orb)
        self.key_ctrl = KeyboardController(
            on_toggle_activation=self.toggle_activation,
            on_toggle_listening=self.toggle_listening
        )

        # Global Hotkey Manager
        self.global_hotkey = WindowsGlobalHotkey(parent=self)
        self.global_hotkey.activated.connect(self.toggle_activation)

        # Setup screen geometry
        self._setup_screen_geometry()

        # System tray icon
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._init_system_tray()

        # Animation timing
        self.last_frame_time = time.perf_counter()
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(self.config.visual.frame_interval_ms)
        self.anim_timer.timeout.connect(self._on_animation_frame)

        # Wire orb signals
        self.orb.activated.connect(self._on_orb_activated)
        self.orb.deactivated.connect(self._on_orb_deactivated)
        self.orb.state_changed.connect(self._on_orb_state_changed)
        self.orb.listening_requested.connect(self.request_toggle_listen.emit)

    def _setup_screen_geometry(self):
        """Fit overlay to primary screen resolution and initialize orb center."""
        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        self.setGeometry(geo)

        # Default orb resting position: upper-center or upper-right desktop area
        # Floating gracefully at ~65% width and 35% height
        default_cx = float(geo.width() * 0.70)
        default_cy = float(geo.height() * 0.38)
        self.orb.set_center(default_cx, default_cy)
        self.orb.set_screen_bottom(float(geo.height()))

    def _init_system_tray(self):
        """Build futuristic system tray icon with control menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray_pixmap = self._generate_tray_icon()
        self.tray_icon = QSystemTrayIcon(QIcon(tray_pixmap), self)
        self.tray_icon.setToolTip("DARK SHADOW® - Minimal Living AI")

        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #0F172A;
                color: #E2E8F0;
                border: 1px solid #38BDF8;
                border-radius: 6px;
                padding: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1E293B;
                color: #38BDF8;
            }
        """)

        title_action = QAction("DARK SHADOW® [Ready]", self)
        title_action.setEnabled(False)
        self.action_title = title_action
        tray_menu.addAction(title_action)
        tray_menu.addSeparator()

        self.action_toggle = QAction("Activate / Deactivate (Ctrl+Shift+D)", self)
        self.action_toggle.triggered.connect(self.toggle_activation)
        tray_menu.addAction(self.action_toggle)

        self.action_listen = QAction("Listen / Speak", self)
        self.action_listen.triggered.connect(self.toggle_listening)
        tray_menu.addAction(self.action_listen)

        reset_pos_action = QAction("Reset Position", self)
        reset_pos_action.triggered.connect(self.reset_orb_position)
        tray_menu.addAction(reset_pos_action)

        tray_menu.addSeparator()
        quit_action = QAction("Exit DARK SHADOW", self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _generate_tray_icon(self) -> QPixmap:
        """Draw minimal glowing cyan orb icon for system tray."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer soft glow
        painter.setBrush(QColor(56, 189, 248, 60))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)

        # Mid ring
        painter.setBrush(QColor(34, 211, 238, 160))
        painter.drawEllipse(6, 6, 20, 20)

        # Radiant core
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawEllipse(11, 11, 10, 10)

        painter.end()
        return pixmap

    def start(self):
        """Start animation loop and register global hotkeys."""
        self.last_frame_time = time.perf_counter()
        self.anim_timer.start()
        self.global_hotkey.start()
        self.update_window_mask()

    def stop(self):
        """Cleanup on shutdown."""
        self.anim_timer.stop()
        self.global_hotkey.stop()
        if self.tray_icon:
            self.tray_icon.hide()

    def activate_orb(self):
        """Launch the emergence and assembly animation."""
        if self.orb.state == OrbState.IDLE or not self.isVisible():
            self.show()
        self.orb.activate()
        self.update_window_mask()

    def deactivate_orb(self):
        """Dissolve the orb into the desktop."""
        self.orb.deactivate()

    def toggle_activation(self):
        """Toggle active appearance or dormant concealment."""
        if self.orb.state in (OrbState.IDLE, OrbState.DEACTIVATING):
            self.activate_orb()
        else:
            self.deactivate_orb()

    def toggle_listening(self):
        """Toggle voice listening mode."""
        if self.orb.state == OrbState.IDLE:
            self.activate_orb()
        elif self.orb.state == OrbState.LISTENING:
            self.orb.set_state(OrbState.INTERACTING)
        else:
            self.orb.set_state(OrbState.LISTENING)
            self.request_toggle_listen.emit()

    def reset_orb_position(self):
        """Return orb to default desktop coordinates."""
        geo = QApplication.primaryScreen().geometry()
        self.orb.set_center(float(geo.width() * 0.70), float(geo.height() * 0.38))
        self.update_window_mask()

    def quit_application(self):
        """Gracefully exit DARK SHADOW."""
        self.stop()
        self.quit_requested.emit()
        QApplication.quit()

    def _on_orb_activated(self):
        """Callback when orb starts assembling."""
        self.show()
        self.update_window_mask()

    def _on_orb_deactivated(self):
        """Callback when orb finishes dissolving."""
        self.hide()
        self.setMask(QRegion())  # Release all mouse capture

    def _on_orb_state_changed(self, new_state: OrbState):
        """Update system tray and mask upon state change."""
        if hasattr(self, 'action_title') and self.action_title:
            self.action_title.setText(f"DARK SHADOW® [{new_state.value.capitalize()}]")
        self.update_window_mask()

    def _on_tray_activated(self, reason):
        """Trigger activation on single/double tray click."""
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_activation()

    def update_window_mask(self):
        """
        Dynamically adjusts Windows mouse hit-test region.
        When active, only a circular envelope around the orb intercepts mouse events.
        All clicks outside pass through to the Windows desktop!
        """
        state = self.orb.state

        if state == OrbState.IDLE:
            # Idle: no mouse capture
            self.setMask(QRegion())
            return

        elif state == OrbState.ACTIVATING:
            # During bottom-emergence, capture the screen or the bottom-to-orb column
            self.clearMask()
            return

        elif state == OrbState.DEACTIVATING:
            # During dissolution, keep mask around dissolving particles
            cx = int(self.orb.particles.center_x)
            cy = int(self.orb.particles.center_y)
            r = int(self.orb.particles.current_radius * 2.5)
            rect = QRect(cx - r, cy - r, r * 2, r * 2)
            self.setMask(QRegion(rect, QRegion.RegionType.Ellipse))
            return

        else:
            # Normal active states: Mask is tightly fitted around the orb + hover margin
            cx = int(self.orb.particles.center_x + self.orb.particles.floating_offset_x)
            cy = int(self.orb.particles.center_y + self.orb.particles.floating_offset_y)
            # Interactive hover radius
            r = int(self.orb.particles.current_radius * 1.65)
            rect = QRect(cx - r, cy - r, r * 2, r * 2)
            self.setMask(QRegion(rect, QRegion.RegionType.Ellipse))

    def _on_animation_frame(self):
        """60 FPS physics calculation and repaint cycle."""
        now = time.perf_counter()
        dt = now - self.last_frame_time
        self.last_frame_time = now

        # Update orb physics
        self.orb.update(dt)

        # Repaint if visible
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        """Render frame."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Render living orb and particles
        self.orb.render(painter)
        painter.end()

    # --- Mouse Event Dispatches ---

    def mousePressEvent(self, event: QMouseEvent):
        if self.mouse_ctrl.handle_mouse_press(event):
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent):
        def update_center(nx, ny):
            self.orb.set_center(nx, ny)
            self.update_window_mask()

        if self.mouse_ctrl.handle_mouse_move(event, update_center_callback=update_center):
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.mouse_ctrl.handle_mouse_release(event):
            event.accept()
        else:
            event.ignore()

    def leaveEvent(self, event):
        self.mouse_ctrl.handle_mouse_leave()
        super().leaveEvent(event)

    # --- Scroll Wheel Dispatch ---

    def wheelEvent(self, event: QWheelEvent):
        if self.scroll_ctrl.handle_wheel_event(event):
            event.accept()
        else:
            event.ignore()

    # --- Keyboard Shortcuts ---

    def keyPressEvent(self, event: QKeyEvent):
        if self.key_ctrl.handle_key_press(event):
            event.accept()
        else:
            super().keyPressEvent(event)
