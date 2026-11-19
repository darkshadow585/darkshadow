"""
DarkShadow Desktop — Option B (Python + Embedded Transparent WebGL2 Overlay)
===========================================================================
All 5 Upgrades integrated for Windows 11 Desktop:
  1. Voice Engine: Offline wake-word support ("Hey Dark Shadow") + 3-band FFT + interruptible TTS
  2. Screen Vision & Windows OS Tools: Gemini function calling + mss monitor vision (Zero-Camera)
  3. Long-Term Semantic Memory: SQLite + gemini-embedding-2 + auto episodic summaries
  4. Proactive Desktop Sentinel: Due reminders + low-battery particle shield alerts
  5. Embedded WebGL2 6,000-Particle Engine: Bottom rise -> 3D Sphere / DNA Helix / Plasma Torus / Shield Cube

Run on Windows 11:
  pip install -r windows_requirements.txt
  python darkshadow_desktop.py
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from memory_engine import SemanticMemoryEngine
from sentinel_monitor import DesktopSentinel
from voice_engine import VoiceEngine
from windows_tools import WindowsToolExecutor, check_hard_shields, get_gemini_tool_declarations

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
SYSTEM_INSTRUCTION = (
    "You are DarkShadow, Captain's elite Windows 11 desktop AI co-pilot. "
    "Speak naturally in crisp Hindi/Hinglish or English (1-3 spoken sentences). "
    "Never use markdown asterisks or stage directions. Use tools whenever Captain asks to "
    "open apps, inspect the monitor screen, adjust brightness, save memory, or set reminders."
)

# Native Win32 constants for strict Desktop-Behind-Apps (non-overlapping) window layering
_HWND_BOTTOM = 1
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_NOOWNERZORDER = 0x0200
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000


def _apply_win32_layer(hwnd_int: int, behind_apps: bool) -> None:
    """Keep DarkShadow strictly behind all open Windows apps (never overlapping/blocking them)."""
    if sys.platform != "win32" or not hwnd_int:
        return
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_long.restype = ctypes.c_ssize_t

        hwnd = ctypes.c_void_p(hwnd_int)
        ex_style = int(get_long(hwnd, _GWL_EXSTYLE))
        # Always click-through & non-activating so active apps are never interrupted
        new_style = ex_style | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT
        if new_style != ex_style:
            set_long(hwnd, _GWL_EXSTYLE, new_style)

        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_NOOWNERZORDER
        if behind_apps:
            # Only strip topmost if currently topmost (avoids any Z-order flicker)
            if ex_style & _WS_EX_TOPMOST:
                user32.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_NOTOPMOST), 0, 0, 0, 0, flags)
            user32.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_BOTTOM), 0, 0, 0, 0, flags)
        else:
            user32.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_TOPMOST), 0, 0, 0, 0, flags)
    except Exception:
        pass


class DarkShadowBridge(QObject):
    fx_state = Signal(str, str)
    fx_audio = Signal(float, float, float)
    fx_caption = Signal(str, str)


class DarkShadowDesktopApp(QWebEngineView):
    """Frameless, transparent WebGL2 desktop wallpaper-layer overlay (stays behind all apps)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DarkShadow Desktop AI")
        # Default: strictly BEHIND all running applications so open apps are never overlapped/blocked
        self._stay_behind_apps = True
        self._apply_qt_window_flags()

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.page().setBackgroundColor(Qt.transparent)
        self.setContextMenuPolicy(Qt.NoContextMenu)

        # Use availableGeometry so DarkShadow never overlaps the Windows Taskbar either
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self._page_ready = False
        self._turns: list[tuple[str, str]] = []
        self._api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self._model = os.getenv("DARKSHADOW_MODEL", "gemini-2.5-flash").strip()
        self._client = genai.Client(api_key=self._api_key) if (HAS_GENAI and self._api_key) else None

        self.memory = SemanticMemoryEngine(APP_DIR / ".darkshadow" / "memory.db", self._client)
        self.tools = WindowsToolExecutor(self.memory, self._client)

        self.bridge = DarkShadowBridge()
        self.bridge.fx_state.connect(self._push_fx_state)
        self.bridge.fx_audio.connect(self._push_fx_audio)
        self.bridge.fx_caption.connect(self._push_fx_caption)

        self.voice = VoiceEngine(
            on_audio_fft=lambda b, m, t: self.bridge.fx_audio.emit(b, m, t),
            on_wake=self._on_wake_word,
            on_command=self._on_voice_command,
            on_sleep=self._on_sleep_command,
        )
        self.sentinel = DesktopSentinel(self.memory, self._on_sentinel_alert)

        # Periodic Z-order guard keeps DarkShadow behind every newly opened/focused app on Windows 11
        self._z_guard_timer = QTimer(self)
        self._z_guard_timer.setInterval(500)
        self._z_guard_timer.timeout.connect(self._enforce_window_layer)
        self._z_guard_timer.start()

        self.loadFinished.connect(self._on_webgl_loaded)
        self.load(QUrl.fromLocalFile(str(APP_DIR / "particle_engine.html")))
        self._setup_tray()

    def _apply_qt_window_flags(self) -> None:
        base_flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if self._stay_behind_apps:
            self.setWindowFlags(base_flags | Qt.WindowStaysOnBottomHint)
        else:
            self.setWindowFlags(base_flags | Qt.WindowStaysOnTopHint)

    def _enforce_window_layer(self) -> None:
        if self._stay_behind_apps:
            self.lower()
        _apply_win32_layer(int(self.winId()), behind_apps=self._stay_behind_apps)

    def _set_layer_mode(self, behind_apps: bool) -> None:
        self._stay_behind_apps = behind_apps
        self._apply_qt_window_flags()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.show()
        self._enforce_window_layer()
        if hasattr(self, "_act_behind_apps"):
            self._act_behind_apps.setChecked(behind_apps)
        if hasattr(self, "_act_float_top"):
            self._act_float_top.setChecked(not behind_apps)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(50, self._enforce_window_layer)

    def _js(self, code: str) -> None:
        if self._page_ready:
            self.page().runJavaScript(code)

    def _on_webgl_loaded(self, ok: bool) -> None:
        self._page_ready = ok
        self._enforce_window_layer()
        self.voice.start()
        self.sentinel.start()
        # Summon once on launch so Captain immediately sees particles rise from the bottom edge!
        QTimer.singleShot(350, lambda: self._on_wake_word(""))

    def _push_fx_state(self, state: str, shape: str) -> None:
        self._js(f"window.DarkShadowFX && window.DarkShadowFX.setState({json.dumps(state)}, {json.dumps(shape)});")
        # Always stay click-through & behind open apps so user's active screen is never blocked
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._enforce_window_layer()

    def _push_fx_audio(self, bass: float, mid: float, treble: float) -> None:
        self._js(f"window.DarkShadowFX && window.DarkShadowFX.setAudio({bass:.3f}, {mid:.3f}, {treble:.3f});")

    def _push_fx_caption(self, main_text: str, sub_text: str) -> None:
        self._js(f"window.DarkShadowFX && window.DarkShadowFX.setCaption({json.dumps(main_text)}, {json.dumps(sub_text)});")

    def _setup_tray(self) -> None:
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        grad = QRadialGradient(16, 16, 14)
        grad.setColorAt(0.0, QColor("#00D2FF"))
        grad.setColorAt(0.65, QColor("#765CFF"))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(2, 2, 28, 28)
        p.end()

        self.tray = QSystemTrayIcon(QIcon(pix), self)
        menu = QMenu()
        menu.addAction(self._act("Summon DarkShadow (Bottom -> Sphere)", lambda: self._on_wake_word("")))
        menu.addAction(self._act("Sleep / Dissolve Particles", self._on_sleep_command))
        menu.addSeparator()
        self._act_behind_apps = self._act(
            "Desktop Layer: Stay Behind Apps (No Overlap)",
            lambda: self._set_layer_mode(True),
            checkable=True,
            checked=True,
        )
        self._act_float_top = self._act(
            "Overlay Mode: Float On Top of Apps",
            lambda: self._set_layer_mode(False),
            checkable=True,
            checked=False,
        )
        menu.addAction(self._act_behind_apps)
        menu.addAction(self._act_float_top)
        menu.addSeparator()
        menu.addAction(self._act("Morph: Sphere", lambda: self.bridge.fx_state.emit("listening", "sphere")))
        menu.addAction(self._act("Morph: DNA Helix", lambda: self.bridge.fx_state.emit("thinking", "helix")))
        menu.addAction(self._act("Morph: Plasma Torus", lambda: self.bridge.fx_state.emit("speaking", "torus")))
        menu.addAction(self._act("Morph: Shield Cube", lambda: self.bridge.fx_state.emit("alert", "shield")))
        menu.addSeparator()
        menu.addAction(self._act("Exit DarkShadow", self._quit_app))
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("DarkShadow Desktop AI — Behind Apps (No Overlap)")
        self.tray.show()

    def _act(self, label: str, fn, checkable: bool = False, checked: bool = False) -> QAction:
        act = QAction(label, self)
        act.setCheckable(checkable)
        if checkable:
            act.setChecked(checked)
        act.triggered.connect(fn)
        return act

    def _on_wake_word(self, inline_command: str) -> None:
        def _worker():
            self.voice.active = True
            self.bridge.fx_state.emit("rising", "sphere")
            self.bridge.fx_caption.emit("Haanji Captain, sun raha hoon...", "HEY DARK SHADOW")
            time.sleep(1.55)
            if inline_command:
                self._process_command(inline_command)
            else:
                self.bridge.fx_state.emit("speaking", "torus")
                self.voice.speak("Haanji Captain! DarkShadow active hai, bataiye kya hukum hai?")
                if self.voice.active:
                    self.bridge.fx_state.emit("listening", "sphere")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_voice_command(self, text: str) -> None:
        threading.Thread(target=self._process_command, args=(text,), daemon=True).start()

    def _on_sleep_command(self) -> None:
        def _worker():
            self.voice.active = False
            self.voice.interrupt_speech()
            self.memory.archive_episode(self._turns)
            self._turns.clear()
            self.bridge.fx_caption.emit("Standby par ja raha hoon, Captain.", "")
            self.bridge.fx_state.emit("dissolving", "sphere")
            time.sleep(1.3)
            self.bridge.fx_caption.emit("", "")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_sentinel_alert(self, alert_text: str) -> None:
        def _worker():
            was_active = self.voice.active
            self.bridge.fx_state.emit("rising", "shield")
            self.bridge.fx_caption.emit(alert_text, "DARKSHADOW SENTINEL")
            time.sleep(1.4)
            self.bridge.fx_state.emit("alert", "shield")
            self.voice.speak(alert_text)
            if not was_active:
                self.bridge.fx_state.emit("dissolving", "shield")
                time.sleep(1.3)
                self.bridge.fx_caption.emit("", "")
            else:
                self.bridge.fx_state.emit("listening", "sphere")

        threading.Thread(target=_worker, daemon=True).start()

    def _process_command(self, user_text: str) -> None:
        self.bridge.fx_caption.emit(user_text, "CAPTAIN")

        # Hard Safety Shield check (zero LLM tokens spent)
        blocked = check_hard_shields(user_text)
        if blocked:
            self.bridge.fx_state.emit("alert", "shield")
            self.bridge.fx_caption.emit(blocked, "SECURITY SHIELD")
            self.voice.speak(blocked)
            self.bridge.fx_state.emit("listening", "sphere")
            return

        self.bridge.fx_state.emit("thinking", "helix")
        reply = self._generate_with_tools(user_text)
        self._turns.append((user_text, reply))
        self._turns = self._turns[-10:]

        self.bridge.fx_state.emit("speaking", "torus")
        self.bridge.fx_caption.emit(reply, "DARKSHADOW AI")
        self.voice.speak(reply)
        if self.voice.active:
            self.bridge.fx_state.emit("listening", "sphere")

    def _generate_with_tools(self, prompt: str) -> str:
        if self._client is None:
            return (
                "Captain, .env file mein GEMINI_API_KEY add kijiye. "
                "Abhi mera WebGL2 particle core, FFT voice aur Sentinel ready hain!"
            )

        recalled = self.memory.recall_relevant(prompt, limit=4)
        sys_inst = SYSTEM_INSTRUCTION
        if recalled:
            sys_inst += "\n\nRECALLED LONG-TERM MEMORY FOR CAPTAIN:\n" + "\n".join(f"- {r}" for r in recalled)

        contents: list[Any] = []
        for u, a in self._turns[-6:]:
            contents.append({"role": "user", "parts": [{"text": u}]})
            contents.append({"role": "model", "parts": [{"text": a}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        tool_decls = [types.FunctionDeclaration(**d) for d in get_gemini_tool_declarations()]
        cfg = types.GenerateContentConfig(
            system_instruction=sys_inst,
            tools=[types.Tool(function_declarations=tool_decls)],
        )

        try:
            resp = self._client.models.generate_content(model=self._model, contents=contents, config=cfg)
            calls = getattr(resp, "function_calls", None) or []
            if calls:
                tool_outputs = []
                for call in calls[:4]:
                    out = self.tools.execute(str(call.name), dict(call.args or {}))
                    tool_outputs.append(f"{call.name}: {out}")
                follow = self._client.models.generate_content(
                    model=self._model,
                    contents=f"Captain asked: {prompt}\nTool results:\n" + "\n".join(tool_outputs) + "\nRespond concisely in Hinglish.",
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
                )
                return (follow.text or "").strip() or tool_outputs[0]
            return (resp.text or "").strip() or "Captain, dobara boliye."
        except Exception as exc:
            return f"Captain, AI engine error: {type(exc).__name__}"

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._on_sleep_command()
        elif event.key() == Qt.Key_F8:
            self._on_wake_word("")
        else:
            super().keyPressEvent(event)

    def _quit_app(self) -> None:
        self._z_guard_timer.stop()
        self.sentinel.stop()
        self.voice.stop()
        self.memory.archive_episode(self._turns)
        self.tray.hide()
        QApplication.quit()


def main() -> int:
    # Enable transparent WebGL2 GPU acceleration inside PySide6 QWebEngineView on Windows 11
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-webgl --ignore-gpu-blocklist")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = DarkShadowDesktopApp()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
