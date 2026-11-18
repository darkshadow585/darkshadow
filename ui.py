"""Lightweight, single-orb PySide6 interface for DarkShadow.

The fluid GIF supplies the orb material while Qt paints all interactive,
state-aware effects and controls.
"""

from __future__ import annotations

import ctypes
import logging
import math
import random
import sys
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
    QPropertyAnimation,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QGuiApplication,
    QKeySequence,
    QLinearGradient,
    QMouseEvent,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Theme:
    background: str = "#000000"
    surface: str = "#070A10"
    surface_hover: str = "#0F1422"
    border: str = "#181E2C"
    text: str = "#F8F9FD"
    muted: str = "#8A90A4"
    violet: str = "#765CFF"
    cyan: str = "#00D2FF"
    green: str = "#00D2FF"
    red: str = "#FF4560"


@dataclass(frozen=True, slots=True)
class MotionConfig:
    """Animation controls, including an accessibility-friendly reduced mode."""

    reduced_motion: bool = False
    fps: int = 30
    success_return_ms: int = 1800
    error_return_ms: int | None = 4200


THEME = Theme()


class AssistantState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    SUCCESS = "success"
    ERROR = "error"


STATE_TEXT = {
    AssistantState.IDLE: "Ready",
    AssistantState.LISTENING: "Listening…",
    AssistantState.PROCESSING: "Thinking…",
    AssistantState.SPEAKING: "Speaking…",
    AssistantState.SUCCESS: "Done",
    AssistantState.ERROR: "Something went wrong",
}
STATE_PALETTES = {
    AssistantState.IDLE: ("#6C55FF", "#334BCE", "#1B276B"),
    AssistantState.LISTENING: ("#8B6CFF", "#477BFF", "#00D2FF"),
    AssistantState.PROCESSING: ("#CE56FF", "#765CFF", "#3D42D8"),
    AssistantState.SPEAKING: ("#00D2FF", "#745DFF", "#9E68FF"),
    AssistantState.SUCCESS: ("#00D2FF", "#35BFD7", "#426CFF"),
    AssistantState.ERROR: ("#FF4560", "#FF6B8B", "#8A1830"),
}


def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    back = 1.0 - amount
    return QColor(
        round(first.red() * back + second.red() * amount),
        round(first.green() * back + second.green() * amount),
        round(first.blue() * back + second.blue() * amount),
        round(first.alpha() * back + second.alpha() * amount),
    )


class AppMark(QWidget):
    def sizeHint(self) -> QSize:
        return QSize(24, 24)

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        gradient = QConicalGradient(center, -30)
        gradient.setColorAt(0, QColor(THEME.cyan))
        gradient.setColorAt(0.4, QColor(THEME.violet))
        gradient.setColorAt(0.75, QColor("#A95BFF"))
        gradient.setColorAt(1, QColor(THEME.cyan))
        painter.setPen(QPen(gradient, 2.2))
        painter.setBrush(QColor(8, 11, 22, 230))
        painter.drawEllipse(center, 8, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(120, 105, 255, 210))
        painter.drawEllipse(center, 2, 2)


class WindowButton(QPushButton):
    def __init__(self, text: str, name: str, danger: bool = False) -> None:
        super().__init__(text)
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setFixedSize(42, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        hover = "#B7354B" if danger else THEME.surface_hover
        self.setStyleSheet(
            f"""
            QPushButton {{ color:#AEB4C6; background:transparent; border:none;
                border-radius:8px; font:16px "Segoe UI"; }}
            QPushButton:hover {{ color:white; background:{hover}; }}
            QPushButton:pressed {{ background:#282E3C; }}
            """
        )


class TitleBar(QWidget):
    """Custom title bar with native window dragging."""

    def __init__(self, window: "DarkShadowWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setFixedHeight(50)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(17, 6, 10, 6)
        layout.setSpacing(8)
        mark = AppMark()
        mark.setFixedSize(24, 24)
        layout.addWidget(mark)
        name = QLabel("DarkShadow")
        name.setStyleSheet(
            f'color:{THEME.text}; font:600 13px "Segoe UI"; background:transparent;'
        )
        layout.addWidget(name)
        layout.addStretch()
        self.min_button = WindowButton("—", "Minimize")
        self.max_button = WindowButton("□", "Maximize or restore")
        settings_button = WindowButton("⚙", "Settings and privacy")
        reminders_button = WindowButton("◷", "Reminders")
        close_button = WindowButton("×", "Close", True)
        self.min_button.clicked.connect(window.showMinimized)
        self.max_button.clicked.connect(self.toggle_maximized)
        settings_button.clicked.connect(window.show_control_center)
        reminders_button.clicked.connect(window.reminders_requested)
        close_button.clicked.connect(window.close)
        layout.addWidget(reminders_button)
        layout.addWidget(settings_button)
        layout.addWidget(self.min_button)
        layout.addWidget(self.max_button)
        layout.addWidget(close_button)

    @Slot()
    def toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
            self.max_button.setText("□")
        else:
            self.window.showMaximized()
            self.max_button.setText("❐")
        self.window.sync_window_shape()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not self.window.isMaximized():
            handle = self.window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)


class FadingLabel(QLabel):
    """Word-wrapping temporary text with a low-cost opacity transition."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.PlainText)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self.fade_out)

    def show_message(self, text: str, visible_ms: int | None = None) -> None:
        self._clear_timer.stop()
        self._animation.stop()
        self.setText(text.strip())
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(1.0 if text.strip() else 0.0)
        self._animation.start()
        if text.strip() and visible_ms:
            self._clear_timer.start(visible_ms)

    @Slot()
    def fade_out(self) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.start()


class AssistantOrb(QWidget):
    """Hybrid fluid-media orb with stateful native-painted effects."""

    clicked = Signal()

    def __init__(self, motion: MotionConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.motion = motion
        self._state = AssistantState.IDLE
        self._phase = self._rotation = self._audio = self._target_audio = 0.0
        self._transition = 1.0
        self._from = tuple(QColor(c) for c in STATE_PALETTES[self._state])
        self._to = self._from
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._paused = False
        self._movie: QMovie | None = None
        self._face_time = 0.0
        self._gaze = QPointF(0.0, 0.0)
        self._gaze_target = QPointF(0.0, 0.0)
        self._next_gaze_at = 1.2
        self._blink_started: float | None = None
        self._next_blink_at = 4.2
        self._face_random = random.Random(7341)
        self.setFixedSize(430, 430)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to start or stop listening")
        self.setAccessibleName("DarkShadow assistant orb")
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(max(16, round(1000 / max(1, motion.fps))))
        self._timer.timeout.connect(self._advance)
        self._timer.start()
        self._load_movie()

    def _load_movie(self) -> None:
        asset = Path(__file__).resolve().parent / "assets" / "darkshadow_core.gif"
        if not asset.is_file():
            LOGGER.warning("Hybrid orb asset not found; using native fallback")
            return
        movie = QMovie(str(asset), parent=self)
        if not movie.isValid():
            LOGGER.warning("Hybrid orb GIF is invalid; using native fallback")
            movie.deleteLater()
            return
        # Sequential decoding avoids retaining all 63 full-size frames in RAM.
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        movie.setScaledSize(QSize(480, 360))
        movie.frameChanged.connect(lambda _frame: self.update())
        self._movie = movie
        self._sync_movie_speed()
        movie.start()

    def _sync_movie_speed(self) -> None:
        if self._movie is None:
            return
        speed = {
            AssistantState.IDLE: 48,
            AssistantState.LISTENING: 92,
            AssistantState.PROCESSING: 125,
            AssistantState.SPEAKING: 108,
            AssistantState.SUCCESS: 72,
            AssistantState.ERROR: 56,
        }[self._state]
        self._movie.setSpeed(min(speed, 45) if self.motion.reduced_motion else speed)

    @property
    def state(self) -> AssistantState:
        return self._state

    def colors(self) -> tuple[QColor, QColor, QColor]:
        return tuple(
            _mix(a, b, self._transition) for a, b in zip(self._from, self._to)
        )  # type: ignore[return-value]

    def set_state(self, state: AssistantState) -> None:
        if state == self._state:
            return
        self._from = self.colors()
        self._to = tuple(QColor(c) for c in STATE_PALETTES[state])
        self._transition = 0.0
        self._state = state
        if state in {AssistantState.LISTENING, AssistantState.SUCCESS}:
            self._gaze_target = QPointF(0.0, 0.0)
        if state == AssistantState.SUCCESS:
            self._blink_started = self._face_time
        self._sync_movie_speed()
        self.update()

    def set_audio_level(self, level: float) -> None:
        self._target_audio = max(0.0, min(1.0, float(level)))

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self._timer.stop()
            if self._movie is not None:
                self._movie.setPaused(True)
        elif not self._timer.isActive():
            self._elapsed.restart()
            self._timer.start()
            if self._movie is not None:
                self._movie.setPaused(False)

    @Slot()
    def _advance(self) -> None:
        if self._paused or not self.isVisible():
            return
        delta = min(0.08, max(0.001, self._elapsed.restart() / 1000))
        speed = {
            AssistantState.IDLE: 0.52,
            AssistantState.LISTENING: 1.8,
            AssistantState.PROCESSING: 2.4,
            AssistantState.SPEAKING: 2.0,
            AssistantState.SUCCESS: 1.1,
            AssistantState.ERROR: 1.35,
        }[self._state]
        if self.motion.reduced_motion:
            speed *= 0.22
        self._phase = (self._phase + delta * speed) % (math.tau * 8)
        self._rotation = (self._rotation + delta * speed * 27) % 360
        self._audio += (self._target_audio - self._audio) * min(1, delta * 10)
        self._transition = min(1.0, self._transition + delta / 0.42)
        self._advance_face(delta)
        self.update()

    def _advance_face(self, delta: float) -> None:
        """Move the shared gaze gently and schedule short natural blinks."""

        self._face_time += delta
        if self._face_time >= self._next_gaze_at:
            amplitude = {
                AssistantState.IDLE: (0.72, 0.48),
                AssistantState.LISTENING: (0.28, 0.22),
                AssistantState.PROCESSING: (1.0, 0.42),
                AssistantState.SPEAKING: (0.54, 0.38),
                AssistantState.SUCCESS: (0.18, 0.12),
                AssistantState.ERROR: (0.36, 0.18),
            }[self._state]
            if self.motion.reduced_motion:
                amplitude = (amplitude[0] * 0.35, amplitude[1] * 0.35)
            self._gaze_target = QPointF(
                self._face_random.uniform(-amplitude[0], amplitude[0]),
                self._face_random.uniform(-amplitude[1], amplitude[1]),
            )
            delay = {
                AssistantState.PROCESSING: (0.75, 1.35),
                AssistantState.LISTENING: (2.4, 4.2),
            }.get(self._state, (1.8, 3.8))
            self._next_gaze_at = self._face_time + self._face_random.uniform(*delay)

        easing = 1.0 - math.exp(-delta * 5.2)
        self._gaze = QPointF(
            self._gaze.x() + (self._gaze_target.x() - self._gaze.x()) * easing,
            self._gaze.y() + (self._gaze_target.y() - self._gaze.y()) * easing,
        )

        if self._blink_started is None and self._face_time >= self._next_blink_at:
            self._blink_started = self._face_time
        if (
            self._blink_started is not None
            and self._face_time - self._blink_started >= 0.19
        ):
            self._blink_started = None
            self._next_blink_at = self._face_time + self._face_random.uniform(3.8, 7.2)

    def _eye_pose(self, radius: float) -> tuple[float, float, float]:
        """Return gaze offset and eyelid openness for the current frame."""

        blink = 1.0
        if self._blink_started is not None:
            progress = max(
                0.0, min(1.0, (self._face_time - self._blink_started) / 0.19)
            )
            blink = max(0.08, abs(progress * 2.0 - 1.0))
        return (
            self._gaze.x() * radius * 0.036,
            self._gaze.y() * radius * 0.024,
            blink,
        )

    def _blob(self, center: QPointF, radius: float, layer: int, energy: float) -> QPainterPath:
        points: list[QPointF] = []
        for index in range(64):
            angle = math.tau * index / 64
            ripple = (
                math.sin(angle * 3 + self._phase * (0.72 + layer * 0.08) + layer) * 0.53
                + math.sin(angle * 5 - self._phase * 0.9 + layer * 1.7) * 0.29
                + math.sin(angle * 7 + self._phase * 0.38) * 0.18
            )
            local = radius + ripple * energy
            points.append(
                QPointF(center.x() + math.cos(angle) * local,
                        center.y() + math.sin(angle) * local)
            )
        path = QPainterPath()
        path.moveTo((points[0] + points[-1]) / 2)
        for index, point in enumerate(points):
            following = points[(index + 1) % len(points)]
            path.quadTo(point, (point + following) / 2)
        path.closeSubpath()
        return path

    def _paint_hybrid_movie(
        self,
        painter: QPainter,
        center: QPointF,
        audio: float,
        primary: QColor,
        secondary: QColor,
        accent: QColor,
    ) -> bool:
        """Paint the decoded fluid core plus lightweight reactive overlays."""

        if self._movie is None:
            return False
        pixmap = self._movie.currentPixmap()
        if pixmap.isNull():
            return False

        side = float(min(self.width(), self.height()))
        breath = 0.5 + 0.5 * math.sin(self._phase * 1.2)
        target_side = side * (0.96 + breath * 0.012 + audio * 0.035)
        target = QRectF(
            center.x() - target_side / 2,
            center.y() - target_side / 2,
            target_side,
            target_side,
        )
        source_side = float(min(pixmap.width(), pixmap.height()))
        source = QRectF(
            (pixmap.width() - source_side) / 2,
            (pixmap.height() - source_side) / 2,
            source_side,
            source_side,
        )
        # The source background is nearly black but not identical to the
        # application surface. Circular clipping removes any visible media
        # rectangle while retaining the full radial bloom.
        painter.save()
        media_clip = QPainterPath()
        media_clip.addEllipse(target)
        painter.setClipPath(media_clip)
        painter.setCompositionMode(QPainter.CompositionMode_Screen)
        painter.drawPixmap(target, pixmap, source)
        painter.restore()

        visual_radius = target_side * 0.405
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Screen)

        # State tint and bloom preserve the GIF detail while moving the cyan
        # source toward violet, green or red as assistant state changes.
        state_wash = QRadialGradient(center, visual_radius * 1.45)
        wash = _mix(primary, accent, 0.28)
        wash.setAlpha(22 + round(audio * 24))
        state_wash.setColorAt(0.0, QColor(wash.red(), wash.green(), wash.blue(), 3))
        state_wash.setColorAt(0.68, wash)
        state_wash.setColorAt(1.0, QColor(wash.red(), wash.green(), wash.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(state_wash)
        painter.drawEllipse(center, visual_radius * 1.45, visual_radius * 1.45)

        # Sparse procedural pin-points give the orb presence without a particle
        # object system or persistent allocations.
        for index in range(76):
            angle = math.tau * index / 76 + self._phase * 0.014
            spread = 1.12 + 0.26 * (
                0.5 + 0.5 * math.sin(index * 2.17 + self._phase * 0.09)
            )
            dot_radius = visual_radius * spread
            dot = _mix(primary, accent, (index % 7) / 7)
            dot.setAlpha(24 + (index * 19) % 58)
            painter.setBrush(dot)
            size = 0.45 + (index % 3) * 0.22
            painter.drawEllipse(
                QPointF(
                    center.x() + math.cos(angle) * dot_radius,
                    center.y() + math.sin(angle) * dot_radius,
                ),
                size,
                size,
            )

        ring = QConicalGradient(center, -self._rotation * 0.22)
        ring.setColorAt(0.0, accent.lighter(145))
        ring.setColorAt(0.30, primary)
        ring.setColorAt(0.62, QColor("#C59AFF"))
        ring.setColorAt(1.0, accent.lighter(145))
        painter.setBrush(Qt.NoBrush)
        glow = QColor(primary)
        glow.setAlpha(34 + round(audio * 46))
        painter.setPen(QPen(glow, 9 + audio * 7))
        painter.drawEllipse(center, visual_radius, visual_radius)
        painter.setPen(QPen(ring, 2.5 + audio * 1.4))
        painter.drawEllipse(center, visual_radius, visual_radius)

        if self._state == AssistantState.PROCESSING and not self.motion.reduced_motion:
            arc = QColor(accent.lighter(160))
            arc.setAlpha(230)
            painter.setPen(QPen(arc, 3.2, Qt.SolidLine, Qt.RoundCap))
            arc_radius = visual_radius * 1.055
            painter.drawArc(
                QRectF(
                    center.x() - arc_radius,
                    center.y() - arc_radius,
                    arc_radius * 2,
                    arc_radius * 2,
                ),
                round(-self._rotation * 16),
                76 * 16,
            )
        painter.restore()

        # The source has a calm dark center; two native lights maintain the
        # assistant personality from the original DarkShadow concept.
        gaze_x, gaze_y, blink = self._eye_pose(visual_radius)
        eye_y = center.y() + visual_radius * 0.015 + gaze_y
        eye_offset = visual_radius * 0.16
        eye_width = visual_radius * (0.040 + audio * 0.006)
        eye_height = max(
            visual_radius * 0.006,
            visual_radius * (0.067 + audio * 0.008) * blink,
        )
        for eye_x in (
            center.x() - eye_offset + gaze_x,
            center.x() + eye_offset + gaze_x,
        ):
            eye_glow = QRadialGradient(
                QPointF(eye_x, eye_y), eye_height * 1.85
            )
            eye_glow.setColorAt(0.0, QColor(255, 255, 255, 255))
            eye_glow.setColorAt(0.42, QColor(192, 220, 255, 105))
            eye_glow.setColorAt(1.0, QColor(95, 125, 255, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(eye_glow)
            painter.drawEllipse(
                QPointF(eye_x, eye_y),
                eye_height * 1.85,
                max(1.0, eye_height * 1.85),
            )
            painter.setBrush(QColor(245, 248, 255, 242))
            painter.drawEllipse(
                QRectF(
                    eye_x - eye_width,
                    eye_y - eye_height,
                    eye_width * 2,
                    eye_height * 2,
                )
            )
        return True

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        base = min(self.width(), self.height()) * 0.34
        audio = self._audio if self._state in {
            AssistantState.LISTENING, AssistantState.SPEAKING
        } else 0.0
        radius = base * (1 + 0.018 * (0.5 + 0.5 * math.sin(self._phase * 1.2))
                         + audio * 0.075)
        if self._state == AssistantState.SUCCESS:
            radius *= 1 + max(0, math.sin(self._phase * 2.2)) * 0.045
        if self._state == AssistantState.ERROR and not self.motion.reduced_motion:
            painter.translate(math.sin(self._phase * 14) * 3.4, 0)
        primary, secondary, accent = self.colors()
        if self._paint_hybrid_movie(
            painter, center, audio, primary, secondary, accent
        ):
            return

        # A radial wash and deterministic pin-points reproduce the reference
        # halo without allocating a particle system.
        halo = QRadialGradient(center, radius * 1.8)
        color = QColor(secondary)
        color.setAlpha(40 + round(audio * 42))
        halo.setColorAt(0, color)
        halo.setColorAt(0.55, QColor(primary.red(), primary.green(), primary.blue(), 24))
        halo.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, radius * 1.8, radius * 1.8)
        for index in range(104):
            angle = math.tau * index / 104 + self._phase * 0.015
            spread = 1.17 + 0.27 * (
                0.5 + 0.5 * math.sin(index * 2.31 + self._phase * 0.12)
            )
            point_radius = radius * spread
            dot = _mix(primary, accent, (index % 9) / 9)
            dot.setAlpha(28 + (index * 17) % 64)
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot)
            size = 0.45 + (index % 4) * 0.16
            painter.drawEllipse(
                QPointF(
                    center.x() + math.cos(angle) * point_radius,
                    center.y() + math.sin(angle) * point_radius,
                ),
                size,
                size,
            )

        # Dark glass sphere first. The colored material is painted as thin,
        # overlapping ribbon bands instead of a solid donut.
        sphere = QRadialGradient(
            center - QPointF(radius * 0.22, radius * 0.25), radius * 1.35
        )
        sphere.setColorAt(0, QColor(31, 32, 82, 245))
        sphere.setColorAt(0.48, QColor(11, 12, 39, 252))
        sphere.setColorAt(1, QColor(3, 5, 17, 255))
        painter.setPen(Qt.NoPen)
        painter.setBrush(sphere)
        painter.drawEllipse(center, radius, radius)

        energy = {
            AssistantState.IDLE: 2.1,
            AssistantState.LISTENING: 5.4 + audio * 7,
            AssistantState.PROCESSING: 8.0,
            AssistantState.SPEAKING: 5.8 + audio * 9,
            AssistantState.SUCCESS: 3.0,
            AssistantState.ERROR: 4.4,
        }[self._state] * (0.28 if self.motion.reduced_motion else 1)
        painter.save()
        circular_clip = QPainterPath()
        circular_clip.addEllipse(center, radius * 0.985, radius * 0.985)
        painter.setClipPath(circular_clip)
        bands = (
            (1, 0.98, 0.70, 124),
            (2, 0.93, 0.66, 102),
            (3, 0.87, 0.62, 82),
            (4, 0.82, 0.59, 62),
        )
        for layer, outer_factor, inner_factor, alpha in bands:
            outer_path = self._blob(
                center, radius * outer_factor, layer, energy * (1 - layer * 0.07)
            )
            inner_path = self._blob(
                center,
                radius * inner_factor,
                layer + 7,
                energy * (0.72 + layer * 0.03),
            )
            ribbon = outer_path.subtracted(inner_path)
            gradient = QConicalGradient(center, self._rotation * (0.35 + layer * 0.07))
            first = _mix(primary, accent, layer * 0.12)
            second = _mix(secondary, QColor("#151956"), 0.24)
            third = accent.lighter(128)
            first.setAlpha(alpha)
            second.setAlpha(max(34, alpha - 26))
            third.setAlpha(min(185, alpha + 24))
            gradient.setColorAt(0, first)
            gradient.setColorAt(0.28, second)
            gradient.setColorAt(0.56, third)
            gradient.setColorAt(0.82, primary)
            gradient.setColorAt(1, first)
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(ribbon)
        painter.restore()

        core = self._blob(center, radius * 0.64, 9, energy * 0.34)
        core_gradient = QRadialGradient(
            center - QPointF(radius * 0.18, radius * 0.22), radius * 0.88
        )
        core_gradient.setColorAt(0, QColor(22, 23, 62, 244))
        core_gradient.setColorAt(0.58, QColor(7, 8, 29, 252))
        core_gradient.setColorAt(1, QColor(2, 3, 14, 255))
        painter.setBrush(core_gradient)
        painter.drawPath(core)

        outer_ring = QConicalGradient(center, -self._rotation * 0.18)
        outer_ring.setColorAt(0, primary.lighter(145))
        outer_ring.setColorAt(0.28, accent.lighter(125))
        outer_ring.setColorAt(0.62, QColor("#B98BFF"))
        outer_ring.setColorAt(1, primary.lighter(145))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 35), 10))
        painter.drawEllipse(center, radius * 1.01, radius * 1.01)
        painter.setPen(QPen(outer_ring, 3.2))
        painter.drawEllipse(center, radius, radius)

        if self._state == AssistantState.PROCESSING and not self.motion.reduced_motion:
            color = QColor(accent.lighter(135))
            color.setAlpha(210)
            painter.setPen(QPen(color, 3.1, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(
                QRectF(center.x() - radius * 1.18, center.y() - radius * 1.18,
                       radius * 2.36, radius * 2.36),
                round(-self._rotation * 16), 72 * 16,
            )

        gaze_x, gaze_y, blink = self._eye_pose(radius)
        eye_y, eye_offset = center.y() + radius * .03 + gaze_y, radius * .20
        eye_radius = max(4.0, radius * .055 + audio * 1.7)
        eye_height = max(1.0, eye_radius * 1.2 * blink)
        for eye_x in (
            center.x() - eye_offset + gaze_x,
            center.x() + eye_offset + gaze_x,
        ):
            glow = QRadialGradient(QPointF(eye_x, eye_y), eye_radius * 2.4)
            glow.setColorAt(0, QColor(255, 255, 255))
            glow.setColorAt(.38, accent.lighter(170))
            glow.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(
                QPointF(eye_x, eye_y), eye_radius * 2.4, eye_height * 2.0
            )
            painter.setBrush(QColor(244, 244, 255, 238))
            painter.drawEllipse(QPointF(eye_x, eye_y), eye_radius, eye_height)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class AudioWaveform(QWidget):
    """Small state-aware native waveform shown only during audio states."""

    def __init__(self, motion: MotionConfig) -> None:
        super().__init__()
        self.motion = motion
        self._state = AssistantState.IDLE
        self._level = self._display = self._phase = 0.0
        self.setFixedSize(250, 48)
        self._timer = QTimer(self)
        self._timer.setInterval(max(24, round(1000 / max(1, motion.fps))))
        self._timer.timeout.connect(self._advance)

    def set_state(self, state: AssistantState) -> None:
        self._state = state
        active = state in {AssistantState.LISTENING, AssistantState.SPEAKING}
        self.setVisible(active)
        self._timer.start() if active else self._timer.stop()

    def set_audio_level(self, level: float) -> None:
        self._level = max(0, min(1, float(level)))

    @Slot()
    def _advance(self) -> None:
        self._display += (self._level - self._display) * .24
        self._phase += .06 if self.motion.reduced_motion else .24
        self.update()

    def paintEvent(self, event: Any) -> None:
        del event
        if not self.isVisible():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(
            QColor(THEME.cyan if self._state == AssistantState.SPEAKING else THEME.violet),
            3.2, Qt.SolidLine, Qt.RoundCap,
        ))
        count, center_y, spacing = 25, self.height() / 2, self.width() / 26
        for index in range(count):
            distance = abs(index - 12) / 12
            envelope = (1 - distance) ** 1.55
            motion = .55 + .45 * math.sin(self._phase + index * .74) ** 2
            height = 3 + envelope * (8 + self._display * 20) * motion
            x = spacing * (index + 1)
            painter.drawLine(QPointF(x, center_y - height / 2),
                             QPointF(x, center_y + height / 2))


class MicrophoneButton(QPushButton):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(42, 42)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Use microphone")
        self.setToolTip("Use microphone")
        self.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:19px;}}"
            f"QPushButton:hover{{background:{THEME.surface_hover};}}"
            f"QPushButton:focus{{border:1px solid {THEME.violet};}}"
        )

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#A9B0C5"), 1.8, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(17, 10, 8, 14), 4, 4)
        path = QPainterPath(QPointF(13.5, 20))
        path.cubicTo(13.5, 29, 28.5, 29, 28.5, 20)
        painter.drawPath(path)
        painter.drawLine(QPointF(21, 28), QPointF(21, 33))
        painter.drawLine(QPointF(17, 33), QPointF(25, 33))


class CommandInput(QFrame):
    command_submitted = Signal(str)
    microphone_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("commandInput")
        self.setMaximumWidth(620)
        self.setFixedHeight(54)
        self.setStyleSheet(
            f"""QFrame#commandInput{{background:rgba(11,15,25,232);
            border:1px solid {THEME.border};border-radius:17px;}}
            QLineEdit{{color:{THEME.text};background:transparent;border:none;
            padding:0 5px;font:13px "Segoe UI";selection-background-color:{THEME.violet};}}"""
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 5, 6, 5)
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("Type a command...")
        self.line_edit.setAccessibleName("Command")
        self.line_edit.setClearButtonEnabled(True)
        self.line_edit.returnPressed.connect(self._submit)
        layout.addWidget(self.line_edit, 1)
        mic = MicrophoneButton()
        mic.clicked.connect(self.microphone_requested)
        layout.addWidget(mic)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.InOutCubic)
        self._hiding = False
        self._fade.finished.connect(lambda: self.hide() if self._hiding else None)

    @Slot()
    def _submit(self) -> None:
        text = self.line_edit.text().strip()
        if text:
            self.line_edit.clear()
            self.command_submitted.emit(text)

    def focus_input(self) -> None:
        if self.isVisible():
            self.line_edit.setFocus(Qt.ShortcutFocusReason)

    def set_voice_only(self, enabled: bool) -> None:
        self._fade.stop()
        self._hiding = enabled
        if not enabled:
            self.show()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0 if enabled else 1.0)
        self._fade.start()


class AssistantActions(QWidget):
    """Compact contextual actions, including a true speech interrupt."""

    suggestion_selected = Signal(str)
    stop_requested = Signal()
    copy_requested = Signal()
    regenerate_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._suggestions: tuple[str, ...] = ()
        self._has_response = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 2)
        layout.setSpacing(8)
        layout.addStretch()
        self.suggestion_buttons: list[QPushButton] = []
        for _index in range(3):
            button = QPushButton()
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(30)
            button.setStyleSheet(
                f"QPushButton{{color:{THEME.muted};background:{THEME.surface};"
                f"border:1px solid {THEME.border};border-radius:15px;"
                'padding:0 13px;font:10px "Segoe UI";}'
                f"QPushButton:hover{{color:{THEME.text};"
                f"border-color:{THEME.violet};background:{THEME.surface_hover};}}"
            )
            button.clicked.connect(
                lambda _checked=False, control=button: self.suggestion_selected.emit(
                    control.text()
                )
            )
            button.hide()
            self.suggestion_buttons.append(button)
            layout.addWidget(button)
        self.stop_button = QPushButton("■  Stop speaking")
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setFixedHeight(32)
        self.stop_button.setStyleSheet(
            f"QPushButton{{color:{THEME.red};background:{THEME.surface};"
            "border:1px solid #5A2630;border-radius:16px;"
            'padding:0 15px;font:600 10px "Segoe UI";}'
            f"QPushButton:hover{{color:#FFFFFF;background:#3A1720;"
            f"border-color:{THEME.red};}}"
        )
        self.stop_button.clicked.connect(self.stop_requested)
        self.stop_button.hide()
        layout.addWidget(self.stop_button)
        self.copy_button = QPushButton("Copy")
        self.regenerate_button = QPushButton("Regenerate")
        for button in (self.copy_button, self.regenerate_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(30)
            button.setStyleSheet(
                f"QPushButton{{color:{THEME.muted};background:transparent;"
                f"border:1px solid {THEME.border};border-radius:15px;"
                "padding:0 11px;font:10px 'Segoe UI';}"
                f"QPushButton:hover{{color:{THEME.text};"
                f"border-color:{THEME.violet};}}"
            )
            button.hide()
            layout.addWidget(button)
        self.copy_button.clicked.connect(self.copy_requested)
        self.regenerate_button.clicked.connect(self.regenerate_requested)
        layout.addStretch()
        self.setFixedHeight(40)
        self.hide()

    def set_suggestions(self, suggestions: tuple[str, ...]) -> None:
        self._suggestions = tuple(
            str(text).strip() for text in suggestions[:3] if str(text).strip()
        )
        self._sync(False)

    def set_speaking(self, speaking: bool) -> None:
        self._sync(speaking)

    def set_response_available(self, available: bool) -> None:
        self._has_response = bool(available)
        self._sync(self.stop_button.isVisible())

    def _sync(self, speaking: bool) -> None:
        self.stop_button.setVisible(speaking)
        for index, button in enumerate(self.suggestion_buttons):
            text = self._suggestions[index] if index < len(self._suggestions) else ""
            button.setText(text)
            button.setVisible(bool(text) and not speaking)
        self.copy_button.setVisible(self._has_response and not speaking)
        self.regenerate_button.setVisible(self._has_response and not speaking)
        self.setVisible(speaking or bool(self._suggestions) or self._has_response)


class ControlCenterDialog(QDialog):
    """Small runtime settings surface; secrets and raw memory never appear."""

    preferences_applied = Signal(bool, bool, bool)
    clear_chat_requested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("DarkShadow Control Center")
        self.setModal(False)
        self.setFixedWidth(430)
        self.setStyleSheet(
            f"QDialog{{background:{THEME.background};color:{THEME.text};}}"
            f"QLabel{{color:{THEME.muted};font:11px 'Segoe UI';}}"
            f"QCheckBox{{color:{THEME.text};font:12px 'Segoe UI';spacing:10px;}}"
            f"QPushButton{{color:{THEME.text};background:{THEME.surface};"
            f"border:1px solid {THEME.border};border-radius:9px;"
            "padding:8px 14px;font:11px 'Segoe UI';}"
            f"QPushButton:hover{{border-color:{THEME.violet};"
            f"background:{THEME.surface_hover};}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel("Settings & privacy")
        title.setStyleSheet(
            f"color:{THEME.text};font:600 18px 'Segoe UI';"
        )
        layout.addWidget(title)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.voice_checkbox = QCheckBox("Speak assistant replies")
        self.motion_checkbox = QCheckBox("Reduce orb motion")
        self.privacy_checkbox = QCheckBox(
            "Privacy mode (pause persistent memory access)"
        )
        layout.addWidget(self.voice_checkbox)
        layout.addWidget(self.motion_checkbox)
        layout.addWidget(self.privacy_checkbox)
        note = QLabel(
            "Privacy mode affects this app session only. API keys and saved "
            "memory contents are never shown here."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        clear_button = QPushButton("Clear chat context")
        clear_button.clicked.connect(self.clear_chat_requested)
        apply_button = QPushButton("Apply")
        apply_button.setStyleSheet(
            f"QPushButton{{color:white;background:{THEME.violet};"
            f"border:1px solid {THEME.violet};border-radius:9px;"
            "padding:8px 18px;font:600 11px 'Segoe UI';}"
        )
        apply_button.clicked.connect(self._apply)
        buttons.addWidget(clear_button)
        buttons.addStretch()
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def configure(
        self,
        *,
        voice_enabled: bool,
        reduced_motion: bool,
        privacy_mode: bool,
        status: str,
    ) -> None:
        self.voice_checkbox.setChecked(voice_enabled)
        self.motion_checkbox.setChecked(reduced_motion)
        self.privacy_checkbox.setChecked(privacy_mode)
        self.status_label.setText(status)

    @Slot()
    def _apply(self) -> None:
        self.preferences_applied.emit(
            self.voice_checkbox.isChecked(),
            self.motion_checkbox.isChecked(),
            self.privacy_checkbox.isChecked(),
        )
        self.accept()


class ReminderDialog(QDialog):
    """Read-only upcoming reminder list; reminders are still created by chat."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upcoming reminders")
        self.setFixedWidth(430)
        self.setStyleSheet(
            f"QDialog{{background:{THEME.background};color:{THEME.text};}}"
            f"QLabel{{color:{THEME.text};font:11px 'Segoe UI';}}"
            f"QPushButton{{color:{THEME.text};background:{THEME.surface};"
            f"border:1px solid {THEME.border};border-radius:9px;"
            "padding:8px 18px;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        title = QLabel("Upcoming reminders")
        title.setStyleSheet(
            f"color:{THEME.text};font:600 18px 'Segoe UI';"
        )
        layout.addWidget(title)
        self.items_label = QLabel("Loading…")
        self.items_label.setWordWrap(True)
        self.items_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.items_label)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)

    def set_items(self, items: tuple[str, ...]) -> None:
        self.items_label.setText(
            "\n\n".join(items)
            if items
            else "No upcoming reminders. Try: “Remind me tomorrow at 7 PM.”"
        )


class DarkShadowWindow(QMainWindow):
    """Single-orb desktop window with a thread-safe public API."""

    command_submitted = Signal(str)
    microphone_requested = Signal()
    suggestion_selected = Signal(str)
    stop_speaking_requested = Signal()
    regenerate_requested = Signal()
    preferences_changed = Signal(bool, bool, bool)
    clear_chat_requested = Signal()
    reminders_requested = Signal()
    _state_requested = Signal(str, str)
    _audio_requested = Signal(float)
    _status_requested = Signal(str)
    _transcript_requested = Signal(str)
    _response_requested = Signal(str)
    _source_count_requested = Signal(int)
    _suggestions_requested = Signal(object)
    _voice_only_requested = Signal(bool)

    def __init__(self, *, motion: MotionConfig | None = None) -> None:
        super().__init__()
        self.motion = motion or MotionConfig()
        self.current_state = AssistantState.IDLE
        self._controller: QObject | None = None
        self._cleanup_callback: Any = None
        self._voice_enabled = True
        self._privacy_mode = False
        self._environment_status = "Runtime status will appear after startup."
        self.setWindowTitle("DarkShadow")
        self.setMinimumSize(920, 620)
        self.resize(1140, 760)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._build_ui()
        self.control_center = ControlCenterDialog(self)
        self.control_center.preferences_applied.connect(self.preferences_changed)
        self.control_center.clear_chat_requested.connect(self.clear_chat_requested)
        self.reminder_dialog = ReminderDialog(self)
        self._wire_api()
        self._install_shortcuts()
        self._return_timer = QTimer(self)
        self._return_timer.setSingleShot(True)
        self._return_timer.timeout.connect(lambda: self.set_state("idle"))

    def _build_ui(self) -> None:
        host = QWidget()
        self.setCentralWidget(host)
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(10, 10, 10, 10)
        self.frame = QFrame()
        self.frame.setObjectName("windowFrame")
        self.frame.setStyleSheet(self._frame_style(False))
        host_layout.addWidget(self.frame)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(1, 1, 1, 13)
        frame_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        frame_layout.addWidget(self.title_bar)
        content = QWidget()
        frame_layout.addWidget(content, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 6, 20, 10)
        layout.setSpacing(10)

        # ── 3-Column Panoramic Cyber HUD: Left (Captain) | Center (Orb) | Right (DarkShadow) ──
        stage = QWidget()
        stage_layout = QHBoxLayout(stage)
        stage_layout.setContentsMargins(10, 0, 10, 0)
        stage_layout.setSpacing(18)

        # ── Left Column: Captain's Question (Light Sky Blue, No Box) ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 10, 8, 10)
        left_layout.setSpacing(8)

        captain_badge = QLabel("👤  CAPTAIN'S PROMPT")
        captain_badge.setStyleSheet(
            'color: #80D8FF; font: 700 11px "Segoe UI"; letter-spacing: 1.5px; background: transparent;'
        )
        left_layout.addWidget(captain_badge)

        self.transcript_label = FadingLabel()
        self.transcript_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.transcript_label.setStyleSheet(
            'color: #80D8FF; font: 13px "Segoe UI"; line-height: 1.45; background: transparent;'
        )
        self.transcript_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.transcript_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.transcript_label, 1)

        stage_layout.addWidget(left_panel, 3)

        # ── Center Column: Interactive Avatar Orb ──
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)
        center_layout.addStretch(1)

        self.orb = AssistantOrb(self.motion)
        self.orb.clicked.connect(self._toggle_listening)
        center_layout.addWidget(self.orb, 0, Qt.AlignHCenter)

        self.state_label = QLabel("Ready")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setMinimumHeight(28)
        center_layout.addWidget(self.state_label, 0, Qt.AlignHCenter)

        self.waveform = AudioWaveform(self.motion)
        self.waveform.hide()
        center_layout.addWidget(self.waveform, 0, Qt.AlignHCenter)
        center_layout.addStretch(1)

        stage_layout.addWidget(center_widget, 4)

        # ── Right Column: DarkShadow's Response (White, No Box) & Actions ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 10, 8, 10)
        right_layout.setSpacing(8)

        ds_badge = QLabel("⚡  DARKSHADOW AI")
        ds_badge.setStyleSheet(
            'color: #FFFFFF; font: 700 11px "Segoe UI"; letter-spacing: 1.5px; background: transparent;'
        )
        right_layout.addWidget(ds_badge)

        self.response_label = FadingLabel()
        self.response_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.response_label.setStyleSheet(
            'color: #FFFFFF; font: 13px "Segoe UI"; line-height: 1.45; background: transparent;'
        )
        self.response_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.response_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.response_label, 1)

        self.source_label = FadingLabel()
        self.source_label.setFixedHeight(22)
        self.source_label.setStyleSheet(
            'color: #80D8FF; font: 600 11px "Segoe UI"; background: transparent;'
        )
        right_layout.addWidget(self.source_label)

        self.actions = AssistantActions()
        self.actions.suggestion_selected.connect(self.suggestion_selected)
        self.actions.stop_requested.connect(self.stop_speaking_requested)
        self.actions.copy_requested.connect(self._copy_response)
        self.actions.regenerate_requested.connect(self.regenerate_requested)
        right_layout.addWidget(self.actions)

        stage_layout.addWidget(right_panel, 3)

        layout.addWidget(stage, 1)

        # ── Bottom Command Input ──
        self.command_input = CommandInput()
        self.command_input.command_submitted.connect(self.command_submitted)
        self.command_input.microphone_requested.connect(self.microphone_requested)
        layout.addWidget(self.command_input, 0, Qt.AlignHCenter)
        self._style_state(AssistantState.IDLE)

    def _wire_api(self) -> None:
        self._state_requested.connect(self._apply_state)
        self._audio_requested.connect(self._apply_audio)
        self._status_requested.connect(lambda text: self.state_label.setText(text.strip()))
        self._transcript_requested.connect(self._apply_transcript)
        self._response_requested.connect(self._apply_response)
        self._source_count_requested.connect(self._apply_source_count)
        self._suggestions_requested.connect(self._apply_suggestions)
        self._voice_only_requested.connect(self.command_input.set_voice_only)

    def _install_shortcuts(self) -> None:
        for number, state in enumerate(AssistantState, 1):
            shortcut = QShortcut(QKeySequence(str(number)), self)
            shortcut.activated.connect(lambda value=state.value: self.set_state(value))
        space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        space_shortcut.activated.connect(self._space_shortcut)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.command_input.focus_input)
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(self._safe_escape)

    @staticmethod
    def _frame_style(maximized: bool) -> str:
        return (
            f"QFrame#windowFrame{{background:{THEME.background};"
            f"border:1px solid {THEME.border};"
            f"border-radius:{0 if maximized else 20}px;}}"
        )

    def _style_state(self, state: AssistantState) -> None:
        color = {
            AssistantState.IDLE: THEME.muted,
            AssistantState.LISTENING: THEME.cyan,
            AssistantState.PROCESSING: "#B86CFF",
            AssistantState.SPEAKING: THEME.cyan,
            AssistantState.SUCCESS: THEME.green,
            AssistantState.ERROR: THEME.red,
        }[state]
        self.state_label.setStyleSheet(
            f'color:{color};font:600 13px "Segoe UI";letter-spacing:1px;'
            "background:transparent;"
        )

    def sync_window_shape(self) -> None:
        self.frame.setStyleSheet(self._frame_style(self.isMaximized()))
        margin = 0 if self.isMaximized() else 10
        self.centralWidget().layout().setContentsMargins(margin, margin, margin, margin)

    def attach_controller(self, controller: QObject, cleanup_callback: Any = None) -> None:
        self._controller, self._cleanup_callback = controller, cleanup_callback

    @Slot()
    def show_control_center(self) -> None:
        self.control_center.configure(
            voice_enabled=self._voice_enabled,
            reduced_motion=self.motion.reduced_motion,
            privacy_mode=self._privacy_mode,
            status=self._environment_status,
        )
        self.control_center.show()
        self.control_center.raise_()
        self.control_center.activateWindow()

    def configure_control_center(
        self,
        *,
        voice_enabled: bool,
        privacy_mode: bool,
        status: str,
    ) -> None:
        self._voice_enabled = bool(voice_enabled)
        self._privacy_mode = bool(privacy_mode)
        self._environment_status = str(status)

    def set_reduced_motion(self, enabled: bool) -> None:
        self.motion = replace(self.motion, reduced_motion=bool(enabled))
        self.orb.motion = self.motion
        self.waveform.motion = self.motion
        self.orb._sync_movie_speed()

    def show_reminders(self, items: tuple[str, ...]) -> None:
        self.reminder_dialog.set_items(items)
        self.reminder_dialog.show()
        self.reminder_dialog.raise_()
        self.reminder_dialog.activateWindow()

    # These methods only emit Qt signals and are safe to call from worker threads.
    def set_state(self, state: str, message: str = "") -> None:
        self._state_requested.emit(str(state).strip().lower(), message)

    def set_audio_level(self, level: float) -> None:
        self._audio_requested.emit(float(level))

    def set_status_text(self, text: str) -> None:
        self._status_requested.emit(str(text))

    def set_transcript(self, text: str) -> None:
        self._transcript_requested.emit(str(text))

    def set_response_text(self, text: str) -> None:
        self._response_requested.emit(str(text))

    def set_source_count(self, count: int) -> None:
        self._source_count_requested.emit(max(0, int(count)))

    def set_suggestions(self, suggestions: Any) -> None:
        self._suggestions_requested.emit(tuple(suggestions or ()))

    def set_voice_only(self, enabled: bool) -> None:
        self._voice_only_requested.emit(bool(enabled))

    @Slot(str)
    def _apply_transcript(self, text: str) -> None:
        cleaned = text.strip()
        self.transcript_label.show_message(
            cleaned if cleaned else "", 25000 if cleaned else None
        )

    @Slot(int)
    def _apply_source_count(self, count: int) -> None:
        if count <= 0:
            self.source_label.show_message("")
            return
        noun = "source" if count == 1 else "sources"
        self.source_label.show_message(
            f"Live  •  {count} verified {noun}", 15000
        )

    @Slot(object)
    def _apply_suggestions(self, suggestions: Any) -> None:
        self.actions.set_suggestions(tuple(str(item) for item in suggestions))

    @Slot(str)
    def _apply_response(self, text: str) -> None:
        self.response_label.show_message(text, 25000)
        self.actions.set_response_available(
            bool(text.strip())
            and self.current_state
            not in {AssistantState.PROCESSING, AssistantState.LISTENING}
        )

    @Slot()
    def _copy_response(self) -> None:
        text = self.response_label.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.set_status_text("Copied to clipboard")

    @Slot(str, str)
    def _apply_state(self, name: str, message: str) -> None:
        try:
            state = AssistantState(name)
        except ValueError:
            LOGGER.warning("Ignored unknown UI state: %s", name)
            return
        self._return_timer.stop()
        self.current_state = state
        self.orb.set_state(state)
        self.waveform.set_state(state)
        self.state_label.setText(message.strip() or STATE_TEXT[state])
        self._style_state(state)
        self.actions.set_response_available(
            bool(self.response_label.text().strip())
            and state not in {AssistantState.PROCESSING, AssistantState.LISTENING}
        )
        self.actions.set_speaking(state == AssistantState.SPEAKING)
        if state == AssistantState.SUCCESS and self.motion.success_return_ms > 0:
            self._return_timer.start(self.motion.success_return_ms)
        elif state == AssistantState.ERROR and self.motion.error_return_ms:
            self._return_timer.start(self.motion.error_return_ms)

    @Slot(float)
    def _apply_audio(self, level: float) -> None:
        bounded = max(0.0, min(1.0, level))
        self.orb.set_audio_level(bounded)
        self.waveform.set_audio_level(bounded)

    @Slot()
    def _toggle_listening(self) -> None:
        self.microphone_requested.emit()

    @Slot()
    def _space_shortcut(self) -> None:
        # Preserve normal spaces while the command editor owns keyboard focus.
        if self.command_input.line_edit.hasFocus():
            self.command_input.line_edit.insert(" ")
        else:
            self._toggle_listening()

    @Slot()
    def _safe_escape(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showMinimized()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.WindowStateChange:
            self.orb.set_paused(self.isMinimized())
            self.sync_window_shape()
        super().changeEvent(event)

    def closeEvent(self, event: Any) -> None:
        self._return_timer.stop()
        self.orb.set_paused(True)
        if callable(self._cleanup_callback):
            try:
                self._cleanup_callback()
            except Exception:
                LOGGER.exception("Controller cleanup failed")
        event.accept()

    def nativeEvent(self, event_type: bytes, message: int) -> tuple[bool, int]:
        """Native edge hit testing keeps the frameless window smoothly resizable."""

        if sys.platform != "win32" or self.isMaximized():
            return super().nativeEvent(event_type, message)
        try:
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message != 0x0084:  # WM_NCHITTEST
                return super().nativeEvent(event_type, message)
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            point, margin = self.mapFromGlobal(QPoint(x, y)), 8
            left, right = point.x() < margin, point.x() >= self.width() - margin
            top, bottom = point.y() < margin, point.y() >= self.height() - margin
            hit = {(1, 0, 1, 0): 13, (0, 1, 1, 0): 14,
                   (1, 0, 0, 1): 16, (0, 1, 0, 1): 17}.get(
                (int(left), int(right), int(top), int(bottom))
            )
            hit = hit or (10 if left else 11 if right else 12 if top else 15 if bottom else 0)
            if hit:
                return True, hit
        except (AttributeError, TypeError, ValueError, OSError):
            pass
        return super().nativeEvent(event_type, message)


class _BackendWorker(QObject):
    """Run existing assistant, microphone, and TTS services off the UI thread."""

    chunk_received = Signal(int, str)
    activity = Signal(int, str)
    command_finished = Signal(int, object)
    speech_recognized = Signal(int, object)
    speech_finished = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, settings: Any, chatbot: Any, realtime: Any, memory: Any) -> None:
        super().__init__()
        self.settings, self.chatbot = settings, chatbot
        self.realtime, self.memory = realtime, memory
        self.memory_access_enabled = True
        self._stt: Any = None
        self._tts: Any = None
        self._automation_context: Any = None

    @Slot(int, str)
    def process_command(self, request_id: int, message: str) -> None:
        try:
            from automation import (
                AutomationContext,
                execute_automation_plan,
                handle_automation_command,
                looks_like_automation_request,
            )
            from chatbot import ChatResponse
            from memory import handle_memory_command, recall_memory
            from realtimeinfo import requires_fresh_information
            from safety import ensure_captain_address, speech_friendly_text

            self._automation_context = self._automation_context or AutomationContext(
                confirm_whatsapp_send=getattr(
                    self.settings,
                    "whatsapp_confirm_send",
                    True,
                )
            )
            active_memory = self.memory if self.memory_access_enabled else None
            result = handle_memory_command(message, active_memory)
            if result is None:
                result = recall_memory(message, active_memory)
            if result is not None:
                display = ensure_captain_address(result.message)
                response = ChatResponse(
                    display, speech_friendly_text(display), result.action, result.error
                )
            else:
                automation = (
                    None
                    if message.lstrip().startswith("/")
                    else handle_automation_command(message, self._automation_context)
                )
                if (
                    automation is None
                    and looks_like_automation_request(message)
                    and callable(getattr(self.chatbot, "plan_automation", None))
                ):
                    self.activity.emit(request_id, "Planning safe actions…")
                    commands = self.chatbot.plan_automation(message)
                    automation = execute_automation_plan(
                        commands, self._automation_context
                    )
                if automation is not None:
                    display = ensure_captain_address(automation.message)
                    suggestions = (
                        ("Confirm action", "Cancel action")
                        if automation.error == "confirmation_required"
                        and automation.data.get("can_confirm")
                        else ()
                    )
                    response = ChatResponse(
                        display_text=display,
                        speech_text=speech_friendly_text(display),
                        intent=automation.action,
                        error=automation.error,
                        emotion="serious" if suggestions else "neutral",
                        suggestions=suggestions,
                    )
                elif (
                    self.realtime is not None
                    and not message.lstrip().startswith("/")
                    and requires_fresh_information(message)
                ):
                    self.activity.emit(request_id, "Checking live sources…")
                    response = self.realtime.answer(message)
                else:
                    response = self.chatbot.respond(
                        message,
                        stream_callback=lambda chunk: self.chunk_received.emit(
                            request_id, chunk
                        ),
                        memory_store=active_memory,
                    )
            self._automation_context.observe(
                message, str(getattr(response, "display_text", response))
            )
            self.command_finished.emit(request_id, response)
        except Exception as exc:
            LOGGER.exception("Assistant command failed")
            self.failed.emit(request_id, str(exc) or type(exc).__name__)

    @Slot(int)
    def listen_once(self, request_id: int) -> None:
        try:
            from stt import PushToTalkSTT
            self._stt = self._stt or PushToTalkSTT(self.settings)
            self.speech_recognized.emit(request_id, self._stt.listen_once())
        except Exception as exc:
            LOGGER.exception("Microphone capture failed")
            self.failed.emit(request_id, str(exc) or type(exc).__name__)

    @Slot(int, str)
    def speak(self, request_id: int, text: str) -> None:
        try:
            from tts import EdgeTTSPlayer, TTSResult
            from tts_router import TTSRouter

            if self._tts is None:
                router = TTSRouter(
                    self.settings.tts_usage_file,
                    fish_segment_words=self.settings.tts_fish_segment_words,
                )
                self._tts = EdgeTTSPlayer(self.settings, router=router)
            queued = self._tts.speak(text)
            if not queued.success:
                self.speech_finished.emit(request_id, queued)
                return
            result = self._tts.wait(timeout=90)
            if result is None:
                result = TTSResult(False, "Voice playback timed out.", error="tts_timeout")
            self.speech_finished.emit(request_id, result)
        except Exception as exc:
            LOGGER.exception("Speech playback failed")
            self.failed.emit(request_id, str(exc) or type(exc).__name__)

    def stop_audio(self) -> None:
        if self._tts is not None:
            self._tts.stop(wait=False)

    def close(self) -> None:
        if self._tts is not None:
            self._tts.close()


class LiveVoiceThread(QThread):
    """Run real-time Gemini Multimodal Live Voice-to-Voice session in a dedicated worker thread."""

    state_changed = Signal(str, str)
    audio_level_changed = Signal(float)
    user_transcript_received = Signal(str)
    model_transcript_received = Signal(str)
    tool_executed = Signal(str, str)
    error_occurred = Signal(str)

    def __init__(self, settings: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._session: Any = None
        self._loop: Any = None
        self._stop_requested = False

    def run(self) -> None:
        import asyncio
        from live_voice import LiveVoiceSession, LiveVoiceCallbacks

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        callbacks = LiveVoiceCallbacks(
            on_state_change=lambda state, msg: self.state_changed.emit(str(state), str(msg)),
            on_audio_level=lambda lvl: self.audio_level_changed.emit(float(lvl)),
            on_user_transcript=lambda txt: self.user_transcript_received.emit(str(txt)),
            on_model_transcript=lambda txt: self.model_transcript_received.emit(str(txt)),
            on_tool_call=lambda name, args: self.tool_executed.emit(str(name), f"Executing {name}…"),
            on_tool_result=lambda name, res: self.tool_executed.emit(
                str(name), str(res.get("message", "Done")) if isinstance(res, dict) else "Done"
            ),
            on_error=lambda err: self.error_occurred.emit(str(err)),
        )

        self._session = LiveVoiceSession(
            self.settings,
            output_fn=lambda msg: None,
            callbacks=callbacks,
        )

        async def run_live() -> None:
            self.state_changed.emit("listening", "Live Voice Active · Speak freely")
            while not self._stop_requested:
                retry, duration = await self._session._run_session()
                if not retry or self._stop_requested:
                    break
                await asyncio.sleep(0.3)

        try:
            self._loop.run_until_complete(run_live())
        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            if self._session is not None:
                self._session.close()
            self.state_changed.emit("idle", "Ready")
            try:
                pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                if pending:
                    for t in pending:
                        t.cancel()
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop_requested = True
        if self._session is not None:
            self._session.stop()


class IntegratedAssistantController(QObject):
    """Connect the presentation layer to both Gemini Live V2V and conversational services."""

    command_requested = Signal(int, str)
    listen_requested = Signal(int)
    speak_requested = Signal(int, str)

    def __init__(
        self,
        window: DarkShadowWindow,
        *,
        settings: Any = None,
        chatbot: Any = None,
        realtime: Any = None,
        memory: Any = None,
    ) -> None:
        super().__init__(window if isinstance(window, QObject) else None)
        self.window = window
        self._request_id = 0
        self._streamed_text = ""
        self._closed = False
        self._cancelled_speech_ids: set[int] = set()
        self._last_user_message = ""
        self._voice_replies_enabled = True
        self._privacy_mode = False
        self._live_voice_thread: LiveVoiceThread | None = None
        
        self._listen_timer = QTimer(self)
        self._listen_timer.setSingleShot(True)
        self._listen_timer.setInterval(15_000)  # 15s STT timeout
        self._listen_timer.timeout.connect(
            lambda: self.window.set_state("idle", "Listening timed out")
        )

        self._owns_services = settings is None
        if settings is None:
            from chatbot import DarkShadowChatbot
            from config import load_settings
            from memory import SQLiteMemoryStore
            from realtimeinfo import RealtimeInfoService
            from tts_router import TTSRouter

            settings = load_settings()
            router = TTSRouter(
                settings.tts_usage_file,
                fish_segment_words=settings.tts_fish_segment_words,
            )
            chatbot = DarkShadowChatbot(settings, tts_router=router)
            realtime = RealtimeInfoService(settings)
            memory = (
                SQLiteMemoryStore(settings.memory_database_path)
                if settings.memory_enabled else None
            )
        self.settings, self.chatbot = settings, chatbot
        self.realtime, self.memory = realtime, memory

        self.thread = QThread(self)
        self.worker = _BackendWorker(
            self.settings, self.chatbot, self.realtime, self.memory
        )
        self.worker.moveToThread(self.thread)
        self.command_requested.connect(self.worker.process_command)
        self.listen_requested.connect(self.worker.listen_once)
        self.speak_requested.connect(self.worker.speak)
        self.worker.chunk_received.connect(self._on_chunk)
        self.worker.activity.connect(self._on_activity)
        self.worker.command_finished.connect(self._on_command_finished)
        self.worker.speech_recognized.connect(self._on_speech_recognized)
        self.worker.speech_finished.connect(self._on_speech_finished)
        self.worker.failed.connect(self._on_failure)
        window.command_submitted.connect(self.submit_command)
        window.microphone_requested.connect(self.request_microphone)
        window.suggestion_selected.connect(self.submit_command)
        window.stop_speaking_requested.connect(self.stop_speaking)
        window.regenerate_requested.connect(self.regenerate_response)
        window.preferences_changed.connect(self._apply_preferences)
        window.clear_chat_requested.connect(self.clear_chat_context)
        window.reminders_requested.connect(self.show_reminders)
        self._refresh_control_center()
        self.thread.start()

    def _next_request(self) -> int:
        self._request_id += 1
        return self._request_id

    @property
    def is_live_voice_active(self) -> bool:
        return self._live_voice_thread is not None and self._live_voice_thread.isRunning()

    @Slot(str)
    def submit_command(self, message: str) -> None:
        message = message.strip()
        if not message:
            return
        if self.is_live_voice_active:
            self.stop_live_voice()
        self._last_user_message = message
        if self.window.current_state == AssistantState.SPEAKING:
            self._cancelled_speech_ids.add(self._request_id)
            self.worker.stop_audio()
        request_id = self._next_request()
        self._streamed_text = ""
        self.window.set_transcript(message)
        self.window.set_response_text("")
        self.window.set_source_count(0)
        self.window.set_suggestions(())
        self.window.set_state("processing")
        self.command_requested.emit(request_id, message)

    @Slot()
    def regenerate_response(self) -> None:
        if self._last_user_message:
            self.submit_command(self._last_user_message)

    @Slot()
    def request_microphone(self) -> None:
        """Toggle real-time Gemini Live Voice-to-Voice session on/off."""
        if self.is_live_voice_active:
            self.stop_live_voice()
        else:
            self.start_live_voice()

    def start_live_voice(self) -> None:
        if self.window.current_state == AssistantState.SPEAKING:
            self.stop_speaking()
        self.window.set_transcript("")
        self.window.set_response_text("")
        self.window.set_source_count(0)
        self.window.set_suggestions(())
        self.window.set_state("listening", "Connecting to Gemini Live…")

        self._live_voice_thread = LiveVoiceThread(self.settings, self)
        self._live_voice_thread.state_changed.connect(self._on_live_state_changed)
        self._live_voice_thread.audio_level_changed.connect(self.window.set_audio_level)
        self._live_voice_thread.user_transcript_received.connect(self._on_live_user_transcript)
        self._live_voice_thread.model_transcript_received.connect(self._on_live_model_transcript)
        self._live_voice_thread.tool_executed.connect(self._on_live_tool_executed)
        self._live_voice_thread.error_occurred.connect(self._on_live_error)
        self._live_voice_thread.start()

    def stop_live_voice(self) -> None:
        if self._live_voice_thread is not None:
            thread = self._live_voice_thread
            self._live_voice_thread = None
            thread.stop()
            thread.wait(1200)
        self.window.set_state("idle", "Ready")
        self.window.set_audio_level(0.0)

    def close(self) -> None:
        """Cleanly tear down worker thread, live voice, and audio resources."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self.stop_live_voice()
        if hasattr(self, "worker") and hasattr(self.worker, "close"):
            self.worker.close()
        if hasattr(self, "thread") and hasattr(self.thread, "quit"):
            self.thread.quit()
            self.thread.wait(600)

    @Slot(str, str)
    def _on_live_state_changed(self, state: str, message: str) -> None:
        self.window.set_state(state, message)

    @Slot(str)
    def _on_live_user_transcript(self, text: str) -> None:
        self.window.set_transcript(text)

    @Slot(str)
    def _on_live_model_transcript(self, text: str) -> None:
        self.window.set_response_text(text)

    @Slot(str, str)
    def _on_live_tool_executed(self, name: str, message: str) -> None:
        self.window.set_status_text(f"⚡ {message}")

    @Slot(str)
    def _on_live_error(self, message: str) -> None:
        self.window.set_state("error", "Live session disconnected")
        self.window.set_response_text(f"Live voice status: {message}")

    @Slot(int, str)
    def _on_chunk(self, request_id: int, chunk: str) -> None:
        if request_id == self._request_id:
            self._streamed_text += chunk
            self.window.set_response_text(self._streamed_text)

    @Slot(int, str)
    def _on_activity(self, request_id: int, text: str) -> None:
        if request_id == self._request_id:
            self.window.set_status_text(text)

    @Slot(int, object)
    def _on_command_finished(self, request_id: int, response: Any) -> None:
        if request_id != self._request_id:
            return
        display = str(getattr(response, "display_text", response))
        speech = str(getattr(response, "speech_text", display))
        sources = tuple(getattr(response, "sources", ()) or ())
        visible_answer = display.split("\n\nSources:", 1)[0].strip()
        self.window.set_response_text(visible_answer)
        self.window.set_source_count(len(sources))
        self.window.set_suggestions(getattr(response, "suggestions", ()) or ())
        if getattr(response, "error", None):
            self.window.set_state("error", "Couldn’t complete that")
            return
        self.window.set_state("success")
        if speech.strip() and self._voice_replies_enabled:
            QTimer.singleShot(450, lambda: self._start_speech(request_id, speech))

    def _start_speech(self, request_id: int, speech: str) -> None:
        if request_id == self._request_id and not self._closed:
            self.window.set_state("speaking")
            self.speak_requested.emit(request_id, speech)

    @Slot()
    def stop_speaking(self) -> None:
        if self.window.current_state != AssistantState.SPEAKING:
            return
        self._cancelled_speech_ids.add(self._request_id)
        self.worker.stop_audio()
        self.window.set_state("idle", "Speech stopped")

    @Slot(int, object)
    def _on_speech_recognized(self, request_id: int, result: Any) -> None:
        if request_id != self._request_id:
            return
        self._listen_timer.stop()
        text = str(getattr(result, "text", "")).strip()
        if getattr(result, "success", False) and text:
            self.submit_command(text)
        else:
            message = str(
                getattr(result, "message", "") or "I couldn’t hear that clearly."
            )
            self.window.set_response_text(message)
            self.window.set_state(
                "error",
                "I couldn’t hear that clearly",
            )

    @Slot(int, object)
    def _on_speech_finished(self, request_id: int, result: Any) -> None:
        if request_id in self._cancelled_speech_ids:
            self._cancelled_speech_ids.discard(request_id)
            return
        if request_id != self._request_id:
            return
        if getattr(result, "success", False):
            self.window.set_state("idle")
        else:
            message = str(
                getattr(result, "message", "") or "Voice playback is unavailable."
            )
            self.window.set_response_text(message)
            self.window.set_state(
                "error",
                "Voice playback unavailable",
            )

    @Slot(int, str)
    def _on_failure(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._listen_timer.stop()
            self.window.set_source_count(0)
            self.window.set_response_text(message)
            self.window.set_state("error", "Couldn’t complete that")

    def _refresh_control_center(self) -> None:
        model = str(getattr(self.settings, "model", "configured"))
        voice = str(getattr(self.settings, "tts_provider", "auto"))
        memory_status = (
            "paused"
            if self._privacy_mode
            else ("on" if self.memory is not None else "off")
        )
        live_status = "on" if self.realtime is not None else "off"
        self.window.configure_control_center(
            voice_enabled=self._voice_replies_enabled,
            privacy_mode=self._privacy_mode,
            status=(
                f"AI: {model}  •  Voice: {voice}  •  "
                f"Memory: {memory_status}  •  Live search: {live_status}"
            ),
        )

    @Slot(bool, bool, bool)
    def _apply_preferences(
        self,
        voice_enabled: bool,
        reduced_motion: bool,
        privacy_mode: bool,
    ) -> None:
        if not voice_enabled and self.window.current_state == AssistantState.SPEAKING:
            self.stop_speaking()
        self._voice_replies_enabled = bool(voice_enabled)
        self._privacy_mode = bool(privacy_mode)
        self.worker.memory_access_enabled = not self._privacy_mode
        self.window.set_reduced_motion(reduced_motion)
        self._refresh_control_center()
        self.window.set_response_text("Runtime preferences updated.")
        self.window.set_state("success", "Settings updated")

    @Slot()
    def clear_chat_context(self) -> None:
        clear = getattr(self.chatbot, "clear_history", None)
        if callable(clear):
            clear()
        self.worker._automation_context = None
        self.window.set_suggestions(())
        self.window.set_response_text("Conversation context cleared. Saved memory is unchanged.")
        self.window.set_state("success", "Chat context cleared")

    @Slot()
    def show_reminders(self) -> None:
        if self._privacy_mode or self.memory is None:
            self.window.show_reminders(())
            return
        try:
            reminders = self.memory.list_reminders(limit=20)
            items = tuple(
                f"#{item.id}  {item.due_at.astimezone().strftime('%d %b, %I:%M %p')}"
                f"\n{item.message}"
                for item in reminders
            )
        except Exception as exc:
            LOGGER.warning(
                "Could not list reminders (type=%s)", type(exc).__name__
            )
            items = ("Reminders are temporarily unavailable.",)
        self.window.show_reminders(items)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_live_voice()
        self.worker.stop_audio()
        self.thread.quit()
        if not self.thread.wait(1800):
            LOGGER.warning("Assistant worker did not stop before timeout")
        self.worker.close()
        if self._owns_services:
            if self.memory is not None:
                self.memory.close()
            if self.realtime is not None:
                self.realtime.close()
            if self.chatbot is not None:
                self.chatbot.close()


class DemoController(QObject):
    """Cycle through every state and simulate audio for standalone testing."""

    SEQUENCE = (
        (AssistantState.IDLE, 2200),
        (AssistantState.LISTENING, 4200),
        (AssistantState.PROCESSING, 3500),
        (AssistantState.SPEAKING, 4300),
        (AssistantState.SUCCESS, 2500),
        (AssistantState.ERROR, 3000),
        (AssistantState.IDLE, 2500),
    )

    def __init__(self, window: DarkShadowWindow) -> None:
        super().__init__(window)
        self.window, self._index, self._phase = window, -1, 0.0
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._advance_state)
        self._audio_timer = QTimer(self)
        self._audio_timer.setInterval(50)
        self._audio_timer.timeout.connect(self._simulate_audio)
        self._audio_timer.start()
        QTimer.singleShot(450, self._advance_state)

    @Slot()
    def _advance_state(self) -> None:
        self._index = (self._index + 1) % len(self.SEQUENCE)
        state, duration = self.SEQUENCE[self._index]
        message = "Microphone unavailable" if state == AssistantState.ERROR else ""
        self.window.set_state(state.value, message)
        if state == AssistantState.LISTENING:
            self.window.set_transcript("Try saying: Open YouTube")
        elif state == AssistantState.PROCESSING:
            self.window.set_transcript("Open YouTube")
            self.window.set_response_text("Working on it...")
        elif state == AssistantState.SPEAKING:
            self.window.set_response_text("Opening YouTube for you, Captain.")
        elif state == AssistantState.SUCCESS:
            self.window.set_response_text("Command completed.")
        self._state_timer.start(duration)

    @Slot()
    def _simulate_audio(self) -> None:
        if self.window.current_state in {
            AssistantState.LISTENING, AssistantState.SPEAKING
        }:
            self._phase += .31
            level = .16 + .48 * abs(math.sin(self._phase)) + random.uniform(0, .22)
            self.window.set_audio_level(min(1, level))
        else:
            self.window.set_audio_level(0)


# Compatibility for the previous GUI entry-point name.
DarkShadowMainWindow = DarkShadowWindow


def _setup_sigint_handler(app: QApplication, window: DarkShadowWindow) -> None:
    import signal
    timer = QTimer(window)
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    def handle_sigint(sig: int, frame: Any) -> None:
        window.close()
        app.quit()

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except Exception:
        pass


def main(
    *,
    demo: bool = False,
    integrated: bool = True,
    settings: Any = None,
    chatbot: Any = None,
    realtime: Any = None,
    memory: Any = None,
) -> int:
    """Launch DarkShadow in integrated or explicitly requested demo mode."""

    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(sys.argv)
    app.setApplicationName("DarkShadow")
    app.setOrganizationName("DarkShadow")
    app.setStyle("Fusion")
    window = DarkShadowWindow()
    _setup_sigint_handler(app, window)
    if demo:
        controller: QObject = DemoController(window)
        window.attach_controller(controller)
    elif integrated:
        controller = IntegratedAssistantController(
            window,
            settings=settings,
            chatbot=chatbot,
            realtime=realtime,
            memory=memory,
        )
        window.attach_controller(controller, controller.shutdown)
    window.show()
    return app.exec() if owns_application else 0


def _standalone_launch_options(argv: list[str]) -> tuple[bool, bool]:
    """Return ``(demo, integrated)`` for a direct ``ui.py`` launch."""

    demo = "--demo" in argv
    return demo, not demo


if __name__ == "__main__":
    standalone_demo, standalone_integrated = _standalone_launch_options(sys.argv[1:])
    if standalone_demo:
        # Remove our switch before Qt parses its own application arguments.
        sys.argv.remove("--demo")
    raise SystemExit(
        main(demo=standalone_demo, integrated=standalone_integrated)
    )
