"""Non-blocking, interruptible, streaming TTS for DarkShadow."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Callable, Iterable, Iterator

from config import Settings
from networking import install_ipv4_first_dns
from speech_language import select_edge_voice
from spoken_output import prepare_speech_engine, speak_response, wait_for_speech
from tts_router import TTSRouter


LOGGER = logging.getLogger(__name__)
_UNSET = object()
TTSCallback = Callable[["TTSResult"], None]
PCM_SAMPLE_RATE = 24000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH_BYTES = 2
PCM_BUFFER_FRAMES = 960  # 40 ms at 24 kHz; avoids tiny-write audio underruns.
PCM_BUFFER_BYTES = PCM_BUFFER_FRAMES * PCM_SAMPLE_WIDTH_BYTES


class _PlaybackInterrupted(Exception):
    pass


class _StreamingUnavailable(Exception):
    pass


class _ProviderPlaybackError(Exception):
    def __init__(self, cause: Exception, *, audio_started: bool) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.audio_started = audio_started


@dataclass(frozen=True, slots=True)
class TTSResult:
    """Structured status for queued or completed speech output."""

    success: bool
    message: str
    error: str | None = None
    interrupted: bool = False
    truncated: bool = False


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _decode_audio(value: Any) -> bytes:
    if isinstance(value, str):
        return base64.b64decode(value, validate=True)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    return b""


import array


def _apply_volume_gain(pcm_data: bytes, gain: float = 1.6) -> bytes:
    """Amplify 16-bit PCM audio using a soft-knee compressor to prevent clipping.

    Preserves clarity at loud volumes without harsh digital distortion.
    """
    if gain <= 1.0 or not pcm_data:
        return pcm_data
    samples = array.array("h", pcm_data)
    threshold = 24000
    headroom = 32767 - threshold  # 8767
    for i in range(len(samples)):
        val = samples[i] * gain
        if val > threshold:
            excess = val - threshold
            val = threshold + (headroom * excess) / (excess + headroom)
        elif val < -threshold:
            excess = -val - threshold
            val = -(threshold + (headroom * excess) / (excess + headroom))
        samples[i] = int(val)
    return samples.tobytes()


def _clean_speech_text(text: str) -> str:
    cleaned = re.sub(r"\[.*?\]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text


_GEMINI_AUDIO_TAGS = {
    "amazed",
    "crying",
    "curious",
    "excited",
    "excitedly",
    "gasp",
    "giggles",
    "laughs",
    "mischievously",
    "panicked",
    "sarcastic",
    "serious",
    "shouting",
    "sighs",
    "tired",
    "trembling",
    "whispers",
}


def _clean_gemini_speech_text(text: str) -> str:
    """Preserve supported expressive tags while dropping arbitrary brackets."""

    def keep_allowed_tag(match: re.Match[str]) -> str:
        tag = " ".join(match.group(1).casefold().split())
        return f"[{tag}]" if tag in _GEMINI_AUDIO_TAGS else ""

    cleaned = re.sub(r"\[([^\[\]]{1,48})\]", keep_allowed_tag, text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or _clean_speech_text(text)


def _strip_wave_header(chunk: bytes) -> bytes:
    """Remove a WAV header when an audio delta contains one."""

    if not chunk.startswith(b"RIFF"):
        return chunk
    data_index = chunk.find(b"data", 12)
    if data_index < 0 or len(chunk) < data_index + 8:
        return b""
    return chunk[data_index + 8 :]


class PCMStreamPlayer:
    """Play ordered 24 kHz mono 16-bit PCM chunks as they arrive."""

    def __init__(self, pyaudio_module: Any = _UNSET) -> None:
        self._pyaudio_module = pyaudio_module
        self._audio: Any | None = None
        self._active_stream: Any | None = None
        self._lock = threading.RLock()
        self._play_lock = threading.Lock()

    def _get_pyaudio(self) -> Any:
        if self._pyaudio_module is _UNSET:
            self._pyaudio_module = import_module("pyaudio")
        return self._pyaudio_module

    def _get_audio(self) -> tuple[Any, Any]:
        module = self._get_pyaudio()
        with self._lock:
            if self._audio is None:
                self._audio = module.PyAudio()
            return module, self._audio

    @property
    def has_active_stream(self) -> bool:
        with self._lock:
            return self._active_stream is not None

    def play_chunks(
        self,
        chunks: Iterable[bytes],
        stop_event: threading.Event,
    ) -> bool:
        """Open output on the first chunk and synchronously preserve order."""

        stream: Any | None = None
        played = False
        pending = bytearray()
        iterator = iter(chunks)

        def write_buffer(*, flush: bool = False) -> None:
            nonlocal stream, played
            while len(pending) >= PCM_BUFFER_BYTES or (flush and len(pending) >= 2):
                byte_count = (
                    PCM_BUFFER_BYTES
                    if len(pending) >= PCM_BUFFER_BYTES
                    else len(pending) - (len(pending) % PCM_SAMPLE_WIDTH_BYTES)
                )
                if byte_count <= 0:
                    return
                if stream is None:
                    module, audio = self._get_audio()
                    stream = audio.open(
                        format=module.paInt16,
                        channels=PCM_CHANNELS,
                        rate=PCM_SAMPLE_RATE,
                        frames_per_buffer=PCM_BUFFER_FRAMES,
                        output=True,
                    )
                    with self._lock:
                        self._active_stream = stream
                raw_pcm = bytes(pending[:byte_count])
                boosted_pcm = _apply_volume_gain(raw_pcm, gain=1.7)
                stream.write(boosted_pcm)
                del pending[:byte_count]
                played = True

        with self._play_lock:
            try:
                while True:
                    if stop_event.is_set():
                        raise _PlaybackInterrupted
                    try:
                        raw_chunk = next(iterator)
                    except StopIteration:
                        break
                    if stop_event.is_set():
                        raise _PlaybackInterrupted
                    chunk = bytes(raw_chunk) if raw_chunk else b""
                    if not chunk:
                        continue
                    pending.extend(chunk)
                    write_buffer()
                write_buffer(flush=True)
                if stop_event.is_set():
                    raise _PlaybackInterrupted
                return played
            except (_PlaybackInterrupted, _StreamingUnavailable):
                raise
            except Exception as exc:
                if pending and not stop_event.is_set():
                    try:
                        write_buffer(flush=True)
                    except Exception:
                        pass
                raise _ProviderPlaybackError(exc, audio_started=played) from exc
            finally:
                close_iterator = getattr(iterator, "close", None)
                if callable(close_iterator):
                    try:
                        close_iterator()
                    except Exception:
                        pass
                with self._lock:
                    if self._active_stream is stream:
                        self._active_stream = None
                if stream is not None:
                    try:
                        if getattr(stream, "is_active", lambda: False)():
                            stream.stop_stream()
                    except Exception:
                        pass
                    try:
                        stream.close()
                    except Exception:
                        pass

    def stop(self) -> None:
        """Promptly release a blocked/active device stream."""

        with self._lock:
            stream = self._active_stream
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass

    def close(self) -> None:
        self.stop()
        with self._lock:
            audio = self._audio
            self._audio = None
        if audio is not None:
            try:
                audio.terminate()
            except Exception:
                pass


class EdgeTTSPlayer:
    """Queue whole responses and synthesize them through safe provider fallbacks."""

    def __init__(
        self,
        settings: Settings,
        *,
        gemini_client: Any = _UNSET,
        edge_tts_module: Any = _UNSET,
        pygame_module: Any = _UNSET,
        pyaudio_module: Any = _UNSET,
        pcm_player: PCMStreamPlayer | None = None,
        router: TTSRouter | None = None,
        callback: TTSCallback | None = None,
        temp_directory: Path | None = None,
        max_text_chars: int | None = None,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.settings = settings
        if settings.ipv4_first:
            install_ipv4_first_dns()
        self._gemini_client = gemini_client
        self._edge_tts_module = edge_tts_module
        self._pygame_module = pygame_module
        self._pcm_player = pcm_player or PCMStreamPlayer(pyaudio_module)
        self._router = router or TTSRouter(
            settings.tts_usage_file,
            fish_segment_characters=settings.tts_fish_segment_characters,
            gemini_segment_characters=settings.tts_gemini_segment_characters,
        )
        self._callback = callback
        self._temp_directory = temp_directory
        self._max_text_chars = max_text_chars
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._cooldowns: dict[str, float] = {}
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active_music: Any | None = None
        self._active_audio_source: Any | None = None
        self._last_result: TTSResult | None = None
        prepare_speech_engine()

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_result(self) -> TTSResult | None:
        with self._lock:
            return self._last_result

    def speak(self, text: str) -> TTSResult:
        """Select one provider for the complete response in a daemon worker."""

        speech_text = str(text).strip()
        if not speech_text:
            return TTSResult(False, "TTS text empty hai.", error="empty_text")
        self.stop(wait=True, timeout=1.0)
        stop_event = threading.Event()
        worker = threading.Thread(
            target=self._run_worker,
            args=(speech_text, stop_event),
            name="darkshadow-tts-playback",
            daemon=True,
        )
        with self._lock:
            self._stop_event = stop_event
            self._thread = worker
            self._last_result = None
        worker.start()
        return TTSResult(True, "Speech non-blocking playback ke liye queue ho gayi.")

    def stop(self, *, wait: bool = False, timeout: float = 1.0) -> bool:
        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
            music = self._active_music
            audio_source = self._active_audio_source
        was_active = bool(thread and thread.is_alive())
        stop_event.set()
        self._pcm_player.stop()
        close_source = getattr(audio_source, "close", None)
        if callable(close_source):
            try:
                close_source()
            except Exception:
                pass
        if music is not None:
            try:
                music.stop()
            except Exception:
                pass
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        return was_active

    def wait(self, timeout: float | None = None) -> TTSResult | None:
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return self.last_result

    def close(self) -> None:
        self.stop(wait=True, timeout=2.0)
        self._pcm_player.close()
        pygame = self._pygame_module
        if pygame is not _UNSET:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
        if self._gemini_client is not _UNSET and self._gemini_client is not None:
            close_method = getattr(self._gemini_client, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception:
                    pass

    def _get_edge_tts(self) -> Any:
        if self._edge_tts_module is _UNSET:
            self._edge_tts_module = import_module("edge_tts")
        return self._edge_tts_module

    def _get_pygame(self) -> Any:
        if self._pygame_module is _UNSET:
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            self._pygame_module = import_module("pygame")
        return self._pygame_module

    def _get_gemini_client(self) -> Any:
        if self._gemini_client is not _UNSET and self._gemini_client is not None:
            return self._gemini_client
        if not self.settings.api_configured:
            raise _StreamingUnavailable("Gemini API key not configured")
        from google import genai
        self._gemini_client = genai.Client(api_key=self.settings.api_key)
        return self._gemini_client

    def _reset_gemini_client(self) -> None:
        client = self._gemini_client
        self._gemini_client = _UNSET
        if client is _UNSET or client is None:
            return
        close_method = getattr(client, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass

    def _temporary_audio_path(self, suffix: str) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="darkshadow-tts-",
            suffix=suffix,
            dir=str(self._temp_directory) if self._temp_directory else None,
        )
        os.close(descriptor)
        return Path(raw_path)

    def _generate_edge_audio(self, text: str, audio_path: Path) -> None:
        clean_text = _clean_speech_text(text)
        communicator = self._get_edge_tts().Communicate(
            clean_text,
            select_edge_voice(
                clean_text, self.settings.tts_voice, self.settings.tts_english_voice
            ),
            rate=self.settings.tts_rate,
            pitch=self.settings.tts_pitch,
            volume=self.settings.tts_volume,
            connect_timeout=4,
            receive_timeout=8,
        )
        asyncio.run(communicator.save(str(audio_path)))

    def _gemini_stream_chunks(
        self, text: str, stop_event: threading.Event
    ) -> Iterator[bytes]:
        client = self._get_gemini_client()
        self._router.record_attempt("gemini", text)
        speech_content = _clean_gemini_speech_text(text)
        input_prompt = (
            "Speak with a calm, intelligent, emotionally aware voice and natural cadence. "
            "Treat allowed bracketed audio tags such as [laughs], [sighs], [serious], "
            "[excited], [giggles], [trembling], and [whispers] as performance directions; "
            "never read the tag words aloud. "
            f"This text contains Hindi or Romanized Hindi words; pronounce them as Hindi: {speech_content}"
        )
        model_name = self.settings.tts_gemini_model

        interactions_api = getattr(client, "interactions", None)
        if interactions_api is not None and callable(getattr(interactions_api, "create", None)):
            try:
                events = interactions_api.create(
                    model=model_name,
                    input=input_prompt,
                    response_format={"type": "audio"},
                    generation_config={
                        "speech_config": [{"voice": self.settings.tts_gemini_voice}]
                    },
                    timeout=self.settings.tts_gemini_timeout_seconds,
                    stream=True,
                )
                if not hasattr(events, "__iter__") or hasattr(events, "output_audio"):
                    output_audio = getattr(events, "output_audio", None)
                    if output_audio:
                        raw_data = _field(output_audio, "data")
                        decoded = _decode_audio(raw_data)
                        if decoded:
                            yield _strip_wave_header(decoded)
                    return

                with self._lock:
                    self._active_audio_source = events
                try:
                    for event in events:
                        if stop_event.is_set():
                            raise _PlaybackInterrupted
                        raw_data = None
                        delta = _field(event, "delta")
                        if delta:
                            raw_data = _field(delta, "data") or _field(delta, "audio")
                        if not raw_data:
                            raw_data = _field(event, "data") or _field(event, "audio") or _field(event, "output_audio")
                            if raw_data and not isinstance(raw_data, (bytes, str)):
                                raw_data = _field(raw_data, "data")
                        if not raw_data:
                            candidates = _field(event, "candidates")
                            if candidates and isinstance(candidates, (list, tuple)) and len(candidates) > 0:
                                content = _field(candidates[0], "content")
                                parts = _field(content, "parts") if content else None
                                if parts and isinstance(parts, (list, tuple)) and len(parts) > 0:
                                    inline_data = _field(parts[0], "inline_data")
                                    raw_data = _field(inline_data, "data") if inline_data else None

                        if raw_data:
                            decoded = _decode_audio(raw_data)
                            if decoded:
                                yield _strip_wave_header(decoded)
                    return
                finally:
                    with self._lock:
                        if self._active_audio_source is events:
                            self._active_audio_source = None
                    close_method = getattr(events, "close", None)
                    if callable(close_method):
                        try:
                            close_method()
                        except Exception:
                            pass
            except _PlaybackInterrupted:
                raise
            except Exception:
                pass

        # Fallback to models.generate_content with AUDIO modality
        models_api = getattr(client, "models", None)
        if models_api is not None and callable(getattr(models_api, "generate_content", None)):
            from google.genai import types
            config = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self.settings.tts_gemini_voice
                        )
                    )
                ),
            )
            response = models_api.generate_content(
                model=model_name,
                contents=input_prompt,
                config=config,
            )
            candidates = getattr(response, "candidates", None)
            if candidates and len(candidates) > 0:
                parts = getattr(candidates[0].content, "parts", None)
                if parts:
                    for part in parts:
                        inline_data = getattr(part, "inline_data", None)
                        if inline_data and getattr(inline_data, "data", None):
                            decoded = _decode_audio(inline_data.data)
                            if decoded:
                                yield _strip_wave_header(decoded)
                                return

    def _play_gemini(self, text: str, stop_event: threading.Event) -> None:
        if not self._pcm_player.play_chunks(self._gemini_stream_chunks(text, stop_event), stop_event):
            raise ValueError("Gemini TTS returned empty audio")

    def _play_gemini_with_start_deadline(
        self,
        text: str,
        stop_event: threading.Event,
    ) -> None:
        """Start Gemini in a daemon and bound time-to-first-audio."""

        provider_stop = threading.Event()
        finished = threading.Event()
        errors: list[Exception] = []

        def run_provider() -> None:
            try:
                self._play_gemini(text, provider_stop)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        provider_thread = threading.Thread(
            target=run_provider,
            daemon=True,
            name="darkshadow-gemini-first-audio",
        )
        provider_thread.start()
        first_audio_deadline = time.monotonic() + min(
            4.0,
            max(1.0, self.settings.tts_gemini_timeout_seconds),
        )

        while not finished.wait(0.05):
            if stop_event.is_set():
                provider_stop.set()
                self._reset_gemini_client()
                raise _PlaybackInterrupted
            if self._pcm_player.has_active_stream:
                break
            if time.monotonic() >= first_audio_deadline:
                provider_stop.set()
                self._reset_gemini_client()
                raise TimeoutError("Gemini TTS first audio timed out")

        # Once playback begins, allow the stream to finish while preserving
        # immediate cancellation from the UI.
        while not finished.wait(0.05):
            if stop_event.is_set():
                provider_stop.set()
                self._reset_gemini_client()
                raise _PlaybackInterrupted

        if stop_event.is_set():
            raise _PlaybackInterrupted
        if errors:
            raise errors[0]

    def _generate_fish_audio(self, text: str, output_path: Path) -> None:
        api_key = self.settings.fish_api_key
        if not api_key:
            raise ValueError("Fish Audio API key not configured")
        url = "https://api.fish.audio/v1/tts"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "text": text,
            "format": "mp3",
            "latency": getattr(self.settings, "tts_fish_latency", "normal"),
        }
        if self.settings.tts_fish_reference_id:
            payload["reference_id"] = self.settings.tts_fish_reference_id
        if getattr(self.settings, "tts_fish_model", None):
            payload["model"] = self.settings.tts_fish_model

        import httpx
        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(
                    f"Fish Audio TTS failed ({response.status_code}): {response.text[:200]}"
                )
            output_path.write_bytes(response.content)

    def _play_fish(self, text: str, stop_event: threading.Event) -> None:
        audio_path = self._temporary_audio_path(".mp3")
        try:
            self._router.record_attempt("fish", text)
            self._generate_fish_audio(text, audio_path)
            self._play_file(audio_path, stop_event)
        finally:
            audio_path.unlink(missing_ok=True)

    def _play_file(self, audio_path: Path, stop_event: threading.Event) -> None:
        if stop_event.is_set():
            raise _PlaybackInterrupted
        pygame = self._get_pygame()
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        music = pygame.mixer.music
        with self._lock:
            self._active_music = music
        started = False
        try:
            music.load(str(audio_path))
            music.play()
            started = True
            while music.get_busy():
                if stop_event.wait(0.05):
                    music.stop()
                    raise _PlaybackInterrupted
        except _PlaybackInterrupted:
            raise
        except Exception as exc:
            raise _ProviderPlaybackError(exc, audio_started=started) from exc
        finally:
            try:
                music.unload()
            except Exception:
                pass

    def _play_edge(self, text: str, stop_event: threading.Event) -> None:
        audio_path = self._temporary_audio_path(".mp3")
        try:
            self._generate_edge_audio(text, audio_path)
            self._play_file(audio_path, stop_event)
        finally:
            audio_path.unlink(missing_ok=True)

    def _cooling_down(self, provider: str) -> bool:
        return time.monotonic() < self._cooldowns.get(provider, 0.0)

    def _mark_failure(self, provider: str) -> None:
        self._cooldowns[provider] = time.monotonic() + self._cooldown_seconds

    def _provider_order(self) -> tuple[str, ...]:
        primary = self.settings.tts_provider
        if primary == "offline":
            return ("offline",)
        if primary == "gemini":
            order = ["gemini", "offline"]
        elif primary == "fish":
            order = ["fish", "gemini", "edge"]
        elif primary == "auto":
            first = self._router.selected_provider(
                gemini_available=self.settings.api_configured and not self._cooling_down("gemini"),
                fish_available=self.settings.fish_configured and not self._cooling_down("fish"),
            )
            if first == "gemini":
                order = ["gemini", "fish", "edge"]
            else:
                order = ["fish", "gemini", "edge"]
        elif primary == "edge":
            order = ["edge", "gemini", "fish"]
        else:
            order = ["gemini", "fish", "edge"]

        if self.settings.tts_edge_fallback and "edge" not in order:
            order.append("edge")
        return tuple(order)

    @staticmethod
    def _error_status(exc: Exception) -> object:
        return getattr(exc, "status_code", None) or getattr(exc, "code", None)

    def _run_worker(self, text: str, stop_event: threading.Event) -> None:
        attempted: list[str] = []
        try:
            for provider in self._provider_order():
                if provider in attempted:
                    continue
                attempted.append(provider)
                if stop_event.is_set():
                    raise _PlaybackInterrupted
                if provider == "gemini" and (
                    not self.settings.api_configured or self._cooling_down(provider)
                ):
                    continue
                if provider == "fish" and (
                    not self.settings.fish_configured or self._cooling_down(provider)
                ):
                    continue
                try:
                    if provider == "gemini":
                        self._play_gemini_with_start_deadline(text, stop_event)
                    elif provider == "fish":
                        self._play_fish(_clean_speech_text(text), stop_event)
                    elif provider == "edge":
                        self._play_edge(text, stop_event)
                    elif provider == "offline":
                        if speak_response(text):
                            wait_for_speech()
                            self._finish(TTSResult(True, "Offline Windows voice playback complete."))
                            return
                        raise RuntimeError("Offline Windows voice unavailable")

                    if provider == "edge" and any(
                        cloud in attempted for cloud in ("fish", "gemini")
                    ):
                        message = "Cloud TTS failed; Edge fallback playback complete."
                    else:
                        message = f"Speech playback complete ({provider})."
                    self._finish(TTSResult(True, message))
                    return
                except _PlaybackInterrupted:
                    raise
                except Exception as exc:
                    actual_error = (
                        exc.cause if isinstance(exc, _ProviderPlaybackError) else exc
                    )
                    if provider in {"gemini", "fish"}:
                        self._mark_failure(provider)
                    LOGGER.warning(
                        "%s TTS failed (type=%s, status=%s)",
                        provider.capitalize(),
                        type(actual_error).__name__,
                        self._error_status(actual_error),
                    )
                    if (
                        isinstance(exc, _ProviderPlaybackError)
                        and exc.audio_started
                    ):
                        self._finish(
                            TTSResult(
                                False,
                                "Streaming TTS partial playback ke baad fail hui; "
                                "voice switch nahi ki gayi.",
                                error="tts_error",
                            )
                        )
                        return

            if speak_response(text):
                wait_for_speech()
                self._finish(TTSResult(True, "Offline Windows voice playback complete."))
                return

            self._finish(
                TTSResult(
                    False,
                    "TTS fail hui; answer screen par available hai.",
                    error="tts_error",
                )
            )
        except _PlaybackInterrupted:
            self._finish(
                TTSResult(
                    False,
                    "Speech playback interrupt hui.",
                    error="interrupted",
                    interrupted=True,
                )
            )
        finally:
            with self._lock:
                music = self._active_music
                self._active_music = None
            if music is not None:
                try:
                    music.unload()
                except Exception:
                    pass

    def _finish(self, result: TTSResult) -> None:
        with self._lock:
            self._last_result = result
        if self._callback is not None:
            try:
                self._callback(result)
            except Exception as exc:
                LOGGER.warning("TTS callback failed (type=%s)", type(exc).__name__)


__all__ = ["EdgeTTSPlayer", "PCMStreamPlayer", "TTSResult"]
