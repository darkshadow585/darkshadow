"""Ambient Screen & Proactive Copilot (Sentinel Mode) for DarkShadow.

Monitors desktop environment proactively:
1. ErrorWatcherSentinel: Detects terminal/IDE errors (Python tracebacks, npm crashes).
2. MorningBriefingSentinel: Gives an intelligent once-a-day briefing in the morning.
3. SystemHealthSentinel: Proactively alerts if RAM > 90% or disk space is critically low.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import platform
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

_ERROR_KEYWORDS = [
    re.compile(r"\b(?:ModuleNotFoundError|ImportError):\s+No module named\s+['\"]?([a-zA-Z0-9_\-]+)['\"]?", re.IGNORECASE),
    re.compile(r"\bSyntaxError:\s+(.+)", re.IGNORECASE),
    re.compile(r"\b(?:ZeroDivisionError|TypeError|ValueError|KeyError|IndexError):\s+(.+)", re.IGNORECASE),
    re.compile(r"\bnpm\s+ERR!\s+(.+)", re.IGNORECASE),
    re.compile(r"\b(?:fatal|panic):\s+(.+)", re.IGNORECASE),
    re.compile(r"Traceback\s+\(most recent call last\):", re.IGNORECASE),
]

_DEV_WINDOW_KEYWORDS = ["code", "terminal", "powershell", "cmd", "bash", "pycharm", "cursor", "sublime"]


class ErrorWatcherSentinel:
    """Watches active IDE and terminal windows for programming errors and crashes."""

    def __init__(self, cooldown_seconds: float = 600.0) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_alert_fingerprint: str = ""
        self._last_alert_time: float = 0.0

    def check(self) -> str | None:
        """Inspect foreground window and return a proactive alert string if an error is detected."""
        try:
            from desktop_engine import get_desktop_engine
            engine = get_desktop_engine()
            title = engine.get_active_window_title().lower()

            # Check if active window is a development / terminal window
            if not any(k in title for k in _DEV_WINDOW_KEYWORDS):
                return None

            # Inspect controls in the window
            context_summary = engine.get_active_window_context(max_controls=20)
            if not context_summary:
                return None

            # Look for error signatures
            matched_error: str | None = None
            for pat in _ERROR_KEYWORDS:
                match = pat.search(context_summary)
                if match:
                    matched_error = match.group(0).strip()
                    break

            if not matched_error:
                return None

            # Deduplication & cooldown check
            fingerprint = hashlib.md5(matched_error.encode("utf-8", errors="ignore")).hexdigest()
            now = time.time()
            if fingerprint == self._last_alert_fingerprint and (now - self._last_alert_time) < self.cooldown_seconds:
                return None

            self._last_alert_fingerprint = fingerprint
            self._last_alert_time = now

            LOGGER.info("ErrorWatcherSentinel detected error in '%s': %s", title, matched_error[:60])
            return (
                f"Captain, active window me error dikh raha hai: '{matched_error[:80]}'. "
                "Agar aap kahein toh main iska quick fix analyze karu?"
            )
        except Exception as exc:
            LOGGER.debug("ErrorWatcherSentinel check notice: %s", exc)
            return None


class MorningBriefingSentinel:
    """Prepares an intelligent, friendly spoken briefing once per day during morning hours."""

    def __init__(self) -> None:
        self._last_briefing_date: str = ""

    def check(self, memory_store: Any = None) -> str | None:
        """Return morning briefing if not delivered today and current time is morning (06:00 - 12:00)."""
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self._last_briefing_date == today_str:
            return None

        # Check morning window: 6:00 AM to 12:00 PM
        if not (6 <= now.hour < 12):
            return None

        self._last_briefing_date = today_str

        date_display = now.strftime("%A, %d %B")
        time_display = now.strftime("%I:%M %p")

        # Check pending reminders if memory store provided
        reminder_note = ""
        if memory_store and hasattr(memory_store, "get_due_reminders"):
            try:
                due = memory_store.get_due_reminders(limit=5)
                if due:
                    reminder_note = f" Aur aapke {len(due)} reminders pending hain."
            except Exception:
                pass

        return (
            f"Good morning Captain! Aaj {date_display} hai, time {time_display} ho raha hai. "
            f"DarkShadow systems 100% active hain.{reminder_note} Aaj ke mission par shuru karein?"
        )


class SystemHealthSentinel:
    """Monitors CPU, RAM, and Disk space to proactively alert before performance degrades."""

    def __init__(self, cooldown_seconds: float = 900.0) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_alert_time: float = 0.0

    def check(self) -> str | None:
        """Check system resources and return warning if thresholds are crossed."""
        now = time.time()
        if (now - self._last_alert_time) < self.cooldown_seconds:
            return None

        try:
            # Check RAM and Disk using standard psutil or shutil
            total, used, free = shutil.disk_usage("C:\\" if os.name == "nt" else "/")
            free_gb = free / (1024**3)

            if free_gb < 5.0:
                self._last_alert_time = now
                return f"Captain, C: drive par storage critically low hai ({free_gb:.1f} GB bacha hai). Cleanup run karein?"

            # Try psutil if installed
            try:
                import psutil
                ram = psutil.virtual_memory()
                if ram.percent > 90.0:
                    self._last_alert_time = now
                    return f"Captain, RAM usage high chal raha hai ({ram.percent:.0f}%). Background apps check karne chahiye."
            except ImportError:
                pass

        except Exception as exc:
            LOGGER.debug("SystemHealthSentinel check notice: %s", exc)

        return None


class SentinelCoordinator:
    """Coordinates all proactive sentinel monitors."""

    def __init__(self, memory_store: Any = None) -> None:
        self.memory_store = memory_store
        self.error_watcher = ErrorWatcherSentinel()
        self.morning_briefing = MorningBriefingSentinel()
        self.health_sentinel = SystemHealthSentinel()

    def run_all_checks(self) -> list[str]:
        """Execute all sentinel monitors and collect any generated alerts."""
        alerts = []

        err_alert = self.error_watcher.check()
        if err_alert:
            alerts.append(err_alert)

        briefing = self.morning_briefing.check(memory_store=self.memory_store)
        if briefing:
            alerts.append(briefing)

        health_alert = self.health_sentinel.check()
        if health_alert:
            alerts.append(health_alert)

        return alerts


__all__ = [
    "ErrorWatcherSentinel",
    "MorningBriefingSentinel",
    "SystemHealthSentinel",
    "SentinelCoordinator",
]
