"""Multi-Level Desktop Workflow Agent for DarkShadow.

Executes complex, multi-stage desktop tasks across Windows applications:
1. WhatsAppInChatSearchAgent: Opens WhatsApp -> navigates to contact -> executes in-chat search ->
   reads matching message bubbles from screen/UI -> synthesizes verbal report for Captain.
2. HierarchicalTaskExecutor: General ReAct loop orchestrating multi-step app navigation.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import time
from typing import Any

LOGGER = logging.getLogger(__name__)


class WhatsAppInChatSearchAgent:
    """Executes end-to-end in-chat message search and extraction inside WhatsApp Desktop."""

    @classmethod
    def search_and_read(
        cls,
        contact_name: str,
        search_term: str,
        gemini_client: Any = None,
    ) -> dict[str, Any]:
        """Navigate WhatsApp, search for term in contact's chat, and read results."""
        c_name = str(contact_name).strip()
        q_term = str(search_term).strip()
        if not c_name or not q_term:
            return {
                "success": False,
                "error": "missing_parameters",
                "message": "Contact name aur search term dono zaroori hain.",
            }

        LOGGER.info("Starting WhatsApp In-Chat Search for '%s' in chat '%s'", q_term, c_name)

        # 1. Bring WhatsApp Desktop to foreground
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            try:
                startfile("whatsapp://")
            except Exception:
                pass

        time.sleep(1.0)
        hwnd = cls._get_whatsapp_hwnd()

        try:
            import pyautogui
            import pyperclip

            pyautogui.FAILSAFE = False

            if hwnd:
                try:
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
                    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
                except Exception:
                    pass

            time.sleep(0.5)

            # 2. Search & Open the Contact
            # Global search shortcut in WhatsApp
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyperclip.copy(c_name)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(0.8)

            # 3. Trigger In-Chat Search (Ctrl+Shift+F in WhatsApp Desktop)
            pyautogui.hotkey("ctrl", "shift", "f")
            time.sleep(0.4)
            # Some builds respond to Ctrl+F inside focused chat
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)

            # 4. Type the search term
            pyperclip.copy(q_term)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.5)
            pyautogui.press("enter")
            time.sleep(1.0)

            # 5. Perception: Read matching messages from UI controls or screen
            extracted_messages = cls._extract_messages_from_ui(hwnd, q_term)

            # If UI Automation was unable to read internal message controls, use Screen Vision
            if not extracted_messages and gemini_client is not None:
                extracted_messages = cls._extract_messages_via_vision(q_term, gemini_client)

            # 6. Format Final Spoken Synthesis
            count = len(extracted_messages)
            if count > 0:
                snippets = " | ".join(f"'{m}'" for m in extracted_messages[:3])
                msg_summary = (
                    f"Captain, WhatsApp par {c_name} ke chat me '{q_term}' dhoonda. "
                    f"{count} message(s) mile hain: {snippets}"
                )
            else:
                msg_summary = (
                    f"Captain, WhatsApp par {c_name} ka chat open karke '{q_term}' search kar diya hai. "
                    f"Screen par search results visible hain."
                )

            return {
                "success": True,
                "contact": c_name,
                "query": q_term,
                "count": count,
                "messages": extracted_messages,
                "summary": msg_summary,
                "message": msg_summary,
            }

        except Exception as exc:
            LOGGER.warning("WhatsAppInChatSearchAgent error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "message": f"WhatsApp in-chat search me error aaya: {exc}",
            }

    @staticmethod
    def _get_whatsapp_hwnd() -> int:
        """Locate WhatsApp window handle."""
        try:
            user32 = ctypes.windll.user32
            found_hwnd = 0

            def _enum_cb(hwnd: int, lparam: Any) -> int:
                nonlocal found_hwnd
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if "whatsapp" in title.lower():
                        found_hwnd = hwnd
                        return 0  # Stop
                return 1

            cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(cb_type(_enum_cb), 0)
            return found_hwnd
        except Exception:
            return 0

    @staticmethod
    def _extract_messages_from_ui(hwnd: int, search_term: str) -> list[str]:
        """Read text from WhatsApp controls via UI Automation."""
        results: list[str] = []
        try:
            from desktop_engine import get_desktop_engine
            engine = get_desktop_engine()
            controls = engine.list_window_controls(hwnd=hwnd)
            term_lower = search_term.casefold()

            for c in controls:
                txt = c.name.strip()
                if txt and term_lower in txt.casefold():
                    if txt not in results and len(txt) > len(search_term):
                        results.append(txt)
        except Exception as exc:
            LOGGER.debug("UI message extraction notice: %s", exc)
        return results

    @staticmethod
    def _extract_messages_via_vision(search_term: str, gemini_client: Any) -> list[str]:
        """Capture screen and use Gemini Vision to read matching highlighted messages."""
        try:
            from vision_agent import ScreenCaptureEngine
            img = ScreenCaptureEngine.capture_screenshot()
            if img is None:
                return []

            import io
            from google.genai import types

            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=85)
            img_bytes = buffered.getvalue()

            prompt = (
                f"Analyze this WhatsApp screenshot. Look at the in-chat search results for '{search_term}'.\n"
                "Extract the matching message text lines found.\n"
                'Return JSON ONLY: {"messages": ["<snippet 1>", "<snippet 2>"]}\n'
                'If none found, return {"messages": []}'
            )

            from config import load_settings
            settings = load_settings()
            model_name = getattr(settings, "vision_model", getattr(settings, "casual_model", "gemini-2.5-flash"))

            resp = gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
            )
            raw = (resp.text or "").strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return data.get("messages", [])
        except Exception as exc:
            LOGGER.debug("Vision message extraction notice: %s", exc)
        return []


class HierarchicalTaskExecutor:
    """Orchestrates general multi-level goals across applications."""

    @classmethod
    def execute_goal(cls, goal: str, gemini_client: Any = None) -> dict[str, Any]:
        """Decompose a high-level goal into steps and coordinate execution."""
        cleaned = str(goal).strip()
        LOGGER.info("Executing hierarchical goal: '%s'", cleaned)

        # Check if the goal is specifically a WhatsApp in-chat search
        m_wa = re.search(
            r"\bwhatsapp\b.*\b([a-zA-Z0-9_\s]{2,20})\b.*\b(?:search|dhoond|dhund|khoj)\b.*['\"]?([a-zA-Z0-9_\s]{2,20})['\"]?",
            cleaned,
            re.IGNORECASE,
        )
        if m_wa:
            contact = m_wa.group(1).strip()
            query = m_wa.group(2).strip()
            return WhatsAppInChatSearchAgent.search_and_read(contact, query, gemini_client=gemini_client)

        # Fallback for goals that don't match a specialized handler
        LOGGER.info("No specialized handler for goal: '%s'. Returning graceful fallback.", cleaned)
        return {
            "success": False,
            "message": f"Captain, is goal ke liye abhi specialized handler available nahi hai: '{cleaned}'. "
                       f"Aap computer_use_agent ya manual automation try kar sakte hain.",
            "goal": cleaned,
            "handler": "none",
        }

class UniversalInAppOperator:
    """Universal stateful operator for in-app and in-page navigation without redundant tabs."""

    _APP_KEYWORDS = {
        "youtube": ("youtube",),
        "spotify": ("spotify",),
        "vscode": ("visual studio code", "- code", "cursor"),
        "explorer": ("file explorer", "cabinetwclass"),
        "notepad": ("notepad",),
        "whatsapp": ("whatsapp",),
        "browser": ("chrome", "edge", "brave", "firefox"),
    }

    @classmethod
    def get_foreground_app_info(cls) -> tuple[str, int, str]:
        """Return (app_type, hwnd, window_title) of current active window."""
        try:
            windll = getattr(ctypes, "windll", None)
            if not windll:
                return "unknown", 0, ""
            user32 = windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return "unknown", 0, ""
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
            title_lower = title.casefold()

            for app_type, keywords in cls._APP_KEYWORDS.items():
                if any(k in title_lower for k in keywords):
                    return app_type, hwnd, title

            return "unknown", hwnd, title
        except Exception as exc:
            LOGGER.debug("Foreground app detection notice: %s", exc)
            return "unknown", 0, ""

    @classmethod
    def find_open_app_window(cls, app_type: str) -> tuple[int, str]:
        """Find an already open top-level window for target app, even if not active."""
        keywords = cls._APP_KEYWORDS.get(app_type.casefold(), (app_type.casefold(),))
        found_hwnd = 0
        found_title = ""

        try:
            windll = getattr(ctypes, "windll", None)
            if not windll:
                return 0, ""
            user32 = windll.user32

            def _enum_cb(hwnd: int, lparam: Any) -> int:
                nonlocal found_hwnd, found_title
                if not user32.IsWindowVisible(hwnd):
                    return 1
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()
                    if any(k in title.casefold() for k in keywords):
                        found_hwnd = hwnd
                        found_title = title
                        return 0
                return 1

            cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(cb_type(_enum_cb), 0)
        except Exception:
            pass

        return found_hwnd, found_title

    @classmethod
    def bring_to_foreground(cls, hwnd: int) -> bool:
        """Force restore and bring window to foreground, bypassing Windows focus restrictions."""
        if not hwnd:
            return False
        try:
            windll = getattr(ctypes, "windll", None)
            if not windll:
                return False
            user32 = windll.user32

            # 1. Restore if minimized
            if user32.IsIconic(hwnd):
                user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
            else:
                user32.ShowWindow(ctypes.c_void_p(hwnd), 5)  # SW_SHOW

            # 2. AttachThreadInput to bypass SetForegroundWindow lock
            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd and fg_hwnd != hwnd:
                fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
                target_thread = user32.GetWindowThreadProcessId(hwnd, None)
                if fg_thread != target_thread:
                    user32.AttachThreadInput(fg_thread, target_thread, True)
                    user32.BringWindowToTop(ctypes.c_void_p(hwnd))
                    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
                    user32.AttachThreadInput(fg_thread, target_thread, False)

            # 3. Z-order topmost toggle to ensure window pops above all others
            user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-2), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)

            # 4. Alt key pulse
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))

            time.sleep(0.3)
            return True
        except Exception as exc:
            LOGGER.debug("bring_to_foreground notice: %s", exc)
            return False

    @classmethod
    def search_in_active_or_open_app(
        cls,
        query: str,
        target_app: str | None = None,
    ) -> dict[str, Any]:
        """Perform search directly within the existing active or open app without opening a new tab/window."""
        cleaned_query = str(query).strip()
        if not cleaned_query:
            return {"success": False, "error": "empty_query", "message": "Search query khaali hai."}

        # 1. Identify which app to target
        active_type, active_hwnd, active_title = cls.get_foreground_app_info()
        chosen_type = (target_app or active_type or "unknown").casefold()

        # If user targeted YouTube specifically, check if a YouTube window is already open
        hwnd_to_use = active_hwnd
        if chosen_type == "youtube" and active_type != "youtube":
            yt_hwnd, yt_title = cls.find_open_app_window("youtube")
            if yt_hwnd:
                hwnd_to_use = yt_hwnd
                cls.bring_to_foreground(yt_hwnd)
                active_type = "youtube"

        try:
            import pyautogui
            import pyperclip
            pyautogui.FAILSAFE = False

            if hwnd_to_use:
                cls.bring_to_foreground(hwnd_to_use)

            # -------------------------------------------------------------
            # YOUTUBE: In-Page Search (NO NEW TAB!)
            # -------------------------------------------------------------
            if chosen_type == "youtube" or "youtube" in active_title.casefold():
                from urllib.parse import quote_plus
                search_url = f"https://www.youtube.com/results?search_query={quote_plus(cleaned_query)}"
                # Use Ctrl+L in current tab to navigate directly to search results without opening duplicate tab
                pyautogui.hotkey("ctrl", "l")
                time.sleep(0.2)
                pyperclip.copy(search_url)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.2)
                pyautogui.press("enter")

                return {
                    "success": True,
                    "action": "youtube_in_page_search",
                    "app": "youtube",
                    "query": cleaned_query,
                    "same_tab": True,
                    "message": f"Active YouTube tab me '{cleaned_query}' search kar diya hai (bina naya tab khole).",
                }

            # -------------------------------------------------------------
            # SPOTIFY: In-App Search (Ctrl+K or Ctrl+L)
            # -------------------------------------------------------------
            elif chosen_type == "spotify" or "spotify" in active_title.casefold():
                pyautogui.hotkey("ctrl", "k")
                time.sleep(0.2)
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.1)
                pyperclip.copy(cleaned_query)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("enter")

                return {
                    "success": True,
                    "action": "spotify_in_app_search",
                    "app": "spotify",
                    "query": cleaned_query,
                    "message": f"Active Spotify app me '{cleaned_query}' search kar diya hai.",
                }

            # -------------------------------------------------------------
            # VS CODE: In-Editor Search (Ctrl+P / Ctrl+Shift+F)
            # -------------------------------------------------------------
            elif chosen_type == "vscode" or any(k in active_title.casefold() for k in ("visual studio code", "- code")):
                # File search or text search
                pyautogui.hotkey("ctrl", "p")
                time.sleep(0.2)
                pyperclip.copy(cleaned_query)
                pyautogui.hotkey("ctrl", "v")

                return {
                    "success": True,
                    "action": "vscode_in_editor_search",
                    "app": "vscode",
                    "query": cleaned_query,
                    "message": f"VS Code me '{cleaned_query}' search open kar diya hai.",
                }

            # -------------------------------------------------------------
            # FILE EXPLORER: In-Folder Search (Ctrl+E)
            # -------------------------------------------------------------
            elif chosen_type == "explorer" or "file explorer" in active_title.casefold():
                pyautogui.hotkey("ctrl", "e")
                time.sleep(0.2)
                pyperclip.copy(cleaned_query)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.2)
                pyautogui.press("enter")

                return {
                    "success": True,
                    "action": "explorer_in_folder_search",
                    "app": "explorer",
                    "query": cleaned_query,
                    "message": f"File Explorer me '{cleaned_query}' search kar diya hai.",
                }

            # -------------------------------------------------------------
            # GENERAL BROWSER (Chrome, Edge, Brave): Address Bar In-Tab Search
            # -------------------------------------------------------------
            elif chosen_type == "browser" or any(k in active_title.casefold() for k in ("chrome", "edge", "brave", "firefox")):
                pyautogui.hotkey("ctrl", "l")
                time.sleep(0.2)
                pyperclip.copy(cleaned_query)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.2)
                pyautogui.press("enter")

                return {
                    "success": True,
                    "action": "browser_in_tab_search",
                    "app": "browser",
                    "query": cleaned_query,
                    "same_tab": True,
                    "message": f"Active browser tab me '{cleaned_query}' search navigate kar diya hai.",
                }

            # Fallback
            return {
                "success": False,
                "error": "unsupported_or_inactive_app",
                "message": f"Active window '{active_title}' me in-app search command identify nahi hui.",
            }

        except Exception as exc:
            LOGGER.warning("UniversalInAppOperator error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "message": f"In-app search me error aaya: {exc}",
            }


__all__ = [
    "WhatsAppInChatSearchAgent",
    "HierarchicalTaskExecutor",
    "UniversalInAppOperator",
]
