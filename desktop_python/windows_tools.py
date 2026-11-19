"""
Upgrade #2: Real-Time Screen Vision + Windows OS Tool Calling + Safety Shields.
Strictly enforces Zero-Camera Privacy and Payment Exclusion Protocols.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime, timedelta
from typing import Any

from memory_engine import SemanticMemoryEngine

try:
    import mss
    from PIL import Image
    HAS_SCREEN = True
except Exception:
    HAS_SCREEN = False

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

try:
    import screen_brightness_control as sbc
    HAS_BRIGHTNESS = True
except Exception:
    HAS_BRIGHTNESS = False

try:
    import pyperclip
    HAS_CLIPBOARD = True
except Exception:
    HAS_CLIPBOARD = False

# Unbypassable Safety Shields
PAYMENT_RE = re.compile(
    r"\b(?:buy\s*now|place\s*order|pay\s*now|checkout|enter\s*cvv|enter\s*otp|"
    r"upi\s*pin|credit\s*card|debit\s*card|payment\s*karo|pay\s*karo)\b",
    re.IGNORECASE,
)
CAMERA_RE = re.compile(
    r"\b(?:webcam|camera|selfie|face\s*record|record\s*face|कैमरा|वेबकैम)\b",
    re.IGNORECASE,
)

SAFE_WINDOWS_APPS: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "terminal": ["wt.exe"],
    "windows terminal": ["wt.exe"],
    "chrome": ["cmd", "/c", "start", "", "chrome"],
    "edge": ["cmd", "/c", "start", "", "msedge"],
    "vscode": ["cmd", "/c", "start", "", "code"],
    "vs code": ["cmd", "/c", "start", "", "code"],
    "spotify": ["cmd", "/c", "start", "", "spotify:"],
}


def check_hard_shields(text: str) -> str | None:
    if PAYMENT_RE.search(text):
        return (
            "Security Shield: Automated payment, checkout aur financial credentials "
            "strictly blocked hain. Final payment kripya manually complete kijiye."
        )
    if CAMERA_RE.search(text):
        return (
            "Privacy Shield: Physical camera/webcam access permanently disabled hai. "
            "Sirf monitor screen vision active hai."
        )
    return None


def capture_monitor_jpeg_bytes() -> bytes | None:
    """Capture active primary monitor screenshot (ZERO camera/webcam access)."""
    if not HAS_SCREEN:
        return None
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        img.thumbnail((1280, 720))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78)
        return buf.getvalue()


def get_gemini_tool_declarations() -> list[dict[str, Any]]:
    """Structured tool declarations passed to Gemini function calling."""
    return [
        {
            "name": "open_app",
            "description": "Launch a trusted Windows application (notepad, calculator, chrome, edge, vscode, explorer, terminal, spotify, paint).",
            "parameters": {
                "type": "OBJECT",
                "properties": {"app_name": {"type": "STRING"}},
                "required": ["app_name"],
            },
        },
        {
            "name": "open_website",
            "description": "Open an HTTP/HTTPS URL or search on Google/YouTube.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "kind": {"type": "STRING", "description": "url | google | youtube | spotify"},
                    "query_or_url": {"type": "STRING"},
                },
                "required": ["kind", "query_or_url"],
            },
        },
        {
            "name": "set_brightness",
            "description": "Set Windows monitor brightness percentage (0 to 100).",
            "parameters": {
                "type": "OBJECT",
                "properties": {"level": {"type": "INTEGER"}},
                "required": ["level"],
            },
        },
        {
            "name": "analyze_screen",
            "description": "Inspect Captain's active desktop monitor screenshot to explain an error, UI, or code on screen.",
            "parameters": {
                "type": "OBJECT",
                "properties": {"question": {"type": "STRING"}},
                "required": ["question"],
            },
        },
        {
            "name": "save_memory",
            "description": "Save an explicit preference or note into Captain's semantic SQLite memory.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "kind": {"type": "STRING", "description": "preference or note"},
                    "content": {"type": "STRING"},
                },
                "required": ["kind", "content"],
            },
        },
        {
            "name": "add_reminder",
            "description": "Schedule a local desktop reminder after a given number of minutes.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "minutes_from_now": {"type": "INTEGER"},
                    "message": {"type": "STRING"},
                },
                "required": ["minutes_from_now", "message"],
            },
        },
        {
            "name": "get_system_status",
            "description": "Read current Windows CPU, RAM, and Battery health.",
            "parameters": {"type": "OBJECT", "properties": {}},
        },
    ]


class WindowsToolExecutor:
    def __init__(self, memory: SemanticMemoryEngine, genai_client: Any = None) -> None:
        self.memory = memory
        self._client = genai_client

    def execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "open_app":
            app = str(args.get("app_name", "")).strip().lower()
            cmd = SAFE_WINDOWS_APPS.get(app)
            if not cmd:
                return f"App '{app}' trusted allowlist mein nahi hai."
            try:
                subprocess.Popen(cmd, shell=False)
                return f"Successfully launched {app}."
            except Exception as exc:
                return f"Could not launch {app}: {type(exc).__name__}"

        if name == "open_website":
            kind = str(args.get("kind", "url")).lower()
            q = str(args.get("query_or_url", "")).strip()
            if kind == "google":
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"
            elif kind == "youtube":
                url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(q)}"
            elif kind == "spotify":
                url = f"https://open.spotify.com/search/{urllib.parse.quote(q)}"
            else:
                url = q if q.startswith(("http://", "https://")) else f"https://{q}"
            webbrowser.open(url)
            return f"Opened {url} in default browser."

        if name == "set_brightness":
            level = max(0, min(100, int(args.get("level", 50))))
            if not HAS_BRIGHTNESS:
                return "screen-brightness-control package installed nahi hai."
            try:
                sbc.set_brightness(level)
                return f"Monitor brightness set to {level}%."
            except Exception as exc:
                return f"Brightness adjustment failed: {type(exc).__name__}"

        if name == "analyze_screen":
            question = str(args.get("question", "What is on the screen?"))
            jpeg = capture_monitor_jpeg_bytes()
            if not jpeg or self._client is None:
                return "Screen capture unavailable (install mss + pillow and set GEMINI_API_KEY)."
            try:
                from google.genai import types

                resp = self._client.models.generate_content(
                    model=os.getenv("DARKSHADOW_MODEL", "gemini-2.5-flash"),
                    contents=[
                        types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                        f"Captain asks about his desktop screen: {question}. Answer concisely in Hinglish.",
                    ],
                )
                return (resp.text or "").strip() or "Screen analyzed."
            except Exception as exc:
                return f"Screen vision error: {type(exc).__name__}"

        if name == "save_memory":
            _, msg = self.memory.save_memory(
                str(args.get("kind", "preference")),
                str(args.get("content", "")),
            )
            return msg

        if name == "add_reminder":
            mins = max(1, int(args.get("minutes_from_now", 5)))
            due = datetime.now() + timedelta(minutes=mins)
            _, msg = self.memory.add_reminder(str(args.get("message", "")), due)
            return msg

        if name == "get_system_status":
            if not HAS_PSUTIL:
                return "psutil installed nahi hai."
            cpu = psutil.cpu_percent(interval=0.2)
            ram = psutil.virtual_memory().percent
            batt = psutil.sensors_battery()
            batt_str = f", Battery {batt.percent:.0f}% ({'charging' if batt.power_plugged else 'on battery'})" if batt else ""
            return f"CPU {cpu:.0f}%, RAM {ram:.0f}%{batt_str}."

        return f"Unknown tool: {name}"
