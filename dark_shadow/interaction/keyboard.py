"""
DARK SHADOW® - Keyboard Interaction & Global Windows Hotkeys
Provides system-wide hotkeys (RegisterHotKey) and widget shortcuts.
"""

import sys
import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QKeyEvent


# Windows API constants for RegisterHotKey
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 9101


class WindowsGlobalHotkey(QObject):
    """
    Listens for Windows global hotkeys across the entire operating system,
    allowing the user to wake or hide DARK SHADOW from any active window.
    """
    activated = Signal()

    def __init__(self, modifier_flags=MOD_CONTROL | MOD_SHIFT, vk_code=ord('D'), parent=None):
        super().__init__(parent)
        self.modifier_flags = modifier_flags
        self.vk_code = vk_code
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start background message loop for global hotkey."""
        if sys.platform != "win32":
            return
        self.running = True
        self._thread = threading.Thread(target=self._hotkey_loop, daemon=True, name="DS-GlobalHotkey")
        self._thread.start()

    def stop(self):
        """Unregister hotkey and terminate message loop."""
        self.running = False
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass

    def _hotkey_loop(self):
        """Windows API message pump for WM_HOTKEY."""
        user32 = ctypes.windll.user32

        # Register hotkey
        success = user32.RegisterHotKey(
            None,
            HOTKEY_ID,
            self.modifier_flags | MOD_NOREPEAT,
            self.vk_code
        )
        if not success:
            # Fallback without MOD_NOREPEAT if unsupported on older subsystem
            user32.RegisterHotKey(
                None,
                HOTKEY_ID,
                self.modifier_flags,
                self.vk_code
            )

        msg = wintypes.MSG()
        while self.running:
            # Non-blocking or 100ms peek to allow graceful shutdown
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.activated.emit()

            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


class KeyboardController:
    """
    Handles local Qt keyboard shortcuts when overlay is focused.
    """

    def __init__(self, on_toggle_activation: Callable[[], None],
                 on_toggle_listening: Callable[[], None]):
        self.on_toggle_activation = on_toggle_activation
        self.on_toggle_listening = on_toggle_listening

    def handle_key_press(self, event: QKeyEvent) -> bool:
        """Process local key presses."""
        key = event.key()

        if key == Qt.Key.Key_Escape:
            # Deactivate / hide
            self.on_toggle_activation()
            return True

        elif key == Qt.Key.Key_Space:
            # Toggle listening state
            self.on_toggle_listening()
            return True

        return False
