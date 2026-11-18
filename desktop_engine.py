"""Level 5: Universal Windows UI Automation & Desktop GUI Engine for DarkShadow.

Provides OS-level application inspection and control (buttons, edits, menus)
across any native Windows desktop software (Notepad, File Explorer, VS Code,
Calculator, Settings, etc.) using Windows Accessibility / UI Automation.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DesktopControl:
    """Represents one native desktop UI control."""

    name: str
    control_type: str
    automation_id: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    enabled: bool = True
    hwnd: int = 0


class ScreenDeltaDetector:
    """Jugaad 2: Lightweight CPU-based pixel delta detector for screen frames.

    Computes normalized Mean Absolute Difference (MAD) between consecutive downsampled
    grayscale thumbnails (64x64). If delta < threshold (e.g. 0.08), the screen is considered
    unchanged and frame transmission can be skipped, saving 100% of idle vision tokens.
    """

    def __init__(
        self,
        threshold: float = 0.08,
        thumbnail_size: tuple[int, int] = (64, 64),
    ) -> None:
        self.threshold = threshold
        self.thumbnail_size = thumbnail_size
        self._last_thumbnail_bytes: bytes | None = None
        self._last_delta: float = 1.0
        self._frames_checked: int = 0
        self._frames_skipped: int = 0
        self._frames_sent: int = 0

    def compute_delta(self, image: Any) -> float:
        """Compute normalized delta [0.0 - 1.0] compared to the previous thumbnail."""
        if image is None:
            return 0.0
        try:
            thumb = image.resize(self.thumbnail_size).convert("L")
            thumb_bytes = thumb.tobytes()
        except Exception as exc:
            LOGGER.debug("Failed to compute thumbnail: %s", exc)
            return 1.0

        if self._last_thumbnail_bytes is None:
            self._last_thumbnail_bytes = thumb_bytes
            self._last_delta = 1.0
            return 1.0

        prev = self._last_thumbnail_bytes
        curr = thumb_bytes
        n = len(curr)
        if len(prev) != n or n == 0:
            self._last_thumbnail_bytes = thumb_bytes
            self._last_delta = 1.0
            return 1.0

        total_diff = sum(abs(b1 - b2) for b1, b2 in zip(curr, prev))
        delta = total_diff / (n * 255.0)
        self._last_delta = delta
        return delta

    def should_send_frame(self, image: Any, force: bool = False) -> tuple[bool, float]:
        """Determine whether the current frame should be sent.

        Returns:
            (should_send: bool, delta: float)
        """
        self._frames_checked += 1
        if force:
            try:
                thumb = image.resize(self.thumbnail_size).convert("L")
                self._last_thumbnail_bytes = thumb.tobytes()
            except Exception:
                pass
            self._frames_sent += 1
            return True, 1.0

        delta = self.compute_delta(image)
        if delta >= self.threshold or self._last_thumbnail_bytes is None:
            try:
                thumb = image.resize(self.thumbnail_size).convert("L")
                self._last_thumbnail_bytes = thumb.tobytes()
            except Exception:
                pass
            self._frames_sent += 1
            return True, delta
        else:
            self._frames_skipped += 1
            return False, delta

    def reset(self) -> None:
        """Reset thumbnail history."""
        self._last_thumbnail_bytes = None
        self._last_delta = 1.0

    @property
    def stats(self) -> dict[str, Any]:
        """Return token-saving statistics."""
        saved_ratio = (
            (self._frames_skipped / self._frames_checked)
            if self._frames_checked > 0
            else 0.0
        )
        return {
            "frames_checked": self._frames_checked,
            "frames_sent": self._frames_sent,
            "frames_skipped": self._frames_skipped,
            "tokens_saved_approx": self._frames_skipped * 258,
            "saving_percentage": round(saved_ratio * 100, 1),
            "last_delta": round(self._last_delta, 4),
        }


class WindowsUIAutomationEngine:
    """Universal OS-level desktop automation using Windows UI Automation COM APIs and ctypes."""

    _instance: WindowsUIAutomationEngine | None = None

    def __init__(self) -> None:
        self.is_windows = os.name == "nt" and platform.system() == "Windows"

    @classmethod
    def get_instance(cls) -> WindowsUIAutomationEngine:
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_active_window_title(self) -> str:
        """Return the window title of the current foreground application."""
        if not self.is_windows:
            return "Active Window"
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                return buff.value
        except Exception as exc:
            LOGGER.debug("GetForegroundWindow error: %s", exc)
        return ""

    def _get_foreground_process_name(self) -> str:
        """Get the process name of the current foreground window via PID lookup."""
        if not self.is_windows:
            return "unknown"
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return "unknown"
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == 0:
                return "unknown"
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid.value}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=2,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            if result.returncode == 0 and result.stdout.strip():
                # tasklist CSV: "process.exe","PID","Session","...","Mem"
                first_line = result.stdout.strip().splitlines()[0]
                return first_line.split(",")[0].strip('"')
        except Exception as exc:
            LOGGER.debug("_get_foreground_process_name error: %s", exc)
        return "unknown"

    def get_active_window_context(self, max_controls: int = 25) -> str:
        """Format the active foreground window and its controls as a concise text summary.

        Jugaad 3: Uses ~30-60 text tokens instead of ~258 vision tokens for UI grounding and navigation.
        Includes process name for better app identification by the model.
        """
        title = self.get_active_window_title() or "Desktop / No active window"
        process_name = self._get_foreground_process_name()
        controls = self.list_window_controls()

        if not controls:
            return f'Active Window: "{title}" (Process: {process_name}, No accessible controls found)'

        lines = [f'Active Window: "{title}" (Process: {process_name}, Controls: {len(controls)})']
        lines.append("Interactive Elements:")

        shown = 0
        for c in controls:
            if shown >= max_controls:
                break
            if c.name and c.name.casefold() != title.casefold():
                lines.append(f'  - [{c.control_type}] "{c.name}"')
                shown += 1

        return "\n".join(lines)

    def inspect_active_window(self) -> dict[str, Any]:
        """Inspect the active window: returns title, process, and interactive controls."""
        title = self.get_active_window_title()
        process_name = self._get_foreground_process_name()
        controls = self.list_window_controls()
        context_summary = self.get_active_window_context()
        return {
            "title": title,
            "process": process_name,
            "control_count": len(controls),
            "context_summary": context_summary,
            "controls": [
                {
                    "name": c.name,
                    "type": c.control_type,
                    "rect": list(c.rect),
                }
                for c in controls[:30]  # Return top 30 controls
            ],
        }

    def list_window_controls(self, hwnd: int | None = None) -> list[DesktopControl]:
        """Enumerate child controls of the target window using Windows EnumChildWindows."""
        if not self.is_windows:
            return []

        if hwnd is None:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return []

        controls: list[DesktopControl] = []

        # Callback for EnumChildWindows
        def _enum_proc(child_hwnd: int, lparam: Any) -> int:
            try:
                # Check if visible
                if not ctypes.windll.user32.IsWindowVisible(child_hwnd):
                    return 1

                # Get class name
                class_buff = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(child_hwnd, class_buff, 256)
                class_name = class_buff.value

                # Get window text / label
                txt_len = ctypes.windll.user32.GetWindowTextLengthW(child_hwnd)
                txt = ""
                if txt_len > 0:
                    txt_buff = ctypes.create_unicode_buffer(txt_len + 1)
                    ctypes.windll.user32.GetWindowTextW(child_hwnd, txt_buff, txt_len + 1)
                    txt = txt_buff.value.strip()

                # Get bounding rect
                rect = (ctypes.c_long * 4)()  # left, top, right, bottom
                ctypes.windll.user32.GetWindowRect(child_hwnd, rect)
                left, top, right, bottom = rect[0], rect[1], rect[2], rect[3]

                # Classify control type
                c_type = "Control"
                lower_class = class_name.lower()
                if "button" in lower_class:
                    c_type = "Button"
                elif "edit" in lower_class:
                    c_type = "Edit"
                elif "combo" in lower_class:
                    c_type = "ComboBox"
                elif "list" in lower_class:
                    c_type = "ListBox"
                elif "static" in lower_class:
                    c_type = "Text"

                if txt or c_type in {"Button", "Edit"}:
                    controls.append(
                        DesktopControl(
                            name=txt or f"{c_type}_{len(controls) + 1}",
                            control_type=c_type,
                            rect=(left, top, right, bottom),
                            hwnd=child_hwnd,
                        )
                    )
            except Exception as exc:
                LOGGER.debug("EnumChild exception: %s", exc)
            return 1

        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        cb = enum_proc_type(_enum_proc)
        try:
            ctypes.windll.user32.EnumChildWindows(hwnd, cb, 0)
        except Exception as exc:
            LOGGER.debug("EnumChildWindows error: %s", exc)

        return controls

    def click_control(self, name_or_type: str) -> dict[str, Any]:
        """Locate and click a desktop control by text/name or fallback to visual click."""
        target = str(name_or_type).strip().casefold()
        controls = self.list_window_controls()

        matched: DesktopControl | None = None
        for c in controls:
            if target in c.name.casefold() or c.name.casefold() in target:
                matched = c
                break

        if matched:
            left, top, right, bottom = matched.rect
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            if cx > 0 and cy > 0:
                try:
                    import pyautogui
                    pyautogui.click(cx, cy)
                    return {
                        "success": True,
                        "action": "click_control",
                        "control_name": matched.name,
                        "control_type": matched.control_type,
                        "coordinates": (cx, cy),
                    }
                except Exception as exc:
                    LOGGER.debug("PyAutoGUI click error: %s", exc)

        # Fallback to visual coordinate locator and computer use executor
        try:
            from vision_agent import get_computer_use_executor
            vis_res = get_computer_use_executor().visual_click(target=name_or_type)
            if vis_res.get("success"):
                return {
                    "success": True,
                    "action": "click_control",
                    "control_name": name_or_type,
                    "fallback_used": True,
                    "method": vis_res.get("method", "vision_agent"),
                    "coordinates": vis_res.get("coordinates"),
                    "message": vis_res.get("message"),
                }
        except Exception as v_exc:
            LOGGER.debug("Vision agent fallback click notice: %s", v_exc)

        # Fallback to desktop screen visual click
        from automation import click_screen_element
        res = click_screen_element(target=name_or_type)
        return {
            "success": res.success,
            "action": "click_control",
            "control_name": name_or_type,
            "fallback_used": True,
            "message": res.message,
        }

    def type_into_control(self, text: str, control_name: str | None = None) -> dict[str, Any]:
        """Type text into a focused or specific edit control."""
        if control_name:
            click_res = self.click_control(control_name)
            if not click_res.get("success"):
                LOGGER.debug("Control click before type notice: %s", click_res)
            time.sleep(0.2)

        try:
            import pyautogui
            # If text has non-ASCII characters (e.g. Hindi, Unicode), paste via clipboard
            if any(ord(c) > 127 for c in text):
                try:
                    import pyperclip
                    pyperclip.copy(text)
                    pyautogui.hotkey("ctrl", "v")
                    time.sleep(0.05)
                except Exception:
                    pyautogui.write(text, interval=0.02)
            else:
                pyautogui.write(text, interval=0.02)

            return {
                "success": True,
                "action": "type_into_control",
                "typed_text": text,
                "control": control_name,
            }
        except Exception as exc:
            LOGGER.warning("type_into_control error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
            }


def get_desktop_engine() -> WindowsUIAutomationEngine:
    """Return the global desktop UI automation engine."""
    return WindowsUIAutomationEngine.get_instance()


__all__ = [
    "DesktopControl",
    "ScreenDeltaDetector",
    "WindowsUIAutomationEngine",
    "get_desktop_engine",
]
