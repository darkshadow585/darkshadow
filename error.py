"""DarkShadow Error & Self-Correction Journal.

Stores and retrieves error correction records from a JSONL file
(.darkshadow/errors.jsonl) instead of appending raw Python code
to source files.

When Captain says "tumne yaha galat kiya" or "ye nahi ye hota hai",
DarkShadow captures the context and stores a structured error record
in the JSONL file for persistent debugging and learning.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent
_ERRORS_DIR = _PROJECT_ROOT / ".darkshadow"
ERRORS_JSONL_PATH = _ERRORS_DIR / "errors.jsonl"

# In-memory cache of active error records (loaded on first access)
_ERROR_LOGS: list[dict[str, Any]] | None = None


def _ensure_dir() -> None:
    """Ensure the .darkshadow directory exists."""
    _ERRORS_DIR.mkdir(parents=True, exist_ok=True)


def _load_from_disk() -> list[dict[str, Any]]:
    """Load all error records from the JSONL file."""
    records: list[dict[str, Any]] = []
    if not ERRORS_JSONL_PATH.exists():
        return records
    try:
        with open(ERRORS_JSONL_PATH, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    LOGGER.debug("Skipping malformed JSONL line %d in %s", line_num, ERRORS_JSONL_PATH)
    except Exception as exc:
        LOGGER.warning("Failed to read %s: %s", ERRORS_JSONL_PATH, exc)
    return records


def _get_logs() -> list[dict[str, Any]]:
    """Return the in-memory error logs, loading from disk on first call."""
    global _ERROR_LOGS
    if _ERROR_LOGS is None:
        _ERROR_LOGS = _load_from_disk()
    return _ERROR_LOGS


def append_record(record: dict[str, Any]) -> None:
    """Append a single error record to the JSONL file and in-memory cache.

    Uses atomic append semantics to prevent corruption on crash.
    """
    _ensure_dir()
    logs = _get_logs()

    # Deduplicate: skip if an identical lesson for the same module already exists
    new_lesson = record.get("lesson_learned", "").strip().casefold()
    new_module = record.get("affected_module", "").strip().casefold()
    for existing in logs:
        if (
            existing.get("lesson_learned", "").strip().casefold() == new_lesson
            and existing.get("affected_module", "").strip().casefold() == new_module
        ):
            LOGGER.debug("Duplicate correction skipped: %s", record.get("id", "?"))
            # Still add to in-memory so the caller sees it
            return

    try:
        with open(ERRORS_JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as exc:
        LOGGER.warning("Failed to write error record to %s: %s", ERRORS_JSONL_PATH, exc)

    logs.append(record)


# ──────────────────────── Public API (backward compatible) ────────────────────

# Module-level alias for backward compatibility with code that imports ERROR_LOGS directly.
# This is a property-like access that works at module level.
@property  # type: ignore[misc]
def _error_logs_compat(self: Any) -> list[dict[str, Any]]:
    return _get_logs()


# For backward compat: ERROR_LOGS is accessed as a module-level list.
# We eagerly load on import so `from error import ERROR_LOGS` works.
ERROR_LOGS: list[dict[str, Any]] = []


def _init_compat() -> None:
    """Populate ERROR_LOGS with records from disk on import."""
    global ERROR_LOGS
    ERROR_LOGS = _get_logs()


_init_compat()


def get_all_errors() -> list[dict[str, Any]]:
    """Return all logged error records."""
    return list(_get_logs())


def get_pending_errors() -> list[dict[str, Any]]:
    """Return errors marked as PENDING_FIX."""
    return [e for e in _get_logs() if e.get("status") == "PENDING_FIX"]


def clear_errors() -> None:
    """Clear all error logs from memory AND disk."""
    global _ERROR_LOGS
    _ERROR_LOGS = []
    ERROR_LOGS.clear()
    try:
        if ERRORS_JSONL_PATH.exists():
            ERRORS_JSONL_PATH.unlink()
            LOGGER.info("Cleared error records from %s", ERRORS_JSONL_PATH)
    except Exception as exc:
        LOGGER.warning("Failed to delete %s: %s", ERRORS_JSONL_PATH, exc)
