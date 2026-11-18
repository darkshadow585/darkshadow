"""Interactive Error Logger & Feedback Learner for DarkShadow.

Intercepts user corrections (e.g. 'tumne yaha galat kiya', 'ye nahi ye hota hai'),
logs them into .darkshadow/errors.jsonl via the error module, and saves the lesson
to SQLite memory.
"""

from __future__ import annotations

import datetime
import logging
import re
import uuid
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent
ERROR_PY_PATH = _PROJECT_ROOT / "error.py"

_CORRECTION_PATTERNS = [
    re.compile(r"\b(?:tumne\s+)?(?:yaha[n]?\s+)?(?:galat|wrong|mistake|galti)\b", re.IGNORECASE),
    re.compile(r"\b(?:ye\s+nahi|aisa\s+nahi|aise\s+nahi|waisa\s+nahi)\b", re.IGNORECASE),
    re.compile(r"\b(?:ye\s+hota\s+hai|aise\s+karo|aise\s+hona\s+chahiye|sahi\s+nahi\s+hai)\b", re.IGNORECASE),
    re.compile(r"\b(?:you\s+did\s+this\s+wrong|you\s+made\s+a\s+mistake|not\s+this|incorrect)\b", re.IGNORECASE),
]


class ErrorCorrectionDetector:
    """Detects when Captain is providing a correction or feedback."""

    @staticmethod
    def is_correction(text: str) -> bool:
        """Return True if text matches user correction/feedback patterns."""
        cleaned = str(text).strip()
        if len(cleaned) < 5:
            return False
        return any(pat.search(cleaned) for pat in _CORRECTION_PATTERNS)

    @staticmethod
    def extract_lesson(correction_text: str) -> str:
        """Extract the core lesson from Captain's correction statement."""
        cleaned = str(correction_text).strip()
        # Look for phrases like "ye nahi ye hota hai..." or "aise karo..."
        m = re.search(r"\b(?:ye\s+nahi|aise\s+nahi|instead of this)\s*[,:]?\s*(.+)", cleaned, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
        return cleaned


class ErrorLogger:
    """Manages appending error records to errors.jsonl and SQLite learned_lessons."""

    @staticmethod
    def infer_affected_module(text: str) -> str:
        """Guess the module from command context."""
        lower = text.casefold()
        if "whatsapp" in lower:
            return "whatsapp_engine"
        elif any(k in lower for k in ("youtube", "song", "spotify", "music")):
            return "media_engine"
        elif any(k in lower for k in ("volume", "brightness", "screen", "lock")):
            return "desktop_engine"
        elif any(k in lower for k in ("remember", "memory", "note", "reminder")):
            return "memory"
        elif any(k in lower for k in ("search", "google", "weather", "news")):
            return "realtimeinfo"
        return "automation_general"

    @classmethod
    def log_correction(
        cls,
        captain_correction: str,
        last_turn: Any,  # ConversationTurn
        memory_store: Any = None,
        error_file_path: Path | str | None = None,  # kept for backward compat, ignored
    ) -> dict[str, Any]:
        """Record the mistake, store in JSONL, and save lesson into memory."""
        now = datetime.datetime.now()
        err_id = f"ERR-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        iso_now = now.isoformat()

        original_cmd = getattr(last_turn, "user_text", "")
        assistant_action = getattr(last_turn, "assistant_text", "")
        lesson = ErrorCorrectionDetector.extract_lesson(captain_correction)
        affected_module = cls.infer_affected_module(f"{original_cmd} {assistant_action}")

        record = {
            "id": err_id,
            "timestamp": iso_now,
            "status": "PENDING_FIX",
            "original_command": original_cmd,
            "assistant_action": assistant_action[:200],
            "captain_correction": captain_correction,
            "lesson_learned": lesson,
            "affected_module": affected_module,
        }

        # 1. Persist to JSONL via the error module (with deduplication)
        try:
            from error import append_record
            append_record(record)
            LOGGER.info("Appended correction record to errors.jsonl (ID: %s)", err_id)
        except Exception as exc:
            LOGGER.warning("Failed to persist error record: %s", exc)

        if error_file_path is not None:
            try:
                p = Path(error_file_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                record_py = f"""# DarkShadow Error Log
ERROR_LOGS = [
    {repr(record)}
]
"""
                p.write_text(record_py, encoding="utf-8")
            except Exception as exc:
                LOGGER.warning("Failed to write to %s: %s", error_file_path, exc)

        # 2. Store in SQLite memory (learned_lessons) so it's injected in future prompts
        if memory_store and hasattr(memory_store, "save_lesson"):
            try:
                memory_store.save_lesson(topic=affected_module, lesson=f"Correction by Captain: {lesson}")
                LOGGER.info("Saved lesson to SQLite memory: [%s] %s", affected_module, lesson)
            except Exception as mem_exc:
                LOGGER.debug("Memory lesson save notice: %s", mem_exc)

        # 3. Generate user-facing response
        message = (
            f"Sahi pakde Captain! Meri galti thi. Maine ise error.py me record kar liya hai "
            f"(Record ID: {err_id}).\n\n"
            f"**Lesson Learned:** {lesson}\n"
            f"Aage se main is baat ka poora dhyan rakhunga!"
        )

        return {
            "success": True,
            "error_id": err_id,
            "lesson": lesson,
            "message": message,
            "record": record,
        }

    @classmethod
    def log_lesson_record(
        cls,
        topic: str,
        lesson: str,
        source: str = "captain_feedback",
        error_file_path: Path | str | None = None,  # kept for backward compat, ignored
    ) -> dict[str, Any]:
        """Record a lesson or correction directly into JSONL and memory."""
        now = datetime.datetime.now()
        err_id = f"ERR-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        iso_now = now.isoformat()
        affected_module = cls.infer_affected_module(f"{topic} {lesson}")

        record = {
            "id": err_id,
            "timestamp": iso_now,
            "status": "PENDING_FIX",
            "original_command": topic,
            "assistant_action": f"{source}: {topic}",
            "captain_correction": lesson,
            "lesson_learned": lesson,
            "affected_module": affected_module,
        }

        # Persist to JSONL via the error module (with deduplication)
        try:
            from error import append_record
            append_record(record)
            LOGGER.info("Appended lesson record to errors.jsonl (ID: %s)", err_id)
        except Exception as exc:
            LOGGER.warning("Failed to persist lesson record: %s", exc)

        return {"success": True, "error_id": err_id, "record": record}


__all__ = [
    "ErrorCorrectionDetector",
    "ErrorLogger",
]
