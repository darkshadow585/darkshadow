"""Persistent, non-sensitive TTS provider cycling for DarkShadow."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


KOLKATA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class TTSUsageState:
    """The complete, deliberately non-sensitive persisted TTS state."""

    date: str
    active_provider: str = "fish"
    segment_characters: int = 0
    fish_daily_characters: int = 0
    gemini_daily_characters: int = 0


class TTSRouter:
    """Cycle whole responses between Fish Audio and Gemini using persisted counters."""

    def __init__(
        self,
        usage_file: Path,
        *,
        fish_segment_characters: int = 500,
        gemini_segment_characters: int = 1000,
        fish_segment_words: int | None = None,
        gemini_segment_words: int | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.usage_file = Path(usage_file)
        fish_val = fish_segment_words if fish_segment_words is not None else fish_segment_characters
        gemini_val = gemini_segment_words if gemini_segment_words is not None else gemini_segment_characters

        self.fish_segment_characters = max(1, int(fish_val))
        self.gemini_segment_characters = max(1, int(gemini_val))
        self.fish_segment_words = self.fish_segment_characters
        self.gemini_segment_words = self.gemini_segment_characters

        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._loaded_state_needs_repair = False
        self._state = self._load_state()
        if self._loaded_state_needs_repair:
            self._write_state()

    def _today(self) -> str:
        current = self._clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=KOLKATA_TIMEZONE)
        return current.astimezone(KOLKATA_TIMEZONE).date().isoformat()

    def _fresh_state(self) -> TTSUsageState:
        return TTSUsageState(date=self._today())

    @staticmethod
    def _valid_date(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    @classmethod
    def _validated_state(cls, raw: object) -> TTSUsageState | None:
        if not isinstance(raw, dict):
            return None
        expected = {
            "date",
            "active_provider",
            "segment_characters",
            "fish_daily_characters",
            "gemini_daily_characters",
        }
        if set(raw) != expected or not cls._valid_date(raw.get("date")):
            return None
        if raw.get("active_provider") not in {"fish", "gemini"}:
            return None
        counters = (
            raw.get("segment_characters"),
            raw.get("fish_daily_characters"),
            raw.get("gemini_daily_characters"),
        )
        if any(type(value) is not int or value < 0 for value in counters):
            return None
        return TTSUsageState(
            date=raw["date"],
            active_provider=raw["active_provider"],
            segment_characters=raw["segment_characters"],
            fish_daily_characters=raw["fish_daily_characters"],
            gemini_daily_characters=raw["gemini_daily_characters"],
        )

    def _load_state(self) -> TTSUsageState:
        file_exists = self.usage_file.exists()
        try:
            raw_text = self.usage_file.read_text(encoding="utf-8")
            loaded = self._validated_state(json.loads(raw_text))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            loaded = None
        if loaded is None or loaded.date != self._today():
            self._loaded_state_needs_repair = file_exists
            return self._fresh_state()
        return loaded

    def _reset_if_needed(self) -> None:
        if self._state.date != self._today():
            self._state = self._fresh_state()
            self._write_state()

    def _write_state(self) -> None:
        """Replace the usage JSON atomically from a temporary sibling file."""

        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.usage_file.name}.",
            suffix=".tmp",
            dir=str(self.usage_file.parent),
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                json.dump(asdict(self._state), file, separators=(",", ":"))
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.usage_file)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _threshold_for(self, provider: str) -> int:
        if provider == "gemini":
            return self.gemini_segment_characters
        return self.fish_segment_characters

    def selected_provider(
        self,
        *,
        fish_available: bool = True,
        gemini_available: bool = True,
    ) -> str:
        """Return one provider for the next whole response."""

        with self._lock:
            self._reset_if_needed()
            active = self._state.active_provider
            if active == "fish" and not fish_available:
                active = "gemini" if gemini_available else "fish"
            elif active == "gemini" and not gemini_available:
                active = "fish" if fish_available else "gemini"
            return active

    def record_attempt(self, provider: str, speech_text: str) -> None:
        """Conservatively record one cloud synthesis request before it is sent."""

        normalized = provider.casefold()
        if normalized not in {"fish", "gemini"}:
            return
        character_count = len(str(speech_text))
        with self._lock:
            self._reset_if_needed()
            state = self._state
            fish_total = state.fish_daily_characters
            gemini_total = state.gemini_daily_characters

            if normalized == "fish":
                fish_total += character_count
            elif normalized == "gemini":
                gemini_total += character_count

            active_provider = state.active_provider
            segment_chars = state.segment_characters
            if normalized == active_provider:
                segment_chars += character_count
                threshold = self._threshold_for(normalized)
                if segment_chars >= threshold:
                    if normalized == "fish":
                        active_provider = "gemini"
                    elif normalized == "gemini":
                        active_provider = "fish"
                    segment_chars = 0

            self._state = TTSUsageState(
                date=state.date,
                active_provider=active_provider,
                segment_characters=segment_chars,
                fish_daily_characters=fish_total,
                gemini_daily_characters=gemini_total,
            )
            self._write_state()

    def status(self) -> dict[str, str | int]:
        """Return only safe provider and aggregate counter information."""

        with self._lock:
            self._reset_if_needed()
            state = self._state
            threshold = self._threshold_for(state.active_provider)
            return {
                "date": state.date,
                "active_provider": state.active_provider,
                "segment_characters": state.segment_characters,
                "segment_words": state.segment_characters,
                "segment_threshold": threshold,
                "fish_daily_characters": state.fish_daily_characters,
                "gemini_daily_characters": state.gemini_daily_characters,
                "fish_daily_words": state.fish_daily_characters,
            }


__all__ = ["KOLKATA_TIMEZONE", "TTSRouter", "TTSUsageState"]
