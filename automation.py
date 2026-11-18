"""Safe, deterministic browser and Windows automation for DarkShadow Phase 3.

No model-generated string is ever passed to a shell.  Browser URLs are
validated, search text is encoded, and applications resolve through a fixed
allowlist of absolute executable paths.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import threading
import webbrowser
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit, urlunsplit
from networking import install_ipv4_first_dns
install_ipv4_first_dns()
from safety import ensure_captain_address, is_payment_or_checkout_intent, PAYMENT_BLOCKED_MESSAGE

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class AutomationResult:
    """Structured result returned by every automation function."""

    success: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedAutomationCommand:
    """A deterministic local intent and its validated arguments."""

    intent: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AutomationContext:
    """Small local context used to resolve safe follow-up automation commands."""

    confirm_whatsapp_send: bool = True
    last_subject: str | None = None
    last_media_query: str | None = None
    last_command: ParsedAutomationCommand | None = None
    pending_confirmation: ParsedAutomationCommand | None = None
    pending_plan: tuple[ParsedAutomationCommand, ...] = ()
    pending_request: str | None = None
    last_search_results: list[dict[str, str]] = field(default_factory=list)
    last_search_query: str | None = None

    def observe(self, user_text: str, assistant_text: str = "") -> None:
        """Remember a likely conversation subject without storing secrets."""

        del assistant_text  # Reserved for future structured entity extraction.
        cleaned = _strip_invocation(user_text)
        patterns = (
            r"^(?:who\s+is|who's)\s+(.+?)[?.!]*$",
            r"^(.+?)\s+(?:kaun\s+hai|kon\s+hai|koun\s+hai)[?.!]*$",
            r"^(?:tell\s+me\s+about)\s+(.+?)[?.!]*$",
            r"^(.+?)\s+ke\s+baare\s+mein\s+(?:batao|bataye|bataiye|kya\s+jaante\s+ho)[?.!]*$",
            r"^(?:do\s+you\s+know|know|you\s+know|have\s+you\s+heard\s+of|heard\s+of)\s+(.+?)[?.!]*$",
            r"^(?:kya\s+aap\s+)?(.+?)\s+(?:ko\s+)?jaante\s+(?:ho|hain|hai)[?.!]*$",
        )
        for pattern in patterns:
            match = re.match(pattern, cleaned, re.I)
            if not match:
                continue
            subject = _clean_subject(match.group(1))
            if subject:
                self.last_subject = subject
            return

    def remember_media(self, query: str) -> None:
        cleaned = re.sub(r"\s+", " ", str(query)).strip(" .?!")
        if cleaned:
            self.last_media_query = cleaned

    def remember_search_results(self, query: str, results: list[dict[str, str]]) -> None:
        self.last_search_query = query
        self.last_search_results = list(results)

    def get_search_result_by_index(self, index: int) -> dict[str, str] | None:
        if not self.last_search_results:
            return None
        idx = (len(self.last_search_results) - 1) if index == -1 else (index - 1)
        if 0 <= idx < len(self.last_search_results):
            return self.last_search_results[idx]
        return None

    def remember_command(self, command: ParsedAutomationCommand) -> None:
        if command.intent not in {
            "confirmation_required",
            "missing_media_context",
            "automation_sequence",
            "send_whatsapp_message",
        }:
            self.last_command = command


GLOBAL_AUTOMATION_CONTEXT = AutomationContext()


WEBSITE_ALIASES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "spotify": "https://open.spotify.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://chatgpt.com",
    "gemini": "https://gemini.google.com",
    "claude": "https://claude.ai",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com",
    "hotstar": "https://www.hotstar.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
}

APPLICATION_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "chrome.exe": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "msedge.exe": "edge",
    "browser": "edge",
    "web browser": "edge",
    "internet": "edge",
    "notepad": "notepad",
    "notepad.exe": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "calc.exe": "calculator",
    "file explorer": "file_explorer",
    "explorer": "file_explorer",
    "explorer.exe": "file_explorer",
    "vs code": "vscode",
    "vscode": "vscode",
    "visual studio code": "vscode",
    "code": "vscode",
    "code.exe": "vscode",
    "paint": "paint",
    "mspaint": "paint",
    "mspaint.exe": "paint",
    "spotify": "spotify",
    "spotify.exe": "spotify",
    "windows terminal": "terminal",
    "terminal": "terminal",
    "wt": "terminal",
    "wt.exe": "terminal",
    "cmd": "cmd",
    "command prompt": "cmd",
    "cmd.exe": "cmd",
    "task manager": "taskmgr",
    "taskmgr": "taskmgr",
    "taskmgr.exe": "taskmgr",
    "control panel": "control",
    "control": "control",
    "control.exe": "control",
    "vlc": "vlc",
    "vlc media player": "vlc",
    "vlc.exe": "vlc",
    "whatsapp": "whatsapp",
    "whatsapp desktop": "whatsapp",
    "whatsapp.exe": "whatsapp",
    "whatsapp web": "whatsapp",
    "instagram": "instagram",
    "instagram app": "instagram",
    "instagram.exe": "instagram",
    "youtube": "youtube",
    "youtube.com": "youtube",
    "yt": "youtube",
    "yt music": "youtube",
}

ALLOWED_APPLICATIONS = (
    "Edge",
    "Notepad",
    "Calculator",
    "File Explorer",
    "VS Code",
    "Paint",
    "Spotify",
    "Windows Terminal",
    "Command Prompt",
    "Task Manager",
    "Control Panel",
    "WhatsApp",
    "Instagram",
    "Chrome",
)

CONFIRMATION_REQUIRED_ACTIONS = frozenset(
    {
        "shutdown_or_restart",
        "close_application",
        "delete_or_move_files",
        "install_software",
        "send_message_or_email",
        "purchase_or_financial_action",
        "unknown_executable",
        "important_system_setting",
    }
)


AUTOMATION_FUNCTION_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "execute_computer_task",
        "description": "Autonomously execute multi-step visual UI actions on Windows desktop or applications using Computer Use (mouse clicks, typing, shortcuts, and navigation).",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The desktop or UI workflow to execute on screen"}
            },
            "required": ["task"],
        },
    },
    {
        "name": "search_location_or_places",
        "description": "Find nearby places, restaurants, cafes, hotels, routes, directions, or geographic locations using Google Maps Grounding.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Place, route, or navigation query (e.g. 'Kanpur me best cafe', 'petrol pump near me')"},
                "location": {"type": "string", "description": "Optional city or area name"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "index_document_or_folder",
        "description": "Index a local file, document, or code folder into DarkShadow's Personal Knowledge Base / Vector RAG for semantic retrieval.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file or directory to index"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": "Search Captain's indexed personal documents, notes, codebases, and files using semantic dense vector embeddings.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search question or keywords to retrieve from personal notes and indexed files"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_website",
        "description": (
            "Open a validated HTTP or HTTPS website in Captain's preferred browser (Microsoft Edge). "
            "ALWAYS use this tool for opening YouTube (url_or_name='https://youtube.com'), Google, or any web URL. "
            "If YouTube is already open, this automatically brings the existing tab to the foreground with zero duplicate tabs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_or_name": {"type": "string", "description": "URL or known site name (e.g. 'https://youtube.com', 'https://google.com')"}
            },
            "required": ["url_or_name"],
        },
    },
    {
        "name": "search_google",
        "description": "Search Google and the web for real-time information, facts, weather, news, or model comparisons, and retrieve grounded summaries to answer Captain aloud. Only opens a browser tab if Captain explicitly asks to open Google or show the webpage.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "search_youtube",
        "description": "Search YouTube for videos/songs and display/index the top results so the user can choose.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query, artist, or song topic"}},
            "required": ["query"],
        },
    },
    {
        "name": "search_in_active_app",
        "description": "Search directly inside the currently active application or open window (YouTube, Spotify, VS Code, File Explorer, Browser) without opening new tabs.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query, song, or text to search for"},
                "app_name": {"type": "string", "description": "Optional app identifier like 'youtube', 'spotify', 'vscode', 'explorer'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "play_youtube",
        "description": (
            "Play a YouTube video or song by name/artist, or select by ordinal from recent search results "
            "(e.g. '2nd', 'second', '2nd wala', '3rd', 'first', 'doosra')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Song name, artist, music topic, or ordinal index (e.g. '2nd', 'second', '3rd')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_whatsapp_contact",
        "description": "Search or look up a contact/chat on WhatsApp WITHOUT sending any message. Use when Captain asks if a contact exists or asks to search someone on WhatsApp (e.g. 'Shivani ko search karo', 'Kuldeep hai kya dekho').",
        "parameters": {
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Contact name to search (e.g. 'Shivani', 'Kuldeep')"}
            },
            "required": ["contact_name"],
        },
    },
    {
        "name": "prepare_whatsapp_message",
        "description": (
            "Open a WhatsApp Desktop draft for a contact by name (e.g. Kajal, Rahul, Mom) "
            "or phone number. This prepares the message in chat without pressing Send."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "Contact name or phone number"},
                "message": {"type": "string", "description": "The draft message text"},
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "send_whatsapp_message",
        "description": "Send a WhatsApp message directly ONLY when Captain explicitly commanded to send a specific message. NEVER use this tool if Captain only asked to search or check someone. NEVER invent fake placeholder messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Contact name (e.g. Kuldeep, Mom, Rahul) or phone number",
                },
                "message": {
                    "type": "string",
                    "description": "The exact message Captain asked to send (never invent messages)",
                },
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "make_phone_call",
        "description": "Make a phone call to a contact or phone number via Microsoft Mobile Link (Phone Link) or connected Android phone. Use when Captain says 'call karo', 'phone lagao', 'call lagao', 'mobile link se call karo', 'call Papa'.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Contact name (e.g. Papa, Kuldeep, Mom) or phone number to dial",
                },
                "method": {
                    "type": "string",
                    "description": "Calling method: 'phone_link' (Microsoft Mobile Link / Phone Link, recommended) or 'adb' (Android ADB)",
                    "enum": ["phone_link", "adb", "auto"],
                },
            },
            "required": ["recipient"],
        },
    },
    {
        "name": "open_application",
        "description": (
            "Open one local desktop application from the Windows allowlist (Edge, Notepad, Calculator, "
            "File Explorer, VS Code, Paint, Spotify, WhatsApp, Instagram). "
            "CRITICAL: NEVER use this tool for YouTube, Google, or any web URL! For YouTube, ALWAYS call "
            "open_website(url_or_name='https://youtube.com'). Captain's preferred browser is Microsoft Edge (Edge), NEVER Chrome."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "enum": list(ALLOWED_APPLICATIONS)}
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "get_current_time",
        "description": "Return the current local time.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_current_date",
        "description": "Return the current local date.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_system_status",
        "description": "Return safe local OS, memory, disk, and uptime status.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_volume",
        "description": "Set Windows master volume from 0 to 100.",
        "parameters": {
            "type": "object",
            "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["level"],
        },
    },
    {
        "name": "change_volume",
        "description": "Increase or decrease Windows master volume.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"]},
                "amount": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["direction", "amount"],
        },
    },
    {
        "name": "set_brightness",
        "description": "Set display brightness from 0 to 100.",
        "parameters": {
            "type": "object",
            "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["level"],
        },
    },
    {
        "name": "analyze_screen",
        "description": "Capture the user's active monitor screen and visually analyze what is displayed, open apps, or errors.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to look for or question about the screen (e.g. 'explain the error on screen', 'summarize current window')",
                }
            },
        },
    },
    {
        "name": "search_product_prices",
        "description": "Search online shopping sites (Amazon, Flipkart, etc.) for a product and return top prices, deals, and specifications.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The product to search (e.g. 'iPhone 15 128GB', 'Sony WH-1000XM5')"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "ecommerce_multi_cart",
        "description": "Autonomous multi-level e-commerce shopping automation. Searches products on Amazon, Flipkart, etc., filters by price limit, selects the best matching item, and adds it to cart.",
        "parameters": {
            "type": "object",
            "properties": {
                "product": {"type": "string", "description": "Product name or search keyword (e.g. 'laptop', 'gaming mouse')"},
                "max_price": {"type": "number", "description": "Optional maximum price filter in INR (e.g. 40000)"},
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target shopping platforms, e.g. ['amazon', 'flipkart']",
                },
            },
            "required": ["product"],
        },
    },
    {
        "name": "vision_browser_goal",
        "description": "Autonomous Level 3 Vision-Grounded Web Agent. Uses Set-of-Marks visual element tagging and Gemini 3.8 Flash to visually interact with any website without brittle CSS selectors (e.g. click buttons, close popups, fill forms).",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Specific visual action to achieve on the webpage (e.g. 'Click Add to Cart button', 'Close promotional popup', 'Select size Medium')"},
                "url": {"type": "string", "description": "Optional target URL to navigate to first if browser is not on the target page"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "start_background_task",
        "description": "Level 4: Launch an autonomous automation task in the background without blocking the conversation or UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Short descriptive label for the task (e.g. 'Price research for iPhone')"},
                "task_command": {"type": "string", "description": "Full command or query to execute in background"},
            },
            "required": ["task_name", "task_command"],
        },
    },
    {
        "name": "check_background_tasks",
        "description": "Level 4: Check running background tasks, worker status, and pending notifications.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_token_usage",
        "description": "Report total session token usage, prompt and candidate token counts, and last model request statistics.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "desktop_control_action",
        "description": "Level 5: Universal OS-level GUI action on active native desktop Windows apps (click buttons, type in text fields, inspect controls).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["click", "type", "inspect"], "description": "Action type ('click', 'type', 'inspect')"},
                "target": {"type": "string", "description": "Name or text of the control to click or target"},
                "text": {"type": "string", "description": "Text to type into the control if action is 'type'"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "inspect_desktop_window",
        "description": "Level 5: Inspect active window and its native desktop controls.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "scroll_screen",
        "description": "Scroll the active window or webpage up or down (e.g. 'scroll down', 'scroll up', 'neeche scroll karo').",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["down", "up"], "description": "Scroll direction ('down' or 'up')"},
                "amount": {"type": "integer", "description": "Scroll intensity/notches (default 5)"},
            },
        },
    },
    {
        "name": "click_screen_element",
        "description": "Click on a link or element on screen (e.g. 'click the first link', 'click 2nd link', 'click center').",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target element or position (e.g. 'first_link', 'second_link', 'center')"},
                "x": {"type": "integer", "description": "Optional X coordinate"},
                "y": {"type": "integer", "description": "Optional Y coordinate"},
            },
        },
    },
    {
        "name": "control_browser_action",
        "description": "Perform browser navigation shortcuts like going back, forward, refreshing, or closing/opening tabs.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["back", "forward", "refresh", "close_tab", "new_tab", "zoom_in", "zoom_out"],
                    "description": "Browser action to execute",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "press_keyboard_key",
        "description": "Press a keyboard key on the active window (e.g. 'enter', 'tab', 'escape', 'space', 'down', 'up', 'pagedown', 'pageup').",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name (enter, tab, esc, space, down, up, pagedown, pageup)"}
            },
            "required": ["key"],
        },
    },
    {
        "name": "play_spotify",
        "description": "Play a song, artist, album, or playlist on Spotify (opens desktop app or Web Player).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Song name or artist to play on Spotify"}
            },
            "required": [],
        },
    },
    {
        "name": "search_spotify",
        "description": "Search tracks, artists, or playlists on Spotify.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for Spotify"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_live_news",
        "description": "Fetch verified real-time live news, breaking headlines, current weather, scores, or world events via Tavily Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "News topic, city, or event (e.g. 'India breaking news', 'Delhi weather', 'Tech news today')"}
            },
            "required": ["topic"],
        },
    },
    {
        "name": "play_mood_music",
        "description": "Play AI-curated top-rated music for Captain's specific mood or activity (coding, study, gym, chill, romantic, party, sad, 90s, bhajan).",
        "parameters": {
            "type": "object",
            "properties": {
                "mood": {"type": "string", "description": "Mood or activity (e.g. 'coding', 'study', 'gym', 'chill', 'romantic', '90s')"}
            },
            "required": ["mood"],
        },
    },
    {
        "name": "search_youtube_live",
        "description": "Find and play verified 24/7 Live Streams on YouTube (Live News, Live Cricket, Lofi streams).",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Live topic or channel (e.g. 'cricket match live', 'aaj tak live news', 'lofi live stream')"}
            },
            "required": ["topic"],
        },
    },
    {
        "name": "jump_to_video_time",
        "description": "Jump active video player to a specific timestamp (e.g. 'start', 'middle', '10s forward', '10s backward').",
        "parameters": {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string", "description": "Timestamp or position ('start', 'middle', '10s forward', '10s backward')"}
            },
            "required": ["timestamp"],
        },
    },
    {
        "name": "add_to_favorites",
        "description": "Save Captain's favorite song, artist, video, or channel to persistent memory database.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Song title or artist name"},
                "artist": {"type": "string", "description": "Artist name (optional)"}
            },
            "required": ["title"],
        },
    },
    {
        "name": "play_favorites",
        "description": "Play a random or top favorite song from Captain's saved favorites list.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "save_captain_fact",
        "description": "Learn and save a personal fact, habit, or preference about Captain (e.g. favorite singer, college, city, hobby).",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Fact key (e.g. 'favorite_singer', 'college', 'city', 'coding_music')"},
                "value": {"type": "string", "description": "Fact detail or value"},
                "category": {"type": "string", "description": "Category (optional)"}
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "save_captain_lesson",
        "description": "Learn an operational lesson or user correction from past conversation to remember forever.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic or context"},
                "lesson": {"type": "string", "description": "The exact lesson or preference learned"}
            },
            "required": ["topic", "lesson"],
        },
    },
    {
        "name": "recall_captain_memory",
        "description": "Recall or search Captain's personal profile, favorite subjects, past conversation sessions, notes, or memories.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to recall (e.g. 'favorite subjects', 'college', 'pichhla session', 'past chat')"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "execute_terminal_command",
        "description": "Execute a secure Windows PowerShell or CMD command with 4-Layer Security Shield (read-only auto-run, destructive commands strictly blocked). Use this for instant accurate system checks, network info, process management, and developer commands.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact PowerShell or CMD command to execute (e.g. 'Get-Process', 'ipconfig /all', 'systeminfo', 'dir')",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory path (defaults to current project root)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (default 25)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "trigger_media_key",
        "description": "Control global media playback (play/pause, next track, previous track, stop) across Spotify, YouTube, or media players without switching window focus.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": ["play_pause", "next", "previous", "stop"],
                    "description": "Media key action to trigger (default: play_pause)"
                }
            },
            "required": ["key"],
        },
    },
    {
        "name": "lock_workstation",
        "description": "Instantly lock the Windows PC screen / workstation.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_local_files",
        "description": "Search for files on Captain's computer across Documents, Downloads, Desktop, or custom folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "File name or keyword to search for"},
                "directory": {"type": "string", "description": "Optional search folder path"},
                "extension": {"type": "string", "description": "Optional file extension filter (e.g. 'pdf', 'docx', 'py', 'png')"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_clipboard_text",
        "description": "Read the text currently copied to the Windows clipboard.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_clipboard_text",
        "description": "Copy specified text into the Windows clipboard.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to copy to clipboard"}
            },
            "required": ["text"],
        },
    },
    {
        "name": "save_screenshot",
        "description": "Capture the full desktop screen and save as a PNG image file.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Optional custom filename for the screenshot"}
            },
        },
    },
    {
        "name": "save_quick_note",
        "description": "Save a quick note, memo, or idea to Captain's persistent Markdown notes journal.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Note title or subject"},
                "content": {"type": "string", "description": "The detailed note content to write"}
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "browser_navigate",
        "description": "Open and navigate to a website URL with DOM automation support.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target website URL"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_click_selector",
        "description": "Click a specific button, link, or element on the active browser page using CSS selector, XPath, or text.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector, XPath, or text selector (e.g. 'button:has-text(\"Submit\")', '#login-btn')"}
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_fill_input",
        "description": "Type text into a form input or search box on the active browser page.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector or input field name (e.g. 'input[name=\"q\"]', '#username')"},
                "text": {"type": "string", "description": "Text to fill into the input field"}
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "browser_extract_text",
        "description": "Extract readable text content from the active browser webpage.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Optional specific element or container selector"}
            },
        },
    },
    {
        "name": "summarize_youtube_video",
        "description": "Generate an AI summary with key takeaways and insights for any YouTube video or podcast URL/title from its subtitles/transcript.",
        "parameters": {
            "type": "object",
            "properties": {
                "url_or_name": {"type": "string", "description": "YouTube video URL or title/query to summarize"},
                "detail_level": {"type": "string", "enum": ["concise", "detailed"], "description": "Summary detail level (default: concise)"}
            },
            "required": ["url_or_name"],
        },
    },
    {
        "name": "analyze_youtube_comments",
        "description": "Analyze public comments and audience sentiment (praise, criticism, consensus) on a YouTube video.",
        "parameters": {
            "type": "object",
            "properties": {
                "url_or_name": {"type": "string", "description": "YouTube video URL or title"},
                "max_comments": {"type": "integer", "description": "Number of comments to analyze (default 30)"}
            },
            "required": ["url_or_name"],
        },
    },
    {
        "name": "get_youtube_video_details",
        "description": "Fetch deep metadata for a YouTube video including exact duration, view count, like count, and channel info.",
        "parameters": {
            "type": "object",
            "properties": {
                "url_or_name": {"type": "string", "description": "YouTube video URL or title"}
            },
            "required": ["url_or_name"],
        },
    },
)


def _failure(action: str, message: str, error: str, **data: Any) -> AutomationResult:
    return AutomationResult(False, action, message, data, error)


def _clean_required(value: str, label: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{label} empty nahi ho sakta.")
    return cleaned


def _validated_http_url(url_or_name: str) -> str:
    cleaned = _clean_required(url_or_name, "URL")
    alias = WEBSITE_ALIASES.get(cleaned.casefold())
    candidate = alias or cleaned
    if any(character.isspace() for character in candidate):
        raise ValueError("URL mein spaces allowed nahi hain.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("Sirf http:// ya https:// URL allowed hai.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Valid public website host required hai.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("URL port invalid hai.") from exc
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc, parsed.path or "", parsed.query, "")
    )


def _open_browser_url(action: str, url: str, message: str) -> AutomationResult:
    # If this is a YouTube URL and YouTube window is ALREADY OPEN, navigate existing tab to avoid duplicate tab
    try:
        if "youtube.com" in url.casefold():
            from desktop_workflow_agent import UniversalInAppOperator
            active_t, _, active_title = UniversalInAppOperator.get_foreground_app_info()
            yt_hwnd, _ = UniversalInAppOperator.find_open_app_window("youtube")
            if (active_t == "youtube" or "youtube" in active_title.casefold()) or yt_hwnd:
                target_hwnd = yt_hwnd or (active_t == "youtube" and UniversalInAppOperator.get_foreground_app_info()[1])
                if target_hwnd:
                    UniversalInAppOperator.bring_to_foreground(target_hwnd)
                import pyautogui, pyperclip
                pyautogui.FAILSAFE = False
                pyautogui.hotkey("ctrl", "l")
                time.sleep(0.2)
                pyperclip.copy(url)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.2)
                pyautogui.press("enter")
                return AutomationResult(True, action, message, {"url": url, "same_tab": True})
    except Exception as dup_exc:
        LOGGER.debug("Same-tab browser navigation notice: %s", dup_exc)

    try:
        opened = bool(webbrowser.open(url, new=2))
    except Exception as exc:
        return _failure(
            action,
            "Browser request fail hui; koi success assume nahi ki gayi.",
            "browser_error",
            exception_type=type(exc).__name__,
        )
    if not opened:
        return _failure(
            action,
            "Default browser ne open request accept nahi ki.",
            "browser_rejected",
            url=url,
        )
    return AutomationResult(True, action, message, {"url": url})


def open_website(url_or_name: str) -> AutomationResult:
    """Open a validated HTTP/HTTPS URL, known website alias, or local folder path."""
    raw_str = str(url_or_name).strip()
    if os.name == "nt" and (
        re.match(r"^[a-zA-Z]:[\\/]", raw_str)
        or raw_str.lower() in {"downloads", "documents", "desktop", "pictures", "videos"}
    ):
        try:
            target_path = raw_str
            if raw_str.lower() in {"downloads", "documents", "desktop", "pictures", "videos"}:
                target_path = str(Path.home() / raw_str.title())
            if os.path.exists(target_path):
                subprocess.Popen(["explorer.exe", target_path], shell=False, close_fds=True)
                return AutomationResult(True, "open_website", f"Folder open kar diya: {target_path}", {"path": target_path})
        except Exception as p_exc:
            LOGGER.debug("Local path open exception: %s", p_exc)

    try:
        url = _validated_http_url(url_or_name)
    except (TypeError, ValueError) as exc:
        return _failure("open_website", str(exc), "invalid_url")

    # Prevent duplicate tabs if YouTube is already open in browser
    try:
        if "youtube.com" in url.casefold():
            from urllib.parse import parse_qs, urlparse
            from desktop_workflow_agent import UniversalInAppOperator
            parsed_u = urlparse(url)
            # If this is a search query URL (e.g. youtube.com/results?search_query=...)
            if "results" in parsed_u.path and parsed_u.query:
                q_params = parse_qs(parsed_u.query)
                sq = q_params.get("search_query", [""])[0]
                if sq:
                    active_t, _, active_title = UniversalInAppOperator.get_foreground_app_info()
                    yt_hwnd, _ = UniversalInAppOperator.find_open_app_window("youtube")
                    if (active_t == "youtube" or "youtube" in active_title.casefold()) or yt_hwnd:
                        res = UniversalInAppOperator.search_in_active_or_open_app(sq, target_app="youtube")
                        if res.get("success"):
                            return AutomationResult(
                                True,
                                "open_website",
                                f"Active YouTube tab me '{sq}' search kar diya (bina naya tab khole).",
                                {"url": url, "same_tab": True},
                            )
            # If this is root youtube.com and YouTube window is already open, bring to foreground!
            elif parsed_u.path in {"", "/"} and not parsed_u.query:
                active_t, _, active_title = UniversalInAppOperator.get_foreground_app_info()
                if active_t == "youtube" or "youtube" in active_title.casefold():
                    return AutomationResult(
                        True,
                        "open_website",
                        "YouTube already active foreground window me open hai.",
                        {"url": url, "already_active": True},
                    )
                yt_hwnd, _ = UniversalInAppOperator.find_open_app_window("youtube")
                if yt_hwnd:
                    UniversalInAppOperator.bring_to_foreground(yt_hwnd)
                    return AutomationResult(
                        True,
                        "open_website",
                        "YouTube window already open thi, foreground me le aaya.",
                        {"url": url, "focused_existing": True},
                    )
    except Exception as yt_dup_exc:
        LOGGER.debug("open_website duplicate tab avoidance notice: %s", yt_dup_exc)

    return _open_browser_url("open_website", url, f"Website open kar di: {url}")


def search_google(query: str, open_browser: bool | None = None) -> AutomationResult:
    """Search Google/Web for real-time information and return grounded facts to speak aloud."""
    try:
        cleaned = _clean_required(query, "Search query")
    except (TypeError, ValueError) as exc:
        return _failure("search_google", str(exc), "empty_query")

    search_summary = ""
    sources_text = ""
    try:
        from config import load_settings
        from realtimeinfo import RealtimeInfoService
        s = load_settings()
        service = RealtimeInfoService(s)
        resp = service.answer(cleaned)
        if resp and resp.speech_text and not resp.error:
            search_summary = resp.speech_text
            if resp.sources:
                sources_text = " (" + ", ".join(getattr(src, "title", "") for src in resp.sources[:2]) + ")"
    except Exception as exc:
        LOGGER.debug("Realtime search lookup notice: %s", exc)

    # Check if user explicitly asked to open the browser / Chrome
    should_open_browser = open_browser
    if should_open_browser is None:
        should_open_browser = bool(
            re.search(r"\b(?:open|kholo|dikhao|browser|chrome|tab|page)\b", cleaned, re.I)
        )

    url = f"https://www.google.com/search?q={quote_plus(cleaned)}"
    if should_open_browser:
        _open_browser_url("search_google", url, f"Google par search open kar diya: {cleaned}")

    if search_summary:
        msg = f"Web search results for '{cleaned}':\n{search_summary}{sources_text}"
        return AutomationResult(True, "search_google", msg, {"query": cleaned, "summary": search_summary, "url": url})

    # Fallback if no search summary retrieved
    if not should_open_browser:
        _open_browser_url("search_google", url, f"Google par search open kar diya: {cleaned}")
    return AutomationResult(True, "search_google", f"Google par search open kar diya: {cleaned}", {"query": cleaned, "url": url})


_SENSITIVE_MESSAGE_PATTERN = re.compile(
    r"\b(?:otp|one[- ]time password|password|passcode|cvv|card pin|upi pin|"
    r"private key|recovery phrase|seed phrase|access token)\b",
    re.I,
)
_AMBIGUOUS_RECIPIENTS = frozenset(
    {"him", "her", "them", "someone", "isko", "usko", "inko", "unko"}
)


def prepare_whatsapp_message(recipient: str, message: str = "") -> AutomationResult:
    """Open a prefilled WhatsApp Desktop or Web draft without sending the message."""

    try:
        cleaned_recipient = _clean_required(recipient, "Recipient").strip(" ,:;")
        cleaned_message = str(message or "").strip()
    except (TypeError, ValueError) as exc:
        return _failure(
            "prepare_whatsapp_message",
            str(exc),
            "invalid_whatsapp_draft",
        )
    # Auto-resolve contact name to phone number via contact.py
    if not compact_phone.isdigit() or len(compact_phone) < 7:
        try:
            from contact import resolve_contact_phone
            resolved_p = resolve_contact_phone(cleaned_recipient)
            if resolved_p:
                compact_phone = re.sub(r"[\s()+.-]", "", resolved_p)
        except Exception:
            pass

    try:
        from contact import is_dummy_phone
        if is_dummy_phone(compact_phone):
            compact_phone = ""
    except Exception:
        pass

    if not compact_phone.isdigit() or len(compact_phone) < 7:
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            try:
                startfile("whatsapp://")
                return AutomationResult(
                    True,
                    "prepare_whatsapp_message",
                    f"WhatsApp Desktop open kar diya. '{cleaned_recipient}' ke liye message draft karne ke liye WhatsApp me contact select kijiye.",
                    {
                        "recipient": cleaned_recipient,
                        "draft_only": True,
                        "recipient_selection_required": True,
                    },
                )
            except Exception:
                pass
        return _failure(
            "prepare_whatsapp_message",
            "WhatsApp draft ke liye valid phone number ya contacts.json me saved contact chahiye.",
            "invalid_phone_number",
        )
    # Auto-prepend 91 if 10-digit Indian number without country code
    if len(compact_phone) == 10:
        compact_phone = f"91{compact_phone}"

    if len(cleaned_message) > 1000:
        return _failure(
            "prepare_whatsapp_message",
            "WhatsApp draft 1000 characters se chhota rakhiye.",
            "message_too_long",
        )
    if cleaned_message and _SENSITIVE_MESSAGE_PATTERN.search(cleaned_message):
        return _failure(
            "prepare_whatsapp_message",
            "OTP, password, PIN, private key ya access token ka draft blocked hai.",
            "sensitive_message_blocked",
        )

    uri = f"whatsapp://send?phone={compact_phone}"
    if cleaned_message:
        uri += f"&text={quote_plus(cleaned_message)}"

    startfile = getattr(os, "startfile", None)
    if callable(startfile):
        try:
            startfile(uri)
            return AutomationResult(
                True,
                "prepare_whatsapp_message",
                (
                    f"WhatsApp draft +{compact_phone} ke liye open kar diya. "
                    "Message abhi send nahi hua."
                ),
                {
                    "recipient": f"+{compact_phone}",
                    "draft_only": True,
                    "recipient_selection_required": False,
                },
            )
        except Exception:
            pass

    # Browser fallback via WhatsApp Web / wa.me
    web_url = f"https://web.whatsapp.com/send?phone={compact_phone}"
    if cleaned_message:
        web_url += f"&text={quote_plus(cleaned_message)}"
    return _open_browser_url(
        "prepare_whatsapp_message",
        web_url,
        f"WhatsApp Web draft +{compact_phone} ke liye open kar diya.",
    )


def _foreground_window_identity() -> tuple[int, str, str]:
    """Return foreground HWND, title, and executable path on Windows."""

    if os.name != "nt":
        return 0, "", ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        kernel32.OpenProcess.restype = ctypes.c_void_p
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return 0, "", ""

        title_length = int(user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd)))
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        user32.GetWindowTextW(
            ctypes.c_void_p(hwnd),
            title_buffer,
            len(title_buffer),
        )

        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(
            ctypes.c_void_p(hwnd),
            ctypes.byref(process_id),
        )
        process_handle = kernel32.OpenProcess(
            0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
            False,
            process_id.value,
        )
        process_path = ""
        if process_handle:
            try:
                path_buffer = ctypes.create_unicode_buffer(32768)
                path_size = ctypes.c_ulong(len(path_buffer))
                if kernel32.QueryFullProcessImageNameW(
                    ctypes.c_void_p(process_handle),
                    0,
                    path_buffer,
                    ctypes.byref(path_size),
                ):
                    process_path = path_buffer.value
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(process_handle))
        return hwnd, title_buffer.value, process_path
    except Exception:
        return 0, "", ""


def _is_verified_whatsapp_window(title: str, process_path: str) -> bool:
    title_key = str(title).casefold()
    process_path_key = str(process_path).casefold()
    process_name = Path(str(process_path)).name.casefold()
    if process_name == "whatsapp.root.exe":
        return "5319275a.whatsappdesktop" in process_path_key or "whatsapp" in title_key
    if process_name == "whatsapp.exe":
        return "whatsapp" in title_key or not title_key
    return (
        (process_name == "applicationframehost.exe" and "whatsapp" in title_key)
        or ("whatsapp" in title_key and ("whatsapp" in process_path_key or not process_path_key))
    )


def _find_whatsapp_hwnd() -> int:
    """Locate the top-level WhatsApp desktop window handle across all processes."""
    if os.name != "nt":
        return 0
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        candidates: list[tuple[int, int]] = []

        def _enum_cb(hwnd: int, _: Any) -> int:
            try:
                if not user32.IsWindow(ctypes.c_void_p(hwnd)):
                    return 1
                length = user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
                title = ""
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(ctypes.c_void_p(hwnd), buff, length + 1)
                    title = buff.value

                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
                proc_path = ""
                if pid.value:
                    hproc = kernel32.OpenProcess(0x1000, False, pid.value)
                    if hproc:
                        try:
                            pbuff = ctypes.create_unicode_buffer(1024)
                            psize = ctypes.c_ulong(1024)
                            if kernel32.QueryFullProcessImageNameW(
                                ctypes.c_void_p(hproc), 0, pbuff, ctypes.byref(psize)
                            ):
                                proc_path = pbuff.value
                        finally:
                            kernel32.CloseHandle(ctypes.c_void_p(hproc))

                if _is_verified_whatsapp_window(title, proc_path):
                    is_vis = bool(user32.IsWindowVisible(ctypes.c_void_p(hwnd)))
                    priority = 2 if (is_vis and title) else (1 if (is_vis or title) else 0)
                    candidates.append((priority, hwnd))
            except Exception:
                pass
            return 1

        cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(cb_type(_enum_cb), 0)
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
    except Exception as exc:
        LOGGER.debug("WhatsApp HWND search error: %s", exc)
    return 0


def _bring_window_to_foreground(hwnd: int) -> bool:
    """Bring target window to foreground bypassing Windows focus-stealing lock."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        fg_hwnd = int(user32.GetForegroundWindow() or 0)
        if fg_hwnd == hwnd:
            return True

        fg_thread = user32.GetWindowThreadProcessId(ctypes.c_void_p(fg_hwnd), None) if fg_hwnd else 0
        cur_thread = kernel32.GetCurrentThreadId()

        attached = False
        if fg_thread and fg_thread != cur_thread:
            attached = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))

        try:
            # Simulate Alt key tap to unlock SetForegroundWindow on Windows
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 0x0002, 0)

            # SW_RESTORE = 9, SW_SHOW = 5
            if user32.IsIconic(ctypes.c_void_p(hwnd)):
                user32.ShowWindow(ctypes.c_void_p(hwnd), 9)
            else:
                user32.ShowWindow(ctypes.c_void_p(hwnd), 5)

            user32.BringWindowToTop(ctypes.c_void_p(hwnd))
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        finally:
            if attached:
                user32.AttachThreadInput(cur_thread, fg_thread, False)

        time.sleep(0.35)
        active = int(user32.GetForegroundWindow() or 0)
        return active == hwnd or bool(user32.IsWindowVisible(ctypes.c_void_p(hwnd)))
    except Exception as exc:
        LOGGER.debug("Bring window to foreground error: %s", exc)
        return False


def _wait_for_whatsapp_window(timeout_seconds: float = 6.0) -> int:
    """Locate WhatsApp window and ensure it owns foreground focus."""
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        hwnd = _find_whatsapp_hwnd()
        if hwnd:
            _bring_window_to_foreground(hwnd)
            return hwnd
        fg_hwnd, title, proc_path = _foreground_window_identity()
        if fg_hwnd and _is_verified_whatsapp_window(title, proc_path):
            return fg_hwnd
        time.sleep(0.3)
    return 0


def _send_enter_to_verified_window(hwnd: int) -> bool:
    """Send Enter only while the verified WhatsApp window owns focus."""

    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        time.sleep(0.15)
        active_hwnd, title, process_path = _foreground_window_identity()
        if active_hwnd != hwnd or not _is_verified_whatsapp_window(
            title,
            process_path,
        ):
            return False
        user32.keybd_event(0x0D, 0, 0, 0)
        user32.keybd_event(0x0D, 0, 0x0002, 0)
        return True
    except Exception:
        return False


def _send_unicode_text(text: str) -> bool:
    """Type arbitrary Unicode into the currently focused Windows control."""

    if os.name != "nt":
        return False
    try:
        class KeyboardInput(ctypes.Structure):
            _fields_ = (
                ("virtual_key", ctypes.c_ushort),
                ("scan_code", ctypes.c_ushort),
                ("flags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("extra_info", ctypes.c_size_t),
            )

        class MouseInput(ctypes.Structure):
            _fields_ = (
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouse_data", ctypes.c_ulong),
                ("flags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("extra_info", ctypes.c_size_t),
            )

        class HardwareInput(ctypes.Structure):
            _fields_ = (
                ("message", ctypes.c_ulong),
                ("parameter_low", ctypes.c_ushort),
                ("parameter_high", ctypes.c_ushort),
            )

        class InputValue(ctypes.Union):
            _fields_ = (
                ("mouse", MouseInput),
                ("keyboard", KeyboardInput),
                ("hardware", HardwareInput),
            )

        class Input(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = (("input_type", ctypes.c_ulong), ("value", InputValue))

        units = [
            int.from_bytes(encoded[index : index + 2], "little")
            for encoded in (str(text).encode("utf-16-le"),)
            for index in range(0, len(encoded), 2)
        ]
        events: list[Input] = []
        for unit in units:
            events.append(
                Input(
                    input_type=1,
                    keyboard=KeyboardInput(0, unit, 0x0004, 0, 0),
                )
            )
            events.append(
                Input(
                    input_type=1,
                    keyboard=KeyboardInput(0, unit, 0x0004 | 0x0002, 0, 0),
                )
            )
        if not events:
            return True
        event_array = (Input * len(events))(*events)
        sent = ctypes.windll.user32.SendInput(
            len(event_array),
            ctypes.byref(event_array),
            ctypes.sizeof(Input),
        )
        return int(sent) == len(event_array)
    except Exception:
        return False


def _control_identity(control: Any) -> tuple[Any, ...]:
    info = control.element_info
    runtime_id = tuple(getattr(info, "runtime_id", ()) or ())
    if runtime_id:
        return runtime_id
    rectangle = control.rectangle()
    return (
        getattr(info, "control_type", ""),
        rectangle.left,
        rectangle.top,
        rectangle.right,
        rectangle.bottom,
    )


def _exact_whatsapp_contact(window: Any, recipient: str) -> tuple[Any | None, str | None]:
    """Return one exact UIA contact result, rejecting missing/duplicate names."""

    wanted = recipient.strip().casefold()
    unique: dict[tuple[Any, ...], Any] = {}
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        for control in window.descendants():
            try:
                if not control.is_visible() or not control.is_enabled():
                    continue
                if control.window_text().strip().casefold() != wanted:
                    continue
                if control.element_info.control_type == "Edit":
                    continue
                clickable = control
                parent = control
                for _ in range(3):
                    parent = parent.parent()
                    if parent is None:
                        break
                    if parent.element_info.control_type in {"ListItem", "Button"}:
                        clickable = parent
                        break
                unique[_control_identity(clickable)] = clickable
            except Exception:
                continue
        if unique:
            break
        time.sleep(0.25)
    if not unique:
        return None, "contact_not_found"
    if len(unique) != 1:
        return None, "ambiguous_contact"
    return next(iter(unique.values())), None


def _whatsapp_message_box(window: Any) -> Any | None:
    """Find the visible message composer, preferring its accessible label."""

    try:
        window_rectangle = window.rectangle()
        candidates = []
        for control in window.descendants(control_type="Edit"):
            if not control.is_visible() or not control.is_enabled():
                continue
            rectangle = control.rectangle()
            label = control.window_text().strip().casefold()
            if "search" in label:
                continue
            named_message_box = any(
                marker in label
                for marker in ("message", "type a message", "संदेश")
            )
            lower_area = rectangle.top >= (
                window_rectangle.top + int(window_rectangle.height() * 0.55)
            )
            if named_message_box or lower_area:
                candidates.append((named_message_box, rectangle.bottom, control))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]
    except Exception:
        return None


def _search_contact_and_send(hwnd: int, recipient: str, message: str) -> str | None:
    """Search WhatsApp contact by name, open chat, paste message into composer, and send."""
    if not hwnd:
        return "whatsapp_not_running"

    try:
        import pyautogui
        import pyperclip
        pyautogui.FAILSAFE = False
    except ImportError:
        return "pyautogui_dependency_missing"

    try:
        _bring_window_to_foreground(hwnd)
        time.sleep(0.6)

        # 1. Dismiss any open modal dialogs (e.g. "Number isn't on WhatsApp") or clear active search
        pyautogui.press("escape")
        time.sleep(0.15)
        pyautogui.press("enter")
        time.sleep(0.15)
        pyautogui.press("escape")
        time.sleep(0.2)

        # 2. Focus New Chat contact search dialog in WhatsApp Desktop
        pyautogui.hotkey("ctrl", "n")
        time.sleep(0.4)

        # 3. Paste contact name
        pyperclip.copy(recipient)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.8)

        # 4. Open chat for that contact
        pyautogui.press("enter")
        time.sleep(1.0)  # Wait for chat composer to fully mount and focus

        # 5. Paste message and send
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
        pyautogui.press("enter")
        time.sleep(0.5)
        return None
    except Exception as exc:
        LOGGER.warning("WhatsApp contact search/send failed: %s", exc)
        return "whatsapp_gui_failed"


def send_whatsapp_message(recipient: str, message: str) -> AutomationResult:
    """Open WhatsApp Desktop/Web and dispatch Send directly by contact name or number."""

    try:
        cleaned_recipient = _clean_required(recipient, "Recipient").strip(" ,:;")
        cleaned_message = _clean_required(message, "Message")
    except (TypeError, ValueError) as exc:
        return _failure(
            "send_whatsapp_message",
            str(exc),
            "invalid_whatsapp_message",
        )
    compact_phone = re.sub(r"[\s()+.-]", "", cleaned_recipient)
    is_phone = (
        (cleaned_recipient.startswith("+") and compact_phone.isdigit())
        or (compact_phone.isdigit() and len(compact_phone) == 10)
    )
    if is_phone and len(compact_phone) == 10 and not cleaned_recipient.startswith("+"):
        compact_phone = f"91{compact_phone}"

    # Auto-resolve contact name to phone number via contact.py
    if not is_phone:
        try:
            from contact import resolve_contact_phone
            resolved_p = resolve_contact_phone(cleaned_recipient)
            if resolved_p:
                compact_phone = re.sub(r"[\s()+.-]", "", resolved_p)
                is_phone = True
        except Exception:
            pass

    # Dummy phone check: avoid treating mock/placeholder numbers as dialable phones
    try:
        from contact import is_dummy_phone
        if is_phone and is_dummy_phone(compact_phone):
            is_phone = False
    except Exception:
        pass

    if len(cleaned_message) > 1000:
        return _failure(
            "send_whatsapp_message",
            "WhatsApp message 1000 characters se chhota rakhiye.",
            "message_too_long",
        )
    if _SENSITIVE_MESSAGE_PATTERN.search(cleaned_message):
        return _failure(
            "send_whatsapp_message",
            "OTP, password, PIN, private key ya access token send karna blocked hai.",
            "sensitive_message_blocked",
        )

    # 1. Headless Background Dispatch (Meta Cloud API / Twilio) if configured
    try:
        from whatsapp_engine import dispatch_headless_whatsapp
        from config import load_settings
        settings = load_settings()
        headless_res = dispatch_headless_whatsapp(cleaned_recipient, cleaned_message, settings=settings)
        if headless_res and headless_res.get("success"):
            provider_label = "WhatsApp Cloud API" if headless_res.get("provider") == "cloud_api" else "Twilio API"
            return AutomationResult(
                True,
                "send_whatsapp_message",
                f"Captain, {provider_label} se background me message send kar diya: '{cleaned_message}'",
                {
                    "recipient": cleaned_recipient,
                    "message": cleaned_message,
                    "provider": headless_res.get("provider"),
                    "message_id": headless_res.get("message_id") or headless_res.get("message_sid"),
                    "headless": True,
                },
            )
    except Exception as headless_err:
        LOGGER.debug("Headless WhatsApp attempt notice: %s", headless_err)

    startfile = getattr(os, "startfile", None)
    uri = (
        f"whatsapp://send?phone={compact_phone}&text={quote_plus(cleaned_message)}"
        if is_phone
        else "whatsapp://"
    )
    if callable(startfile):
        try:
            startfile(uri)
        except Exception:
            pass

    hwnd = _wait_for_whatsapp_window(timeout_seconds=6.0)
    if not hwnd:
        if is_phone:
            # Fallback to WhatsApp Web send
            return _open_browser_url(
                "send_whatsapp_message",
                f"https://web.whatsapp.com/send?phone={compact_phone}&text={quote_plus(cleaned_message)}",
                f"WhatsApp Web par {cleaned_recipient} ke liye message draft open kar diya.",
            )
        return _failure(
            "send_whatsapp_message",
            f"WhatsApp Desktop open ya screen par focus nahi ho saka. Kripya pehle WhatsApp open kijiye.",
            "whatsapp_window_not_found",
        )

    _bring_window_to_foreground(hwnd)

    if is_phone:
        # Give WhatsApp 2 seconds to load chat and enable Send button
        time.sleep(2.0)
        sent = _send_enter_to_verified_window(hwnd)
        if not sent:
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.press("enter")
            except Exception:
                pass
    else:
        send_error = _search_contact_and_send(
            hwnd,
            cleaned_recipient,
            cleaned_message,
        )
        if send_error is not None:
            return _failure(
                "send_whatsapp_message",
                f"WhatsApp par '{cleaned_recipient}' search karke message send nahi ho saka.",
                send_error,
            )

    return AutomationResult(
        True,
        "send_whatsapp_message",
        f"WhatsApp par {cleaned_recipient} ko message send kar diya: '{cleaned_message}'",
        {
            "recipient": cleaned_recipient,
            "message": cleaned_message,
            "send_dispatched": True,
        },
    )


def search_whatsapp_contact(contact_name: str) -> AutomationResult:
    """Search for a contact or chat on WhatsApp Desktop WITHOUT sending any message."""
    try:
        cleaned = _clean_required(contact_name, "Contact name").strip(" ,:;")
    except (TypeError, ValueError) as exc:
        return _failure("search_whatsapp_contact", str(exc), "invalid_contact_name")

    startfile = getattr(os, "startfile", None)
    if callable(startfile):
        try:
            startfile("whatsapp://")
        except Exception:
            pass

    hwnd = _wait_for_whatsapp_window(timeout_seconds=5.0)
    if not hwnd:
        return _failure(
            "search_whatsapp_contact",
            f"WhatsApp Desktop open ya screen par focus nahi ho saka. Kripya pehle WhatsApp Desktop start kijiye.",
            "whatsapp_window_not_found",
        )

    _bring_window_to_foreground(hwnd)
    time.sleep(0.5)

    try:
        import pyautogui
        import pyperclip
        pyautogui.FAILSAFE = False

        # 1. Clear any active chat search / modal
        pyautogui.press("escape")
        time.sleep(0.2)
        pyautogui.press("escape")
        time.sleep(0.2)

        # 2. Focus contact search in WhatsApp Desktop (Ctrl+N opens New Chat search)
        pyautogui.hotkey("ctrl", "n")
        time.sleep(0.4)

        # 3. Paste contact name into search box
        pyperclip.copy(cleaned)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.8)

        # 4. Open chat for top search result
        pyautogui.press("enter")
        time.sleep(0.6)

        return AutomationResult(
            True,
            "search_whatsapp_contact",
            f"WhatsApp par '{cleaned}' search karke chat open kar di hai. Screen par dekh lijiye.",
            {"contact": cleaned, "action": "searched_and_opened", "message_sent": False},
        )
    except Exception as exc:
        return _failure("search_whatsapp_contact", f"WhatsApp contact search fail hua: {exc}", "gui_error")


def make_phone_call(recipient: str, method: str = "auto") -> AutomationResult:
    """Dial a cellular/phone call via Microsoft Mobile Link (Phone Link) or connected Android ADB."""
    try:
        cleaned = _clean_required(recipient, "Recipient")
    except (TypeError, ValueError) as exc:
        return _failure("make_phone_call", str(exc), "invalid_recipient")

    try:
        from contact import make_phone_call as _dispatch_call
        res = _dispatch_call(cleaned, method=method)
        if res.get("success"):
            return AutomationResult(
                True,
                "make_phone_call",
                res.get("message", f"{cleaned} ko call laga diya hai."),
                res,
            )
        return _failure(
            "make_phone_call",
            res.get("message", f"{cleaned} ko call lagane me error aaya."),
            res.get("error", "call_failed"),
        )
    except Exception as exc:
        LOGGER.warning("Phone call dispatch error: %s", exc)
        return _failure("make_phone_call", f"Call lagane me error aaya: {exc}", "call_error")


_ORDINAL_WORDS: dict[str, int] = {
    "1st": 1, "first": 1, "pehla": 1, "pahla": 1, "1": 1, "one": 1, "ek": 1,
    "2nd": 2, "second": 2, "doosra": 2, "dusra": 2, "2": 2, "two": 2, "do": 2,
    "3rd": 3, "third": 3, "teesra": 3, "tisra": 3, "3": 3, "three": 3, "teen": 3,
    "4th": 4, "fourth": 4, "chautha": 4, "4": 4, "four": 4, "chaar": 4, "char": 4,
    "5th": 5, "fifth": 5, "paanchwa": 5, "panchwa": 5, "5": 5, "five": 5, "paanch": 5,
    "last": -1, "aakhri": -1, "akhri": -1,
}


def parse_ordinal_selection(text: str) -> int | None:
    """Extract a 1-based index from phrases like '2nd wala', 'second option', 'teesra gaana'."""
    cleaned = text.strip().casefold()

    # 1. Explicit ordinal words (1st, first, pehla, 2nd, second, doosra, 3rd, third, teesra, 4th, 5th, last, etc.)
    explicit_match = re.search(
        r"\b(1st|first|pehla|pahla|2nd|second|doosra|dusra|3rd|third|teesra|tisra|4th|fourth|chautha|5th|fifth|paanchwa|panchwa|last|aakhri|akhri)\b(?:\s*(?:wala|waala|wali|waali|number|no|option|video|song|gana|gaana|track|item|link))?",
        cleaned,
        re.I,
    )
    if explicit_match:
        token = explicit_match.group(1).lower()
        return _ORDINAL_WORDS.get(token)

    # 2. Ambiguous cardinal numbers (1, 2, 3, 4, 5, one, two, three, ek, do, teen, etc.) REQUIRE an ordinal marker suffix
    cardinal_match = re.search(
        r"\b(1|one|ek|2|two|do|3|three|teen|4|four|chaar|char|5|five|paanch)\s+(?:wala|waala|wali|waali|number|no|option|video|song|gana|gaana|track|item|link)\b",
        cleaned,
        re.I,
    )
    if cardinal_match:
        token = cardinal_match.group(1).lower()
        return _ORDINAL_WORDS.get(token)

    return None


def extract_youtube_search_results(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Extract indexed YouTube video titles and IDs using official YouTube API v3 (if configured) or scraping."""
    results: list[dict[str, str]] = []

    # 1. Official YouTube Data API v3 (sub-50ms latency)
    try:
        from config import load_settings
        s = load_settings()
        yt_api_key = s.youtube_api_key or os.environ.get("YOUTUBE_API_KEY")
        if yt_api_key:
            import json
            api_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults={max_results}&q={quote_plus(query)}&key={yt_api_key}"
            req = urllib.request.Request(api_url, headers={"User-Agent": "DarkShadow-AI/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("items", []):
                    vid = item.get("id", {}).get("videoId")
                    snippet = item.get("snippet", {})
                    if vid and len(vid) == 11:
                        results.append({
                            "id": vid,
                            "title": snippet.get("title", f"Video {len(results)+1}"),
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "channel": snippet.get("channelTitle", ""),
                        })
                if results:
                    return results
    except Exception as api_err:
        LOGGER.debug("YouTube Data API v3 query failed: %s", api_err)

    # 2. HTML data scraping fallback
    try:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
            m = re.search(r"var ytInitialData = ({.*?});</script>", html)
            if m:
                import json
                data = json.loads(m.group(1))
                seen_ids: set[str] = set()

                def _walk(obj: Any) -> None:
                    if len(results) >= max_results:
                        return
                    if isinstance(obj, dict):
                        if "videoRenderer" in obj:
                            vr = obj["videoRenderer"]
                            vid = str(vr.get("videoId", "") or "").strip()
                            runs = vr.get("title", {}).get("runs", [{}])
                            title = (runs[0].get("text", "") if runs else "") or vr.get("title", {}).get("simpleText", "")
                            if vid and len(vid) == 11 and vid not in seen_ids:
                                seen_ids.add(vid)
                                results.append({
                                    "id": vid,
                                    "title": title.strip() or f"Video {len(results)+1}",
                                    "url": f"https://www.youtube.com/watch?v={vid}",
                                })
                        for v in obj.values():
                            _walk(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            _walk(item)

                _walk(data)

            if not results:
                raw_ids = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
                seen_ids = set()
                for vid in raw_ids:
                    if vid not in seen_ids and len(vid) == 11:
                        seen_ids.add(vid)
                        results.append({
                            "id": vid,
                            "title": f"YouTube Video ({vid})",
                            "url": f"https://www.youtube.com/watch?v={vid}",
                        })
                        if len(results) >= max_results:
                            break
    except Exception as exc:
        LOGGER.debug("YouTube result extraction failed: %s", exc)
    return results


def search_youtube(query: str, context: AutomationContext | None = None) -> AutomationResult:
    """Search YouTube, open results in browser, and save indexed list in context."""
    try:
        cleaned = _clean_required(query, "Search query")
    except (TypeError, ValueError) as exc:
        return _failure("search_youtube", str(exc), "empty_query")

    ctx = context or GLOBAL_AUTOMATION_CONTEXT
    results = extract_youtube_search_results(cleaned, max_results=5)
    if results:
        ctx.remember_search_results(cleaned, results)

    # Prevent opening duplicate tabs if YouTube is already active or open in background
    try:
        from desktop_workflow_agent import UniversalInAppOperator
        active_type, active_hwnd, active_title = UniversalInAppOperator.get_foreground_app_info()
        yt_hwnd, yt_title = UniversalInAppOperator.find_open_app_window("youtube")
        if (active_type == "youtube" or "youtube" in active_title.casefold()) or yt_hwnd:
            res = UniversalInAppOperator.search_in_active_or_open_app(cleaned, target_app="youtube")
            if res.get("success"):
                formatted_list = "\n".join(f"{i}. {r['title']}" for i, r in enumerate(results[:3], 1)) if results else ""
                msg = f"Captain, active YouTube tab me '{cleaned}' search kar diya hai (bina naya tab khole)."
                if formatted_list:
                    msg += f"\nTop Options:\n{formatted_list}\n\n(Aap bol sakte hain: '2nd wala chala do')"
                return AutomationResult(
                    True,
                    "search_youtube",
                    msg,
                    {"query": cleaned, "results": results, "same_tab": True},
                )
    except Exception as exc:
        LOGGER.debug("In-page YouTube search check notice: %s", exc)

    url = f"https://www.youtube.com/results?search_query={quote_plus(cleaned)}"
    _open_browser_url("search_youtube", url, f"YouTube search open kar diya: {cleaned}")

    if results:
        formatted_list = "\n".join(f"{i}. {r['title']}" for i, r in enumerate(results[:3], 1))
        msg = f"Captain, YouTube par '{cleaned}' search kar diya hai.\nTop Options:\n{formatted_list}\n\n(Aap bol sakte hain: '2nd wala chala do')"
    else:
        msg = f"YouTube search open kar diya: {cleaned}"

    return AutomationResult(
        True,
        "search_youtube",
        msg,
        {"query": cleaned, "results": results, "url": url},
    )


def search_in_active_app(query: str, app_name: str | None = None) -> AutomationResult:
    """Perform search directly within currently active app or open target app without duplicate tabs."""
    try:
        cleaned = _clean_required(query, "Search query")
    except (TypeError, ValueError) as exc:
        return _failure("search_in_active_app", str(exc), "empty_query")
    try:
        from desktop_workflow_agent import UniversalInAppOperator
        res = UniversalInAppOperator.search_in_active_or_open_app(cleaned, target_app=app_name)
        if res.get("success"):
            return AutomationResult(
                True,
                "search_in_active_app",
                ensure_captain_address(res.get("message", f"'{cleaned}' search kar diya hai.")),
                res,
            )
        return _failure("search_in_active_app", res.get("message", "In-app search fail hua."), res.get("error", "search_failed"))
    except Exception as exc:
        LOGGER.warning("search_in_active_app error: %s", exc)
        return _failure("search_in_active_app", f"In-app search error: {exc}", "execution_error")


def search_spotify(query: str) -> AutomationResult:
    """Open a safely encoded Spotify search page."""

    try:
        cleaned = _clean_required(query, "Search query")
    except (TypeError, ValueError) as exc:
        return _failure("search_spotify", str(exc), "empty_query")
    url = f"https://open.spotify.com/search/{quote_plus(cleaned)}"
    return _open_browser_url(
        "search_spotify",
        url,
        f"Spotify par search open kar diya: {cleaned}",
    )


def _trigger_spotify_autoplay(query: str = "") -> None:
    """Background helper to click the green play button on Spotify after page loads using visual grounding."""
    def _worker() -> None:
        time.sleep(2.5)
        try:
            _focus_browser_window()
            target_desc = f"play button for {query}" if query else "green round play button"
            res = click_screen_element(target=target_desc)
            if not res.success:
                res2 = click_screen_element(target="play button")
                if not res2.success:
                    import pyautogui
                    pyautogui.FAILSAFE = False
                    screen_w, screen_h = pyautogui.size()
                    play_btn_x = int(screen_w * 0.605)
                    play_btn_y = int(screen_h * 0.345)
                    pyautogui.click(play_btn_x, play_btn_y)
        except Exception as exc:
            LOGGER.debug("Spotify autoplay trigger error: %s", exc)
    threading.Thread(target=_worker, name="spotify-autoplay", daemon=True).start()


def play_spotify(query: str = "") -> AutomationResult:
    """Play a track or open search on Spotify using Official Web API or Web Player."""
    q = str(query).strip()
    if not q:
        return open_application("Spotify")

    # Spelling correction for popular tracks (e.g. 'Ahista' -> 'Aahista Arijit Singh')
    clean_q = q
    if "ahista" in clean_q.lower() and "aahista" not in clean_q.lower():
        clean_q = re.sub(r"\bahista\b", "Aahista", clean_q, flags=re.I)
        if "arijit" not in clean_q.lower():
            clean_q = f"{clean_q} Arijit Singh"

    # 1. Official Spotify Web API exact track resolution
    try:
        from spotify_engine import get_spotify_client
        sp = get_spotify_client()
        if sp is not None:
            tracks = sp.search_track(clean_q, limit=3)
            if tracks:
                top = tracks[0]
                track_url = top["url"]
                track_title = f"{top['title']} by {top['artists']}"
                _open_browser_url("play_spotify", track_url, f"Spotify par '{track_title}' play kar diya.")
                _trigger_spotify_autoplay(clean_q)
                return AutomationResult(
                    True,
                    "play_spotify",
                    f"Captain, Spotify API se '{track_title}' play kar diya hai!",
                    {"track": top, "url": track_url, "api_used": True},
                )
    except Exception as exc:
        LOGGER.debug("Spotify Web API lookup error: %s", exc)

    # 2. Direct Spotify search with auto-click play trigger
    res = search_spotify(clean_q)
    _trigger_spotify_autoplay(clean_q)
    return AutomationResult(
        True,
        "play_spotify",
        f"Spotify par '{clean_q}' search karke play trigger kar diya hai.",
        {"query": clean_q, "url": res.data.get("url", ""), "fallback": True},
    )


def _enhance_youtube_music_query(raw_query: str) -> str:
    """Transform generic or ambiguous music queries into curated search terms while preserving specific song titles."""
    cleaned = _strip_invocation(raw_query).strip().casefold()
    
    # Remove playback action keywords
    cleaned = re.sub(
        r"\b(?:chalao|chalo|bajao|bajaao|lagao|lagaao|sunao|sunaao|play\s+karo|play\s+kar\s+do|play|listen\s+to|start)\b",
        "",
        cleaned,
        flags=re.I,
    ).strip()

    # 1. Curated generic mappings ONLY when the entire query is a generic request (e.g. "koi gana", "romantic song", "sad song")
    if cleaned in {
        "", "koi achha gana", "achha gana", "accha gana", "acha gana", "achha song", "accha song",
        "koi achha song", "badhiya gana", "badhiya song", "mast gana", "mast song", "koi mast song",
        "koi badhiya gana", "best song", "best songs", "top song", "top songs", "hit song", "hit songs",
        "koi gana", "koi gaana", "gana", "gaana", "song", "songs", "music", "koi song", "koi track",
        "kuch achha", "kuch acha", "kuch badhiya", "kuch mast", "kuch achha gana", "koi acha gana",
    }:
        return "Top Bollywood Hindi Songs Trending Hits Official Music Video"

    generic_moods = {
        r"^(?:koi\s+)?(?:romantic|love|pyaar|ishq|mohabbat)\s*(?:song|songs|gaana|gana|music|hits|track)?$": "Best Hindi Romantic Songs Love Hits Official Music Video",
        r"^(?:koi\s+)?(?:sad|dard|heartbreak|broken|dukh|udaas)\s*(?:song|songs|gaana|gana|music|hits)?$": "Heart Touching Sad Hindi Songs Arijit Singh Hits",
        r"^(?:koi\s+)?(?:party|dance|club|dj|energetic|dhamaka)\s*(?:song|songs|gaana|gana|music|hits)?$": "Top Bollywood Party Dance Hits Latest Songs",
        r"^(?:koi\s+)?(?:lofi|chill|relax|peaceful|study|sukoon|neend)\s*(?:song|songs|gaana|gana|music|beats|vibes)?$": "Lofi Hindi Songs Slowed Reverb Chill Vibes",
        r"^(?:koi\s+)?(?:punjabi|punjab)\s*(?:song|songs|gaana|gana|music|hits)?$": "Latest Punjabi Hit Songs Official Music Video",
        r"^(?:koi\s+)?(?:bhajan|bhakti|devotional|aarti|krishna|shiv|hanuman)\s*(?:song|songs|gaana|gana|music|bhajan)?$": "Morning Peaceful Hindi Bhajans Best Devotional Songs",
        r"^(?:koi\s+)?(?:90s|old|purane|retro|kishore|rafi|lata|mukesh|rd burman)\s*(?:song|songs|gaana|gana|music|hits)?$": "Best of 90s Bollywood Songs Evergreen Hindi Hits",
        r"^(?:koi\s+)?(?:workout|gym|motivation|josh)\s*(?:song|songs|gaana|gana|music|tracks)?$": "High Energy Workout Motivation Hindi Songs",
    }
    for pattern, mapped_query in generic_moods.items():
        if re.fullmatch(pattern, cleaned, re.I):
            return mapped_query

    # 2. If it's a specific song or artist name (e.g. "Dil Chahte Ho", "Arijit Singh", "Kesariya", "Believer")
    cleaned_term = re.sub(
        r"^(?:koi|ek|kisi|achha|accha|badhiya|mast|popular|famous)\s+",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    if cleaned_term and not any(kw in cleaned_term for kw in {"official", "song", "video", "lyrics", "audio", "jukebox", "hits"}):
        return f"{cleaned_term} official song"
    return cleaned_term or raw_query


def _fetch_first_youtube_video_id(query: str) -> str | None:
    # 1. Try official YouTube Data API or structured search extraction
    try:
        from automation import extract_youtube_search_results
        results = extract_youtube_search_results(query, max_results=3)
        if results:
            for item in results:
                vid = item.get("id")
                if vid and len(vid) == 11:
                    return vid
    except Exception:
        pass

    # 2. Resilient web search fallback (prefer videoId in initialData)
    try:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
            vid_matches = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
            if vid_matches:
                for vid in vid_matches:
                    if vid and len(vid) == 11:
                        return vid
            matches = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
            if matches:
                for vid in matches:
                    if vid and len(vid) == 11:
                        return vid
    except Exception:
        pass
    return None


def play_youtube(
    query: str,
    context: AutomationContext | None = None,
    memory_store: Any | None = None,
) -> AutomationResult:
    """Play a curated YouTube result or resolve an ordinal selection from recent search."""
    try:
        raw_cleaned = _clean_required(query, "Video query")
    except (TypeError, ValueError) as exc:
        return _failure("play_youtube", str(exc), "empty_query")

    ctx = context or GLOBAL_AUTOMATION_CONTEXT

    # 1. Check if user is selecting by ordinal (e.g. "2nd wala", "second option", "teesra")
    ordinal = parse_ordinal_selection(raw_cleaned)
    if ordinal is not None and ctx.last_search_results:
        selected = ctx.get_search_result_by_index(ordinal)
        if selected:
            video_url = f"https://www.youtube.com/watch?v={selected['id']}&autoplay=1"
            _open_browser_url("play_youtube", video_url, f"YouTube par song chala diya: {selected['title']}")
            display_num = "last" if ordinal == -1 else f"{ordinal}"
            return AutomationResult(
                True,
                "play_youtube",
                f"Captain, {display_num} video '{selected['title']}' chala raha hoon.",
                {"selected_video": selected, "index": ordinal, "url": video_url, "from_search_results": True},
            )

    # 2. Check if query is generic and memory has user's favorite music/artist preferences
    curated_query = raw_cleaned
    if memory_store is not None:
        try:
            prefs = (
                memory_store.search_preferences("favorite music")
                or memory_store.search_preferences("music")
                or memory_store.search_preferences("song")
                or memory_store.search_preferences("singer")
            )
            if prefs and any(kw in raw_cleaned.casefold() for kw in {"best", "koi", "achha", "accha", "badhiya", "mast", "pasand", "meri pasand"}):
                pref_content = prefs[0].content
                curated_query = f"{pref_content} best songs"
        except Exception:
            pass

    curated_query = _enhance_youtube_music_query(curated_query)

    try:
        pywhatkit = import_module("pywhatkit")
        if pywhatkit is not None and hasattr(pywhatkit, "playonyt"):
            pywhatkit.playonyt(curated_query)
            return AutomationResult(
                True,
                "play_youtube",
                f"YouTube par '{curated_query}' play kar diya.",
                {"query": curated_query, "raw_query": raw_cleaned, "fallback": False},
            )
    except Exception:
        pass

    video_id = _fetch_first_youtube_video_id(curated_query)
    if video_id:
        video_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
        res = _open_browser_url("play_youtube", video_url, f"YouTube par song chala diya: {curated_query}")
        if res.success:
            return AutomationResult(
                True,
                "play_youtube",
                f"YouTube par song chala diya: {curated_query}",
                {"query": curated_query, "raw_query": raw_cleaned, "video_id": video_id, "url": video_url, "fallback": True},
            )

    fallback = search_youtube(curated_query, context=ctx)
    if fallback.success:
        return AutomationResult(
            True,
            "play_youtube",
            f"Direct playback unavailable tha; YouTube search open kar diya: {curated_query}",
            {
                **fallback.data,
                "query": curated_query,
                "raw_query": raw_cleaned,
                "fallback": True,
            },
        )


def summarize_youtube_video(url_or_name: str, detail_level: str = "concise") -> AutomationResult:
    """Generate an AI summary of a YouTube video or podcast."""
    try:
        cleaned = _clean_required(url_or_name, "Video URL or query")
    except (TypeError, ValueError) as exc:
        return _failure("summarize_youtube_video", str(exc), "empty_query")

    try:
        from youtube_engine import summarize_youtube_video_ai
        from config import load_settings
        s = load_settings()
        res = summarize_youtube_video_ai(
            url_or_query=cleaned,
            detail_level=detail_level,
            youtube_api_key=s.youtube_api_key,
            gemini_api_key=s.api_key,
        )
        if res.get("success"):
            summary = res.get("summary", "")
            title = res.get("title", "")
            msg = f"Captain, '{title}' video ka AI summary:\n\n{summary}"
            return AutomationResult(True, "summarize_youtube_video", msg, res)
        return _failure("summarize_youtube_video", res.get("message", "Summary generation fail hui."), res.get("error", "summary_error"))
    except Exception as exc:
        return _failure("summarize_youtube_video", f"Video summarize nahi ho saki: {exc}", "summarize_error")


def analyze_youtube_comments(url_or_name: str, max_comments: int = 30) -> AutomationResult:
    """Analyze public comments and audience sentiment for a YouTube video."""
    try:
        cleaned = _clean_required(url_or_name, "Video URL or query")
    except (TypeError, ValueError) as exc:
        return _failure("analyze_youtube_comments", str(exc), "empty_query")

    try:
        from youtube_engine import analyze_youtube_comments_ai
        from config import load_settings
        s = load_settings()
        res = analyze_youtube_comments_ai(
            url_or_query=cleaned,
            max_comments=max_comments,
            youtube_api_key=s.youtube_api_key,
            gemini_api_key=s.api_key,
        )
        if res.get("success"):
            analysis = res.get("analysis", "")
            title = res.get("title", "")
            top_comments = res.get("top_comments", [])
            comments_preview = ""
            if top_comments:
                comments_preview = "\n\nTop Comments:\n" + "\n".join(
                    f"{i+1}. {c.get('author', 'User')} ({c.get('likes', 0)} likes): \"{c.get('text', '')[:120]}\""
                    for i, c in enumerate(top_comments[:5])
                )
            msg = f"Captain, '{title}' ke audience comments report:\n\n{analysis}{comments_preview}"
            return AutomationResult(True, "analyze_youtube_comments", msg, res)
        return _failure("analyze_youtube_comments", res.get("message", "Comments analysis fail hui."), res.get("error", "comments_error"))
    except Exception as exc:
        return _failure("analyze_youtube_comments", f"Comments analyze nahi ho sake: {exc}", "comments_error")


def analyze_local_video(
    file_path: str,
    prompt: str = "Analyze this screen recording / video, identify actions, errors, or key events with timestamps.",
) -> AutomationResult:
    """Analyze a local screen recording or video file using Gemini video understanding."""
    try:
        from youtube_engine import analyze_local_video_file
        res = analyze_local_video_file(file_path, prompt=prompt)
        if res.get("success"):
            return AutomationResult(
                True,
                "analyze_local_video",
                f"Captain, video file '{res.get('file_name')}' ka analysis:\n\n{res.get('summary')}",
                res,
            )
        return _failure("analyze_local_video", res.get("message", "Video analysis fail hui."), res.get("error", "video_error"))
    except Exception as exc:
        return _failure("analyze_local_video", f"Video analyze nahi ho saki: {exc}", "video_error")


def get_youtube_video_details(url_or_name: str) -> AutomationResult:
    """Fetch structured metadata and details for a YouTube video."""
    try:
        cleaned = _clean_required(url_or_name, "Video URL or query")
    except (TypeError, ValueError) as exc:
        return _failure("get_youtube_video_details", str(exc), "empty_query")

    try:
        from youtube_engine import extract_youtube_video_id, fetch_video_details
        from config import load_settings
        s = load_settings()
        vid = extract_youtube_video_id(cleaned)
        if not vid:
            from automation import extract_youtube_search_results
            search_res = extract_youtube_search_results(cleaned, max_results=1)
            if search_res:
                vid = search_res[0]["id"]

        if not vid:
            return _failure("get_youtube_video_details", f"'{cleaned}' video nahi mili.", "video_not_found")

        details = fetch_video_details(vid, api_key=s.youtube_api_key)
        if details:
            views_fmt = f"{details['view_count']:,}" if details.get("view_count") else "N/A"
            likes_fmt = f"{details['like_count']:,}" if details.get("like_count") else "N/A"
            msg = (
                f"Captain, '{details.get('title', '')}' video details:\n"
                f"- Channel: {details.get('channel', 'N/A')}\n"
                f"- Duration: {details.get('duration', 'N/A')}\n"
                f"- Views: {views_fmt} | Likes: {likes_fmt}\n"
                f"- Link: {details.get('url', '')}"
            )
            return AutomationResult(True, "get_youtube_video_details", msg, details)
        return _failure("get_youtube_video_details", "Video details prapt nahi ho sake.", "metadata_error")
    except Exception as exc:
        return _failure("get_youtube_video_details", f"Video details read fail hua: {exc}", "details_error")


def play_mood_music(mood: str = "coding") -> AutomationResult:
    """Play AI-curated top-rated music for Captain's specific mood or activity."""
    m = str(mood).strip().lower()
    mood_map = {
        "coding": "Lofi Hip Hop Chill Beats 24/7 Live Coding Focus Music",
        "program": "Lofi Hip Hop Chill Beats 24/7 Live Coding Focus Music",
        "programming": "Lofi Hip Hop Chill Beats 24/7 Live Coding Focus Music",
        "study": "Deep Focus Study Music Alpha Waves Brain Power",
        "padhai": "Deep Focus Study Music Alpha Waves Brain Power",
        "focus": "Deep Focus Study Music Alpha Waves Brain Power",
        "gym": "High Energy Gym Workout Motivation Beast Mode",
        "workout": "High Energy Gym Workout Motivation Beast Mode",
        "exercise": "High Energy Gym Workout Motivation Beast Mode",
        "chill": "Peaceful Hindi Acoustic Guitar Relaxing Songs",
        "relax": "Peaceful Hindi Acoustic Guitar Relaxing Songs",
        "sukoon": "Peaceful Hindi Acoustic Guitar Relaxing Songs",
        "romantic": "Best Bollywood Romantic Songs Hits",
        "love": "Best Bollywood Romantic Songs Hits",
        "party": "Top Bollywood Party Dance Hits Latest",
        "dance": "Top Bollywood Party Dance Hits Latest",
        "sad": "Heart Touching Sad Hindi Songs Arijit Singh",
        "dard": "Heart Touching Sad Hindi Songs Arijit Singh",
        "90s": "Best of 90s Bollywood Evergreen Hindi Songs",
        "old": "Best of 90s Bollywood Evergreen Hindi Songs",
        "purane": "Best of 90s Bollywood Evergreen Hindi Songs",
        "bhajan": "Morning Peaceful Hindi Bhajans Best Devotional Songs",
        "bhakti": "Morning Peaceful Hindi Bhajans Best Devotional Songs",
    }
    selected_query = "Top Trending Bollywood Songs"
    for k, v in mood_map.items():
        if k in m:
            selected_query = v
            break
    return play_youtube(selected_query)


def get_live_news(topic: str = "top headlines") -> AutomationResult:
    """Fetch real-time live news, breaking news, weather, or current affairs using Tavily API."""
    try:
        from config import load_settings
        from realtimeinfo import RealtimeInfoService
        s = load_settings()
        if not s.tavily_configured:
            return _failure("get_live_news", "Tavily API key configured nahi hai.", "missing_tavily_key")
        service = RealtimeInfoService(s)
        query = f"latest {topic} news today" if "news" not in topic.lower() else topic
        resp = service.answer(query)
        if resp.display_text:
            return AutomationResult(
                True,
                "get_live_news",
                resp.display_text,
                {"topic": topic, "sources": [getattr(src, "url", str(src)) for src in resp.sources], "speech": resp.speech_text},
            )
        return _failure("get_live_news", "Tavily se live news prapt nahi ho saki.", "no_news")
    except Exception as exc:
        return _failure("get_live_news", f"Live news fetch fail hua: {exc}", "tavily_error")


def search_youtube_live(topic: str = "news") -> AutomationResult:
    """Find and play verified 24/7 Live Streams on YouTube (News, Cricket, Lofi, Space)."""
    t = str(topic).strip()
    try:
        from config import load_settings
        s = load_settings()
        yt_api_key = s.youtube_api_key or os.environ.get("YOUTUBE_API_KEY")
        if yt_api_key:
            import json
            api_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&eventType=live&type=video&maxResults=3&q={quote_plus(t)}&key={yt_api_key}"
            req = urllib.request.Request(api_url, headers={"User-Agent": "DarkShadow-AI/1.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    vid = items[0].get("id", {}).get("videoId")
                    title = items[0].get("snippet", {}).get("title", t)
                    if vid:
                        url = f"https://www.youtube.com/watch?v={vid}&autoplay=1"
                        _open_browser_url("search_youtube_live", url, f"Live stream open kar diya: {title}")
                        return AutomationResult(
                            True,
                            "search_youtube_live",
                            f"Captain, '{title}' live stream play kar di hai!",
                            {"video_id": vid, "title": title, "url": url},
                        )
    except Exception as exc:
        LOGGER.debug("Live stream search error: %s", exc)
    return play_youtube(f"{t} live stream")


def parse_timestamp_to_seconds(timestamp_str: str) -> int | None:
    """Parse time string in MM:SS, HH:MM:SS, seconds, or natural language (e.g. '2 min 30s', '2:00', 'dedh minute')."""
    raw = str(timestamp_str).strip().lower()
    if not raw:
        return None

    # Handle special Hinglish fractional phrases
    if "dedh" in raw or "dehd" in raw:
        return 90
    if "dhai" in raw or "dhaai" in raw:
        return 150
    if "aadha" in raw or "adha" in raw:
        return 30

    # Format MM:SS or HH:MM:SS (e.g. 02:00, 1:15:30, 0:45)
    colon_parts = raw.split(":")
    if 2 <= len(colon_parts) <= 3:
        try:
            nums = [int(re.sub(r"[^\d]", "", p).strip()) for p in colon_parts if re.sub(r"[^\d]", "", p).strip()]
            if len(nums) == 2:
                return nums[0] * 60 + nums[1]
            elif len(nums) == 3:
                return nums[0] * 3600 + nums[1] * 60 + nums[2]
        except (ValueError, TypeError):
            pass

    # Natural text e.g. "2 hour 15 min 30 sec", "5m20s", "2 minute", "45s", "1 ghanta"
    hours = 0.0
    minutes = 0.0
    seconds = 0.0
    found = False

    h_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|ghante?|h)(?![a-zA-Z])", raw)
    if h_match:
        hours = float(h_match.group(1))
        found = True

    m_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|minut|m)(?![a-zA-Z])", raw)
    if m_match:
        minutes = float(m_match.group(1))
        found = True

    s_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)(?![a-zA-Z])", raw)
    if s_match:
        seconds = float(s_match.group(1))
        found = True

    if found:
        return int(hours * 3600 + minutes * 60 + seconds)

    # Clean raw digits
    digits_only = re.sub(r"[^\d]", "", raw)
    if digits_only and raw.strip() == digits_only:
        return int(digits_only)

    return None


def jump_to_video_time(timestamp: str) -> AutomationResult:
    """Jump active video or media player to a specific timestamp (e.g. '2:00', '10:30', '5m20s', 'start', 'middle')."""
    ts = str(timestamp).strip().lower()
    try:
        import pyautogui
        import pyperclip
        _focus_browser_window()
        time.sleep(0.06)

        # 1. Start / 0%
        if ts in {"start", "shuru", "begin", "0", "0%", "pehla"}:
            pyautogui.press("0")
            return AutomationResult(True, "jump_to_video_time", "Video shuru se play kar di.", {"target": "0%"})

        # 2. Middle / 50%
        if ts in {"middle", "beech me", "half", "50%"}:
            pyautogui.press("5")
            return AutomationResult(True, "jump_to_video_time", "Video ke 50% par jump kar diya.", {"target": "50%"})

        # 3. Direct percentages e.g. "10%", "20%", "30%", ..., "90%"
        pct_match = re.match(r"^([1-9])0%$", ts)
        if pct_match:
            digit = pct_match.group(1)
            pyautogui.press(digit)
            return AutomationResult(True, "jump_to_video_time", f"Video ke {digit}0% par jump kar diya.", {"target": f"{digit}0%"})

        # 4. Relative forward / backward (e.g. "10s forward", "30 seconds aage", "10s backward", "peeche")
        if any(w in ts for w in ["forward", "aage", "+"]):
            sec_val = parse_timestamp_to_seconds(ts) or 10
            presses = max(1, round(sec_val / 10))
            for _ in range(presses):
                pyautogui.press("l")
                time.sleep(0.02)
            return AutomationResult(True, "jump_to_video_time", f"{presses * 10} seconds aage jump kiya.", {"target": f"+{presses * 10}s"})

        if any(w in ts for w in ["backward", "peeche", "piche", "-"]):
            sec_val = parse_timestamp_to_seconds(ts) or 10
            presses = max(1, round(sec_val / 10))
            for _ in range(presses):
                pyautogui.press("j")
                time.sleep(0.02)
            return AutomationResult(True, "jump_to_video_time", f"{presses * 10} seconds peeche jump kiya.", {"target": f"-{presses * 10}s"})

        # 5. Exact Timestamp Seek (e.g. "2:00", "2 minute", "1:30", "120s")
        total_seconds = parse_timestamp_to_seconds(ts)
        if total_seconds is not None:
            orig_clip = ""
            try:
                orig_clip = pyperclip.paste()
            except Exception:
                pass

            # Focus browser address bar and copy current URL
            pyautogui.hotkey("alt", "d")
            time.sleep(0.08)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.08)

            copied_url = ""
            try:
                copied_url = pyperclip.paste()
            except Exception:
                pass

            seek_done = False
            if copied_url and ("youtube.com" in copied_url or "youtu.be" in copied_url):
                parsed = urlsplit(copied_url)
                qs = parsed.query
                params = urllib.parse.parse_qs(qs, keep_blank_values=True)
                params["t"] = [f"{total_seconds}s"]
                new_query = urllib.parse.urlencode(params, doseq=True)
                new_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

                pyperclip.copy(new_url)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.04)
                pyautogui.press("enter")
                time.sleep(0.15)
                pyautogui.press("esc")
                seek_done = True
            else:
                pyautogui.press("esc")

            # Fallback if address bar copy was empty or missed
            if not seek_done:
                last_media = getattr(GLOBAL_AUTOMATION_CONTEXT, "last_media_query", "")
                if last_media:
                    vid_id = extract_youtube_video_id(last_media)
                    if vid_id:
                        direct_url = f"https://www.youtube.com/watch?v={vid_id}&t={total_seconds}s"
                        _open_browser_url("jump_to_video_time", direct_url, f"Video ko {total_seconds}s par seek kiya.")
                        seek_done = True

            if orig_clip:
                try:
                    pyperclip.copy(orig_clip)
                except Exception:
                    pass

            mins, secs = divmod(total_seconds, 60)
            time_display = f"{mins}:{secs:02d}" if mins < 60 else f"{mins // 60}:{mins % 60:02d}:{secs:02d}"
            return AutomationResult(
                True,
                "jump_to_video_time",
                f"Video timestamp '{time_display}' ({total_seconds} seconds) par navigate kar diya.",
                {"timestamp": ts, "seconds": total_seconds, "formatted": time_display},
            )

        return AutomationResult(True, "jump_to_video_time", f"Video timestamp '{ts}' par navigate kar diya.", {"timestamp": ts})
    except Exception as exc:
        return _failure("jump_to_video_time", f"Timestamp jump nahi ho saka: {exc}", "seek_error")


def add_to_favorites(title: str, artist: str = "") -> AutomationResult:
    """Save Captain's favorite song or artist to persistent database."""
    try:
        from config import load_settings
        from memory import SQLiteMemoryStore
        s = load_settings()
        mem = SQLiteMemoryStore(s.memory_database_path)
        res = mem.add_favorite(title=title, artist_or_author=artist)
        return AutomationResult(res.success, "add_to_favorites", res.message, res.data)
    except Exception as exc:
        return _failure("add_to_favorites", f"Favorite save nahi ho saka: {exc}", "db_error")


def play_favorites() -> AutomationResult:
    """Play Captain's saved favorite songs from persistent database."""
    try:
        from config import load_settings
        from memory import SQLiteMemoryStore
        s = load_settings()
        mem = SQLiteMemoryStore(s.memory_database_path)
        favs = mem.get_favorites("song")
        if not favs:
            return play_youtube("Top Best Bollywood Hit Songs")
        import random
        chosen = random.choice(favs)
        song_title = chosen["title"]
        artist = chosen.get("artist_or_author", "")
        q = f"{song_title} {artist}".strip()
        res = play_youtube(q)
        return AutomationResult(
            res.success,
            "play_favorites",
            f"Captain, aapke favorites me se '{song_title}' chala raha hoon.",
            {"favorite": chosen, "query": q},
        )
    except Exception as exc:
        return _failure("play_favorites", f"Favorites play nahi ho sake: {exc}", "db_error")


def save_captain_fact(key: str, value: str, category: str = "general") -> AutomationResult:
    """Save personal fact about Captain to persistent profile."""
    try:
        from config import load_settings
        from memory import SQLiteMemoryStore
        s = load_settings()
        mem = SQLiteMemoryStore(s.memory_database_path)
        res = mem.save_profile_fact(key=key, value=value, category=category)
        return AutomationResult(res.success, "save_captain_fact", res.message, res.data)
    except Exception as exc:
        return _failure("save_captain_fact", f"Fact save nahi ho saka: {exc}", "db_error")


def save_captain_lesson(topic: str, lesson: str) -> AutomationResult:
    """Save an operational lesson or user preference correction."""
    try:
        from config import load_settings
        from memory import SQLiteMemoryStore
        s = load_settings()
        mem = SQLiteMemoryStore(s.memory_database_path)
        res = mem.save_lesson(topic=topic, lesson=lesson)

        # Log into error.py journal as requested by Captain!
        try:
            from error_logger import ErrorLogger
            ErrorLogger.log_lesson_record(topic=topic, lesson=lesson)
        except Exception as err_exc:
            LOGGER.debug("ErrorLogger log_lesson_record notice: %s", err_exc)

        return AutomationResult(res.success, "save_captain_lesson", res.message, res.data)
    except Exception as exc:
        return _failure("save_captain_lesson", f"Lesson save nahi ho saka: {exc}", "db_error")


def recall_captain_memory(query: str = "") -> AutomationResult:
    """Recall Captain's personal facts, preferences, past chat sessions, and notes."""
    try:
        from config import load_settings
        from memory import SQLiteMemoryStore
        s = load_settings()
        mem = SQLiteMemoryStore(s.memory_database_path)
        recalled_text = mem.recall_comprehensive_memory(query=str(query).strip())
        return AutomationResult(
            success=True,
            action="recall_captain_memory",
            message=recalled_text,
            data={"query": query, "memory": recalled_text},
        )
    except Exception as exc:
        return _failure("recall_captain_memory", f"Memory recall failed: {exc}", "db_error")


def execute_terminal_command(
    command: str,
    working_dir: str = "",
    timeout: int = 25,
) -> AutomationResult:
    """Execute a Windows PowerShell command with 4-Layer Security Shield and output capture."""
    clean_cmd = str(command).strip()
    if not clean_cmd:
        return _failure("execute_terminal_command", "Command cannot be empty.", "empty_command")

    # 1. Security Check: 4-layer Zero-Tolerance Shield
    from safety import is_dangerous_terminal_command, is_read_only_terminal_command
    is_danger, reason = is_dangerous_terminal_command(clean_cmd)
    if is_danger:
        return _failure(
            "execute_terminal_command",
            f"Captain, command security shield ne block kar diya: {reason}",
            "security_blocked",
        )

    # 2. Determine working directory
    cwd = Path(working_dir).resolve() if working_dir else PROJECT_ROOT
    if not cwd.exists():
        cwd = PROJECT_ROOT

    # 3. Execution via safe PowerShell process
    exec_timeout = max(3, min(int(timeout or 25), 60))
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                clean_cmd,
            ],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=exec_timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        stdout_clean = (proc.stdout or "").strip()
        stderr_clean = (proc.stderr or "").strip()

        # Cap output size to 3000 chars to avoid memory/context flooding
        max_len = 3000
        if len(stdout_clean) > max_len:
            stdout_clean = stdout_clean[:max_len] + f"\n... [Output truncated ({len(proc.stdout)} chars)]"
        if len(stderr_clean) > max_len:
            stderr_clean = stderr_clean[:max_len] + f"\n... [Error truncated ({len(proc.stderr)} chars)]"

        if proc.returncode == 0:
            msg = stdout_clean or "Command executed successfully with 0 exit code."
            return AutomationResult(
                True,
                "execute_terminal_command",
                msg,
                {
                    "command": clean_cmd,
                    "exit_code": 0,
                    "stdout": stdout_clean,
                    "is_read_only": is_read_only_terminal_command(clean_cmd),
                },
            )
        else:
            err_msg = stderr_clean or stdout_clean or f"Command failed with exit code {proc.returncode}."
            return AutomationResult(
                False,
                "execute_terminal_command",
                f"Command failed (exit code {proc.returncode}): {err_msg}",
                {
                    "command": clean_cmd,
                    "exit_code": proc.returncode,
                    "stderr": stderr_clean,
                    "stdout": stdout_clean,
                },
            )
    except subprocess.TimeoutExpired:
        return _failure(
            "execute_terminal_command",
            f"Command timed out after {exec_timeout} seconds. Execution aborted for safety.",
            "timeout",
        )
    except Exception as exc:
        LOGGER.warning("execute_terminal_command error: %s", exc)
        return _failure(
            "execute_terminal_command",
            f"Terminal command execution error: {exc}",
            "exec_error",
        )


def _capture_desktop_screenshot() -> Any:
    """Capture Windows desktop screenshot with GDI and PIL fallbacks."""
    if os.name == "nt":
        try:
            import ctypes
            import ctypes.wintypes
            from PIL import Image

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
            gdi32.SelectObject(hdc_mem, hbm)
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, 0x00CC0020)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.wintypes.DWORD),
                    ("biWidth", ctypes.wintypes.LONG),
                    ("biHeight", ctypes.wintypes.LONG),
                    ("biPlanes", ctypes.wintypes.WORD),
                    ("biBitCount", ctypes.wintypes.WORD),
                    ("biCompression", ctypes.wintypes.DWORD),
                    ("biSizeImage", ctypes.wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.wintypes.LONG),
                    ("biYPelsPerMeter", ctypes.wintypes.LONG),
                    ("biClrUsed", ctypes.wintypes.DWORD),
                    ("biClrImportant", ctypes.wintypes.DWORD),
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
            return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        except Exception as gdi_err:
            LOGGER.debug("GDI screen capture fallback: %s", gdi_err)

    try:
        from PIL import ImageGrab
        return ImageGrab.grab(all_screens=True).convert("RGB")
    except Exception:
        try:
            import pyautogui
            return pyautogui.screenshot().convert("RGB")
        except Exception as sc_exc:
            LOGGER.error("Screenshot capture failed: %s", sc_exc)
            raise RuntimeError(f"Desktop screenshot capture failed: {sc_exc}") from sc_exc


def is_ollama_available(base_url: str = "http://127.0.0.1:11434", timeout: float = 1.5) -> bool:
    """Check if local Ollama server is reachable."""
    try:
        import urllib.request
        clean_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
        req = urllib.request.Request(f"{clean_url}/api/tags", headers={"User-Agent": "DarkShadow/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def analyze_screen_with_ollama(
    prompt: str = "Describe what is currently visible on the screen, active window, and any key information or errors.",
    model: str = "moondream",
    base_url: str = "http://127.0.0.1:11434",
    timeout: float = 40.0,
    img: Any | None = None,
) -> AutomationResult:
    """Analyze desktop screen locally using Ollama vision model (e.g. moondream) with zero API cost."""
    try:
        import base64
        import io
        import json
        import urllib.request
        try:
            from PIL import Image
        except Exception:
            import PIL.Image as Image

        if img is None:
            img = _capture_desktop_screenshot()

        # Downscale to 768px width for fast local inference
        orig_w, orig_h = img.size
        target_w = 768
        if orig_w > target_w:
            target_h = int(orig_h * (target_w / orig_w))
            img = img.resize((target_w, target_h), Image.Resampling.BILINEAR)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=75)
        b64_img = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Clean prompt for Moondream/Ollama VLM
        clean_p = (prompt or "").strip()
        clean_p = re.sub(
            r"^(?:please\s+|zara\s+)?(?:(?:ollama|local|offline)\s+(?:vision\s+(?:se\s+)?)?)?(?:screen\s+(?:par\s+)?(?:dekh(?:o|iye)?|analyze\s*karo|check\s*karo|batao)\s*(?:ki\s+)?|kya\s+hai\s*)",
            "",
            clean_p,
            flags=re.I,
        ).strip()
        if not clean_p or len(clean_p) < 4 or any(clean_p.casefold() == w for w in {"screen", "screen dekho", "dekho", "check karo", "kya hai", "analyze"}):
            v_prompt = "Describe what is currently visible on this computer screen, active application, and open windows."
        else:
            v_prompt = clean_p if clean_p.endswith(("?", ".")) else f"{clean_p} on this screen."

        clean_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
        payload = {
            "model": model or "moondream",
            "prompt": v_prompt,
            "stream": False,
            "images": [b64_img],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{clean_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "DarkShadow/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            analysis = (res.get("response") or "").strip()

        if not analysis:
            return _failure("analyze_screen_ollama", "Local Ollama model se koi visual response nahi mila.", "empty_response")

        return AutomationResult(
            True,
            "analyze_screen",
            f"Captain, local Ollama ({model}) vision se screen analyze kar liya hai:\n\n{analysis}",
            {"prompt": prompt, "analysis": analysis, "provider": "ollama", "model": model},
        )
    except Exception as exc:
        LOGGER.warning("Ollama screen analysis failed: %s", exc)
        return _failure("analyze_screen_ollama", f"Local Ollama vision analysis fail hua: {exc}", "ollama_error")


def analyze_screen_content(
    prompt: str = "Describe what is currently visible on the screen, active window, and any key information or errors.",
    api_key: str | None = None,
    provider: str | None = None,
) -> AutomationResult:
    """Capture active desktop screen and visually analyze it using Gemini or local Ollama Moondream."""
    try:
        import io
        import re
        from config import load_settings
        try:
            from PIL import Image
        except Exception:
            import PIL.Image as Image
        from google import genai
        from google.genai import types

        s = load_settings()
        selected_provider = (provider or getattr(s, "vision_provider", "auto") or "auto").lower()

        img = _capture_desktop_screenshot()

        # Check if local Ollama requested explicitly or configured as sole provider
        is_explicit_local = bool(
            re.search(r"\b(?:local|offline|ollama|moondream)\b", prompt, re.I)
            or selected_provider == "ollama"
        )
        if is_explicit_local and getattr(s, "ollama_enabled", True):
            return analyze_screen_with_ollama(
                prompt=prompt,
                model=getattr(s, "ollama_vision_model", "moondream"),
                base_url=getattr(s, "ollama_base_url", "http://127.0.0.1:11434"),
                timeout=getattr(s, "ollama_timeout_seconds", 40.0),
                img=img,
            )

        # Fast downscaling to 960px width for 10x smaller payload and faster tokenization
        orig_w, orig_h = img.size
        target_w = 960
        if orig_w > target_w:
            target_h = int(orig_h * (target_w / orig_w))
            img = img.resize((target_w, target_h), Image.Resampling.BILINEAR)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=55)
        img_bytes = buffer.getvalue()

        if not api_key:
            api_key = s.api_key
            raw_candidates = [
                s.casual_model,
                "gemini-3.5-flash-lite",
                "gemini-flash-lite-latest",
                "gemini-3.1-flash-lite",
                "gemini-3-flash-preview",
                "gemini-3.6-flash",
                s.model,
            ]
        else:
            raw_candidates = [
                "gemini-3.5-flash-lite",
                "gemini-flash-lite-latest",
                "gemini-3.1-flash-lite",
                "gemini-3-flash-preview",
                "gemini-3.6-flash",
                "gemini-3.8-flash",
                "gemini-3.7-flash",
            ]

        # Deduplicate while preserving order
        model_candidates = []
        for cand in raw_candidates:
            if cand and cand not in model_candidates:
                model_candidates.append(cand)

        if not api_key:
            # Fallback to local Ollama Moondream if available
            if getattr(s, "ollama_enabled", True) and is_ollama_available(getattr(s, "ollama_base_url", "http://127.0.0.1:11434")):
                LOGGER.info("Gemini API key missing; seamlessly falling back to local Ollama (%s)", getattr(s, "ollama_vision_model", "moondream"))
                return analyze_screen_with_ollama(
                    prompt=prompt,
                    model=getattr(s, "ollama_vision_model", "moondream"),
                    base_url=getattr(s, "ollama_base_url", "http://127.0.0.1:11434"),
                    timeout=getattr(s, "ollama_timeout_seconds", 40.0),
                    img=img,
                )
            return _failure("analyze_screen", "Gemini API key configure nahi hai aur local Ollama available nahi hai.", "no_api_key")

        client = _get_cached_genai_client(api_key)
        last_err = None
        analysis = ""

        # Jugaad 3: Inject accessibility tree context so the vision model has
        # structured text about the active window, not just the pixel screenshot.
        # This helps when the DarkShadow console is in front of the browser.
        uia_context = ""
        try:
            from desktop_engine import get_desktop_engine
            eng = get_desktop_engine()
            uia_context = eng.get_active_window_context(max_controls=15)
        except Exception:
            pass

        for m in model_candidates:
            if not m:
                continue
            try:
                cfg_kwargs: dict[str, Any] = {
                    "max_output_tokens": 120,
                    "temperature": 0.2,
                }
                if hasattr(types, "ThinkingConfig"):
                    try:
                        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                    except Exception:
                        pass
                gen_config = types.GenerateContentConfig(**cfg_kwargs)

                response = client.models.generate_content(
                    model=m,
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                        types.Part.from_text(
                            text=(
                                f"You are DarkShadow AI co-pilot visually analyzing Captain's active screen.\n"
                                + (f"Desktop Context:\n{uia_context}\n\n" if uia_context else "")
                                + f"Prompt: {prompt}\n"
                                f"IMPORTANT: If you see a command-line terminal or console log, look BEHIND it at the actual application window (browser, media player, etc.) visible in the screenshot. Focus on the app content, not the console text.\n"
                                f"Provide a concise, direct, and actionable explanation in Hindi/Hinglish (2-3 short sentences max)."
                            )
                        ),
                    ],
                    config=gen_config,
                )
                analysis = (response.text or "").strip()
                if analysis:
                    break
            except Exception as candidate_err:
                last_err = candidate_err
                LOGGER.debug("Vision model %s failed: %s", m, candidate_err)

        if not analysis and last_err is not None:
            raise last_err

        # If prompt explicitly asks to click/play/press an element after analyzing
        action_match = re.search(r"\b(?:click|play|daba|press|tap|hit|select|chalao)\b", prompt, re.I)
        if action_match:
            try:
                c_res = click_screen_element(target=prompt)
                if c_res.success:
                    lbl = c_res.data.get("label") or "element"
                    return AutomationResult(
                        True,
                        "analyze_screen",
                        f"Captain, screen analyze karke {lbl} par click kar diya hai!\n\n{analysis}",
                        {"prompt": prompt, "analysis": analysis, "clicked": True, "click_result": c_res.data},
                    )
            except Exception as auto_click_err:
                LOGGER.debug("Analyze screen auto-click notice: %s", auto_click_err)

        return AutomationResult(
            True,
            "analyze_screen",
            f"Captain, screen analyze kar liya hai:\n\n{analysis}",
            {"prompt": prompt, "analysis": analysis},
        )
    except Exception as exc:
        LOGGER.warning("Screen analysis failed: %s", exc)
        # Seamless fallback to local Ollama Moondream if cloud vision failed
        try:
            from config import load_settings
            s = load_settings()
            if getattr(s, "ollama_enabled", True) and is_ollama_available(getattr(s, "ollama_base_url", "http://127.0.0.1:11434")):
                LOGGER.info("Cloud vision failed (%s); seamlessly falling back to local Ollama Moondream", exc)
                return analyze_screen_with_ollama(
                    prompt=prompt,
                    model=getattr(s, "ollama_vision_model", "moondream"),
                    base_url=getattr(s, "ollama_base_url", "http://127.0.0.1:11434"),
                    timeout=getattr(s, "ollama_timeout_seconds", 40.0),
                )
        except Exception as fb_exc:
            LOGGER.debug("Ollama fallback attempt notice: %s", fb_exc)

        err_str = str(exc)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            clean_msg = "Captain, screen analyze karte waqt AI vision quota/rate-limit hit hua hai. Thodi der baad try kijiye."
        else:
            clean_msg = f"Captain, screen analyze nahi ho saki: {exc}"
        return _failure("analyze_screen", clean_msg, "vision_error")


def search_product_prices(
    query: str,
    tavily_api_key: str | None = None,
) -> AutomationResult:
    """Search for online product prices, deals, and specifications across shopping sites."""
    try:
        cleaned = _clean_required(query, "Product query")
    except (TypeError, ValueError) as exc:
        return _failure("search_product_prices", str(exc), "empty_query")

    try:
        if not tavily_api_key:
            from config import load_settings
            s = load_settings()
            tavily_api_key = s.tavily_api_key

        if tavily_api_key:
            from realtimeinfo import fetch_tavily_search_summary
            search_query = f"{cleaned} price in India buy online Amazon Flipkart"
            summary, sources = fetch_tavily_search_summary(search_query, tavily_api_key, max_results=4)
            if summary:
                return AutomationResult(
                    True,
                    "search_product_prices",
                    f"Captain, '{cleaned}' ke latest price details:\n{summary}",
                    {"query": cleaned, "summary": summary, "sources": sources},
                )
    except Exception as exc:
        LOGGER.debug("Tavily price search fallback: %s", exc)

    url = f"https://www.google.com/search?tbm=shop&q={quote_plus(cleaned)}"
    _open_browser_url("search_product_prices", url, f"{cleaned} ke prices search kar diye.")
    return AutomationResult(
        True,
        "search_product_prices",
        f"Captain, '{cleaned}' ke prices Google Shopping par open kar diye hain.",
        {"query": cleaned, "url": url},
    )


def ecommerce_multi_cart(
    product: str,
    max_price: float | None = None,
    platforms: list[str] | tuple[str, ...] | None = None,
) -> AutomationResult:
    """Perform multi-level autonomous e-commerce product search, price filter, and carting across platforms."""
    try:
        cleaned_prod = _clean_required(product, "Product query")
    except (TypeError, ValueError) as exc:
        return _failure("ecommerce_multi_cart", str(exc), "empty_product")

    if is_payment_or_checkout_intent(cleaned_prod):
        return AutomationResult(
            False,
            "payment_blocked",
            ensure_captain_address(PAYMENT_BLOCKED_MESSAGE),
            {"product": cleaned_prod},
            error="payment_prohibited",
        )

    # Normalize platforms
    target_platforms = ["amazon", "flipkart"]
    if platforms:
        norm_plats = [str(p).strip().lower() for p in platforms if str(p).strip()]
        if norm_plats:
            target_platforms = norm_plats

    price_val: float | None = None
    if max_price is not None:
        try:
            price_val = float(max_price)
        except (ValueError, TypeError):
            price_val = None

    from browser_engine import get_browser_engine
    engine = get_browser_engine()

    platform_results: list[dict[str, Any]] = []
    messages: list[str] = []

    for plat in target_platforms:
        if "amazon" in plat:
            res = engine.search_and_cart_amazon(cleaned_prod, price_val)
            platform_results.append(res)
            p_name = res.get("product") or cleaned_prod
            p_price = res.get("price") or ""
            if res.get("cart_success"):
                messages.append(f"Amazon par '{p_name}' ({p_price}) cart me add kar diya hai.")
            else:
                messages.append(f"Amazon par '{p_name}' ({p_price}) search & open kar diya hai.")
        elif "flipkart" in plat:
            res = engine.search_and_cart_flipkart(cleaned_prod, price_val)
            platform_results.append(res)
            p_name = res.get("product") or cleaned_prod
            p_price = res.get("price") or ""
            if res.get("cart_success"):
                messages.append(f"Flipkart par '{p_name}' ({p_price}) cart me add kar diya hai.")
            else:
                messages.append(f"Flipkart par '{p_name}' ({p_price}) search & open kar diya hai.")

    combined_msg = "Captain, " + " Aur ".join(messages)
    return AutomationResult(
        True,
        "ecommerce_multi_cart",
        combined_msg,
        {
            "product": cleaned_prod,
            "max_price": price_val,
            "platforms": target_platforms,
            "results": platform_results,
        },
    )


def vision_browser_goal(goal: str, url: str | None = None) -> AutomationResult:
    """Execute Level 3 Vision-Grounded browser action using Set-of-Marks and Gemini 3.8 Flash."""
    try:
        cleaned_goal = _clean_required(goal, "Browser vision goal")
    except (TypeError, ValueError) as exc:
        return _failure("vision_browser_goal", str(exc), "empty_goal")

    if is_payment_or_checkout_intent(cleaned_goal):
        return AutomationResult(
            False,
            "payment_blocked",
            ensure_captain_address(PAYMENT_BLOCKED_MESSAGE),
            {"goal": cleaned_goal},
            error="payment_prohibited",
        )

    try:
        from browser_engine import get_browser_engine
        engine = get_browser_engine()

        if url:
            nav_res = engine.navigate(url.strip())
            if not nav_res.get("success"):
                LOGGER.debug("Vision goal navigation notice: %s", nav_res)

        res = engine.vision_execute_goal(cleaned_goal)
        if res.get("success"):
            default_msg = f"Browser goal '{cleaned_goal}' execute kar diya."
            msg = res.get("message") or default_msg
            return AutomationResult(
                True,
                "vision_browser_goal",
                f"Captain, {msg}",
                {"goal": cleaned_goal, "url": url, "details": res},
            )

        # Level 3 Desktop Screen Fallback:
        # If Playwright browser does not have the page (e.g. open in Chrome/Edge on desktop)
        # or has no interactive elements, visually locate and click the element on the active screen!
        LOGGER.info("Browser vision goal fallback to desktop screen element click for: %s", cleaned_goal)
        try:
            screen_res = click_screen_element(target=cleaned_goal)
            if screen_res.success:
                return AutomationResult(
                    True,
                    "vision_browser_goal",
                    f"Captain, screen par '{cleaned_goal}' locate karke click kar diya hai!",
                    {"goal": cleaned_goal, "desktop_clicked": True, "details": screen_res.data},
                )
        except Exception as s_exc:
            LOGGER.debug("Desktop click fallback error: %s", s_exc)

        return _failure(
            "vision_browser_goal",
            f"Vision browser action fail hua: {res.get('error') or res.get('message')}",
            "vision_execution_failed",
            goal=cleaned_goal,
        )
    except Exception as exc:
        LOGGER.warning("Vision browser goal exception: %s", exc)
        try:
            screen_res = click_screen_element(target=cleaned_goal)
            if screen_res.success:
                return AutomationResult(
                    True,
                    "vision_browser_goal",
                    f"Captain, screen par '{cleaned_goal}' locate karke click kar diya hai!",
                    {"goal": cleaned_goal, "desktop_clicked": True, "details": screen_res.data},
                )
        except Exception:
            pass
        return _failure("vision_browser_goal", f"Browser vision agent fail hua: {exc}", "vision_error")


def scroll_screen(direction: str = "down", amount: int = 5) -> AutomationResult:
    """Scroll active window or webpage up or down."""
    d = str(direction).strip().lower()
    is_down = "down" in d or "niche" in d or "neeche" in d or "-" in d or "bottom" in d
    clicks = -abs(int(amount)) * 120 if is_down else abs(int(amount)) * 120
    action_label = "neeche (down)" if is_down else "upar (up)"
    try:
        import pyautogui
        pyautogui.scroll(clicks)
        return AutomationResult(
            True,
            "scroll_screen",
            f"Screen ko {action_label} scroll kar diya.",
            {"direction": "down" if is_down else "up", "amount": amount},
        )
    except Exception:
        try:
            import pyautogui
            pyautogui.press("pagedown" if is_down else "pageup")
            return AutomationResult(True, "scroll_screen", f"Screen ko {action_label} scroll kar diya.", {"direction": "down" if is_down else "up"})
        except Exception as exc:
            return _failure("scroll_screen", f"Scroll fail hua: {exc}", "scroll_error")


def _focus_browser_window() -> bool:
    """Bring running browser window (Chrome, Edge, Firefox, Brave) to the foreground without altering maximized state."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        import pygetwindow as gw

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg_hwnd = user32.GetForegroundWindow()

        for title_kw in ["youtube", "google chrome", "chrome", "microsoft edge", "edge", "firefox", "brave"]:
            windows = [w for w in gw.getAllWindows() if title_kw in w.title.lower() and w.visible]
            if windows:
                win = windows[0]
                hwnd = getattr(win, "_hWnd", None)
                if hwnd:
                    if fg_hwnd == hwnd:
                        return True

                    cur_thread = kernel32.GetCurrentThreadId()
                    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
                    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

                    if cur_thread != target_thread and fg_thread != target_thread:
                        try:
                            user32.AttachThreadInput(cur_thread, fg_thread, True)
                            user32.AttachThreadInput(cur_thread, target_thread, True)
                        except Exception:
                            pass

                    # Only restore if actually minimized
                    if user32.IsIconic(hwnd):
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    else:
                        user32.ShowWindow(hwnd, 5)  # SW_SHOW

                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                    user32.SetActiveWindow(hwnd)

                    if cur_thread != target_thread and fg_thread != target_thread:
                        try:
                            user32.AttachThreadInput(cur_thread, fg_thread, False)
                            user32.AttachThreadInput(cur_thread, target_thread, False)
                        except Exception:
                            pass

                    time.sleep(0.08)
                    return True
    except Exception as exc:
        LOGGER.debug("Focus browser error: %s", exc)
    return False


_CACHED_GENAI_CLIENT: Any = None


def _get_cached_genai_client(api_key: str) -> Any:
    """Reuse persistent warm GenAI client to eliminate per-call connection setup latency."""
    global _CACHED_GENAI_CLIENT
    if _CACHED_GENAI_CLIENT is None:
        from google import genai
        from google.genai import types

        _CACHED_GENAI_CLIENT = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=12000,
                retry_options=types.HttpRetryOptions(attempts=0),
            ),
        )
    return _CACHED_GENAI_CLIENT


def click_screen_element(
    target: str,
    x: int | None = None,
    y: int | None = None,
) -> AutomationResult:
    """Click a specific button, link, video card, or menu item by name using AI visual grounding."""
    try:
        import pyautogui
        screen_w, screen_h = pyautogui.size()

        click_x, click_y = x, y
        label = target
        target_clean = str(target).strip()

        # If coordinates not provided, use Gemini Vision to locate the element on screen
        if click_x is None or click_y is None:
            try:
                import io
                import json
                import re
                from config import load_settings
                try:
                    from PIL import Image
                except Exception:
                    import PIL.Image as Image
                from google.genai import types

                s = load_settings()
                if s.api_key:
                    img = _capture_desktop_screenshot()
                    orig_w, orig_h = img.size
                    target_w = 1600
                    if orig_w > target_w:
                        target_h = int(orig_h * (target_w / orig_w))
                        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    client = _get_cached_genai_client(s.api_key)

                    # Intelligent prefix/suffix cleaning for action prompts
                    cleaned_search = re.sub(
                        r"^(?:please\s+)?(?:visually\s+)?(?:find\s+(?:the\s+)?|locate\s+(?:the\s+)?|click\s+(?:on\s+)?(?:the\s+)?|press\s+(?:the\s+)?|daba(?:o)?\s+)",
                        "",
                        target_clean,
                        flags=re.I,
                    ).strip()
                    cleaned_search = re.sub(
                        r"(?:\s+and\s+(?:visually\s+)?(?:click|play|press)\s+(?:on\s+)?(?:it|this)?|\s+par\s+(?:click|play)\s*(?:karo)?|\s+ko\s+chalao)$",
                        "",
                        cleaned_search,
                        flags=re.I,
                    ).strip()
                    search_kw = cleaned_search if cleaned_search else target_clean

                    v_prompt = (
                        f"Locate the clickable button, icon, link, video card, or track matching: '{search_kw}' or '{target}' on this screen. "
                        "Identify its center coordinates on a 0-1000 scale (where [0, 0] is top-left and [1000, 1000] is bottom-right). "
                        "Return ONLY a JSON object: {\"point\": [y_coordinate_0_to_1000, x_coordinate_0_to_1000], \"label\": \"matched title\"} "
                        "or {\"box_2d\": [ymin, xmin, ymax, xmax], \"label\": \"name\"}."
                    )
                    v_cfg_kwargs: dict[str, Any] = {
                        "response_mime_type": "application/json",
                        "max_output_tokens": 300,
                        "temperature": 0.1,
                    }
                    if hasattr(types, "ThinkingConfig"):
                        try:
                            v_cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                        except Exception:
                            pass

                    parsed_json = None
                    locator_candidates = [
                        getattr(s, "model", "gemini-3.8-flash"),
                        "gemini-3.8-flash",
                        "gemini-3.6-flash",
                        "gemini-3.7-flash",
                        getattr(s, "casual_model", "gemini-3.5-flash-lite"),
                        "gemini-3.5-flash-lite",
                    ]
                    # Deduplicate while preserving order
                    seen_cands: list[str] = []
                    for c in locator_candidates:
                        if c and c not in seen_cands:
                            seen_cands.append(c)

                    for model_cand in seen_cands:
                        try:
                            v_res = client.models.generate_content(
                                model=model_cand,
                                contents=[
                                    types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                                    v_prompt,
                                ],
                                config=types.GenerateContentConfig(**v_cfg_kwargs),
                            )
                            raw_text = (v_res.text or "").strip() if v_res else ""
                            if raw_text:
                                try:
                                    clean_json_str = raw_text
                                    if "```" in clean_json_str:
                                        clean_json_str = re.sub(r"^```(?:json)?\s*", "", clean_json_str, flags=re.MULTILINE)
                                        clean_json_str = re.sub(r"\s*```$", "", clean_json_str, flags=re.MULTILINE).strip()
                                    pj = json.loads(clean_json_str)
                                except Exception:
                                    m_json = re.search(r"(\{.*\}|\[.*\])", raw_text, re.DOTALL)
                                    if m_json:
                                        try:
                                            pj = json.loads(m_json.group(1))
                                        except Exception:
                                            continue
                                    else:
                                        continue

                                while isinstance(pj, list) and len(pj) == 1 and isinstance(pj[0], (list, dict)):
                                    pj = pj[0]
                                has_coords = False
                                if isinstance(pj, (list, tuple)) and len(pj) >= 2:
                                    has_coords = True
                                elif isinstance(pj, dict):
                                    if "point" in pj and isinstance(pj["point"], (list, tuple)) and len(pj["point"]) >= 2:
                                        has_coords = True
                                    elif "box_2d" in pj and isinstance(pj["box_2d"], (list, tuple)) and len(pj["box_2d"]) >= 4:
                                        has_coords = True
                                    elif "x_percent" in pj and "y_percent" in pj:
                                        has_coords = True
                                if has_coords:
                                    parsed_json = pj
                                    break
                        except Exception as m_err:
                            LOGGER.debug("Vision model %s error in locator: %s", model_cand, m_err)

                    if parsed_json is not None:
                        if isinstance(parsed_json, (list, tuple)) and len(parsed_json) >= 2:
                            py_val, px_val = float(parsed_json[0]), float(parsed_json[1])
                            click_x = int(screen_w * (px_val / 1000.0))
                            click_y = int(screen_h * (py_val / 1000.0))
                            label = target
                        elif isinstance(parsed_json, dict):
                            if "point" in parsed_json and isinstance(parsed_json["point"], (list, tuple)) and len(parsed_json["point"]) >= 2:
                                py_val, px_val = float(parsed_json["point"][0]), float(parsed_json["point"][1])
                                click_x = int(screen_w * (float(px_val) / 1000.0))
                                click_y = int(screen_h * (float(py_val) / 1000.0))
                                label = parsed_json.get("label") or target
                            elif "box_2d" in parsed_json and isinstance(parsed_json["box_2d"], (list, tuple)) and len(parsed_json["box_2d"]) >= 4:
                                ymin, xmin, ymax, xmax = [float(v) for v in parsed_json["box_2d"][:4]]
                                click_x = int(screen_w * ((xmin + xmax) / 2000.0))
                                click_y = int(screen_h * ((ymin + ymax) / 2000.0))
                                label = parsed_json.get("label") or target
                            elif "x_percent" in parsed_json and "y_percent" in parsed_json:
                                xp = parsed_json.get("x_percent")
                                yp = parsed_json.get("y_percent")
                                if xp is not None and yp is not None:
                                    click_x = int(screen_w * float(xp) / 100.0)
                                    click_y = int(screen_h * float(yp) / 100.0)
                                    label = parsed_json.get("label") or target
            except Exception as v_err:
                LOGGER.debug("Vision coordinate locator fallback: %s", v_err)

        # Calibrated fallback coordinates for ordinal search links
        if click_x is None or click_y is None:
            if any(w in target_clean.lower() for w in {"first", "pehli", "1st", "one"}):
                click_x = int(screen_w * 0.30)
                click_y = int(screen_h * 0.40)
                label = "pehli link"
            elif any(w in target_clean.lower() for w in {"second", "doosri", "2nd", "two"}):
                click_x = int(screen_w * 0.30)
                click_y = int(screen_h * 0.54)
                label = "doosri link"
            elif any(w in target_clean.lower() for w in {"third", "teesri", "3rd", "three"}):
                click_x = int(screen_w * 0.30)
                click_y = int(screen_h * 0.68)
                label = "teesri link"
            elif any(w in target_clean.lower() for w in {"center", "middle", "beech"}):
                click_x = screen_w // 2
                click_y = screen_h // 2
                label = "screen center"
            elif any(w in target_clean.lower() for w in {"play", "song", "gaana", "music"}):
                click_x = int(screen_w * 0.40)
                click_y = int(screen_h * 0.38)
                label = "play button"
            else:
                return _failure(
                    "click_screen_element",
                    f"Captain, screen par '{target}' button ya link visible nahi mila. Aap 'scroll down' bol sakte hain ya screen par dikh rahe kisi doosre menu par ja sakte hain.",
                    "not_found",
                )

        # Clamp safely away from corner trigger boundaries (10px margin)
        click_x = max(15, min(screen_w - 15, int(click_x)))
        click_y = max(15, min(screen_h - 15, int(click_y)))

        pyautogui.FAILSAFE = False
        try:
            pyautogui.moveTo(click_x, click_y, duration=0.1)
            pyautogui.click(click_x, click_y)
        finally:
            pyautogui.FAILSAFE = True

        return AutomationResult(
            True,
            "click_screen_element",
            f"Screen par {label} click kar diya.",
            {"target": target, "x": click_x, "y": click_y, "label": label},
        )
    except Exception as exc:
        LOGGER.warning("Click screen element failed: %s", exc)
        return _failure("click_screen_element", f"Click nahi ho saka: {exc}", "click_error")


def hover_screen_element(
    target: str,
    x: int | None = None,
    y: int | None = None,
) -> AutomationResult:
    """Hover mouse over a button, menu, or link on screen without clicking (useful to open dropdown menus)."""
    try:
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        click_x, click_y = x, y
        label = target

        if click_x is None or click_y is None:
            # Use same vision locator logic as click_screen_element by dry run coordinates
            target_clean = str(target).strip().lower()
            import io
            import json
            import re
            from config import load_settings
            try:
                from PIL import Image
            except Exception:
                import PIL.Image as Image
            from google.genai import types

            s = load_settings()
            if s.api_key:
                img = _capture_desktop_screenshot()
                orig_w, orig_h = img.size
                target_w = 1600
                if orig_w > target_w:
                    target_h = int(orig_h * (target_w / orig_w))
                    img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                client = _get_cached_genai_client(s.api_key)

                v_prompt = (
                    f"Locate the menu, button, or link matching: '{target}' on this screen. "
                    "Identify its center coordinates on a 0-1000 scale. "
                    "Return ONLY a JSON object: {\"point\": [y, x], \"label\": \"name\"}."
                )
                v_res = client.models.generate_content(
                    model=getattr(s, "model", "gemini-3.8-flash"),
                    contents=[
                        types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                        v_prompt,
                    ],
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
                )
                raw_text = (v_res.text or "").strip() if v_res else ""
                if raw_text:
                    pj = json.loads(raw_text)
                    if isinstance(pj, dict) and "point" in pj:
                        py_val, px_val = float(pj["point"][0]), float(pj["point"][1])
                        click_x = int(screen_w * (px_val / 1000.0))
                        click_y = int(screen_h * (py_val / 1000.0))

        if click_x is not None and click_y is not None:
            pyautogui.FAILSAFE = False
            try:
                pyautogui.moveTo(int(click_x), int(click_y), duration=0.15)
            finally:
                pyautogui.FAILSAFE = True
            return AutomationResult(
                True,
                "hover_screen_element",
                f"Screen par '{label}' par mouse hover kar diya hai.",
                {"target": target, "x": click_x, "y": click_y, "label": label},
            )
        return _failure("hover_screen_element", f"'{target}' locate nahi hua.", "not_found")
    except Exception as exc:
        return _failure("hover_screen_element", f"Hover fail hua: {exc}", "hover_error")


def start_background_task(task_name: str, task_command: str) -> AutomationResult:
    """Level 4: Launch an autonomous automation task in the background without blocking.

    Multi-step commands (joined by 'and then', 'then', 'aur phir', etc.) are split
    and executed sequentially with brief delays between steps so the browser/app
    has time to react.
    """
    try:
        from background_agent import BackgroundAgentManager
        cleaned_name = _clean_required(task_name, "Task name")
        cleaned_cmd = _clean_required(task_command, "Task command")

        if is_payment_or_checkout_intent(cleaned_cmd):
            return AutomationResult(
                False,
                "payment_blocked",
                ensure_captain_address(PAYMENT_BLOCKED_MESSAGE),
                error="payment_prohibited",
            )

        mgr = BackgroundAgentManager.get_instance()

        def _bg_run():
            import time as _time
            from automation import handle_automation_command, parse_automation_command, execute_automation_command

            # Split complex commands into sequential sub-steps
            step_parts = [
                part.strip(" ,")
                for part in re.split(
                    r"[,;]\s*|\s+(?:and\s+then|then|and|aur\s+phir|aur|phir|uske\s+baad|baad\s+me)\s+",
                    cleaned_cmd,
                    flags=re.I,
                )
                if part.strip(" ,")
            ]

            results = []
            for i, step in enumerate(step_parts):
                step = step.strip()
                if not step:
                    continue
                if is_payment_or_checkout_intent(step):
                    results.append({"step": step, "status": "blocked", "message": PAYMENT_BLOCKED_MESSAGE})
                    continue
                try:
                    res = handle_automation_command(step)
                    if res is not None:
                        results.append({"step": step, "status": "ok" if res.success else "error", "message": res.message})
                    else:
                        results.append({"step": step, "status": "skipped", "message": f"Command not recognized: {step}"})
                except Exception as step_err:
                    results.append({"step": step, "status": "error", "message": str(step_err)})
                # Brief delay between steps so the browser/app can update
                if i < len(step_parts) - 1:
                    _time.sleep(1.5)

            summary_parts = []
            for r in results:
                summary_parts.append(f"Step '{r['step']}': {r['status']} — {r['message']}")
            return {"message": "; ".join(summary_parts) if summary_parts else "No steps executed", "steps": results}

        task_id = mgr.dispatch(cleaned_name, _bg_run)
        return AutomationResult(
            True,
            "start_background_task",
            f"Captain, '{cleaned_name}' background me start kar diya hai (ID: {task_id}). Main complete hone par bata doonga.",
            {"task_id": task_id, "task_name": cleaned_name, "command": cleaned_cmd},
        )
    except Exception as exc:
        LOGGER.warning("start_background_task error: %s", exc)
        return _failure("start_background_task", f"Background task start nahi hua: {exc}", "dispatch_failed")


def check_background_tasks() -> AutomationResult:
    """Level 4: Check status of running background tasks and retrieve notifications."""
    try:
        from background_agent import BackgroundAgentManager
        mgr = BackgroundAgentManager.get_instance()
        notifs = mgr.pop_notifications()
        tasks = mgr.list_tasks(limit=5)
        if notifs:
            msg = "Captain, " + " ".join(notifs)
        elif tasks:
            active_count = sum(1 for t in tasks if t["status"] in {"pending", "running"})
            msg = f"Captain, {active_count} background tasks active hain."
        else:
            msg = "Captain, abhi koi background task active nahi hai."
        return AutomationResult(
            True,
            "check_background_tasks",
            msg,
            {"notifications": notifs, "tasks": tasks},
        )
    except Exception as exc:
        return _failure("check_background_tasks", f"Background tasks check fail: {exc}", "status_failed")


GLOBAL_TOKEN_USAGE: dict[str, Any] = {
    "session_input": 0,
    "session_output": 0,
    "session_total": 0,
    "last_input": 0,
    "last_output": 0,
    "last_total": 0,
    "requests": 0,
    "model": "",
}


def record_token_usage(input_tokens: int, output_tokens: int, total_tokens: int, model: str = "") -> None:
    """Record token counts from a model request/response."""
    GLOBAL_TOKEN_USAGE["session_input"] += max(0, int(input_tokens))
    GLOBAL_TOKEN_USAGE["session_output"] += max(0, int(output_tokens))
    GLOBAL_TOKEN_USAGE["session_total"] += max(0, int(total_tokens))
    GLOBAL_TOKEN_USAGE["last_input"] = max(0, int(input_tokens))
    GLOBAL_TOKEN_USAGE["last_output"] = max(0, int(output_tokens))
    GLOBAL_TOKEN_USAGE["last_total"] = max(0, int(total_tokens))
    GLOBAL_TOKEN_USAGE["requests"] += 1
    if model:
        GLOBAL_TOKEN_USAGE["model"] = str(model)


def get_token_usage() -> AutomationResult:
    """Report total session token usage, prompt/response breakdown, and last call stats."""
    tot = GLOBAL_TOKEN_USAGE["session_total"]
    inp = GLOBAL_TOKEN_USAGE["session_input"]
    out = GLOBAL_TOKEN_USAGE["session_output"]
    reqs = GLOBAL_TOKEN_USAGE["requests"]
    last_tot = GLOBAL_TOKEN_USAGE["last_total"]
    last_mod = GLOBAL_TOKEN_USAGE["model"] or "Gemini"

    if tot == 0 and last_tot > 0:
        tot = last_tot
        inp = GLOBAL_TOKEN_USAGE["last_input"]
        out = GLOBAL_TOKEN_USAGE["last_output"]

    msg = (
        f"Captain, is session me total {tot:,} tokens use huye hain "
        f"(Prompt: {inp:,}, Output: {out:,}, Total Requests: {reqs}). "
        f"Aakhri request me {last_tot:,} tokens ({last_mod}) kharch huye the."
    )
    return AutomationResult(
        True,
        "get_token_usage",
        msg,
        {
            "session_total": tot,
            "session_input": inp,
            "session_output": out,
            "requests": reqs,
            "last_total": last_tot,
            "model": last_mod,
        },
    )



def desktop_control_action(
    action: str, target: str = "", text: str | None = None
) -> AutomationResult:
    """Level 5: Universal Windows GUI control action (click, type, or inspect) on desktop apps."""
    try:
        from desktop_engine import get_desktop_engine
        engine = get_desktop_engine()
        act = str(action).strip().lower()

        if is_payment_or_checkout_intent(target) or (text and is_payment_or_checkout_intent(text)):
            return AutomationResult(
                False,
                "payment_blocked",
                ensure_captain_address(PAYMENT_BLOCKED_MESSAGE),
                error="payment_prohibited",
            )

        if "click" in act:
            res = engine.click_control(target)
            if res.get("success"):
                return AutomationResult(
                    True,
                    "desktop_control_action",
                    f"Captain, desktop par '{target}' click kar diya hai.",
                    res,
                )
            return _failure("desktop_control_action", f"Desktop control '{target}' click nahi hua.", "click_failed")

        elif "type" in act:
            typed_text = text or target
            ctrl_name = target if text else None
            res = engine.type_into_control(typed_text, control_name=ctrl_name)
            if res.get("success"):
                return AutomationResult(
                    True,
                    "desktop_control_action",
                    "Captain, desktop control me text type kar diya hai.",
                    res,
                )
            return _failure("desktop_control_action", "Desktop control me type nahi hua.", "type_failed")

        elif "inspect" in act:
            info = engine.inspect_active_window()
            w_title = info.get("title") or "Active Window"
            c_cnt = info.get("control_count", 0)
            return AutomationResult(
                True,
                "desktop_control_action",
                f"Captain, active window '{w_title}' me {c_cnt} interactive controls paye gaye.",
                info,
            )

        return _failure("desktop_control_action", f"Unknown desktop action '{action}'", "unknown_action")
    except Exception as exc:
        LOGGER.warning("desktop_control_action error: %s", exc)
        return _failure("desktop_control_action", f"Desktop GUI action fail hua: {exc}", "desktop_error")


def inspect_desktop_window() -> AutomationResult:
    """Level 5: Inspect active window and its native desktop controls."""
    return desktop_control_action(action="inspect", target="")


def control_browser_action(action: str = "back") -> AutomationResult:
    """Execute browser navigation shortcuts (back, forward, refresh, new tab, close tab)."""
    act = str(action).strip().lower()
    try:
        import pyautogui
        if "back" in act or "piche" in act:
            pyautogui.hotkey("alt", "left")
            label = "peeche (Back)"
        elif "forward" in act or "aage" in act:
            pyautogui.hotkey("alt", "right")
            label = "aage (Forward)"
        elif "refresh" in act or "reload" in act:
            pyautogui.press("f5")
            label = "Refresh"
        elif "close" in act or "band" in act:
            pyautogui.hotkey("ctrl", "w")
            label = "Tab Close"
        elif "new" in act or "nayi" in act:
            pyautogui.hotkey("ctrl", "t")
            label = "New Tab"
        elif "zoom_in" in act or "bada" in act:
            pyautogui.hotkey("ctrl", "+")
            label = "Zoom In"
        elif "zoom_out" in act or "chhota" in act:
            pyautogui.hotkey("ctrl", "-")
            label = "Zoom Out"
        else:
            pyautogui.hotkey("alt", "left")
            label = act

        return AutomationResult(
            True,
            "control_browser_action",
            f"Browser me {label} kar diya.",
            {"action": act},
        )
    except Exception as exc:
        return _failure("control_browser_action", f"Browser action fail hua: {exc}", "browser_nav_error")


def press_keyboard_key(key: str = "enter") -> AutomationResult:
    """Press a key or key combination on the active window (e.g. enter, tab, ctrl+t, ctrl+n, alt+f4, ctrl+w)."""
    k = str(key).strip().lower()
    key_map = {
        "enter": "enter", "return": "enter",
        "tab": "tab",
        "esc": "esc", "escape": "esc",
        "space": "space",
        "backspace": "backspace",
        "down": "down", "up": "up", "left": "left", "right": "right",
        "pagedown": "pagedown", "pageup": "pageup",
        "fullscreen": "f", "full_screen": "f",
        "mute": "m", "play_pause": "k",
        "ctrl": "ctrl", "control": "ctrl",
        "alt": "alt", "shift": "shift", "win": "win", "windows": "win",
        "new_tab": "ctrl+t", "close_tab": "ctrl+w", "close_window": "alt+f4",
    }
    raw_target = key_map.get(k, k)
    try:
        import pyautogui
        # Handle hotkey combinations with + or -
        if "+" in raw_target or ("-" in raw_target and not raw_target.startswith("-")):
            delimiter = "+" if "+" in raw_target else "-"
            parts = [key_map.get(p.strip(), p.strip()) for p in raw_target.split(delimiter) if p.strip()]
            pyautogui.hotkey(*parts)
            target_str = "+".join(parts)
        else:
            target_key = key_map.get(raw_target, raw_target)
            pyautogui.press(target_key)
            target_str = target_key

        return AutomationResult(
            True,
            "press_keyboard_key",
            f"'{target_str}' key press kar di.",
            {"key": target_str},
        )
    except Exception as exc:
        return _failure("press_keyboard_key", f"Key press nahi ho saki: {exc}", "key_error")


def _application_candidates(app_key: str) -> tuple[Path, ...]:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", r"C:\__DarkShadowMissingLocalAppData")
    )
    candidates = {
        "notepad": (windows / "System32" / "notepad.exe", windows / "notepad.exe"),
        "calculator": (windows / "System32" / "calc.exe",),
        "file_explorer": (windows / "explorer.exe",),
        "edge": (
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ),
        "chrome": (
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        ),
        "vscode": (
            local_app_data / "Programs" / "Microsoft VS Code" / "Code.exe",
            program_files / "Microsoft VS Code" / "Code.exe",
            program_files_x86 / "Microsoft VS Code" / "Code.exe",
        ),
        "paint": (windows / "System32" / "mspaint.exe",),
        "spotify": (
            Path(os.environ.get("APPDATA", local_app_data / "Roaming"))
            / "Spotify"
            / "Spotify.exe",
            local_app_data / "Microsoft" / "WindowsApps" / "Spotify.exe",
        ),
        "terminal": (
            local_app_data / "Microsoft" / "WindowsApps" / "wt.exe",
            program_files / "WindowsApps" / "wt.exe",
        ),
        "cmd": (windows / "System32" / "cmd.exe",),
        "taskmgr": (windows / "System32" / "taskmgr.exe",),
        "control": (windows / "System32" / "control.exe",),
        "vlc": (
            program_files / "VideoLAN" / "VLC" / "vlc.exe",
            program_files_x86 / "VideoLAN" / "VLC" / "vlc.exe",
        ),
        "whatsapp": (
            local_app_data / "WhatsApp" / "WhatsApp.exe",
            local_app_data / "Microsoft" / "WindowsApps" / "WhatsApp.exe",
            program_files / "WindowsApps" / "WhatsApp.exe",
        ),
    }
    return candidates.get(app_key, ())


def _resolve_application_executable(app_key: str) -> Path | None:
    for candidate in _application_candidates(app_key):
        if candidate.is_file():
            return candidate.resolve()
    return None


_INSTALLED_APPS_CACHE: dict[str, Path] = {}
_INSTALLED_APPS_CACHE_TIME: float = 0.0


def _scan_windows_installed_applications() -> dict[str, Path]:
    """Scan Windows Registry App Paths and Start Menu shortcuts to dynamically discover all installed software."""
    global _INSTALLED_APPS_CACHE, _INSTALLED_APPS_CACHE_TIME
    now = time.monotonic()
    if _INSTALLED_APPS_CACHE and (now - _INSTALLED_APPS_CACHE_TIME) < 120.0:
        return _INSTALLED_APPS_CACHE

    apps: dict[str, Path] = {}
    if os.name != "nt":
        return apps

    # 1. Windows Registry: HKLM & HKCU App Paths
    try:
        import winreg
        for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root_key, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as app_paths:
                    count = winreg.QueryInfoKey(app_paths)[0]
                    for idx in range(count):
                        try:
                            subkey_name = winreg.EnumKey(app_paths, idx)
                            with winreg.OpenKey(app_paths, subkey_name) as subkey:
                                raw_path, _ = winreg.QueryValueEx(subkey, "")
                                if raw_path:
                                    clean_path = str(raw_path).strip('"')
                                    p = Path(clean_path)
                                    if p.is_file() and p.suffix.lower() == ".exe":
                                        base_name = p.stem.lower()
                                        sub_base = subkey_name.lower().replace(".exe", "")
                                        apps[sub_base] = p.resolve()
                                        apps[base_name] = p.resolve()
                        except Exception:
                            continue
            except Exception:
                continue
    except Exception:
        pass

    # 2. Start Menu Programs folders (.lnk / .exe shortcuts)
    start_dirs = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", r"C:\Users\Default\AppData\Roaming")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for s_dir in start_dirs:
        if s_dir.is_dir():
            try:
                for entry in s_dir.rglob("*"):
                    if entry.is_file() and entry.suffix.lower() in {".lnk", ".exe"}:
                        clean_name = entry.stem.lower()
                        clean_name = re.sub(r"\s*\((?:x64|64-bit|32-bit)\)", "", clean_name, flags=re.I).strip()
                        if clean_name and clean_name not in apps:
                            apps[clean_name] = entry.resolve()
            except Exception:
                continue

    _INSTALLED_APPS_CACHE = apps
    _INSTALLED_APPS_CACHE_TIME = now
    return apps


def open_application(app_name: str) -> AutomationResult:
    """Open an application from the fixed allowlist or dynamically discovered installed apps on Windows."""

    try:
        cleaned = _clean_required(app_name, "Application name")
    except (TypeError, ValueError) as exc:
        return _failure("open_application", str(exc), "empty_app_name")

    if os.name != "nt":
        return _failure(
            "open_application", "Application launch sirf Windows par supported hai.", "unsupported_os"
        )

    app_key = APPLICATION_ALIASES.get(cleaned.casefold())

    # Special handler: YouTube & websites
    if app_key == "youtube" or any(k in cleaned.casefold() for k in ("youtube", "yt.com", "youtube.com", "yt")):
        return open_website("https://youtube.com")

    # Special handler: WhatsApp
    if app_key == "whatsapp":
        executable = _resolve_application_executable(app_key)
        if executable is not None:
            try:
                subprocess.Popen([str(executable)], shell=False, close_fds=True)
                return AutomationResult(
                    True, "open_application", "WhatsApp open kar diya.", {"app": app_key, "executable": str(executable)}
                )
            except Exception:
                pass
        try:
            os.startfile("whatsapp:")
            return AutomationResult(
                True, "open_application", "WhatsApp open kar diya.", {"app": app_key, "protocol": "whatsapp:"}
            )
        except Exception:
            return _open_browser_url("open_application", "https://web.whatsapp.com", "WhatsApp Web open kar diya.")

    # Special handler: Spotify
    if app_key == "spotify":
        executable = _resolve_application_executable(app_key)
        if executable is not None:
            try:
                subprocess.Popen([str(executable)], shell=False, close_fds=True)
                return AutomationResult(
                    True, "open_application", "Spotify open kar diya.", {"app": app_key, "executable": str(executable)}
                )
            except Exception:
                pass
        try:
            os.startfile("spotify:")
            return AutomationResult(
                True, "open_application", "Spotify open kar diya.", {"app": app_key, "protocol": "spotify:"}
            )
        except Exception:
            pass
        return _open_browser_url("open_application", "https://open.spotify.com", "Spotify Web Player open kar diya.")

    # Special handler: Instagram
    if app_key == "instagram":
        executable = _resolve_application_executable(app_key)
        if executable is not None:
            try:
                subprocess.Popen([str(executable)], shell=False, close_fds=True)
                return AutomationResult(
                    True, "open_application", "Instagram open kar diya.", {"app": app_key, "executable": str(executable)}
                )
            except Exception:
                pass
        try:
            os.startfile("instagram:")
            return AutomationResult(
                True, "open_application", "Instagram open kar diya.", {"app": app_key, "protocol": "instagram:"}
            )
        except Exception:
            pass
        return _open_browser_url("open_application", "https://www.instagram.com", "Instagram open kar diya.")

    # 1. Check fixed allowlist executable candidates
    if app_key is not None:
        executable = _resolve_application_executable(app_key)
        if executable is not None:
            try:
                subprocess.Popen([str(executable)], shell=False, close_fds=True)
                return AutomationResult(
                    True,
                    "open_application",
                    f"{cleaned} open kar diya.",
                    {"app": app_key, "executable": str(executable)},
                )
            except Exception as exc:
                return _failure(
                    "open_application",
                    f"{cleaned} launch nahi hua: {exc}",
                    "launch_error",
                    app=app_key,
                )

    # 2. Dynamic Discovery: Search installed applications across Windows Registry and Start Menu
    dynamic_apps = _scan_windows_installed_applications()
    query_key = cleaned.casefold().strip()

    # Exact key match
    dyn_path = dynamic_apps.get(query_key)
    if not dyn_path:
        # Fuzzy / substring match (e.g. 'discord' matches 'Discord Canary', 'photoshop' matches 'Adobe Photoshop 2024')
        for k, v in dynamic_apps.items():
            if query_key in k or k in query_key:
                dyn_path = v
                break

    if dyn_path is not None and dyn_path.exists():
        try:
            startfile = getattr(os, "startfile", None)
            if callable(startfile):
                startfile(str(dyn_path))
            else:
                subprocess.Popen([str(dyn_path)], shell=False, close_fds=True)
            return AutomationResult(
                True,
                "open_application",
                f"Captain, {cleaned} launch kar diya hai.",
                {"app": cleaned, "path": str(dyn_path), "dynamic_discovery": True},
            )
        except Exception as dyn_err:
            return _failure(
                "open_application",
                f"{cleaned} launch fail hua: {dyn_err}",
                "dynamic_launch_error",
            )

    return _failure(
        "open_application",
        f"Captain, '{cleaned}' system me installed nahi mila.",
        "app_not_found",
        requested_app=cleaned,
    )


VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3


def trigger_media_key(key: str = "play_pause") -> AutomationResult:
    """Control global media playback (play/pause, next track, previous track, stop) across Windows."""
    k = str(key).strip().lower()
    mapping = {
        "play_pause": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "play": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "pause": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "resume": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "chalu": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "unpause": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "toggle": (VK_MEDIA_PLAY_PAUSE, "Play / Pause"),
        "next": (VK_MEDIA_NEXT_TRACK, "Next Track"),
        "next_track": (VK_MEDIA_NEXT_TRACK, "Next Track"),
        "prev": (VK_MEDIA_PREV_TRACK, "Previous Track"),
        "previous": (VK_MEDIA_PREV_TRACK, "Previous Track"),
        "prev_track": (VK_MEDIA_PREV_TRACK, "Previous Track"),
        "stop": (VK_MEDIA_STOP, "Stop Playback"),
    }
    target = mapping.get(k)
    if not target:
        return _failure("trigger_media_key", f"Media key '{key}' valid nahi hai.", "invalid_key")
    vk_code, label = target
    if os.name != "nt":
        return _failure("trigger_media_key", "Media key control Windows-only hai.", "unsupported_os")
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(vk_code, 0, 0, 0)
        user32.keybd_event(vk_code, 0, 0x0002, 0)
        return AutomationResult(
            True,
            "trigger_media_key",
            f"Media {label} kar diya.",
            {"key": k, "label": label},
        )
    except Exception as exc:
        return _failure("trigger_media_key", f"Media key trigger fail hua: {exc}", "keybd_error")


def lock_workstation() -> AutomationResult:
    """Instantly lock the Windows PC workstation / screen."""
    if os.name != "nt":
        return _failure("lock_workstation", "Lock screen sirf Windows par supported hai.", "unsupported_os")
    try:
        user32 = ctypes.windll.user32
        success = bool(user32.LockWorkStation())
        if success:
            return AutomationResult(True, "lock_workstation", "Captain, PC lock kar diya hai.", {"locked": True})
        return _failure("lock_workstation", "LockWorkStation call reject hui.", "lock_failed")
    except Exception as exc:
        return _failure("lock_workstation", f"PC lock nahi ho saka: {exc}", "lock_error")


def search_local_files(
    query: str,
    directory: str | None = None,
    extension: str | None = None,
    max_results: int = 8,
) -> AutomationResult:
    """Search for local files across user directories safely."""
    try:
        cleaned_query = _clean_required(query, "Search query").lower()
    except (TypeError, ValueError) as exc:
        return _failure("search_local_files", str(exc), "empty_query")

    search_roots: list[Path] = []
    if directory:
        p = Path(directory).expanduser()
        if p.is_dir():
            search_roots.append(p)
    if not search_roots:
        home = Path.home()
        for sub in ("Documents", "Downloads", "Desktop", "Pictures", "Videos", "Music"):
            candidate = home / sub
            if candidate.is_dir():
                search_roots.append(candidate)
        if not search_roots:
            search_roots.append(home)

    ext_filter = extension.lower().strip(".") if extension else None
    results: list[dict[str, Any]] = []
    excluded_dirs = {
        "node_modules", ".git", ".venv", "venv", "__pycache__", "appdata",
        "windows", "program files", "program files (x86)", "$recycle.bin",
    }

    deadline = time.monotonic() + 4.0
    for root in search_roots:
        if time.monotonic() > deadline or len(results) >= max_results:
            break
        try:
            for item in root.rglob("*"):
                if time.monotonic() > deadline or len(results) >= max_results:
                    break
                if item.is_dir() and item.name.lower() in excluded_dirs:
                    continue
                if item.is_file():
                    if ext_filter and item.suffix.lower().strip(".") != ext_filter:
                        continue
                    if cleaned_query in item.name.lower():
                        results.append({
                            "name": item.name,
                            "path": str(item.resolve()),
                            "size_kb": round(item.stat().st_size / 1024, 1),
                            "modified": datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                        })
        except Exception:
            continue

    if results:
        formatted = "\n".join(f"- {r['name']} ({r['size_kb']} KB) -> {r['path']}" for r in results[:5])
        return AutomationResult(
            True,
            "search_local_files",
            f"Captain, '{query}' ke matching files mil gayi hain:\n{formatted}",
            {"query": query, "results": results, "count": len(results)},
        )
    return AutomationResult(
        True,
        "search_local_files",
        f"Captain, '{query}' ke naam se koi file nahi mili.",
        {"query": query, "results": [], "count": 0},
    )


def get_clipboard_text() -> AutomationResult:
    """Read current text content from the Windows clipboard."""
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text or not text.strip():
            return AutomationResult(True, "get_clipboard_text", "Clipboard abhi empty hai.", {"text": "", "empty": True})
        truncated = text.strip()[:500]
        preview = truncated if len(text) <= 500 else f"{truncated}..."
        return AutomationResult(
            True,
            "get_clipboard_text",
            f"Clipboard content:\n\"{preview}\"",
            {"text": text, "length": len(text)},
        )
    except Exception:
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                kernel32.GlobalLock.restype = ctypes.c_void_p
                kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
                kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                user32.OpenClipboard.argtypes = [wintypes.HWND]
                user32.GetClipboardData.restype = wintypes.HANDLE
                user32.GetClipboardData.argtypes = [wintypes.UINT]
                if user32.OpenClipboard(None):
                    h_mem = user32.GetClipboardData(13)  # CF_UNICODETEXT
                    text = ""
                    if h_mem:
                        p_mem = kernel32.GlobalLock(h_mem)
                        if p_mem:
                            text = ctypes.wstring_at(p_mem)
                            kernel32.GlobalUnlock(h_mem)
                    user32.CloseClipboard()
                    truncated = text.strip()[:500]
                    preview = truncated if len(text) <= 500 else f"{truncated}..."
                    return AutomationResult(
                        True,
                        "get_clipboard_text",
                        f"Clipboard content:\n\"{preview}\"",
                        {"text": text, "length": len(text)},
                    )
            except Exception as w_exc:
                return _failure("get_clipboard_text", f"Clipboard read fail hua: {w_exc}", "clipboard_error")
        return _failure("get_clipboard_text", "Clipboard read fail hua.", "clipboard_error")


def set_clipboard_text(text: str) -> AutomationResult:
    """Copy text to the Windows clipboard."""
    try:
        cleaned = _clean_required(text, "Clipboard text")
    except (TypeError, ValueError) as exc:
        return _failure("set_clipboard_text", str(exc), "empty_text")
    try:
        import pyperclip
        pyperclip.copy(cleaned)
        return AutomationResult(
            True,
            "set_clipboard_text",
            f"Text clipboard me copy kar diya: '{cleaned[:80]}'",
            {"copied_text": cleaned, "length": len(cleaned)},
        )
    except Exception:
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
                kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
                kernel32.GlobalLock.restype = ctypes.c_void_p
                kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
                kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                user32.OpenClipboard.argtypes = [wintypes.HWND]
                user32.GetClipboardData.restype = wintypes.HANDLE
                user32.GetClipboardData.argtypes = [wintypes.UINT]
                user32.SetClipboardData.restype = wintypes.HANDLE
                user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

                if user32.OpenClipboard(None):
                    user32.EmptyClipboard()
                    data = cleaned.encode("utf-16le") + b"\x00\x00"
                    h_mem = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
                    p_mem = kernel32.GlobalLock(h_mem)
                    if p_mem:
                        ctypes.memmove(p_mem, data, len(data))
                        kernel32.GlobalUnlock(h_mem)
                        user32.SetClipboardData(13, h_mem)  # CF_UNICODETEXT
                    user32.CloseClipboard()
                    return AutomationResult(
                        True,
                        "set_clipboard_text",
                        f"Text clipboard me copy kar diya: '{cleaned[:80]}'",
                        {"copied_text": cleaned, "length": len(cleaned)},
                    )
            except Exception as w_exc:
                return _failure("set_clipboard_text", f"Clipboard copy fail hua: {w_exc}", "clipboard_error")
        return _failure("set_clipboard_text", "Clipboard copy fail hua.", "clipboard_error")


def save_screenshot(filename: str | None = None) -> AutomationResult:
    """Capture full desktop screen and save to disk."""
    try:
        img = _capture_desktop_screenshot()
        from config import load_settings
        s = load_settings()
        pictures_dir = Path.home() / "Pictures" / "Screenshots"
        if not pictures_dir.is_dir():
            pictures_dir = s.notes_directory.parent / "screenshots"
        pictures_dir.mkdir(parents=True, exist_ok=True)

        name = filename or f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not name.endswith(".png") and not name.endswith(".jpg"):
            name += ".png"
        out_path = pictures_dir / name
        img.save(out_path)
        return AutomationResult(
            True,
            "save_screenshot",
            f"Captain, screenshot save kar diya: {out_path.name}",
            {"path": str(out_path.resolve()), "filename": name},
        )
    except Exception as exc:
        return _failure("save_screenshot", f"Screenshot save nahi ho saka: {exc}", "screenshot_error")


def save_quick_note(title: str, content: str) -> AutomationResult:
    """Save a quick note or memo into local Markdown storage."""
    try:
        clean_title = _clean_required(title, "Note title")
        clean_content = _clean_required(content, "Note content")
    except (TypeError, ValueError) as exc:
        return _failure("save_quick_note", str(exc), "empty_content")

    try:
        from config import load_settings
        s = load_settings()
        notes_dir = s.notes_directory
        notes_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%I:%M %p")
        note_file = notes_dir / f"notes_{date_str}.md"

        entry = f"\n### {clean_title} ({time_str})\n{clean_content}\n"
        with open(note_file, "a", encoding="utf-8") as f:
            f.write(entry)

        return AutomationResult(
            True,
            "save_quick_note",
            f"Captain, note save kar liya: '{clean_title}'",
            {"title": clean_title, "file": str(note_file.resolve()), "date": date_str},
        )
    except Exception as exc:
        return _failure("save_quick_note", f"Note save nahi ho saka: {exc}", "note_error")


def browser_navigate(url: str) -> AutomationResult:
    """Open and navigate to a URL using the browser engine."""
    try:
        from browser_engine import get_browser_engine
        eng = get_browser_engine()
        res = eng.navigate(url)
        if res.get("success"):
            return AutomationResult(True, "browser_navigate", f"Browser open karke '{url}' navigate kar diya.", res)
    except Exception as exc:
        LOGGER.debug("Browser engine navigate fallback: %s", exc)
    return open_website(url)


def browser_click_selector(selector: str) -> AutomationResult:
    """Click an element on the active browser page by CSS selector, XPath, or text."""
    try:
        from browser_engine import get_browser_engine
        eng = get_browser_engine()
        res = eng.click_selector(selector)
        if res.get("success"):
            return AutomationResult(True, "browser_click_selector", f"Browser element '{selector}' click kar diya.", res)
    except Exception as exc:
        LOGGER.debug("Browser click selector engine notice: %s", exc)

    # Fallback to desktop active window: if search button/icon clicked, trigger Enter
    if any(k in selector.lower() for k in ("search", "submit", "btn", "icon", "enter")):
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press("enter")
            return AutomationResult(True, "browser_click_selector", "Search submit enter press kar diya.", {"selector": selector, "fallback": True})
        except Exception:
            pass
    return _failure("browser_click_selector", f"Browser click fail hua for '{selector}'.", "browser_error")


def browser_fill_input(selector: str, text: str) -> AutomationResult:
    """Type text into a form input field in the browser with desktop fallback."""
    try:
        from browser_engine import get_browser_engine
        eng = get_browser_engine()
        res = eng.fill_input(selector, text)
        if res.get("success"):
            return AutomationResult(True, "browser_fill_input", f"'{selector}' field me text enter kar diya.", res)
    except Exception as exc:
        LOGGER.debug("Browser fill input engine notice: %s", exc)

    # Fallback: type directly into user's active desktop window (YouTube / Edge / Chrome)
    try:
        from desktop_workflow_agent import UniversalInAppOperator
        op_res = UniversalInAppOperator.search_in_active_or_open_app(text)
        if op_res.get("success"):
            return AutomationResult(True, "browser_fill_input", op_res.get("message", f"Active window me '{text}' type kar diya."), op_res)
    except Exception as op_exc:
        LOGGER.debug("Desktop in-app fill fallback notice: %s", op_exc)

    return _failure("browser_fill_input", f"Browser input fill fail hua: {selector}", "browser_error")


def browser_extract_text(selector: str | None = None) -> AutomationResult:
    """Extract readable text or table from the active browser page."""
    try:
        from browser_engine import get_browser_engine
        eng = get_browser_engine()
        res = eng.extract_text(selector)
        if res.get("success"):
            extracted = res.get("text", "")
            return AutomationResult(
                True,
                "browser_extract_text",
                f"Webpage content extract kar liya:\n{extracted[:400]}...",
                res,
            )
        return _failure("browser_extract_text", res.get("error", "Extraction failed"), "extract_error")
    except Exception as exc:
        return _failure("browser_extract_text", f"Text extraction fail hua: {exc}", "browser_error")


_APPLICATION_PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "file_explorer": "explorer.exe",
    "vscode": "Code.exe",
    "paint": "mspaint.exe",
    "spotify": "Spotify.exe",
    "terminal": "WindowsTerminal.exe",
    "cmd": "cmd.exe",
    "taskmgr": "Taskmgr.exe",
    "control": "control.exe",
    "vlc": "vlc.exe",
}


def close_application(app_name: str) -> AutomationResult:
    """Close one allowlisted app after explicit caller confirmation."""

    try:
        cleaned = _clean_required(app_name, "Application name")
    except (TypeError, ValueError) as exc:
        return _failure("close_application", str(exc), "empty_app_name")
    app_key = APPLICATION_ALIASES.get(cleaned.casefold())
    process_name = _APPLICATION_PROCESS_NAMES.get(str(app_key or ""))
    if process_name is None:
        return _failure(
            "close_application",
            "Sirf allowlisted application close ki ja sakti hai.",
            "application_not_allowed",
        )
    if os.name != "nt":
        return _failure(
            "close_application",
            "Application close automation abhi Windows-only hai.",
            "unsupported_os",
        )
    try:
        completed = subprocess.run(
            ["taskkill", "/IM", process_name, "/T"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _failure(
            "close_application",
            "Application close nahi ho saki; success assume nahi ki gayi.",
            "close_application_error",
            exception_type=type(exc).__name__,
        )
    if completed.returncode != 0:
        return _failure(
            "close_application",
            f"{cleaned} running nahi mili ya Windows ne close request reject ki.",
            "application_not_running",
        )
    return AutomationResult(
        True,
        "close_application",
        f"{cleaned} close kar di.",
        {"app": app_key},
    )


def get_current_time() -> AutomationResult:
    """Return current local time without using the network."""

    now = datetime.now().astimezone()
    return AutomationResult(
        True,
        "get_current_time",
        f"Abhi local time {now.strftime('%I:%M:%S %p')} hai.",
        {"iso": now.isoformat(), "time": now.strftime("%H:%M:%S")},
    )


def get_current_date() -> AutomationResult:
    """Return current local calendar date without using the network."""

    now = datetime.now().astimezone()
    return AutomationResult(
        True,
        "get_current_date",
        f"Aaj {now.strftime('%A, %d %B %Y')} hai.",
        {"iso": now.date().isoformat()},
    )


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_memory_status() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {}
    return {
        "memory_percent": int(status.dwMemoryLoad),
        "memory_total_gb": round(status.ullTotalPhys / (1024**3), 1),
        "memory_available_gb": round(status.ullAvailPhys / (1024**3), 1),
    }


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def _windows_battery_status() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    status = _SystemPowerStatus()
    kernel32 = getattr(ctypes.windll, "kernel32", None)
    if kernel32 is None or not hasattr(kernel32, "GetSystemPowerStatus"):
        return {}
    if not kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return {}
    battery_percent = int(status.BatteryLifePercent)
    if battery_percent > 100 or battery_percent < 0:
        return {}
    ac_state = "Plugged in" if status.ACLineStatus == 1 else "On Battery"
    return {
        "battery_percent": battery_percent,
        "power_plugged": status.ACLineStatus == 1,
        "battery_status": f"{battery_percent}% ({ac_state})",
    }


def get_system_status() -> AutomationResult:
    """Return non-sensitive local OS, memory, disk, and uptime information."""

    try:
        root = Path.cwd().anchor or os.path.abspath(os.sep)
        disk = shutil.disk_usage(root)
        data: dict[str, Any] = {
            "computer": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "python": platform.python_version(),
            "disk_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0.0,
            "disk_free_gb": round(disk.free / (1024**3), 1),
        }
        data.update(_windows_memory_status())
        data.update(_windows_battery_status())
        if os.name == "nt":
            data["uptime_hours"] = round(ctypes.windll.kernel32.GetTickCount64() / 3_600_000, 1)
        summary = f"System {data['os']} | disk {data['disk_percent']}% used"
        if "memory_percent" in data:
            summary += f" | memory {data['memory_percent']}% used"
        if "battery_status" in data:
            summary += f" | battery {data['battery_status']}"
        return AutomationResult(True, "get_system_status", summary + ".", data)
    except Exception as exc:
        return _failure(
            "get_system_status",
            "System status read nahi ho saka.",
            "system_status_error",
            exception_type=type(exc).__name__,
        )


def _percentage(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} 0 se 100 integer hona chahiye.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 0 se 100 integer hona chahiye.") from exc
    if parsed < 0 or parsed > 100:
        raise ValueError(f"{label} 0 se 100 ke beech hona chahiye.")
    return parsed


def _volume_endpoint() -> Any:
    pycaw = import_module("pycaw.pycaw")
    return pycaw.AudioUtilities.GetSpeakers().EndpointVolume


def set_volume(level: int) -> AutomationResult:
    """Set Windows master volume to an absolute 0-100 percentage."""

    try:
        target = _percentage(level, "Volume")
    except ValueError as exc:
        return _failure("set_volume", str(exc), "invalid_level")
    if os.name != "nt":
        return _failure("set_volume", "Volume control sirf Windows par supported hai.", "unsupported_os")
    try:
        endpoint = _volume_endpoint()
        endpoint.SetMasterVolumeLevelScalar(target / 100, None)
        actual = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
    except (ImportError, ModuleNotFoundError):
        return _failure("set_volume", "Pycaw dependency installed nahi hai.", "missing_dependency")
    except Exception as exc:
        return _failure(
            "set_volume",
            "Windows volume change fail hua; success assume nahi ki gayi.",
            "volume_error",
            exception_type=type(exc).__name__,
        )
    return AutomationResult(True, "set_volume", f"Volume {actual}% set kar diya.", {"level": actual})


def change_volume(direction: str, amount: int = 10) -> AutomationResult:
    """Increase or decrease Windows master volume by a bounded amount."""

    cleaned_direction = str(direction).strip().casefold()
    if cleaned_direction not in {"up", "down"}:
        return _failure("change_volume", "Direction sirf up ya down ho sakti hai.", "invalid_direction")
    try:
        step = _percentage(amount, "Volume amount")
    except ValueError as exc:
        return _failure("change_volume", str(exc), "invalid_amount")
    if step == 0:
        return _failure("change_volume", "Volume amount kam se kam 1 hona chahiye.", "invalid_amount")
    if os.name != "nt":
        return _failure("change_volume", "Volume control sirf Windows par supported hai.", "unsupported_os")
    try:
        endpoint = _volume_endpoint()
        current = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
        target = max(0, min(100, current + (step if cleaned_direction == "up" else -step)))
        endpoint.SetMasterVolumeLevelScalar(target / 100, None)
        actual = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
    except (ImportError, ModuleNotFoundError):
        return _failure("change_volume", "Pycaw dependency installed nahi hai.", "missing_dependency")
    except Exception as exc:
        return _failure(
            "change_volume",
            "Windows volume change fail hua; success assume nahi ki gayi.",
            "volume_error",
            exception_type=type(exc).__name__,
        )
    return AutomationResult(
        True,
        "change_volume",
        f"Volume {actual}% ho gaya.",
        {"level": actual, "direction": cleaned_direction, "amount": step},
    )


def set_mute(muted: bool) -> AutomationResult:
    """Mute or unmute Windows master audio without changing its level."""

    if os.name != "nt":
        return _failure(
            "set_mute", "Mute control sirf Windows par supported hai.", "unsupported_os"
        )
    try:
        endpoint = _volume_endpoint()
        endpoint.SetMute(1 if muted else 0, None)
        actual = bool(endpoint.GetMute())
    except (ImportError, ModuleNotFoundError):
        return _failure(
            "set_mute", "Pycaw dependency installed nahi hai.", "missing_dependency"
        )
    except Exception as exc:
        return _failure(
            "set_mute",
            "Windows mute state change fail hui.",
            "volume_error",
            exception_type=type(exc).__name__,
        )
    return AutomationResult(
        True,
        "set_mute",
        "Audio mute kar diya." if actual else "Audio unmute kar diya.",
        {"muted": actual},
    )


def set_brightness(level: int) -> AutomationResult:
    """Set brightness on detected displays to an absolute 0-100 percentage."""

    try:
        target = _percentage(level, "Brightness")
    except ValueError as exc:
        return _failure("set_brightness", str(exc), "invalid_level")
    if os.name != "nt":
        return _failure(
            "set_brightness", "Brightness control sirf Windows par supported hai.", "unsupported_os"
        )
    try:
        brightness = import_module("screen_brightness_control")
        brightness.set_brightness(target)
        readings = brightness.get_brightness()
        values = [int(value) for value in readings] if isinstance(readings, (list, tuple)) else [int(readings)]
    except (ImportError, ModuleNotFoundError):
        return _failure(
            "set_brightness", "screen-brightness-control dependency installed nahi hai.", "missing_dependency"
        )
    except Exception as exc:
        return _failure(
            "set_brightness",
            "Display brightness change fail hua; success assume nahi ki gayi.",
            "brightness_error",
            exception_type=type(exc).__name__,
        )
    return AutomationResult(
        True,
        "set_brightness",
        f"Brightness {target}% set kar di.",
        {"requested_level": target, "display_levels": values},
    )


_CONFIRMATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shutdown_or_restart", re.compile(r"\b(shut\s*down|shutdown|restart|reboot|power\s*off)\b", re.I)),
    (
        "close_application",
        re.compile(
            r"(?:\b(close|kill|terminate|band\s+karo)\b.+"
            r"\b(app|application|chrome|edge|notepad|calculator|explorer|code)\b)"
            r"|(?:\b(chrome|edge|notepad|calculator|explorer|code)\b.+"
            r"\b(close|kill|terminate|band\s+karo)\b)",
            re.I,
        ),
    ),
    ("delete_or_move_files", re.compile(r"\b(delete|remove|erase|move|rename|del|hatao|mitao)\b.+\b(file|folder|directory|files|folders)\b", re.I)),
    ("install_software", re.compile(r"\b(install|uninstall|setup)\b.+\b(app|application|software|package|program)?\b", re.I)),
    ("send_message_or_email", re.compile(r"\b(send|bhejo|forward)\b.+\b(message|email|mail|whatsapp|sms)\b", re.I)),
    ("purchase_or_financial_action", re.compile(r"\b(buy|purchase|order|pay|payment|transfer|upi|bank|stock|crypto)\b", re.I)),
    ("important_system_setting", re.compile(r"\b(registry|firewall|windows update|default app|privacy setting|system setting)\b", re.I)),
)


def confirmation_required_for_text(text: str) -> str | None:
    """Return the risky action category that needs explicit confirmation."""

    cleaned = str(text).strip()
    if re.match(r"^(?:how|why|what)\b|^(?:explain|tell me about)\b", cleaned, re.I):
        return None
    executable = re.search(r"\b(?:run|execute|launch|open)\s+([^\s]+\.(?:exe|bat|cmd|ps1))\b", cleaned, re.I)
    if executable and executable.group(1).casefold() not in APPLICATION_ALIASES:
        return "unknown_executable"
    for action, pattern in _CONFIRMATION_PATTERNS:
        if pattern.search(cleaned):
            return action
    return None


def confirmation_required_result(action: str, request_text: str) -> AutomationResult:
    """Return a non-executing result for a risky request awaiting confirmation."""

    normalized = action if action in CONFIRMATION_REQUIRED_ACTIONS else "important_system_setting"
    return _failure(
        "confirmation_required",
        "Is risky action ke liye explicit confirmation mandatory hai; action execute nahi hua.",
        "confirmation_required",
        requested_action=normalized,
        request=request_text.strip(),
    )


def _confirmation_result_for_command(
    command: ParsedAutomationCommand,
    request_text: str,
) -> AutomationResult:
    if command.intent != "send_whatsapp_message":
        return confirmation_required_result(
            str(
                confirmation_required_for_text(request_text)
                or "important_system_setting"
            ),
            request_text,
        )
    recipient = str(command.arguments.get("recipient", "")).strip()
    message = str(command.arguments.get("message", "")).strip()
    return _failure(
        "confirmation_required",
        (
            "WhatsApp Desktop automatic Send preview:\n"
            f"Number: {recipient}\nMessage: {message}\n"
            "Send karne ke liye Confirm action, warna Cancel action."
        ),
        "confirmation_required",
        requested_action="send_message_or_email",
        request=request_text.strip(),
        recipient=recipient,
        can_confirm=False,
    )


def _confirmed_command_for_text(text: str) -> ParsedAutomationCommand | None:
    """Resolve only risky actions that have a dedicated safe executor."""

    cleaned = str(text).strip()
    whatsapp_request = _parse_whatsapp_message_request(cleaned)
    if (
        whatsapp_request is not None
        and whatsapp_request.intent == "send_whatsapp_message"
    ):
        return whatsapp_request
    match = re.fullmatch(
        r"(?:please\s+)?(?:close|kill|terminate)\s+(?:the\s+)?(.+?)"
        r"(?:\s+(?:app|application))?",
        cleaned,
        re.I,
    )
    if match is None:
        match = re.fullmatch(
            r"(.+?)\s+(?:app\s+)?(?:close|band\s+karo|band\s+kar\s+do)",
            cleaned,
            re.I,
        )
    if match is None:
        return None
    target = re.sub(
        r"^(?:the\s+)?(?:app|application)\s+|"
        r"\s+(?:app|application)$",
        "",
        match.group(1).strip(),
        flags=re.I,
    ).strip()
    if target.casefold() not in APPLICATION_ALIASES:
        return None
    return ParsedAutomationCommand("close_application", {"app_name": target})


_INVOCATION_PREFIX = re.compile(
    r"^(?:(?:he+y+|hi|hello|ok(?:ay)?|please)\s+)*(?:jarvis|dark\s*shadow|captain)"
    r"(?:\s*[,;:!-]\s*|\s+)",
    re.I,
)


def _strip_invocation(text: str) -> str:
    """Remove wake words/fillers and repair a few common speech typos."""

    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = _INVOCATION_PREFIX.sub("", cleaned).strip()
    cleaned = re.sub(r"^(?:achha|accha|acha|bhai|sun|zara|hey|hello|please|pls)\s+(?:ye\s+)?(?:batao\s+)?", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(?:mujhe|zara)\s+", "", cleaned, flags=re.I)
    # Strip conversational prefixes common in voice input
    cleaned = re.sub(
        r"^(?:can\s+you|could\s+you|will\s+you|would\s+you|kya\s+tum|"
        r"please|pls|kindly|just|ok\s+)?(?:\s+(?:please|pls))?\s*",
        "", cleaned, flags=re.I,
    )
    # Strip trailing punctuation (?, !, .)
    cleaned = re.sub(r"[?!.]+$", "", cleaned)
    cleaned = re.sub(r"\boepn\b", "open", cleaned, flags=re.I)
    return cleaned.strip()


def _clean_subject(text: str) -> str:
    subject = _strip_invocation(text)
    subject = re.sub(r"^(?:ye\s+batao\s+ki|batao\s+ki|about)\s+", "", subject, flags=re.I)
    return subject.strip(" ,.;:?!")


def _missing_media_context() -> AutomationResult:
    return _failure(
        "play_youtube",
        "Kis artist ya song ko chalana hai? Pehle naam boliye, jaise 'Arijit Singh ka song chalao'.",
        "missing_media_context",
    )


_WHATSAPP_MESSAGE_PATTERNS = (
    re.compile(
        r"^(?:whats?app|whatapp)(?:\s+app)?"
        r"(?:\s+(?:par|pe|mein))?"
        r"(?:\s+(?:open\s+kar(?:ke|ake)|kholkar))?\s+"
        r"(?P<recipient>.+?)\s+ko\s+(?:message|msg)\s+"
        r"(?P<action>bhej(?:o|\s+do)?|send(?:\s+karo|\s+kar\s+do)?|"
        r"draft(?:\s+karo)?|type(?:\s+karo)?|likho)"
        r"(?:\s+(?:ki|saying|that)|\s*[:,-]\s*)\s*(?P<message>.+)$",
        re.I,
    ),
    re.compile(
        r"^(?P<recipient>.+?)\s+ko\s+(?:whats?app|whatapp)"
        r"(?:\s+(?:par|pe))?\s+(?:message|msg)\s+"
        r"(?P<action>bhej(?:o|\s+do)?|send(?:\s+karo|\s+kar\s+do)?|"
        r"draft(?:\s+karo)?|type(?:\s+karo)?|likho)"
        r"(?:\s+(?:ki|saying|that)|\s*[:,-]\s*)\s*(?P<message>.+)$",
        re.I,
    ),
    re.compile(
        r"^(?P<action>send|draft|prepare)\s+(?P<recipient>.+?)\s+"
        r"(?:a\s+)?(?:whats?app|whatapp)\s+(?:message|msg)"
        r"(?:\s+(?:saying|that)|\s*[:,-]\s*)\s*(?P<message>.+)$",
        re.I,
    ),
)


def _parse_whatsapp_message_request(text: str) -> ParsedAutomationCommand | None:
    """Recognize only requests containing both an explicit recipient and body."""

    cleaned = _strip_invocation(text)
    for pattern in _WHATSAPP_MESSAGE_PATTERNS:
        match = pattern.fullmatch(cleaned)
        if match is None:
            continue
        recipient = match.group("recipient").strip(" ,:;")
        message = match.group("message").strip(" ,")
        if recipient and message:
            action = match.group("action").strip().casefold()
            intent = (
                "prepare_whatsapp_message"
                if action.startswith(("draft", "prepare", "type", "likho"))
                else "send_whatsapp_message"
            )
            return ParsedAutomationCommand(
                intent,
                {"recipient": recipient, "message": message},
            )
    return None


def _parse_phone_call_request(text: str) -> ParsedAutomationCommand | None:
    """Recognize voice and text phone calling requests (Hindi, Hinglish, English) for Microsoft Mobile Link."""
    cleaned = _strip_invocation(text)
    lower = cleaned.casefold()

    # Exclude open app commands: 'open phone link', 'phone link kholo'
    if re.fullmatch(
        r"(?:open|launch|khol(?:o|iye)?)\s+(?:microsoft\s+)?(?:mobile|phone)\s*link|"
        r"(?:microsoft\s+)?(?:mobile|phone)\s*link\s+(?:open|khol(?:o|iye)?)(?:\s+(?:karo|kar\s+do))?",
        lower,
    ):
        return None

    # Exclude non-calling phrases: 'phone ki battery', 'call center', 'what is a call'
    if re.search(r"\b(?:call\s*center|phone\s*(?:ki|ka|ke)\s*(?:battery|price|rate|screen)|what\s+is\s+a\s+call)\b", lower):
        return None

    # Default calling method is phone_link (Microsoft Mobile Link / Phone Link)
    method = "phone_link"

    # Strip method keywords from text for cleaner recipient extraction
    stripped = re.sub(r"\b(?:using\s+|via\s+)?(?:microsoft\s+)?(?:mobile|phone)\s*link(?:\s+(?:se|feature))?\b", "", cleaned, flags=re.I).strip()
    stripped = re.sub(r"\b(?:se\s+)?(?:microsoft\s+)?(?:mobile|phone)\s*link\b", "", stripped, flags=re.I).strip()
    stripped = " ".join(stripped.split())

    def _clean_recipient(recip: str) -> str:
        r = re.sub(r"\s+(?:ko|par|pe|please)$", "", recip.strip(), flags=re.I).strip()
        return r.strip(" ,:;")

    # 1. Pattern: '<recipient> ko/par/pe call/phone/dial lagao/karo/kar do'
    m1 = re.fullmatch(
        r"(.+?)\s+(?:ko|par|pe)\s+(?:ek\s+)?(?:call|phone|dial)(?:\s+(?:lagao|laga\s+do|karo|kar\s+do|karna|lagayein|milao|mila\s+do))?$",
        stripped,
        re.I,
    )
    if m1:
        recip = _clean_recipient(m1.group(1))
        if recip and recip.lower() not in {"kisko", "kise", "who", "whom"}:
            return ParsedAutomationCommand("make_phone_call", {"recipient": recip, "method": method})

    # 2. Pattern: 'call/phone/dial lagao/karo/kar do [ko] <recipient>'
    m2 = re.fullmatch(
        r"(?:call|phone|dial)\s+(?:lagao|laga\s+do|karo|kar\s+do|lagayein|milao|mila\s+do)(?:\s+(?:ko|par|pe|to))?\s+(.+)$",
        stripped,
        re.I,
    )
    if m2:
        recip = _clean_recipient(m2.group(1))
        if recip:
            return ParsedAutomationCommand("make_phone_call", {"recipient": recip, "method": method})

    # 3. Pattern: 'make/place a call to <recipient>'
    m3 = re.fullmatch(
        r"(?:make|place)\s+(?:a\s+)?(?:phone\s+)?call\s+(?:to\s+)(.+)$",
        stripped,
        re.I,
    )
    if m3:
        recip = _clean_recipient(m3.group(1))
        if recip:
            return ParsedAutomationCommand("make_phone_call", {"recipient": recip, "method": method})

    # 4. Pattern: 'call/phone/dial <recipient>'
    m4 = re.fullmatch(r"(?:call|phone|dial)\s+(?:to\s+)?(.+)$", stripped, re.I)
    if m4:
        recip = _clean_recipient(m4.group(1))
        if recip and recip.lower() not in {"center", "later", "back", "history", "logs", "details"}:
            return ParsedAutomationCommand("make_phone_call", {"recipient": recip, "method": method})

    # 5. Pattern: '<recipient> ko call/phone' e.g. 'Papa ko call'
    m5 = re.fullmatch(r"(.+?)\s+ko\s+(?:call|phone|dial)$", stripped, re.I)
    if m5:
        recip = _clean_recipient(m5.group(1))
        if recip:
            return ParsedAutomationCommand("make_phone_call", {"recipient": recip, "method": method})

    return None


def parse_automation_command(
    text: str,
    context: AutomationContext | None = None,
) -> ParsedAutomationCommand | None:
    """Parse supported automation commands without sending text to a model."""

    cleaned = str(text).strip()
    if not cleaned or cleaned.startswith("/"):
        return None
    call_request = _parse_phone_call_request(cleaned)
    if call_request is not None:
        return call_request
    whatsapp_request = _parse_whatsapp_message_request(cleaned)
    if whatsapp_request is not None:
        if whatsapp_request.intent == "send_whatsapp_message":
            return ParsedAutomationCommand(
                "confirmation_required",
                {
                    "action": "send_message_or_email",
                    "request_text": cleaned,
                },
            )
        return whatsapp_request
    risk = confirmation_required_for_text(cleaned)
    if risk:
        return ParsedAutomationCommand("confirmation_required", {"action": risk, "request_text": cleaned})

    cleaned = _strip_invocation(cleaned)
    lower = cleaned.casefold()
    if re.fullmatch(r"(?:what(?:'s| is) the )?(?:current )?time(?: kya hai)?|abhi (?:ka )?time kya hai|samay kya hai", lower):
        return ParsedAutomationCommand("get_current_time")
    if re.fullmatch(r"(?:what(?:'s| is) the )?(?:current |today'?s )?date(?: kya hai)?|aaj (?:ki )?date kya hai|tarikh kya hai", lower):
        return ParsedAutomationCommand("get_current_date")
    if re.fullmatch(r"(?:show |get )?(?:my |current )?(?:system|pc|computer) status", lower):
        return ParsedAutomationCommand("get_system_status")

    if re.fullmatch(r"(?:mute|awaz\s+band(?:\s+karo)?)", lower):
        return ParsedAutomationCommand("set_mute", {"muted": True})
    if re.fullmatch(r"(?:unmute|awaz\s+(?:chalu|on)(?:\s+karo)?)", lower):
        return ParsedAutomationCommand("set_mute", {"muted": False})
    match = re.fullmatch(
        r"(?:set\s+)?volume(?:\s+(?:to|ko))?\s+(\d{1,3})\s*(?:%|percent|pratishat)?(?:\s+(?:karo|kar\s+do))?",
        lower,
    )
    if match:
        return ParsedAutomationCommand("set_volume", {"level": int(match.group(1))})
    match = re.fullmatch(r"(?:volume\s+up|increase\s+(?:the\s+)?volume)(?:\s+by)?(?:\s+(\d{1,3}))?\s*(?:%|percent)?", lower)
    if match:
        return ParsedAutomationCommand("change_volume", {"direction": "up", "amount": int(match.group(1) or 10)})
    match = re.fullmatch(r"(?:volume\s+down|decrease\s+(?:the\s+)?volume)(?:\s+by)?(?:\s+(\d{1,3}))?\s*(?:%|percent)?", lower)
    if match:
        return ParsedAutomationCommand("change_volume", {"direction": "down", "amount": int(match.group(1) or 10)})
    if re.fullmatch(r"(?:awaz|awaaj|volume)\s+(?:badhao|badao|tez\s+karo)", lower):
        return ParsedAutomationCommand("change_volume", {"direction": "up", "amount": 10})
    if re.fullmatch(r"(?:awaz|awaaj|volume)\s+(?:kam\s+karo|ghatao)", lower):
        return ParsedAutomationCommand("change_volume", {"direction": "down", "amount": 10})
    match = re.fullmatch(
        r"(?:set\s+)?brightness(?:\s+(?:to|ko))?\s+(\d{1,3})\s*(?:%|percent|pratishat)?(?:\s+(?:karo|kar\s+do))?",
        lower,
    )
    if match:
        return ParsedAutomationCommand("set_brightness", {"level": int(match.group(1))})

    follow_up = re.fullmatch(
        r"(?:play\s+)?(?:unka|uska|inka|inke|inaka|their|his|her)\s+(?:koi\s+)?(?:song|songs|gaana|gana|music)"
        r"(?:\s+(?:chalao|chalo|cahalo|bajao|play\s+karo|play))?",
        cleaned,
        re.I,
    )
    if follow_up:
        if context is None or not context.last_subject:
            return ParsedAutomationCommand("missing_media_context")
        query = f"{context.last_subject} songs"
        context.remember_media(query)
        return ParsedAutomationCommand("play_youtube", {"query": query})

    match = re.fullmatch(
        r"(?:open\s+)?youtube(?:\s+(?:and|aur|par|pe))?\s+(?:play|chalao|bajao)\s+(.+)",
        cleaned,
        re.I,
    )
    if match:
        query = match.group(1).strip()
        if context is not None:
            context.remember_media(query)
        return ParsedAutomationCommand("play_youtube", {"query": query})

    match = re.fullmatch(
        r"(?:youtube\s+)?(?:kholkar|open\s+karke)\s+(.+?)\s+(?:chalao|bajao|play\s+karo)",
        cleaned,
        re.I,
    )
    if match:
        query = match.group(1).strip()
        if context is not None:
            context.remember_media(query)
    # Video jump / seek command e.g. "gaane ko 2 minute par le jao", "video ko 1:30 par jump karo", "10 second aage karo"
    jump_match = re.search(
        r"(?:(?:gaana|gana|video|song|track)\s+(?:ko\s+)?)?(\d+:\d+|\d+\s*(?:minutes?|mins?|minut|seconds?|secs?|ghante?|hours?)|start|shuru|middle|beech\s+me|10s\s*forward|forward|aage|backward|peeche|10s\s*backward|\d+0%)\s*(?:par\s+|pe\s+)?(?:le\s+jao|jump\s+karo|seek\s+karo|karo|chalao|set\s+karo)",
        cleaned,
        re.I,
    )
    if jump_match and ("par" in cleaned or "pe" in cleaned or "jump" in cleaned or "seek" in cleaned or "le jao" in cleaned or "forward" in cleaned or "backward" in cleaned or "aage" in cleaned or "peeche" in cleaned):
        return ParsedAutomationCommand("jump_to_video_time", {"timestamp": jump_match.group(1).strip()})

    # Media key controls e.g. "pause gaana", "next song", "agla gaana", "gaana roko", "stop", "chalu karo", "play karo"
    if re.fullmatch(r"(?:pause(?:\s+(?:the\s+)?(?:song|music|gaana|gana|video))?|gaana\s+(?:roko|pause\s*karo)|video\s+(?:roko|pause\s*karo)|song\s+pause(?:\s*karo)?|stop\s+(?:the\s+)?(?:music|song|gaana|video)|(?:gaana|video|music)\s+stop(?:\s*karo)?|stop|स्टॉप)", lower):
        if "stop" in lower or "स्टॉप" in lower:
            return ParsedAutomationCommand("trigger_media_key", {"key": "stop"})
        return ParsedAutomationCommand("trigger_media_key", {"key": "play_pause"})
    if re.fullmatch(r"(?:play(?:\s+(?:the\s+)?(?:song|music|gaana|gana|video))?|gaana\s+(?:chalu\s*karo|play\s*karo|chalao)|video\s+(?:chalu\s*karo|play\s*karo)|song\s+play(?:\s*karo)?|chalu\s+karo|fir\s+se\s+(?:play|chalu)\s*karo|resume(?:\s+music)?)", lower):
        return ParsedAutomationCommand("trigger_media_key", {"key": "play_pause"})
    if re.fullmatch(r"(?:next(?:\s+(?:the\s+)?(?:song|music|gaana|gana|track))?|agla\s+(?:gaana|gana|song)|song\s+next(?:\s*karo)?)", lower):
        return ParsedAutomationCommand("trigger_media_key", {"key": "next"})
    if re.fullmatch(r"(?:prev(?:ious)?(?:\s+(?:the\s+)?(?:song|music|gaana|gana|track))?|pichhla\s+(?:gaana|gana|song)|purana\s+gaana)", lower):
        return ParsedAutomationCommand("trigger_media_key", {"key": "previous"})

    # Generic or curated Hindi/English music requests:
    # "koi achha gaana chalao", "gana bajao", "song play karo", "koi lofi song chala do", "kuch mast gaana bajao"
    music_generic = re.fullmatch(
        r"(?:please\s+|zara\s+|kripya\s+)?(?:play\s+|chalao\s+|chalo\s+|bajao\s+|bajaao\s+|lagao\s+|lagaao\s+|sunao\s+|sunaao\s+)?"
        r"(?:koi\s+|kuch\s+|ek\s+|koyi\s+)?"
        r"(?:achha|accha|acha|badhiya|mast|hit|top|latest|romantic|sad|lofi|punjabi|party|new|purana|purane|retro)?\s*"
        r"(?:sa\s+|se\s+)?"
        r"(?:song|songs|gana|gaana|gaane|gane|geet|music|track|video|video\s+song)\s*"
        r"(?:chalao|chalo|bajao|bajaao|lagao|lagaao|sunao|sunaao|play\s+karo|play\s+kar\s+do|play)?",
        cleaned,
        re.I,
    )
    if music_generic:
        if context is not None:
            context.remember_media(cleaned)
        return ParsedAutomationCommand("play_youtube", {"query": cleaned})

    # "Arijit Singh ka gana chalao", "Kesariya song play karo", "Diljit Dosanjh ke gaane sunao"
    song_pattern = re.fullmatch(
        r"(.+?)\s+(?:ka|ke|ki)?\s*(?:song|songs|gana|gaana|gaane|gane|music|track)\s*(?:chalao|bajao|bajaao|lagao|sunao|play\s+karo|play\s+kar\s+do|play)",
        cleaned,
        re.I,
    )
    if song_pattern:
        subject = song_pattern.group(1).strip()
        query = f"{subject} songs"
        if context is not None:
            context.remember_media(query)
        return ParsedAutomationCommand("play_youtube", {"query": query})

    # Contextual In-App Search (e.g., "is par Arijit Singh live song search karo", "ispe pagal dhoondo", "isme X search karo", "is tab me X search karo")
    in_app_match = re.fullmatch(
        r"(?:is\s+par|ispe|isme|is\s+me|yahan|yahi|is\s+tab\s+me|is\s+window\s+me)\s+(?:search\s+(?:karo|kar\s+do)?|dhoondo|dhundo|khojo)?\s*(.+?)(?:\s+(?:search\s*(?:karo|kar\s+do)?|dhoondo|dhundo|khojo))?",
        cleaned,
        re.I,
    )
    if in_app_match:
        query_val = in_app_match.group(1).strip()
        if query_val and not any(kw == query_val.casefold() for kw in {"karo", "kar do", "dhoondo", "dhundo", "khojo"}):
            return ParsedAutomationCommand("search_in_active_app", {"query": query_val})

    match = re.fullmatch(r"(?:google\s+search|search\s+(?:on\s+)?google(?:\s+for)?)\s+(.+)", cleaned, re.I)
    if match:
        return ParsedAutomationCommand("search_google", {"query": match.group(1).strip()})

    yt_match = re.fullmatch(
        r"(?:(?:open\s+)?youtube(?:\s+(?:par|pe|me|mein))?\s+(?:search\s+(?:karo|kar\s+do)?|dhoondo|dhundo|khojo)\s+(.+)|"
        r"(?:open\s+)?youtube\s+(?:par|pe|me|mein)\s+(.+?)(?:\s+(?:search\s*(?:karo|kar\s+do)?|dhoondo|dhundo|khojo))|"
        r"(?:youtube\s+search|search\s+(?:on\s+)?youtube(?:\s+for)?)\s+(.+))",
        cleaned,
        re.I,
    )
    if yt_match:
        yt_query = (yt_match.group(1) or yt_match.group(2) or yt_match.group(3)).strip()
        return ParsedAutomationCommand("search_youtube", {"query": yt_query})
    match = re.fullmatch(r"play\s+(.+?)\s+on\s+youtube", cleaned, re.I)
    if match:
        query = match.group(1).strip()
        if context is not None:
            context.remember_media(query)
        return ParsedAutomationCommand("play_youtube", {"query": query})
    match = re.fullmatch(r"play\s+(.+)", cleaned, re.I)
    if match:
        query = match.group(1).strip()
        if context is not None:
            context.remember_media(query)
        return ParsedAutomationCommand("play_youtube", {"query": query})

    match = re.fullmatch(
        r"(?:spotify(?:\s+par|\s+pe)?\s+)(?:search|play|chalao)\s+(.+)",
        cleaned,
        re.I,
    )
    if match:
        query = match.group(1).strip()
        if context is not None:
            context.remember_media(query)
        return ParsedAutomationCommand("search_spotify", {"query": query})

    # Ordinal selection e.g. "2nd wala chala do", "second wala play karo", "doosra gaana bajao"
    if parse_ordinal_selection(cleaned) is not None:
        return ParsedAutomationCommand("play_youtube", {"query": cleaned})

    # Screen vision e.g. "screen dekho", "screen par kya chal raha hai", "screen analyze karo"
    if re.search(r"\b(?:screen|display|monitor)\s*(?:par\s*kya\s*(?:hai|chal\s*raha\s*hai)|dekho|dekh|check\s*karo|analyze|padho|batao)\b|\b(?:kya\s*chal\s*raha\s*hai\s*screen\s*par|screen\s*read\s*karo)\b", cleaned, re.I):
        args: dict[str, Any] = {"prompt": cleaned}
        if re.search(r"\b(?:ollama|local|offline|moondream)\b", cleaned, re.I):
            args["provider"] = "ollama"
        return ParsedAutomationCommand("analyze_screen", args)

    # Product price check e.g. "iPhone 15 ka price batao", "Sony headphones ka price kya hai"
    price_match = re.fullmatch(
        r"(.+?)\s+(?:ka|ki|ke)?\s*(?:price|keemat|rate|daam|cost)\s*(?:kya\s+hai|batao|search\s+karo|check\s+karo)?",
        cleaned,
        re.I,
    )
    if price_match:
        prod = price_match.group(1).strip()
        if prod and not any(kw in prod.casefold() for kw in {"kya", "ye", "yeh"}):
            return ParsedAutomationCommand("search_product_prices", {"query": prod})

    # Scroll screen commands e.g. "scroll down", "neeche scroll karo", "scroll up", "upar scroll karo"
    if re.search(r"\b(?:scroll\s*down|neeche\s*scroll(?:\s*karo)?|thoda\s*neeche(?:\s*karo)?|niche\s*scroll(?:\s*karo)?|scroll\s*karo)\b", cleaned, re.I):
        return ParsedAutomationCommand("scroll_screen", {"direction": "down"})
    if re.search(r"\b(?:scroll\s*up|upar\s*scroll(?:\s*karo)?|thoda\s*upar(?:\s*karo)?)\b", cleaned, re.I):
        return ParsedAutomationCommand("scroll_screen", {"direction": "up"})

    # Click screen element commands e.g. "click first link", "pehli link click karo", "click 2nd link"
    if re.search(r"\b(?:click\s+(?:on\s+)?(?:the\s+)?(?:first|1st|pehli)\s+link|first\s+link\s+(?:par\s+)?click(?:\s*karo)?|pehli\s+link\s+(?:kholo|click\s*karo)|click\s+first\s+link)\b", cleaned, re.I):
        return ParsedAutomationCommand("click_screen_element", {"target": "first_link"})
    if re.search(r"\b(?:click\s+(?:on\s+)?(?:the\s+)?(?:second|2nd|doosri)\s+link|second\s+link\s+(?:par\s+)?click(?:\s*karo)?|doosri\s+link\s+(?:kholo|click\s*karo))\b", cleaned, re.I):
        return ParsedAutomationCommand("click_screen_element", {"target": "second_link"})
    if re.search(r"\b(?:click\s+(?:on\s+)?(?:the\s+)?(?:third|3rd|teesri)\s+link|third\s+link\s+(?:par\s+)?click(?:\s*karo)?|teesri\s+link\s+(?:kholo|click\s*karo))\b", cleaned, re.I):
        return ParsedAutomationCommand("click_screen_element", {"target": "third_link"})
    if re.search(r"\b(?:click\s+(?:center|middle|beech\s+me)|screen\s+par\s+click\s*karo)\b", cleaned, re.I):
        return ParsedAutomationCommand("click_screen_element", {"target": "center"})

    # Browser navigation commands e.g. "back jao", "refresh karo", "tab close karo", "new tab kholo"
    if re.search(r"\b(?:browser\s+)?(?:back\s+jao|piche\s+jao|go\s+back|peeche\s+karo)\b", cleaned, re.I):
        return ParsedAutomationCommand("control_browser_action", {"action": "back"})
    if re.search(r"\b(?:browser\s+)?(?:forward\s+jao|aage\s+jao|go\s+forward)\b", cleaned, re.I):
        return ParsedAutomationCommand("control_browser_action", {"action": "forward"})
    if re.search(r"\b(?:refresh\s*karo|reload\s*karo|page\s*refresh|refresh\s*page)\b", cleaned, re.I):
        return ParsedAutomationCommand("control_browser_action", {"action": "refresh"})
    if re.search(r"\b(?:tab\s*close\s*karo|tab\s*band\s*karo|close\s*tab)\b", cleaned, re.I):
        return ParsedAutomationCommand("control_browser_action", {"action": "close_tab"})
    if re.search(r"\b(?:new\s*tab\s*kholo|open\s*new\s*tab|nayi\s*tab)\b", cleaned, re.I):
        return ParsedAutomationCommand("control_browser_action", {"action": "new_tab"})

    # Lock workstation / screen e.g. "lock pc", "screen lock karo", "pc lock karo"
    if re.fullmatch(r"(?:lock\s+(?:the\s+)?(?:pc|screen|computer|workstation)|(?:pc|screen|computer)\s+lock(?:\s+karo|\s+kar\s+do)?)", lower):
        return ParsedAutomationCommand("lock_workstation")

    # Clipboard commands e.g. "clipboard me kya hai", "read clipboard", "clipboard padho"
    if re.fullmatch(r"(?:read\s+clipboard|get\s+clipboard|clipboard\s+(?:padho|read\s*karo|me\s*kya\s*hai|dekho))", lower):
        return ParsedAutomationCommand("get_clipboard_text")
    copy_match = re.fullmatch(r"(?:copy\s+(?:to\s+clipboard\s+)?|clipboard\s+me\s+copy\s+karo\s+)(.+)", cleaned, re.I)
    if copy_match:
        return ParsedAutomationCommand("set_clipboard_text", {"text": copy_match.group(1).strip()})

    # Screenshot command e.g. "screenshot lo", "take screenshot", "screen capture karo"
    if re.fullmatch(r"(?:take\s+(?:a\s+)?screenshot|screenshot\s+(?:lo|le\s+lo|save\s*karo)|screen\s+capture(?:\s+karo)?)", lower):
        return ParsedAutomationCommand("save_screenshot")

    # Quick note command e.g. "note likho meeting at 5", "save note shopping list"
    note_match = re.fullmatch(r"(?:save\s+note|note\s+likho|note\s+banao|write\s+note)\s+(?:title\s*[:=]\s*)?(.+?)(?:\s*[:,-]\s*(.+))?$", cleaned, re.I)
    if note_match:
        t = note_match.group(1).strip()
        c = note_match.group(2).strip() if note_match.group(2) else t
        return ParsedAutomationCommand("save_quick_note", {"title": t, "content": c})

    # Local file search e.g. "search file report", "file dhoondho project.py"
    file_search_match = re.fullmatch(r"(?:search\s+file|find\s+file|file\s+(?:dhoondho|search\s*karo|khojo))\s+(.+)", cleaned, re.I)
    if file_search_match:
        return ParsedAutomationCommand("search_local_files", {"query": file_search_match.group(1).strip()})

    # YouTube Video AI Summarizer e.g. "is video ka summary batao https://...", "summarize video Kesariya"
    sum_match = re.fullmatch(r"(?:summarize(?:\s+(?:the\s+)?(?:video|youtube\s+video))?|(?:(?:is|ye|yeh|this)\s+)?(?:video|youtube\s+video)?\s*(?:ka\s+)?(?:summary(?:\s+(?:batao|do|karo))?|summarize|explain(?:\s+karo)?))\s+(.+)", cleaned, re.I)
    if sum_match:
        return ParsedAutomationCommand("summarize_youtube_video", {"url_or_name": sum_match.group(1).strip()})

    # YouTube Comments & Sentiment Analyzer e.g. "is video ke comments analyze karo https://...", "comments dekho https://..."
    com_match = re.fullmatch(r"(?:analyze\s+(?:the\s+)?(?:comments|comment\s+section)?|(?:(?:is|ye|yeh|this)\s+)?(?:video|youtube\s+video)?\s*(?:ke\s+)?(?:comments|comment\s+section)?\s*(?:analyze(?:\s+karo)?|dekho|padho|check\s*karo)|log\s+kya\s+bol\s+rahe\s+hain\s+(?:is\s+video\s+par)?)\s+(.+)", cleaned, re.I)
    if com_match:
        return ParsedAutomationCommand("analyze_youtube_comments", {"url_or_name": com_match.group(1).strip()})

    # YouTube Video Details e.g. "video details https://...", "video metadata https://..."
    det_match = re.fullmatch(r"(?:(?:is|ye|yeh|this)\s+)?(?:video\s+details|details\s+(?:of\s+)?video|video\s+metadata)\s+(.+)", cleaned, re.I)
    if det_match:
        return ParsedAutomationCommand("get_youtube_video_details", {"url_or_name": det_match.group(1).strip()})

    # Keyboard key press commands e.g. "press enter", "enter dabao", "press tab", "press escape"
    key_match = re.fullmatch(r"(?:press|dabao|hit)\s+(enter|tab|esc|escape|space|backspace|pagedown|pageup)", cleaned, re.I)
    if key_match:
        return ParsedAutomationCommand("press_keyboard_key", {"key": key_match.group(1).lower()})

    # Level 4 Background tasks
    if re.search(r"\b(?:check\s+background\s+tasks|background\s+tasks(?:\s+status)?|tasks\s+status|background\s+updates)\b", cleaned, re.I):
        return ParsedAutomationCommand("check_background_tasks", {})

    # Token usage query e.g. "kitne token use hue", "token usage batao", "kitne token ude"
    if re.search(r"\b(?:tokens?)\b.*\b(?:kitne|kitna|use|huye|ude|kharch|consumption|count|batao|lage)\b|\b(?:kitne|kitna|total|kya)\b.*\b(?:tokens?)\b", cleaned, re.I):
        return ParsedAutomationCommand("get_token_usage", {})

    bg_m = re.match(r"^(?:background\s+me|run\s+in\s+background)\s+(.+)", cleaned, re.I)
    if bg_m:
        sub_cmd = bg_m.group(1).strip()
        return ParsedAutomationCommand("start_background_task", {"task_name": sub_cmd[:30], "task_command": sub_cmd})

    # Level 5 Desktop GUI inspect & control
    if re.search(r"\b(?:inspect\s+(?:active\s+)?window|desktop\s+inspect(?:\s*karo)?|window\s+controls(?:\s+dikhao)?)\b", cleaned, re.I):
        return ParsedAutomationCommand("inspect_desktop_window", {})

    desk_click_m = re.match(r"^(?:desktop|window)\s+(?:par|pe|me)\s+(.+?)\s+(?:par\s+)?click\s*karo$", cleaned, re.I)
    if desk_click_m:
        return ParsedAutomationCommand("desktop_control_action", {"action": "click", "target": desk_click_m.group(1).strip()})

    match = re.fullmatch(
        r"(.+?)\s+(?:song|gaana|gana)\s+(?:chalao|chalo|cahalo|bajao|play\s+karo)",
        cleaned,
        re.I,
    )
    if match:
        query = f"{match.group(1).strip()} song"
        if context is not None:
            context.remember_media(query)
        return ParsedAutomationCommand("play_youtube", {"query": query})

    match = re.fullmatch(r"(?:please\s+)?(?:open|launch|khol(?:o|iye)?)\s+(.+)", cleaned, re.I)
    if match:
        target = match.group(1).strip()
        normalized = re.sub(r"^(?:the\s+)?(?:app|application|website|site)\s+", "", target, flags=re.I).strip()
        target_key = normalized.casefold()
        if target_key in APPLICATION_ALIASES:
            return ParsedAutomationCommand("open_application", {"app_name": normalized})
        if target_key in WEBSITE_ALIASES or "." in normalized or "://" in normalized:
            return ParsedAutomationCommand("open_website", {"url_or_name": normalized})
        if re.match(r"^(?:the\s+)?(?:app|application)\s+", target, re.I):
            return ParsedAutomationCommand("open_application", {"app_name": normalized})
        # Try dynamic app resolution
        return ParsedAutomationCommand("open_application", {"app_name": normalized})

    # Suffix pattern match e.g. "chrome open karo", "notepad kholo", "whatsapp open kar do", "instagram open kar do"
    match = re.fullmatch(
        r"(.+?)\s+(?:ko\s+)?(?:open|launch|khol(?:o|iye)?)(?:\s+(?:kar\s+do|karo|do|karna))?",
        cleaned,
        re.I,
    )
    if match:
        target = match.group(1).strip()
        normalized = re.sub(r"^(?:the\s+)?(?:app|application|website|site)\s+", "", target, flags=re.I).strip()
        target_key = normalized.casefold()
        if target_key in APPLICATION_ALIASES:
            return ParsedAutomationCommand("open_application", {"app_name": normalized})
        if target_key in WEBSITE_ALIASES or "." in normalized or "://" in normalized:
            return ParsedAutomationCommand("open_website", {"url_or_name": normalized})
        return ParsedAutomationCommand("open_application", {"app_name": normalized})

    # Level 3 Vision Browser commands e.g. "page par add to cart click karo", "browser me close popup karo", "modal close karo"
    v_goal_m = re.fullmatch(
        r"(?:(?:webpage|page|browser|site)\s+(?:par|pe|mein|me)\s+)(.+?)(?:\s+(?:par\s+)?(?:visually\s+click\s+karo|vision\s+click\s+karo|click\s+karo|click\s+kar\s+do|click|close\s+karo|band\s+karo|dismiss\s+karo|karo|kar\s+do))",
        cleaned,
        re.I,
    )
    if not v_goal_m:
        v_goal_m = re.fullmatch(
            r"(.+?)\s+(?:visually\s+click\s+karo|vision\s+click\s+karo)",
            cleaned,
            re.I,
        )
    if not v_goal_m and any(w in cleaned.lower() for w in ["popup", "modal", "banner"]):
        v_popup = re.fullmatch(
            r"(?:(?:browser|page|webpage)\s+(?:me|par)\s+)?(?:close|dismiss|band\s+karo)\s+(popup|modal|banner)|(?:popup|modal|banner)\s+(?:close\s+karo|dismiss\s+karo|band\s+karo)",
            cleaned,
            re.I,
        )
        if v_popup:
            return ParsedAutomationCommand("vision_browser_goal", {"goal": "Close popup"})
    if v_goal_m:
        matched_target = v_goal_m.group(1).strip()
        if matched_target:
            return ParsedAutomationCommand("vision_browser_goal", {"goal": matched_target})

    # E-Commerce Multi-Cart natural command e.g. "Amazon aur Flipkart par 40000 ke neeche laptop cart me add karo"
    ecom_m = re.search(
        r"(?:(?:amazon|flipkart)(?:\s*(?:aur|and|,)\s*(?:amazon|flipkart))?\s*(?:par|pe)?\s*)?"
        r"(?:(?:under|below|less\s+than|ke\s+neeche|tak\s+ka|tak\s+ke)?\s*(?:rs\.?|inr|₹)?\s*(\d+k|\d{3,7})\s*(?:ke\s+neeche|tak\s+ka|tak)?\s*)?"
        r"(.+?)\s*(?:ko\s+)?(?:cart\s+me\s+add\s*(?:karo|kar\s+do)|add\s+to\s+cart\s*(?:karo|kar\s+do)?|cart\s+me\s+daalo|cart\s+karo)",
        cleaned,
        re.I,
    )
    if ecom_m:
        raw_price = ecom_m.group(1)
        prod = ecom_m.group(2).strip() if ecom_m.group(2) else ""
        price_val = None
        if raw_price:
            raw_p = raw_price.lower().replace("k", "000")
            try:
                price_val = float(raw_p)
            except ValueError:
                pass
        platforms = []
        if "amazon" in cleaned.lower():
            platforms.append("amazon")
        if "flipkart" in cleaned.lower():
            platforms.append("flipkart")
        if not platforms:
            platforms = ["amazon", "flipkart"]
        if prod:
            clean_p = re.sub(r"\b(?:amazon|flipkart|aur|and|par|pe|me|mein)\b", " ", prod, flags=re.I).strip()
            clean_p = " ".join(clean_p.split())
            if clean_p:
                args: dict[str, Any] = {"product": clean_p, "platforms": platforms}
                if price_val:
                    args["max_price"] = price_val
                return ParsedAutomationCommand("ecommerce_multi_cart", args)

    # Screen Vision Analysis (Local Ollama / Moondream or Cloud Gemini)
    if re.fullmatch(
        r"(?:please\s+|zara\s+)?(?:(?:ollama|local|offline|moondream)\s+(?:vision\s+(?:se\s+)?)?screen\s+(?:dekh(?:o|iye)?|analyze\s*karo|check\s*karo|read\s*karo|inspect\s*karo)|"
        r"screen\s+(?:ko\s+)?(?:ollama|local|offline|moondream)\s+(?:vision\s+se\s+)?(?:dekh(?:o|iye)?|analyze\s*karo)|"
        r"(?:ollama|local|moondream)\s+screen\s+dekho)",
        cleaned,
        re.I,
    ):
        return ParsedAutomationCommand("analyze_screen", {"prompt": "Describe what is currently visible on the screen using local ollama vision.", "provider": "ollama"})

    if re.fullmatch(
        r"(?:please\s+|zara\s+)?(?:screen\s+(?:dekh(?:o|iye)?|analyze\s*karo|check\s*karo|read\s*karo|inspect\s*karo)|"
        r"(?:check|analyze|read|inspect)\s+screen|screen\s+par\s+kya\s+hai(?:\s+dekho)?|"
        r"kya\s+chal\s+raha\s+hai\s+screen\s+par|desktop\s+dekho|screen\s+par\s+kya\s+hai)",
        cleaned,
        re.I,
    ):
        return ParsedAutomationCommand("analyze_screen", {"prompt": "Describe what is currently visible on the screen, active window, and any key information or errors."})

    screen_prompt_m = re.fullmatch(
        r"(?:screen\s+(?:par|pe)\s+dekho\s+(?:ki\s+)?|screen\s+analyze\s+karke\s+batao\s+(?:ki\s+)?)(.+)",
        cleaned,
        re.I,
    )
    if screen_prompt_m:
        return ParsedAutomationCommand("analyze_screen", {"prompt": screen_prompt_m.group(1).strip()})

    # Screen Element AI Click
    screen_click_m = re.fullmatch(
        r"(?:screen\s+(?:par|pe)\s+)?(?:click(?:\s+on)?\s+|daba(?:o|iye)?\s+)?(.+?)\s+(?:par\s+|pe\s+)?(?:click\s*karo|click\s*kar\s*do|daba\s*do|click)",
        cleaned,
        re.I,
    )
    if not screen_click_m:
        screen_click_m = re.fullmatch(
            r"(?:screen\s+(?:par|pe)\s+)?(?:click(?:\s+on)?|daba(?:o|iye)?)\s+(.+)",
            cleaned,
            re.I,
        )
    if (
        screen_click_m
        and ("screen" in cleaned.lower() or "click" in cleaned.lower() or "daba" in cleaned.lower())
        and not any(w in cleaned.lower() for w in ["youtube", "spotify", "google", "browser", "url", "http"])
    ):
        target = screen_click_m.group(1).strip()
        if target and len(target) < 60:
            return ParsedAutomationCommand("click_screen_element", {"target": target})

    # Screen Element AI Hover (useful for dropdown menus)
    screen_hover_m = re.fullmatch(
        r"(?:screen\s+(?:par|pe)\s+)?(.+?)\s+(?:par\s+|pe\s+)?hover(?:\s*karo)?",
        cleaned,
        re.I,
    )
    if screen_hover_m and not any(w in cleaned.lower() for w in ["youtube", "spotify", "google", "browser"]):
        target = screen_hover_m.group(1).strip()
        if target and len(target) < 60:
            return ParsedAutomationCommand("hover_screen_element", {"target": target})

    # Screenshot Capture
    if re.fullmatch(
        r"(?:please\s+)?(?:take\s+(?:a\s+)?screenshot|screenshot\s+(?:lo|le\s+lo|save\s*karo|khincho))",
        cleaned,
        re.I,
    ):
        return ParsedAutomationCommand("save_screenshot", {})

    # Video Summarize / Agentic Video Analysis
    video_sum_m = re.fullmatch(
        r"(?:please\s+)?(?:summarize|analyze|explain)\s+(?:this\s+|the\s+)?(?:video|podcast|recording)(?:\s+(.+))?|"
        r"(?:video|podcast)\s+(?:summarize|analyze|explain|samjhao)(?:\s+karo)?(?:\s+(.+))?",
        cleaned,
        re.I,
    )
    if video_sum_m:
        query_v = (video_sum_m.group(1) or video_sum_m.group(2) or "").strip()
        if not query_v and context and context.last_media_query:
            query_v = context.last_media_query
        if query_v:
            return ParsedAutomationCommand("summarize_youtube_video", {"url_or_name": query_v})

def execute_computer_task(task: str) -> AutomationResult:
    """Execute an autonomous multi-step visual UI workflow on desktop using Computer Use."""
    cleaned = str(task).strip()
    if not cleaned:
        return _failure("execute_computer_task", "Captain, task description empty hai.", "empty_task")
    try:
        from computer_use_agent import ComputerUseAgent
        from config import load_settings
        settings = load_settings()
        client = _get_cached_genai_client(settings.api_key)
        agent = ComputerUseAgent(gemini_client=client, model=settings.model, max_steps=settings.computer_use_max_steps)
        res = agent.run_goal(cleaned)
        return AutomationResult(
            success=bool(res.get("success")),
            action="execute_computer_task",
            message=res.get("message", "Task complete ho gaya."),
            data=res,
            error=res.get("error"),
        )
    except Exception as exc:
        LOGGER.warning("Computer Use execution error: %s", exc)
        return _failure("execute_computer_task", f"Captain, Computer Use me error aaya: {exc}", "computer_use_error")


def search_location_or_places(query: str, location: str = "") -> AutomationResult:
    """Find nearby places, restaurants, hotels, routes, or directions via Google Maps Grounding."""
    cleaned = str(query).strip()
    if not cleaned:
        return _failure("search_location_or_places", "Captain, location query empty hai.", "empty_query")
    full_q = f"{cleaned} {location}".strip() if location else cleaned
    try:
        from config import load_settings
        from realtimeinfo import RealtimeInfoService
        settings = load_settings()
        service = RealtimeInfoService(settings)
        resp = service.answer(full_q)
        return AutomationResult(
            success=resp.error is None,
            action="search_location_or_places",
            message=resp.display_text,
            data={"speech": resp.speech_text, "sources": [s.__dict__ for s in resp.sources], "topic": resp.topic},
            error=resp.error,
        )
    except Exception as exc:
        LOGGER.warning("Location/Maps search error: %s", exc)
        return _failure("search_location_or_places", f"Captain, location search nahi ho saki: {exc}", "maps_error")


def index_document_or_folder(path: str) -> AutomationResult:
    """Index a file or folder into the personal vector knowledge base for semantic retrieval."""
    cleaned = str(path).strip()
    if not cleaned:
        return _failure("index_document_or_folder", "Captain, file/folder path empty hai.", "empty_path")
    try:
        from pathlib import Path
        from config import load_settings
        from vector_memory import VectorEmbedder, VectorMemoryStore
        p = Path(cleaned).expanduser().resolve()
        settings = load_settings()
        client = _get_cached_genai_client(settings.api_key)
        embedder = VectorEmbedder(gemini_client=client, model_name=settings.embedding_model)
        store = VectorMemoryStore(settings.memory_database_path, embedder=embedder)

        if p.is_file():
            res = store.index_file(p)
        elif p.is_dir():
            res = store.index_directory(p)
        else:
            return _failure("index_document_or_folder", f"Captain, path '{cleaned}' exist nahi karta.", "path_not_found")

        return AutomationResult(
            success=bool(res.get("success")),
            action="index_document_or_folder",
            message=ensure_captain_address(res.get("message", "Document index ho gaya.")),
            data=res,
            error=res.get("error"),
        )
    except Exception as exc:
        LOGGER.warning("Document indexing error: %s", exc)
        return _failure("index_document_or_folder", f"Captain, document indexing me error aaya: {exc}", "index_error")


def search_knowledge_base(query: str) -> AutomationResult:
    """Retrieve relevant excerpts from Captain's personal indexed knowledge base."""
    cleaned = str(query).strip()
    if not cleaned:
        return _failure("search_knowledge_base", "Captain, search query empty hai.", "empty_query")
    try:
        from config import load_settings
        from vector_memory import VectorEmbedder, VectorMemoryStore
        settings = load_settings()
        client = _get_cached_genai_client(settings.api_key)
        embedder = VectorEmbedder(gemini_client=client, model_name=settings.embedding_model)
        store = VectorMemoryStore(settings.memory_database_path, embedder=embedder)
        if hasattr(store, "hybrid_search_knowledge_base"):
            results = store.hybrid_search_knowledge_base(cleaned, limit=4)
        else:
            results = store.search_knowledge_base(cleaned, limit=4)
        if not results:
            return AutomationResult(
                success=True,
                action="search_knowledge_base",
                message=f"Captain, '{cleaned}' ke baare mein indexed documents mein koi match nahi mila.",
                data={"results": []},
            )

        msg_lines = [f"Captain, aapke indexed notes/documents se '{cleaned}' ke matching excerpts mil gaye hain:"]
        for idx, r in enumerate(results, 1):
            excerpt = r["content"][:220].strip().replace("\n", " ")
            msg_lines.append(f"{idx}. [{r['file_name']}] (similarity: {int(r['similarity']*100)}%):\n   \"{excerpt}...\"")

        full_msg = "\n\n".join(msg_lines)
        return AutomationResult(
            success=True,
            action="search_knowledge_base",
            message=full_msg,
            data={"results": results},
        )
    except Exception as exc:
        LOGGER.warning("Knowledge base search error: %s", exc)
        return _failure("search_knowledge_base", f"Captain, knowledge base search nahi ho saki: {exc}", "search_error")


_AUTOMATION_FUNCTIONS = {
    "execute_computer_task": execute_computer_task,
    "execute_terminal_command": execute_terminal_command,
    "search_location_or_places": search_location_or_places,
    "index_document_or_folder": index_document_or_folder,
    "search_knowledge_base": search_knowledge_base,
    "open_website": open_website,
    "search_google": search_google,
    "search_youtube": search_youtube,
    "search_spotify": search_spotify,
    "play_spotify": play_spotify,
    "play_youtube": play_youtube,
    "play_mood_music": play_mood_music,
    "search_youtube_live": search_youtube_live,
    "jump_to_video_time": jump_to_video_time,
    "get_live_news": get_live_news,
    "add_to_favorites": add_to_favorites,
    "play_favorites": play_favorites,
    "save_captain_fact": save_captain_fact,
    "save_captain_lesson": save_captain_lesson,
    "recall_captain_memory": recall_captain_memory,
    "prepare_whatsapp_message": prepare_whatsapp_message,
    "send_whatsapp_message": send_whatsapp_message,
    "search_whatsapp_contact": search_whatsapp_contact,
    "make_phone_call": make_phone_call,
    "open_application": open_application,
    "close_application": close_application,
    "get_current_time": get_current_time,
    "get_current_date": get_current_date,
    "get_system_status": get_system_status,
    "set_volume": set_volume,
    "change_volume": change_volume,
    "set_mute": set_mute,
    "set_brightness": set_brightness,
    "analyze_screen": analyze_screen_content,
    "analyze_screen_ollama": analyze_screen_with_ollama,
    "search_product_prices": search_product_prices,
    "ecommerce_multi_cart": ecommerce_multi_cart,
    "scroll_screen": scroll_screen,
    "click_screen_element": click_screen_element,
    "hover_screen_element": hover_screen_element,
    "control_browser_action": control_browser_action,
    "press_keyboard_key": press_keyboard_key,
    "trigger_media_key": trigger_media_key,
    "lock_workstation": lock_workstation,
    "search_in_active_app": search_in_active_app,
    "search_local_files": search_local_files,
    "get_clipboard_text": get_clipboard_text,
    "set_clipboard_text": set_clipboard_text,
    "save_screenshot": save_screenshot,
    "save_quick_note": save_quick_note,
    "browser_navigate": browser_navigate,
    "browser_click_selector": browser_click_selector,
    "browser_fill_input": browser_fill_input,
    "browser_extract_text": browser_extract_text,
    "vision_browser_goal": vision_browser_goal,
    "start_background_task": start_background_task,
    "check_background_tasks": check_background_tasks,
    "get_token_usage": get_token_usage,
    "desktop_control_action": desktop_control_action,
    "inspect_desktop_window": inspect_desktop_window,
    "summarize_youtube_video": summarize_youtube_video,
    "analyze_video": summarize_youtube_video,
    "analyze_local_video": analyze_local_video,
    "analyze_youtube_comments": analyze_youtube_comments,
    "get_youtube_video_details": get_youtube_video_details,
    "missing_media_context": _missing_media_context,
}


def execute_automation_command(command: ParsedAutomationCommand) -> AutomationResult:
    """Execute only a parser-produced, allowlisted automation command."""

    if command.intent in {"payment", "buy_now", "checkout", "place_order"} or any(
        is_payment_or_checkout_intent(str(v)) for v in command.arguments.values()
    ):
        return AutomationResult(
            False,
            "payment_blocked",
            ensure_captain_address(PAYMENT_BLOCKED_MESSAGE),
            {"intent": command.intent},
            error="payment_prohibited",
        )

    if command.intent == "confirmation_required":
        return confirmation_required_result(
            str(command.arguments.get("action", "important_system_setting")),
            str(command.arguments.get("request_text", "")),
        )
    function = _AUTOMATION_FUNCTIONS.get(command.intent)
    if function is None:
        return _failure("automation", "Automation intent allowlist mein nahi hai.", "intent_not_allowed")
    try:
        return function(**command.arguments)
    except TypeError as exc:
        return _failure(
            command.intent,
            "Automation arguments invalid hain.",
            "invalid_arguments",
            exception_type=type(exc).__name__,
        )


def looks_like_automation_request(text: str) -> bool:
    """Conservatively identify natural-language requests that may need a tool."""

    cleaned = str(text).strip()
    if not cleaned or cleaned.startswith("/"):
        return False
    return bool(
        re.search(
            r"\b(?:open|launch|start|bring\s+up|khol|kholo|chalao|play|"
            r"search|find|send|bhej|message|whats?app|whatapp|"
            r"volume|brightness|mute|unmute|system\s+status|"
            r"computer\s+status|current\s+time|current\s+date|"
            r"call|phone|dial|mobile\s*link|phone\s*link)\b",
            cleaned,
            re.I,
        )
    )


def parsed_command_from_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
) -> ParsedAutomationCommand | None:
    """Validate a model-selected function strictly against the local schema."""

    schema = next(
        (item for item in AUTOMATION_FUNCTION_SCHEMAS if item["name"] == name),
        None,
    )
    if schema is None or not isinstance(arguments, dict):
        return None
    parameters = schema.get("parameters", {})
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", ()))
    if not required.issubset(arguments) or set(arguments) - set(properties):
        return None

    validated: dict[str, Any] = {}
    for key, value in arguments.items():
        rule = properties.get(key, {})
        expected = rule.get("type")
        if expected == "string":
            if not isinstance(value, str) or not value.strip():
                return None
            candidate: Any = value.strip()
        elif expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            candidate = value
            if candidate < rule.get("minimum", candidate):
                return None
            if candidate > rule.get("maximum", candidate):
                return None
        elif expected in {"number", "float"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            candidate = float(value)
            if candidate < rule.get("minimum", candidate):
                return None
            if candidate > rule.get("maximum", candidate):
                return None
        elif expected == "array":
            if not isinstance(value, (list, tuple)):
                return None
            candidate = list(value)
        elif expected == "boolean":
            if not isinstance(value, bool):
                return None
            candidate = value
        else:
            return None
        if "enum" in rule and candidate not in rule["enum"]:
            return None
        validated[key] = candidate
    return ParsedAutomationCommand(name, validated)


def execute_automation_plan(
    commands: list[ParsedAutomationCommand] | tuple[ParsedAutomationCommand, ...],
    context: AutomationContext | None = None,
) -> AutomationResult | None:
    """Execute a bounded, prevalidated allowlist plan and report every step."""

    bounded = tuple(commands)
    if not bounded or len(bounded) > 4:
        return None
    if any(command.intent == "confirmation_required" for command in bounded):
        command = next(
            command
            for command in bounded
            if command.intent == "confirmation_required"
        )
        return execute_automation_command(command)

    results: list[AutomationResult] = []
    for command in bounded:
        result = execute_automation_command(command)
        results.append(result)
        if not result.success:
            break
        if context is not None:
            context.remember_command(command)
    if len(bounded) == 1:
        return results[0]

    successful = all(result.success for result in results) and len(results) == len(bounded)
    completed = len([result for result in results if result.success])
    messages = " ".join(result.message.strip() for result in results if result.message)
    return AutomationResult(
        success=successful,
        action="automation_sequence",
        message=(
            f"{messages} ({completed}/{len(bounded)} actions complete.)"
            if messages
            else f"{completed}/{len(bounded)} actions complete."
        ),
        data={
            "completed": completed,
            "total": len(bounded),
            "steps": [
                {
                    "action": result.action,
                    "success": result.success,
                    "error": result.error,
                }
                for result in results
            ],
        },
        error=None if successful else (results[-1].error if results else "sequence_failed"),
    )


def handle_automation_command(
    text: str,
    context: AutomationContext | None = None,
) -> AutomationResult | None:
    """Parse and execute one command or a bounded sequence of safe commands."""

    cleaned = str(text).strip()
    if is_payment_or_checkout_intent(cleaned):
        return AutomationResult(
            False,
            "payment_blocked",
            ensure_captain_address(PAYMENT_BLOCKED_MESSAGE),
            {"request": cleaned},
            error="payment_prohibited",
        )

    if context is not None and context.pending_confirmation is not None:
        if re.fullmatch(
            r"(?:confirm(?:\s+action)?|yes|yes\s+do\s+it|haan|ha|"
            r"kar\s+do|continue)",
            cleaned,
            re.I,
        ):
            command = context.pending_confirmation
            plan = context.pending_plan
            context.pending_confirmation = None
            context.pending_plan = ()
            context.pending_request = None
            if plan:
                return execute_automation_plan(plan, context)
            result = execute_automation_command(command)
            if result.success:
                context.remember_command(command)
            return result
        if re.fullmatch(
            r"(?:cancel(?:\s+action)?|no|nahi|mat\s+karo|stop)",
            cleaned,
            re.I,
        ):
            context.pending_confirmation = None
            context.pending_plan = ()
            context.pending_request = None
            return AutomationResult(
                True,
                "cancel_automation",
                "Pending action cancel kar di.",
            )
        context.pending_confirmation = None
        context.pending_plan = ()
        context.pending_request = None

    if context is not None and re.fullmatch(
        r"(?:do\s+it\s+again|repeat(?:\s+that)?|again|dobara(?:\s+karo)?|"
        r"phir\s+se(?:\s+karo)?)",
        cleaned,
        re.I,
    ):
        if context.last_command is None:
            return _failure(
                "repeat_automation",
                "Repeat karne ke liye koi previous automation action nahi hai.",
                "missing_previous_action",
            )
        return execute_automation_command(context.last_command)

    parts = [
        part.strip(" ,")
        for part in re.split(
            r"\s+(?:and\s+then|then|and|aur\s+phir|aur|phir)\s+",
            cleaned,
            flags=re.I,
        )
        if part.strip(" ,")
    ]
    if 2 <= len(parts) <= 4:
        commands: list[ParsedAutomationCommand] = []
        confirmation: tuple[ParsedAutomationCommand, str] | None = None
        for part in parts:
            command = parse_automation_command(part, context)
            if command is None:
                commands = []
                break
            if command.intent == "confirmation_required":
                confirmed = _confirmed_command_for_text(part)
                skip_confirmation = (
                    confirmed is not None
                    and confirmed.intent == "send_whatsapp_message"
                    and context is not None
                    and not context.confirm_whatsapp_send
                )
                if skip_confirmation:
                    commands.append(confirmed)
                    continue
                if confirmed is None or confirmation is not None:
                    result = execute_automation_command(command)
                    result.data["planned_steps"] = len(parts)
                    result.data["can_confirm"] = False
                    return result
                confirmation = (confirmed, part)
                commands.append(confirmed)
            else:
                commands.append(command)
        if len(commands) == len(parts):
            if confirmation is not None:
                confirmed, request_text = confirmation
                result = _confirmation_result_for_command(
                    confirmed,
                    request_text,
                )
                if context is not None:
                    context.pending_confirmation = confirmed
                    context.pending_plan = tuple(commands)
                    context.pending_request = cleaned
                    result.data["can_confirm"] = True
                    result.data["confirmation_label"] = "Confirm action"
                else:
                    result.data["can_confirm"] = False
                result.data["planned_steps"] = len(parts)
                return result
            return execute_automation_plan(commands, context)

    parsed = parse_automation_command(cleaned, context)
    if parsed is None:
        return None
    if parsed.intent == "confirmation_required" and context is not None:
        pending = _confirmed_command_for_text(cleaned)
        if (
            pending is not None
            and pending.intent == "send_whatsapp_message"
            and not context.confirm_whatsapp_send
        ):
            return execute_automation_command(pending)
    result = execute_automation_command(parsed)
    if context is not None and parsed.intent == "confirmation_required":
        pending = _confirmed_command_for_text(cleaned)
        if pending is not None:
            result = _confirmation_result_for_command(pending, cleaned)
            context.pending_confirmation = pending
            context.pending_plan = ()
            context.pending_request = cleaned
            result.data["can_confirm"] = True
            result.data["confirmation_label"] = "Confirm action"
        else:
            result.data["can_confirm"] = False
    if context is not None and result.success:
        context.remember_command(parsed)
    return result


__all__ = [
    "ALLOWED_APPLICATIONS",
    "APPLICATION_ALIASES",
    "AUTOMATION_FUNCTION_SCHEMAS",
    "AutomationContext",
    "AutomationResult",
    "CONFIRMATION_REQUIRED_ACTIONS",
    "ParsedAutomationCommand",
    "change_volume",
    "close_application",
    "confirmation_required_for_text",
    "execute_automation_command",
    "execute_automation_plan",
    "get_current_date",
    "get_current_time",
    "get_system_status",
    "handle_automation_command",
    "looks_like_automation_request",
    "open_application",
    "open_website",
    "parse_automation_command",
    "parsed_command_from_tool_call",
    "play_youtube",
    "prepare_whatsapp_message",
    "send_whatsapp_message",
    "search_google",
    "search_spotify",
    "search_youtube",
    "set_brightness",
    "set_mute",
    "set_volume",
    "trigger_media_key",
    "lock_workstation",
    "search_in_active_app",
    "search_local_files",
    "get_clipboard_text",
    "set_clipboard_text",
    "save_screenshot",
    "save_quick_note",
    "browser_navigate",
    "browser_click_selector",
    "browser_fill_input",
    "browser_extract_text",
    "summarize_youtube_video",
    "analyze_youtube_comments",
    "get_youtube_video_details",
    "recall_captain_memory",
    "execute_terminal_command",
]
