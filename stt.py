"""Cancellable, lightweight push-to-talk speech recognition with Whisper support."""

from __future__ import annotations

import io
import logging
import queue
import threading
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from config import Settings


LOGGER = logging.getLogger(__name__)
_UNSET = object()
_WHISPER_MODEL_CACHE: dict[str, Any] = {}
_WHISPER_LOCK = threading.Lock()
DEFAULT_WHISPER_INITIAL_PROMPT = (
    "DarkShadow, Captain, YouTube kholo, gaana bajao, WhatsApp par message bhejo, "
    "volume badhao, volume kam karo, screen dekho, browser kholo, Hindi Hinglish speech."
)


@dataclass(frozen=True, slots=True)
class SpeechRecognitionResult:
    """Structured result for one bounded push-to-talk recognition attempt."""

    success: bool
    text: str = ""
    language: str | None = None
    message: str = ""
    error: str | None = None


class PushToTalkSTT:
    """Capture one phrase and recognize Hindi, English, or common Hinglish.

    SpeechRecognition and PyAudio are imported lazily. Recognition supports
    Whisper (faster-whisper / openai-whisper) and Google Web Speech.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        speech_module: Any = _UNSET,
        recognizer: Any | None = None,
        microphone_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self._speech_module = speech_module
        self._recognizer = recognizer
        self._microphone_factory = microphone_factory

    def input_devices(self) -> tuple[tuple[int, str], ...]:
        """Return microphone endpoints for user-selectable Windows diagnostics."""

        try:
            speech = self._get_speech_module()
            microphone_factory = self._microphone_factory or speech.Microphone
            names = microphone_factory.list_microphone_names()
        except Exception as exc:
            LOGGER.warning("Microphone enumeration failed (type=%s)", type(exc).__name__)
            return ()
        return tuple((index, str(name)) for index, name in enumerate(names))

    def listen_once(
        self,
        cancel_event: threading.Event | None = None,
    ) -> SpeechRecognitionResult:
        """Listen for one phrase with calibration, timeout, and cancellation.

        When a cancellation event is supplied, microphone work runs in a daemon
        worker. The caller can return immediately while the bounded underlying
        capture releases the audio device no later than the phrase-time limit.
        """

        if cancel_event is None:
            return self._listen_direct()
        if cancel_event.is_set():
            return self._canceled_result()

        results: queue.Queue[SpeechRecognitionResult] = queue.Queue(maxsize=1)

        def capture() -> None:
            result = self._listen_direct()
            try:
                results.put_nowait(result)
            except queue.Full:
                return

        worker = threading.Thread(
            target=capture,
            name="darkshadow-stt-capture",
            daemon=True,
        )
        worker.start()
        while worker.is_alive():
            if cancel_event.wait(0.05):
                return self._canceled_result()
            try:
                return results.get_nowait()
            except queue.Empty:
                continue
        try:
            return results.get_nowait()
        except queue.Empty:
            return SpeechRecognitionResult(
                False,
                message="Speech capture unexpectedly finish hui bina result ke.",
                error="stt_error",
            )

    def _get_speech_module(self) -> Any:
        if self._speech_module is _UNSET:
            self._speech_module = import_module("speech_recognition")
        return self._speech_module

    def _transcribe_whisper(self, audio: Any, recognizer: Any) -> str | None:
        """Transcribe audio using Whisper with faster-whisper or openai-whisper."""

        prompt = getattr(self.settings, "stt_whisper_prompt", DEFAULT_WHISPER_INITIAL_PROMPT)

        # 1. Try faster-whisper (high speed CTranslate2 engine)
        try:
            import os
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            from faster_whisper import WhisperModel

            model_name = getattr(self.settings, "whisper_model", "base")
            device = getattr(self.settings, "whisper_device", "auto")
            cache_key = f"faster_{model_name}_{device}"
            with _WHISPER_LOCK:
                if cache_key not in _WHISPER_MODEL_CACHE:
                    _WHISPER_MODEL_CACHE[cache_key] = WhisperModel(
                        model_name,
                        device=device if device in {"cpu", "cuda"} else "auto",
                        compute_type="int8" if device == "cpu" else "auto",
                    )
                model = _WHISPER_MODEL_CACHE[cache_key]

            wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
            audio_stream = io.BytesIO(wav_bytes)
            segments, _info = model.transcribe(
                audio_stream,
                beam_size=5,
                initial_prompt=prompt,
            )
            text = " ".join(seg.text for seg in segments).strip()
            if text:
                return text
        except (ImportError, Exception) as exc:
            LOGGER.debug("faster-whisper transcription bypass/failed: %s", exc)

        # 2. Try SpeechRecognition's built-in whisper
        try:
            model_name = getattr(self.settings, "whisper_model", "base")
            try:
                text = recognizer.recognize_whisper(
                    audio,
                    model=model_name,
                    language=None,
                    initial_prompt=prompt,
                )
            except TypeError:
                text = recognizer.recognize_whisper(
                    audio,
                    model=model_name,
                    language=None,
                )
            if text and str(text).strip():
                return str(text).strip()
        except Exception as exc:
            LOGGER.debug("SpeechRecognition whisper recognize failed: %s", exc)

        return None

    def _listen_direct(self) -> SpeechRecognitionResult:
        try:
            speech = self._get_speech_module()
        except (ImportError, ModuleNotFoundError):
            return SpeechRecognitionResult(
                False,
                message="SpeechRecognition/PyAudio dependency available nahi hai.",
                error="missing_dependency",
            )

        recognizer = self._recognizer or speech.Recognizer()
        for attribute, value in (
            ("dynamic_energy_threshold", True),
            ("pause_threshold", 0.4),
            ("non_speaking_duration", 0.3),
            ("phrase_threshold", 0.2),
        ):
            if hasattr(recognizer, attribute):
                setattr(recognizer, attribute, value)
        microphone_factory = self._microphone_factory or speech.Microphone
        try:
            microphone = microphone_factory(
                device_index=self.settings.stt_device_index
            )
            with microphone as source:
                if self.settings.stt_calibration_seconds > 0:
                    recognizer.adjust_for_ambient_noise(
                        source,
                        duration=self.settings.stt_calibration_seconds,
                    )
                audio = recognizer.listen(
                    source,
                    timeout=self.settings.stt_timeout_seconds,
                    phrase_time_limit=self.settings.stt_phrase_time_limit_seconds,
                )
        except getattr(speech, "WaitTimeoutError", TimeoutError):
            return SpeechRecognitionResult(
                False,
                message="Listening timeout hua—koi speech detect nahi hui.",
                error="listen_timeout",
            )
        except (OSError, AttributeError) as exc:
            LOGGER.warning("Microphone unavailable (type=%s)", type(exc).__name__)
            return SpeechRecognitionResult(
                False,
                message="Microphone access nahi mila; typed mode available hai.",
                error="microphone_unavailable",
            )
        except Exception as exc:
            LOGGER.warning("Microphone capture failed (type=%s)", type(exc).__name__)
            return SpeechRecognitionResult(
                False,
                message="Voice capture fail hui; typed mode safe hai.",
                error="microphone_unavailable",
            )

        backend = getattr(self.settings, "stt_backend", "whisper").casefold()

        # Primary backend: Whisper
        if backend in {"whisper", "auto"}:
            try:
                whisper_text = self._transcribe_whisper(audio, recognizer)
                if whisper_text:
                    return SpeechRecognitionResult(
                        True,
                        text=whisper_text,
                        language="whisper",
                        message="Speech recognized via Whisper.",
                    )
            except Exception as exc:
                LOGGER.warning("Whisper STT attempt failed: %s", exc)

        # Fallback backend: Google Web Speech
        for language in self.settings.stt_languages:
            try:
                recognized = str(
                    recognizer.recognize_google(audio, language=language)
                ).strip()
            except getattr(speech, "UnknownValueError", ValueError):
                continue
            except getattr(speech, "RequestError", ConnectionError) as exc:
                LOGGER.warning(
                    "Speech recognition service failed (type=%s)",
                    type(exc).__name__,
                )
                return SpeechRecognitionResult(
                    False,
                    message=(
                        "Speech recognition service reachable nahi hai; "
                        "typed mode use kijiye."
                    ),
                    error="recognition_service_error",
                )
            except Exception as exc:
                LOGGER.warning(
                    "Speech recognition failed (type=%s)", type(exc).__name__
                )
                return SpeechRecognitionResult(
                    False,
                    message="Speech recognize nahi ho saki; typed mode use kijiye.",
                    error="recognition_error",
                )
            if recognized:
                return SpeechRecognitionResult(
                    True,
                    text=recognized,
                    language=language,
                    message="Speech recognized.",
                )

        return SpeechRecognitionResult(
            False,
            message=(
                "Speech clear samajh nahi aayi—mic ke paas normal volume mein "
                "boliye, ya /mic se input device check kijiye."
            ),
            error="not_understood",
        )

    @staticmethod
    def _canceled_result() -> SpeechRecognitionResult:
        return SpeechRecognitionResult(
            False,
            message="Voice listening cancel kar di.",
            error="canceled",
        )


__all__ = ["PushToTalkSTT", "SpeechRecognitionResult"]
