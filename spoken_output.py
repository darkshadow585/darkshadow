"""Non-blocking speech output for responses produced in typed mode."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
from typing import Any

from speech_language import detect_speech_language


LOGGER = logging.getLogger(__name__)
_MESSAGES: queue.Queue[str] = queue.Queue()
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_DISABLED = False
_ACTIVE_VOICE: Any | None = None
_ACTIVE_PROCESS: subprocess.Popen[str] | None = None


def _enabled() -> bool:
    setting = os.getenv("DARKSHADOW_TYPED_TTS", "true").strip().lower()
    return setting in {"1", "true", "yes", "on"} and "PYTEST_CURRENT_TEST" not in os.environ


def _offline_delivery(text: str) -> tuple[str, int, int]:
    """Translate Gemini-style audio tags into SAPI-friendly delivery hints."""

    lowered = text.casefold()
    rate = 0
    volume = 100
    if "[excited]" in lowered or "[excitedly]" in lowered:
        rate = 2
    elif "[tired]" in lowered:
        rate = -2
    elif any(tag in lowered for tag in ("[serious]", "[trembling]", "[sighs]")):
        rate = -1
    if "[whispers]" in lowered:
        rate = min(rate, -1)
        volume = 48

    expressive = re.sub(r"\[(?:laughs|giggles)\]", "ha ha, ", text, flags=re.IGNORECASE)
    expressive = re.sub(r"\[sighs\]", "hmm... ", expressive, flags=re.IGNORECASE)
    expressive = re.sub(r"\[[^\[\]]{1,48}\]", "", expressive)
    expressive = re.sub(r"\s+", " ", expressive).strip()
    return expressive or text, rate, volume


def _speak_with_windows(text: str) -> None:
    """Use Windows' built-in SAPI without pywin32 or shell interpolation."""
    global _ACTIVE_PROCESS

    spoken_text, rate, volume = _offline_delivery(text)
    payload = json.dumps(
        {"text": spoken_text, "rate": rate, "volume": volume},
        ensure_ascii=False,
    )
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Volume = [int]$payload.volume; $speaker.Rate = [int]$payload.rate; "
        "try { $speaker.Speak([string]$payload.text) } finally { $speaker.Dispose() }"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            stdin=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _LOCK:
            _ACTIVE_PROCESS = proc
        proc.communicate(input=payload, timeout=120)
    except Exception as exc:
        LOGGER.debug("PowerShell TTS notice: %s", exc)
    finally:
        with _LOCK:
            _ACTIVE_PROCESS = None


def _run() -> None:
    global _DISABLED, _ACTIVE_VOICE
    engine = None
    windows_voice = None
    if sys.platform == "win32":
        try:
            import comtypes
            from comtypes.client import CreateObject

            comtypes.CoInitialize()
            windows_voice = CreateObject("SAPI.SpVoice")
            with _LOCK:
                _ACTIVE_VOICE = windows_voice
        except Exception as exc:
            LOGGER.warning(
                "Direct Windows TTS unavailable; using PowerShell fallback (type=%s)",
                type(exc).__name__,
            )
    else:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 178)
        except Exception as exc:
            _DISABLED = True
            LOGGER.warning("Typed TTS unavailable (type=%s)", type(exc).__name__)
            return

    while True:
        message = _MESSAGES.get()
        try:
            if sys.platform == "win32":
                if windows_voice is not None:
                    spoken_text, rate, volume = _offline_delivery(message)
                    windows_voice.Rate = rate
                    windows_voice.Volume = volume
                    # Flag 0 is synchronous speak; flag 2 is SVSFPurgeBeforeSpeak
                    windows_voice.Speak(spoken_text, 0)
                else:
                    _speak_with_windows(message)
            else:
                target_language = detect_speech_language(message)
                voices = engine.getProperty("voices") or []
                for voice in voices:
                    details = " ".join(
                        [
                            str(getattr(voice, "id", "")),
                            str(getattr(voice, "name", "")),
                            str(getattr(voice, "languages", "")),
                        ]
                    ).casefold()
                    if target_language == "hi" and (
                        "hindi" in details or "hi-in" in details or "hi_in" in details
                    ):
                        engine.setProperty("voice", voice.id)
                        break
                    if target_language == "en" and (
                        "english" in details or "en-in" in details or "en_in" in details
                    ):
                        engine.setProperty("voice", voice.id)
                        break
                engine.say(message)
                engine.runAndWait()
        except Exception as exc:
            LOGGER.warning("Typed TTS failed (type=%s)", type(exc).__name__)
        finally:
            _MESSAGES.task_done()


def speak_response(text: str) -> bool:
    """Queue text for speech without delaying the terminal response."""

    if not text.strip() or not _enabled() or _DISABLED:
        return False
    if not prepare_speech_engine():
        return False
    _MESSAGES.put(text.strip())
    return True


def stop_speech() -> int:
    """Immediately stop active speech and purge all pending queued messages."""
    cleared = 0
    with _LOCK:
        while not _MESSAGES.empty():
            try:
                _MESSAGES.get_nowait()
                _MESSAGES.task_done()
                cleared += 1
            except (queue.Empty, ValueError):
                break

    # Stop active Windows COM SAPI utterance if currently speaking
    with _LOCK:
        voice = _ACTIVE_VOICE
        proc = _ACTIVE_PROCESS

    if voice is not None:
        try:
            # SVSFPurgeBeforeSpeak (flag 2) cancels active voice immediately
            voice.Speak("", 2)
        except Exception as exc:
            LOGGER.debug("SAPI stop notice: %s", exc)

    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass

    return cleared


def prepare_speech_engine() -> bool:
    """Warm the reusable local speech engine in the background."""

    global _WORKER
    if not _enabled() or _DISABLED:
        return False
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_run, daemon=True, name="typed-tts")
            _WORKER.start()
    return True


def wait_for_speech() -> None:
    """Wait until the currently queued offline speech has finished."""

    _MESSAGES.join()


__all__ = ["prepare_speech_engine", "speak_response", "stop_speech", "wait_for_speech"]
