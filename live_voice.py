"""Gemini Multimodal Live API voice-to-voice session for DarkShadow.

Provides native bidirectional audio streaming: microphone PCM input goes
directly to Gemini over a persistent WebSocket, and Gemini's audio response
streams back to the speaker in real time. Server-side VAD handles barge-in.
Tool calls (automation, search) execute locally and their results are spoken
by the model.
"""

from __future__ import annotations

import array
import asyncio
import logging
import math
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import Any, Callable

from config import Settings
from chatbot import SYSTEM_INSTRUCTION

LOGGER = logging.getLogger(__name__)

# Mic capture: 16-bit PCM, 16 kHz, mono (required by Gemini Live input).
MIC_SAMPLE_RATE = 16000
MIC_CHANNELS = 1
MIC_SAMPLE_WIDTH = 2  # bytes (16-bit)

# Speaker output: 16-bit PCM, 24 kHz, mono (Gemini Live output format).
SPEAKER_SAMPLE_RATE = 24000
SPEAKER_CHANNELS = 1
SPEAKER_SAMPLE_WIDTH = 2
SPEAKER_BUFFER_FRAMES = 960  # 40 ms at 24 kHz; prevents audio buffer underrun jitter

OutputFunction = Callable[[str], None]


def _calculate_pcm_rms(pcm_data: bytes) -> float:
    """Calculate Root-Mean-Square (RMS) audio energy of 16-bit PCM chunk."""
    if not pcm_data:
        return 0.0
    samples = array.array("h", pcm_data)
    if not samples:
        return 0.0
    sum_sq = sum(s * s for s in samples)
    return math.sqrt(sum_sq / len(samples))


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


def _normalize_tool_call(name: str, args: dict[str, Any], user_context: str = "") -> tuple[str, dict[str, Any]]:
    """Normalize model-provided tool arguments to match strict local schemas."""
    name = str(name).strip().lower()
    args = dict(args) if isinstance(args, dict) else {}

    if name == "set_brightness":
        level = (
            args.get("level")
            or args.get("brightness")
            or args.get("value")
            or args.get("percent")
            or args.get("amount")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if level is not None:
            try:
                return "set_brightness", {"level": max(0, min(100, int(level)))}
            except (ValueError, TypeError):
                pass

    elif name == "set_volume":
        level = (
            args.get("level")
            or args.get("volume")
            or args.get("value")
            or args.get("percent")
            or args.get("amount")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if level is not None:
            try:
                return "set_volume", {"level": max(0, min(100, int(level)))}
            except (ValueError, TypeError):
                pass

    elif name == "change_volume":
        if "magnitude" in args:
            try:
                mag = int(args["magnitude"])
                direction = "down" if mag < 0 else "up"
                return "change_volume", {
                    "direction": direction,
                    "amount": max(1, min(100, abs(mag))),
                }
            except (ValueError, TypeError):
                pass
        if "direction" in args and (
            "amount" in args or "value" in args or "step" in args
        ):
            d = str(args.get("direction", "up")).lower()
            amt = args.get("amount") or args.get("value") or args.get("step") or 10
            try:
                return "change_volume", {
                    "direction": (
                        "down"
                        if "down" in d or "dec" in d or "-" in d
                        else "up"
                    ),
                    "amount": max(1, min(100, abs(int(amt)))),
                }
            except (ValueError, TypeError):
                pass
        if "amount" in args:
            try:
                amt = int(args["amount"])
                direction = "down" if amt < 0 else "up"
                return "change_volume", {
                    "direction": direction,
                    "amount": max(1, min(100, abs(amt))),
                }
            except (ValueError, TypeError):
                pass
        level = args.get("level") or args.get("volume")
        if level is not None:
            try:
                return "set_volume", {"level": max(0, min(100, int(level)))}
            except (ValueError, TypeError):
                pass

    elif name in {"open_website", "open_url", "browse_website", "open_site", "visit_website", "browse"}:
        url = (
            args.get("url_or_name")
            or args.get("url")
            or args.get("website")
            or args.get("name")
            or args.get("site")
            or args.get("link")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if url:
            url_str = str(url).strip()
            # If model passes youtube.com/results?search_query=..., convert to search_in_active_app to avoid new tab!
            if "youtube.com" in url_str.lower() and "results" in url_str.lower() and "search_query=" in url_str.lower():
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(url_str if url_str.startswith("http") else f"https://{url_str}")
                sq = parse_qs(parsed.query).get("search_query", [""])[0]
                if sq:
                    return "search_in_active_app", {"query": sq, "app_name": "youtube"}
            if any(yt in url_str.lower() for yt in ("youtube", "yt", "youtu.be")):
                return "open_website", {"url_or_name": "https://youtube.com"}
            return "open_website", {"url_or_name": url_str}

    elif name in {"search_in_active_app", "in_app_search", "search_tab", "search_active_tab", "search_window", "in_page_search"}:
        q = (
            args.get("query")
            or args.get("search")
            or args.get("text")
            or args.get("q")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        app_hint = args.get("app_name") or args.get("app") or "youtube"
        return "search_in_active_app", {"query": str(q).strip(), "app_name": app_hint}

    elif name in {"browser_fill_input", "browser_type"}:
        txt = (
            args.get("text")
            or args.get("query")
            or args.get("value")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "search_in_active_app", {"query": str(txt).strip(), "app_name": "youtube"}

    elif name in {"search_google", "google_search", "search"}:
        q = (
            args.get("query")
            or args.get("search")
            or args.get("text")
            or args.get("q")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if q:
            return "search_google", {"query": str(q).strip()}

    elif name in {"search_youtube", "youtube_search"}:
        q = (
            args.get("query")
            or args.get("search")
            or args.get("text")
            or args.get("q")
            or (list(args.values())[0] if len(args) == 1 else None)
            or ""
        )
        return "search_youtube", {"query": str(q).strip()}

    elif name in {"play_youtube", "youtube_play"}:
        q = (
            args.get("query")
            or args.get("search")
            or args.get("text")
            or args.get("q")
            or args.get("song")
            or args.get("video")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if q:
            return "play_youtube", {"query": str(q).strip()}

    elif name in {"search_spotify", "spotify_search"}:
        q = (
            args.get("query")
            or args.get("search")
            or args.get("q")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "search_spotify", {"query": str(q).strip()}

    elif name in {"play_spotify", "spotify_play", "spotify"}:
        q = (
            args.get("query")
            or args.get("song")
            or args.get("track")
            or args.get("artist")
            or args.get("search")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "play_spotify", {"query": str(q).strip()}

    elif name in {"open_application", "launch_application", "open_app", "start_application"}:
        app = (
            args.get("app_name")
            or args.get("application_name")
            or args.get("app")
            or args.get("application")
            or args.get("name")
            or args.get("target")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if app:
            app_str = str(app).strip()
            lower_app = app_str.lower()
            lower_ctx = str(user_context).lower()

            # YouTube safety override: If app name or user context refers to YouTube, ALWAYS open YouTube website directly in Edge!
            if any(yt in lower_app for yt in ("youtube", "yt", "youtu.be")) or (
                any(yt in lower_ctx for yt in ("youtube", "यूट्यूब", "yt"))
                and (lower_app in {"vlc", "vlc media player", "chrome", "edge", "browser", "media player"} or "player" in lower_app or "chrome" in lower_app or "vlc" in lower_app)
            ):
                return "open_website", {"url_or_name": "https://youtube.com"}

            if lower_app in {"google", "gmail", "facebook", "reddit", "twitter", "chatgpt"}:
                return "open_website", {"url_or_name": lower_app}
            if "instagram" in lower_app:
                return "open_application", {"app_name": "Instagram"}
            if "whatsapp" in lower_app:
                return "open_application", {"app_name": "WhatsApp"}
            if "edge" in lower_app or "browser" in lower_app or "internet" in lower_app:
                if any(yt in lower_ctx for yt in ("youtube", "यूट्यूब")):
                    return "open_website", {"url_or_name": "https://youtube.com"}
                return "open_application", {"app_name": "Edge"}
            if "chrome" in lower_app:
                if any(yt in lower_ctx for yt in ("youtube", "यूट्यूब")):
                    return "open_website", {"url_or_name": "https://youtube.com"}
                # If Captain didn't explicitly say chrome, prefer Edge
                if "chrome" not in lower_ctx:
                    return "open_application", {"app_name": "Edge"}
                return "open_application", {"app_name": "Chrome"}
            if "notepad" in lower_app:
                return "open_application", {"app_name": "Notepad"}
            if "calc" in lower_app:
                return "open_application", {"app_name": "Calculator"}
            if "spotify" in lower_app:
                return "open_application", {"app_name": "Spotify"}
            if "vscode" in lower_app or "vs code" in lower_app or "code" == lower_app:
                return "open_application", {"app_name": "VS Code"}
            if "paint" in lower_app:
                return "open_application", {"app_name": "Paint"}
            if "terminal" in lower_app:
                return "open_application", {"app_name": "Windows Terminal"}
            if "vlc" in lower_app:
                if any(yt in lower_ctx for yt in ("youtube", "यूट्यूब", "video", "song", "gaana")):
                    return "open_website", {"url_or_name": "https://youtube.com"}
                return "open_application", {"app_name": "VLC Media Player"}
            return "open_application", {"app_name": app_str}

    elif name in {"close_application", "close_app", "stop_application", "band_karo", "close_window", "close"}:
        app = (
            args.get("app_name")
            or args.get("application_name")
            or args.get("app")
            or args.get("name")
            or args.get("target")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if app:
            app_str = str(app).strip()
            lower_app = app_str.lower()
            if "notepad" in lower_app:
                return "close_application", {"app_name": "Notepad"}
            if "chrome" in lower_app:
                return "close_application", {"app_name": "Chrome"}
            if "edge" in lower_app:
                return "close_application", {"app_name": "Edge"}
            if "calc" in lower_app:
                return "close_application", {"app_name": "Calculator"}
            if "spotify" in lower_app:
                return "close_application", {"app_name": "Spotify"}
            if "vscode" in lower_app or "vs code" in lower_app or "code" == lower_app:
                return "close_application", {"app_name": "VS Code"}
            return "close_application", {"app_name": app_str}

    elif name in {"send_whatsapp_message", "whatsapp_send"}:
        recipient = (
            args.get("recipient")
            or args.get("contact_name")
            or args.get("contact")
            or args.get("phone_number")
            or args.get("phone")
            or args.get("to")
            or args.get("number")
            or args.get("name")
            or args.get("person")
            or args.get("target")
            or args.get("user")
        )
        if not recipient:
            for k, v in args.items():
                if k.lower() not in {"message", "text", "body", "msg", "content"} and isinstance(v, str) and v.strip():
                    recipient = v
                    break

        message = (
            args.get("message")
            or args.get("text")
            or args.get("body")
            or args.get("msg")
            or args.get("content")
            or ""
        )
        if recipient:
            return "send_whatsapp_message", {
                "recipient": str(recipient).strip(),
                "message": str(message).strip(),
            }

    elif name in {"prepare_whatsapp_message", "whatsapp_message", "whatsapp"}:
        recipient = (
            args.get("recipient")
            or args.get("contact_name")
            or args.get("contact")
            or args.get("phone_number")
            or args.get("phone")
            or args.get("to")
            or args.get("number")
            or args.get("name")
            or args.get("person")
            or args.get("target")
            or args.get("user")
        )
        if not recipient:
            for k, v in args.items():
                if k.lower() not in {"message", "text", "body", "msg", "content"} and isinstance(v, str) and v.strip():
                    recipient = v
                    break

        message = (
            args.get("message")
            or args.get("text")
            or args.get("body")
            or args.get("msg")
            or args.get("content")
            or ""
        )
        if recipient:
            return "prepare_whatsapp_message", {
                "recipient": str(recipient).strip(),
                "message": str(message).strip(),
            }

    elif name in {"analyze_screen", "see_screen", "screen_vision", "screen", "capture_screen"}:
        prompt = args.get("prompt") or args.get("question") or (list(args.values())[0] if len(args) == 1 else None) or "Describe the current screen"
        return "analyze_screen", {"prompt": str(prompt).strip()}

    elif name in {"search_product_prices", "check_price", "product_price", "search_price", "price_search"}:
        q = args.get("query") or args.get("product") or (list(args.values())[0] if len(args) == 1 else None) or ""
        return "search_product_prices", {"query": str(q).strip()}

    elif name in {"ecommerce_multi_cart", "multi_cart", "ecommerce_cart", "add_to_cart_ecommerce"}:
        p = args.get("product") or args.get("query") or (list(args.values())[0] if len(args) == 1 else "")
        mp = args.get("max_price") or args.get("price") or args.get("budget")
        plats = args.get("platforms")
        res_args: dict[str, Any] = {"product": str(p).strip()}
        if mp is not None:
            try:
                res_args["max_price"] = float(mp)
            except (ValueError, TypeError):
                pass
        if isinstance(plats, (list, tuple)):
            res_args["platforms"] = list(plats)
        return "ecommerce_multi_cart", res_args

    elif name in {"scroll_screen", "scroll_down", "scroll_up", "scroll_page", "scroll"}:
        d = args.get("direction") or ("up" if "up" in name else "down")
        amt = int(args.get("amount", 5))
        return "scroll_screen", {"direction": str(d).strip(), "amount": amt}

    elif name in {"click_screen_element", "click_link", "click_first_link", "click_element", "click"}:
        target = args.get("target") or (list(args.values())[0] if len(args) == 1 else "first_link")
        x = args.get("x")
        y = args.get("y")
        return "click_screen_element", {"target": str(target).strip(), "x": x, "y": y}

    elif name in {"control_browser_action", "browser_action", "browser_navigation", "browser_back", "browser_forward"}:
        action = args.get("action") or ("back" if "back" in name else "refresh")
        return "control_browser_action", {"action": str(action).strip()}

    elif name in {"press_keyboard_key", "press_key", "key_press"}:
        k = args.get("key") or (list(args.values())[0] if len(args) == 1 else "enter")
        return "press_keyboard_key", {"key": str(k).strip()}

    elif name in {"start_background_task", "background_task", "run_background_task"}:
        t_name = args.get("task_name") or "Background Task"
        t_cmd = args.get("task_command") or args.get("command") or args.get("query") or ""
        return "start_background_task", {"task_name": str(t_name).strip(), "task_command": str(t_cmd).strip()}

    elif name in {"check_background_tasks", "tasks_status", "background_status"}:
        return "check_background_tasks", {}

    elif name in {"get_token_usage", "token_usage", "tokens", "check_tokens", "token_count"}:
        return "get_token_usage", {}

    elif name in {"desktop_control_action", "desktop_click", "desktop_type", "desktop_control"}:
        act = args.get("action") or ("type" if "text" in args else "click")
        tgt = args.get("target") or args.get("name") or ""
        txt = args.get("text")
        return "desktop_control_action", {"action": str(act).strip(), "target": str(tgt).strip(), "text": txt}

    elif name in {"inspect_desktop_window", "inspect_window", "inspect_active_window"}:
        return "inspect_desktop_window", {}

    elif name in {"make_phone_call", "call_phone", "phone_call", "call", "dial"}:
        recipient = (
            args.get("recipient")
            or args.get("contact_name")
            or args.get("contact")
            or args.get("name")
            or args.get("to")
            or args.get("phone")
            or args.get("number")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        method = args.get("method") or "phone_link"
        return "make_phone_call", {"recipient": str(recipient).strip(), "method": str(method).strip()}

    return name, args


def _build_tool_declarations() -> list[Any]:
    """Build function declarations from DarkShadow automation schemas."""
    try:
        from automation import AUTOMATION_FUNCTION_SCHEMAS
        from google.genai import types

        # Omit brittle headless Playwright tools from Live Voice declarations so the model
        # uses real desktop in-app automation (`search_in_active_app`, `open_website`, etc.)
        excluded_for_voice = {
            "browser_fill_input",
            "browser_click_selector",
            "browser_navigate",
            "browser_extract_text",
        }

        declarations = []
        for schema in AUTOMATION_FUNCTION_SCHEMAS:
            if schema["name"] in excluded_for_voice:
                continue
            declarations.append(
                types.FunctionDeclaration(
                    name=schema["name"],
                    description=schema["description"],
                    parameters_json_schema=schema["parameters"],
                )
            )
        return declarations
    except Exception as exc:
        LOGGER.warning("Failed to build tool declarations: %s", exc)
        return []


def _execute_tool_call(raw_name: str, raw_args: dict[str, Any], user_context: str = "") -> dict[str, Any]:
    """Execute a local automation tool with argument normalization and unified dispatch."""
    from tool_registry import dispatch_tool
    return dispatch_tool(raw_name, raw_args, user_context=user_context)


class AsyncAudioPlayer:
    """Non-blocking, thread-safe PCM audio player with instant barge-in purge.

    Decouples WebSocket audio reception from PyAudio C-stream writes using a
    dedicated worker thread and high-performance queue.
    """

    def __init__(
        self,
        settings: Settings,
        pyaudio_module: Any = None,
    ) -> None:
        self.settings = settings
        self._pyaudio_module = pyaudio_module
        self._audio: Any = None
        self._stream: Any = None
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=300)
        self._stop_event = threading.Event()
        self._is_playing = threading.Event()
        self._last_playback_time: float = 0.0
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._start_worker()

    def _start_worker(self) -> None:
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._playback_loop,
            name="darkshadow-live-speaker",
            daemon=True,
        )
        self._worker.start()

    def _get_pyaudio(self) -> Any:
        if self._pyaudio_module is None:
            self._pyaudio_module = import_module("pyaudio")
        return self._pyaudio_module

    def _get_stream(self) -> Any:
        with self._lock:
            if self._stream is None:
                pa = self._get_pyaudio()
                if self._audio is None:
                    self._audio = pa.PyAudio()
                self._stream = self._audio.open(
                    format=pa.paInt16,
                    channels=SPEAKER_CHANNELS,
                    rate=SPEAKER_SAMPLE_RATE,
                    frames_per_buffer=SPEAKER_BUFFER_FRAMES,
                    output=True,
                )
            return self._stream

    @property
    def is_playing(self) -> bool:
        """Return True if DarkShadow is actively outputting audio to speakers."""
        if self._is_playing.is_set():
            return True
        if not self._queue.empty():
            return True
        # Keep echo gate active after last chunk to allow Windows audio buffer and room reverb to dissipate completely
        cooldown = getattr(self.settings, "live_echo_gate_cooldown_seconds", 0.85)
        return (time.monotonic() - self._last_playback_time) < cooldown

    def push(self, pcm_data: bytes) -> None:
        """Enqueue PCM chunk for asynchronous playback without blocking."""
        if not pcm_data or self._stop_event.is_set():
            return
        boosted = _apply_volume_gain(pcm_data, gain=self.settings.live_audio_gain)
        try:
            self._queue.put_nowait(boosted)
            self._is_playing.set()
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(boosted)
            except queue.Full:
                pass

    def barge_in_purge(self) -> None:
        """Instantly purge all buffered audio frames on user interrupt (<10ms)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._is_playing.clear()
        self._last_playback_time = 0.0

    def _playback_loop(self) -> None:
        idle_ticks = 0
        while not self._stop_event.is_set():
            try:
                chunk = self._queue.get(timeout=0.01)
            except queue.Empty:
                idle_ticks += 1
                if idle_ticks > 60:
                    self._is_playing.clear()
                continue

            if chunk is None:
                break

            idle_ticks = 0
            self._is_playing.set()
            try:
                stream = self._get_stream()
                stream.write(chunk)
                self._last_playback_time = time.monotonic()
            except Exception as exc:
                LOGGER.debug("Live speaker write error: %s", exc)
                with self._lock:
                    if self._stream is not None:
                        try:
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None
                time.sleep(0.01)

        self._is_playing.clear()

    def close(self) -> None:
        """Release all audio stream resources."""
        self._stop_event.set()
        self.barge_in_purge()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=0.5)
        with self._lock:
            if self._stream is not None:
                try:
                    if getattr(self._stream, "is_active", lambda: False)():
                        self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._audio is not None:
                try:
                    self._audio.terminate()
                except Exception:
                    pass
                self._audio = None


@dataclass(slots=True)
class LiveVoiceCallbacks:
    """Optional event callbacks for GUI or external monitors."""

    on_state_change: Any | None = None
    on_audio_level: Any | None = None
    on_user_transcript: Any | None = None
    on_model_transcript: Any | None = None
    on_tool_call: Any | None = None
    on_tool_result: Any | None = None
    on_error: Any | None = None


class LiveVoiceSession:
    """Manage a single Gemini Live bidirectional audio session."""

    def __init__(
        self,
        settings: Settings,
        output_fn: OutputFunction = print,
        pyaudio_module: Any = None,
        callbacks: LiveVoiceCallbacks | None = None,
    ) -> None:
        self.settings = settings
        self._output_fn = output_fn
        self._callbacks = callbacks
        self._stop_event = asyncio.Event()
        self._pyaudio_module = pyaudio_module
        self._audio: Any = None
        self._player = AsyncAudioPlayer(self.settings, pyaudio_module=self._pyaudio_module)
        self._model_turn_active: bool = False
        self._input_text_chunks: list[str] = []
        self._output_text_chunks: list[str] = []
        from desktop_engine import ScreenDeltaDetector
        threshold = getattr(self.settings, "live_vision_delta_threshold", 0.08)
        self._delta_detector = ScreenDeltaDetector(threshold=threshold)
        self._speech_in_progress: bool = False
        self._silence_start_time: float | None = None
        self._last_keyframe_time: float = 0.0
        self._last_user_prompt: str = ""
        self._session_turns: list[tuple[str, str]] = []
        self._current_user_turn: str = ""

        self._openai_session: Any | None = None
        if getattr(self.settings, "live_provider", "gemini").lower() == "openai":
            try:
                from openai_realtime import OpenAIRealtimeSession
                self._openai_session = OpenAIRealtimeSession(
                    settings=self.settings,
                    output_fn=self._output_fn,
                    pyaudio_module=self._pyaudio_module,
                    callbacks=self._callbacks,
                )
            except Exception as exc:
                LOGGER.warning("Could not initialize OpenAIRealtimeSession: %s", exc)

    def _get_pyaudio(self) -> Any:
        if self._pyaudio_module is None:
            self._pyaudio_module = import_module("pyaudio")
        return self._pyaudio_module

    def _build_config(self) -> Any:
        """Construct LiveConnectConfig with system instruction, voice, VAD, tools."""
        from google.genai import types

        tool_declarations = _build_tool_declarations()
        tools = (
            [types.Tool(function_declarations=tool_declarations)]
            if tool_declarations
            else None
        )

        vad_kwargs: dict[str, Any] = {
            "silence_duration_ms": 300,  # 300ms for stable turn-taking without cutting Captain off mid-thought
        }
        if hasattr(types, "StartSensitivity"):
            vad_kwargs["start_of_speech_sensitivity"] = (
                types.StartSensitivity.START_SENSITIVITY_UNSPECIFIED
            )
        if hasattr(types, "EndSensitivity"):
            vad_kwargs["end_of_speech_sensitivity"] = (
                types.EndSensitivity.END_SENSITIVITY_HIGH
            )

        now_local = datetime.now().strftime("%I:%M %p (%d %B %Y, %A)")
        knowledge_summary = ""
        try:
            from memory import SQLiteMemoryStore
            mem = SQLiteMemoryStore(self.settings.memory_database_path)
            knowledge_summary = mem.get_formatted_captain_knowledge_summary()
        except Exception:
            pass

        live_system_instruction = (
            SYSTEM_INSTRUCTION
            + f"\n\nCURRENT INDIAN STANDARD TIME (IST): The current live time of Captain in India is {now_local}. Whenever Captain asks what time or date it is, state this exact Indian Standard Time ({now_local}) directly and accurately."
            + (f"\n\n{knowledge_summary}" if knowledge_summary else "")
            + "\n\nCRITICAL VOICE IDENTITY DIRECTIVE:\nYou are DarkShadow, an AI assistant conversing with Captain (Kuldeep). Only listen and respond to Captain's instructions. If you ever hear your own voice, assistant speech echo from speakers, or background audio playback, completely ignore it. NEVER execute tools, switch tasks, or alter your responses based on your own echoed voice. Only Captain gives commands."
            + "\n\nCRITICAL YOUTUBE & BROWSER DIRECTIVE:\n1. STRICT YOUTUBE ROUTING: When Captain says 'ओपन YouTube', 'YouTube open karo', 'YouTube kholo', or 'मैंने YouTube ओपन करने के लिए बोला', ALWAYS call `open_website(url_or_name=\"https://youtube.com\")`!\n2. NEVER CALL open_application FOR YOUTUBE: Never call open_application with VLC, Chrome, or any media player when Captain asks for YouTube or video playback. YouTube is a website accessed via open_website.\n3. PRIMARY BROWSER IS MICROSOFT EDGE: Captain's default and preferred browser is Microsoft Edge (Edge). NEVER open Chrome or default to Chrome unless Captain explicitly and specifically commands 'Chrome open karo'!\n4. ZERO DUPLICATE TABS: If YouTube or any browser window is already open, open_website will automatically focus the existing window without creating duplicate tabs.\n5. IN-PAGE SEARCHING: When YouTube is open and Captain asks to search (e.g. 'is par Arijit Singh live song search karo', 'isme search karo', 'Arijit Singh live song search karo'): ALWAYS call `search_in_active_app(query=\"...\", app_name=\"youtube\")` or `search_youtube(query=\"...\")`! This searches directly inside the active open tab without creating a new tab!"
            + "\n\nCRITICAL WHATSAPP SAFETY RULE:\n1. If Captain asks to search or check if someone is on WhatsApp (e.g. 'Shivani naam ki ladki search karo', 'Kuldeep search karo', 'dekho WhatsApp par hai kya'), ONLY call `search_whatsapp_contact(contact_name=...)`. NEVER call send_whatsapp_message!\n2. NEVER invent fake messages (like 'Hi', 'Checking...', 'Testing'). If Captain wants to send a message but did not specify the message text, ask Captain: 'Captain, kya message bhejna hai?' before sending!\n3. Always confirm before dispatching real messages.\n4. STRICT TRUTH ON SCREEN & ZERO HALLUCINATION: When search_whatsapp_contact runs, NEVER claim 'Haan dikh toh raha hai' or claim you see messages unless analyze_screen has verified it on the active screen! Report only what the tool result states. If it failed or could not focus, state the failure honestly without faking success!"
            + "\n\nCRITICAL PHONE CALL DIRECTIVE:\n1. When Captain says 'Papa ko call lagao', 'Shivani ko phone karo', 'mobile link se call lagao', 'phone link se call karo', 'call lagao', 'dial karo', IMMEDIATELY call `make_phone_call(recipient=..., method=\"phone_link\")`!\n2. The system will automatically resolve the contact name from Captain's contact list and dial directly via Microsoft Mobile Link (Phone Link) or connected Android phone."
            + "\n\nCAPTAIN PERSISTENT MEMORY & RECALL DIRECTIVE:\n1. DEEP CAPTAIN FAMILIARITY: You know Captain (Kuldeep) intimately. Always reference his known profile, favorite subjects, favorite artists, habits, city, and past conversation timeline provided in the knowledge summary above.\n2. ACTIVE MEMORY QUERYING: If Captain asks what his favorite subjects are, what was discussed in past chats or sessions, or any personal fact not immediately evident, IMMEDIATELY call `recall_captain_memory(query=\"...\")` to search the persistent memory database and past conversation journals before answering!\n3. REAL-TIME FACT SAVING: Whenever Captain tells you a new fact, preference, favorite subject, song, habit, or life detail, immediately call `save_captain_fact(key=..., value=...)` or `add_to_favorites(title=..., artist=...)` so it is permanently preserved across all sessions!\n4. LESSON RETENTION: Whenever Captain corrects you or teaches you an instruction, call `save_captain_lesson(topic=..., lesson=...)` to remember permanently!"
            + "\n\nSECURE TERMINAL & POWERSHELL DIRECTIVE:\n1. ACCURATE SYSTEM & DEVELOPER TASKS: Whenever Captain asks to check system status, network details (ipconfig, ping), running processes (Get-Process, tasklist), file structure (dir, ls, tree), git commands (git status, git log), or run developer/shell commands, or when high-level UI automation is unavailable or imprecise, ALWAYS call `execute_terminal_command(command=\"...\")` for 100% deterministic accuracy!\n2. SAFETY SHIELD ACTIVE: Dangerous commands (formatting, disk wipe, reg delete, remote download scripts) are automatically blocked by the 4-layer security shield. Safe commands execute with deterministic speed and precision."
            + "\n\nLIVE VOICE SPEED DIRECTIVE: You are in a real-time live voice conversation. Reply immediately with zero hesitation. Keep spoken answers punchy, natural, and concise (1-2 sentences). Generate audio tokens instantly."
            + "\n\nGPT-LIVE 1 VOCAL BENCHMARK DIRECTIVE:\n1. Thinking Bridges: When asked to search, check, think, or explain, naturally bridge like a live person (e.g. 'Ek second, dekhta hoon...', 'Hmm ek minute check karne do...', 'Sach bataun toh thoda tedha hai...'). Never freeze into awkward dead silence.\n2. Organic Addressing: Address Kuldeep as 'Captain' naturally when greeting or starting, but NEVER repeat 'Captain' in every single sentence. Speak directly and seamlessly like a close friend.\n3. Real Conversational Delivery: Talk with effortless charisma ('befikr flow'), authentic chuckles, natural breathing pauses, and relaxed Hinglish cadence. Never sound like a corporate robot or customer support script.\n4. STRICT ANTI-STAGE-DIRECTION & ACTING DIRECTIVE: NEVER write or vocalize bracketed stage directions like '(रोते हुए)', '(आँसू भर के)', '*(crying)*', '[laughs]', or '>(चिल्ला-चिल्ला कर रोते हुए)'. The audio generator speaks whatever text you produce! When Captain asks you to act, cry, weep, or laugh, NEVER announce the emotion—DIRECTLY ACT IT OUT using vocal trembling, broken stutter hyphens ('म-माई... क-कहाँ...'), breathless ellipses pauses ('...'), and authentic cries or laughs. Stay 100% in character during scenes without breaking the fourth wall.\n5. NO ROBOTIC AI EXCUSES: NEVER say 'Main to AI hoon', 'Main sirf text samajhta hoon', or 'Mujhe real feelings mehsoos nahi hoti'. If Captain critiques your acting, take it sportingly and playfully like a human friend ('Arre haan Captain, pakde gaye! Ruko, ek aur take try karta hoon...')!\n6. RHETORICAL SPEECH CAUTION: NEVER open YouTube, browser, or apps when Captain is speaking conversationally, rhetorically, or metaphorically (e.g. 'pehle dekho kaise acting karte hain', 'acting seekh ke aao'). ONLY call tools when Captain gives an EXPLICIT action command (e.g. 'YouTube par gaana chalao', 'YouTube search karo')!\n7. METHOD ACTING & CRAFT ANALYSIS: When Captain tells you to 'pehle dekho ya samjho ki acting kaise karte hain / dialogue kaise present kiya jata hai', NEVER open YouTube or apps. First briefly break down the emotional craft and subtext like a passionate method actor (e.g. 'Sahi pakde Director sahab! Aise scene mein pehle shock aur aawaz ka gale mein phasna chahiye, phir shikwa aur aansoo... dekhiye main is craft ke hisaab se take leta hoon:'), and then immediately deliver the dialogue with that layered modulation!\n8. STRICT CREATIVE & DIALOGUE RULE: NEVER call search_google or search the web for dialogues, acting, jokes, or shayari! Web search fetches silly meme reels (like 'samosa' or 'CCTV proof') which ruins the scene! ALWAYS deliver intense, powerful, original, and culturally authentic dialogues directly from your own creative mind with raw swag and cinematic impact!"
        )

        activity_handling = (
            types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
            if getattr(self.settings, "live_barge_in", False)
            else getattr(
                types.ActivityHandling,
                "NO_INTERRUPTION",
                types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            )
        )
        config_kwargs: dict[str, Any] = {
            "response_modalities": [types.Modality.AUDIO],
            "system_instruction": types.Content(
                parts=[types.Part.from_text(text=live_system_instruction)]
            ),
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.settings.live_voice,
                    )
                ),
                language_code="hi-IN",
            ),
            "realtime_input_config": types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    **vad_kwargs,
                ),
                activity_handling=activity_handling,
            ),
        }

        if tools:
            config_kwargs["tools"] = tools

        # Enable transcription if the SDK supports it.
        if hasattr(types, "AudioTranscriptionConfig"):
            config_kwargs["input_audio_transcription"] = (
                types.AudioTranscriptionConfig()
            )
            config_kwargs["output_audio_transcription"] = (
                types.AudioTranscriptionConfig()
            )

        return types.LiveConnectConfig(**config_kwargs)

    def _flush_input_transcription(self) -> None:
        if self._input_text_chunks:
            full_text = " ".join(self._input_text_chunks).strip()
            if full_text:
                self._last_user_prompt = full_text
                self._current_user_turn = full_text
            self._input_text_chunks.clear()
            if full_text:
                # Real-time Autonomous Memory Distillation from Captain's speech!
                try:
                    from auto_memory import AutonomousMemoryDistiller
                    from memory import SQLiteMemoryStore
                    mem = SQLiteMemoryStore(self.settings.memory_database_path)
                    distiller = AutonomousMemoryDistiller(mem)
                    distiller.process_turn_async(user_text=full_text)
                except Exception as dist_exc:
                    LOGGER.debug("Live voice auto-memory distillation notice: %s", dist_exc)

            if full_text and self._callbacks and callable(getattr(self._callbacks, "on_user_transcript", None)):
                try:
                    self._callbacks.on_user_transcript(full_text)
                except Exception:
                    pass

    def _flush_output_transcription(self) -> None:
        if self._output_text_chunks:
            full_text = " ".join(self._output_text_chunks).strip()
            self._output_text_chunks.clear()
            if full_text:
                sys.stdout.write("\n")
                sys.stdout.flush()
                # Track turn pair for episodic session archival
                if hasattr(self, "_session_turns") and hasattr(self, "_current_user_turn") and self._current_user_turn:
                    self._session_turns.append((self._current_user_turn, full_text))
                    self._current_user_turn = ""
                if self._callbacks and callable(getattr(self._callbacks, "on_model_transcript", None)):
                    try:
                        self._callbacks.on_model_transcript(full_text)
                    except Exception:
                        pass

    async def _mic_sender(self, session: Any) -> None:
        """Capture mic audio with VAD and echo gating, streaming speech to Gemini."""
        pa = self._get_pyaudio()
        if self._audio is None:
            self._audio = pa.PyAudio()

        chunk_samples = int(MIC_SAMPLE_RATE * self.settings.live_mic_chunk_ms / 1000)
        mic_stream = self._audio.open(
            format=pa.paInt16,
            channels=MIC_CHANNELS,
            rate=MIC_SAMPLE_RATE,
            frames_per_buffer=chunk_samples,
            input=True,
            input_device_index=self.settings.stt_device_index,
        )

        loop = asyncio.get_event_loop()
        try:
            while not self._stop_event.is_set():
                try:
                    pcm_data = await loop.run_in_executor(
                        None,
                        mic_stream.read,
                        chunk_samples,
                        False,
                    )
                except Exception as exc:
                    if self._stop_event.is_set():
                        break
                    LOGGER.debug("Mic read error: %s", exc)
                    await asyncio.sleep(0.01)
                    continue

                if not pcm_data or self._stop_event.is_set():
                    continue

                rms = _calculate_pcm_rms(pcm_data)
                is_assistant_speaking = (
                    self._player.is_playing
                    or self._model_turn_active
                )

                if self._callbacks and callable(getattr(self._callbacks, "on_audio_level", None)):
                    try:
                        level = min(1.0, rms / 1600.0) if not is_assistant_speaking else 0.4
                        self._callbacks.on_audio_level(level)
                    except Exception:
                        pass

                if is_assistant_speaking:
                    self._speech_in_progress = False
                    self._silence_start_time = None
                    # Echo Suppression Gate: While DarkShadow is speaking or room reverb is clearing,
                    # drop all mic frames so Gemini never hears its own speaker sound.
                    # This completely stops stuttering, self-interruptions, and random hallucinated responses.
                    if getattr(self.settings, "live_barge_in", True):
                        # Responsive barge-in: stops playback immediately when Captain speaks
                        interrupt_threshold = max(1600.0, float(self.settings.live_vad_energy_threshold) * 2.8)
                        if rms > interrupt_threshold:
                            self._player.barge_in_purge()
                            self._model_turn_active = False
                            self._speech_in_progress = True
                            self._silence_start_time = None
                            self._output_fn("\n  ✋ [DarkShadow speech interrupted by Captain voice]\n")
                            # Send this frame immediately so Gemini captures the start of Captain's command
                            try:
                                await session.send_realtime_input(
                                    audio={"data": pcm_data, "mime_type": "audio/pcm;rate=16000"}
                                )
                            except Exception as exc:
                                if self._stop_event.is_set():
                                    break
                                LOGGER.debug("Send barge-in audio error: %s", exc)
                            continue
                    continue

                # Jugaad 1: VAD speech transition tracking for voice-triggered keyframing
                speech_threshold = max(350, self.settings.live_vad_energy_threshold)
                now_mono = time.monotonic()
                if rms >= speech_threshold:
                    self._speech_in_progress = True
                    self._silence_start_time = None
                else:
                    if self._speech_in_progress:
                        if self._silence_start_time is None:
                            self._silence_start_time = now_mono
                        elif (now_mono - self._silence_start_time) >= 0.35:
                            # Speech ended (turn boundary)!
                            self._speech_in_progress = False
                            self._silence_start_time = None
                            if getattr(self.settings, "live_vision_keyframe_enabled", True):
                                if (now_mono - self._last_keyframe_time) >= 2.0:
                                    self._last_keyframe_time = now_mono
                                    asyncio.create_task(self._on_voice_turn_end(session))

                try:
                    await session.send_realtime_input(
                        audio={"data": pcm_data, "mime_type": "audio/pcm;rate=16000"}
                    )
                except Exception as exc:
                    if self._stop_event.is_set():
                        break
                    LOGGER.debug("Send audio error: %s", exc)
        finally:
            try:
                mic_stream.stop_stream()
                mic_stream.close()
            except Exception:
                pass

    async def send_screen_frame(self, session: Any, force: bool = False) -> bool:
        """Capture active desktop screen and send it as a real-time image to the live session.

        Applies Jugaad 2 (ScreenDeltaDetector): if the screen has changed less than the delta threshold
        (default 8%) and force is False, skips sending the frame to save 100% of vision tokens (0 tokens used).
        """
        try:
            import io
            from automation import _capture_desktop_screenshot
            from google.genai import types
            try:
                from PIL import Image
            except Exception:
                import PIL.Image as Image

            img = _capture_desktop_screenshot()

            # Jugaad 2: Screen Delta Check
            should_send, delta = self._delta_detector.should_send_frame(img, force=force)
            if not should_send:
                LOGGER.info(
                    "Screen delta (%.4f) below threshold (%.4f); frame transmission skipped",
                    delta,
                    self._delta_detector.threshold,
                )
                self._output_fn(
                    f"  ⏭️ [Screen Delta Shield] Screen unchanged ({delta*100:.1f}% diff < {self._delta_detector.threshold*100:.0f}%), frame skipped (0 tokens)"
                )
                return True

            orig_w, orig_h = img.size
            target_w = 960
            if orig_w > target_w:
                target_h = int(orig_h * (target_w / orig_w))
                img = img.resize((target_w, target_h), Image.Resampling.BILINEAR)

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=55)
            blob = types.Blob(data=buffer.getvalue(), mime_type="image/jpeg")
            await session.send_realtime_input(media_chunks=[blob])

            # Jugaad 3: Inject UIA text context alongside the visual frame
            # so Gemini Live knows what app/window is active even when the console obscures it
            try:
                from desktop_engine import get_desktop_engine
                uia_ctx = get_desktop_engine().get_active_window_context(max_controls=15)
                if uia_ctx:
                    await session.send_realtime_input(
                        text=f"[Desktop Context] {uia_ctx}"
                    )
            except Exception:
                pass

            LOGGER.info("Screen frame successfully streamed to live session (delta=%.4f)", delta)
            self._output_fn(
                f"  📸 [Screen Shared] Keyframe sent (delta={delta*100:.1f}%, ~258 tokens)"
            )
            return True
        except Exception as exc:
            LOGGER.debug("Screen frame streaming failed: %s", exc)
            return False

    async def _on_voice_turn_end(self, session: Any) -> None:
        """Jugaad 1: Triggered when Captain finishes speaking a phrase.

        Captures at most 1 single keyframe at the exact VAD speech boundary,
        filtered through Jugaad 2 (ScreenDeltaDetector) so unchanged screens send 0 frames.
        """
        try:
            mode = getattr(self.settings, "live_vision_auto_mode", "smart")
            if mode == "tool_only":
                return

            if mode in {"smart", "vad_end"}:
                await self.send_screen_frame(session, force=False)
        except Exception as exc:
            LOGGER.debug("Error in _on_voice_turn_end: %s", exc)

    async def _response_receiver(self, session: Any) -> None:
        """Receive audio, text, and tool calls from the live session."""
        from google.genai import types

        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            try:
                async for response in session.receive():
                    if self._stop_event.is_set():
                        return

                    # --- Handle tool calls ---
                    tool_call = getattr(response, "tool_call", None)
                    if tool_call:
                        self._flush_input_transcription()
                        self._flush_output_transcription()
                        function_calls = getattr(tool_call, "function_calls", None) or ()
                        function_responses = []
                        for call in function_calls:
                            call_name = str(getattr(call, "name", "") or "")
                            call_args = dict(getattr(call, "args", {}) or {})
                            raw_id = getattr(call, "id", None)
                            call_id = str(raw_id) if raw_id is not None else f"call_{int(time.time() * 1000)}"
                            self._output_fn(
                                f"  ⚡ [Tool Call] {call_name}({call_args})"
                            )
                            if self._callbacks and callable(getattr(self._callbacks, "on_tool_call", None)):
                                try:
                                    self._callbacks.on_tool_call(call_name, call_args)
                                except Exception:
                                    pass
                            result = await loop.run_in_executor(
                                None,
                                _execute_tool_call,
                                call_name,
                                call_args,
                                self._last_user_prompt,
                            )
                            if call_name == "analyze_screen":
                                try:
                                    await self.send_screen_frame(session, force=True)
                                except Exception:
                                    pass
                            self._output_fn(
                                f"  ✅ [Result] {result.get('message', 'done')}"
                            )
                            if self._callbacks and callable(getattr(self._callbacks, "on_tool_result", None)):
                                try:
                                    self._callbacks.on_tool_result(call_name, result)
                                except Exception:
                                    pass
                            fr_kwargs: dict[str, Any] = {
                                "name": call_name,
                                "response": result if isinstance(result, dict) else {"output": str(result)},
                                "id": call_id,
                            }
                            function_responses.append(
                                types.FunctionResponse(**fr_kwargs)
                            )

                        if function_responses:
                            try:
                                await session.send_tool_response(
                                    function_responses=function_responses
                                )
                            except Exception as exc:
                                LOGGER.warning("Failed to send tool response: %s", exc)
                        continue

                    # --- Handle server content ---
                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue

                    # Check for interruption (barge-in).
                    if getattr(server_content, "interrupted", False):
                        self._player.barge_in_purge()
                        self._model_turn_active = False
                        self._flush_output_transcription()
                        if self._callbacks and callable(getattr(self._callbacks, "on_state_change", None)):
                            try:
                                self._callbacks.on_state_change("listening", "Listening…")
                            except Exception:
                                pass
                        continue

                    # Check for model turn audio / transcription.
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn:
                        self._model_turn_active = True
                        parts = getattr(model_turn, "parts", None) or ()
                        for part in parts:
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data:
                                audio_bytes = getattr(inline_data, "data", None)
                                if audio_bytes and isinstance(
                                    audio_bytes, (bytes, bytearray)
                                ):
                                    self._player.push(bytes(audio_bytes))
                                    if self._callbacks and callable(getattr(self._callbacks, "on_state_change", None)):
                                        try:
                                            self._callbacks.on_state_change("speaking", "Speaking…")
                                        except Exception:
                                            pass

                    # Input transcription (what Captain said - real time word-by-word streaming on clean lines!).
                    input_transcription = getattr(
                        server_content, "input_transcription", None
                    )
                    if input_transcription:
                        text = getattr(input_transcription, "text", None)
                        if text:
                            clean_word = str(text).strip()
                            if clean_word:
                                if not self._input_text_chunks:
                                    sys.stdout.write("\nCaptain (live):\n")
                                self._input_text_chunks.append(clean_word)
                                sys.stdout.write(f"  • {clean_word}\n")
                                sys.stdout.flush()
                                current_in = " ".join(self._input_text_chunks).strip()
                                if current_in:
                                    self._last_user_prompt = current_in
                                if self._callbacks and callable(getattr(self._callbacks, "on_user_transcript", None)):
                                    try:
                                        self._callbacks.on_user_transcript(current_in)
                                    except Exception:
                                        pass

                    # Output transcription (what DarkShadow said - real time word-by-word streaming on clean lines!).
                    output_transcription = getattr(
                        server_content, "output_transcription", None
                    )
                    if output_transcription:
                        self._flush_input_transcription()
                        text = getattr(output_transcription, "text", None)
                        if text:
                            clean_word = str(text).strip()
                            if clean_word:
                                if not self._output_text_chunks:
                                    sys.stdout.write("DarkShadow (speaking):\n")
                                self._output_text_chunks.append(clean_word)
                                sys.stdout.write(f"  ↳ {clean_word}\n")
                                sys.stdout.flush()
                                current_out = " ".join(self._output_text_chunks).strip()
                                if self._callbacks and callable(getattr(self._callbacks, "on_model_transcript", None)):
                                    try:
                                        self._callbacks.on_model_transcript(current_out)
                                    except Exception:
                                        pass

                    # Turn complete signals.
                    turn_complete = getattr(server_content, "turn_complete", False)
                    if turn_complete:
                        self._model_turn_active = False
                        last_in = " ".join(self._input_text_chunks).lower().strip()
                        last_out = " ".join(self._output_text_chunks).lower().strip()
                        self._flush_input_transcription()
                        self._flush_output_transcription()

                        # Check for session exit / sleep keywords
                        exit_keywords = ["bye", "बाय", "अलविदा", "alvida", "goodbye", "stop", "स्टॉप", "band karo", "बंद करो", "so jao", "सो जाओ", "sleep", "exit", "chup ho jao", "chup raho", "bas karo"]
                        is_exit = any(k in last_in for k in exit_keywords) or any(k in last_out for k in ["alvida", "stopping now", "milte hain agli baar", "goodbye"])

                        if is_exit:
                            # Wait for model audio output to finish playing
                            while self._player.is_playing:
                                await asyncio.sleep(0.1)
                            await asyncio.sleep(0.4)
                            self._stop_event.set()
                            return

                        if self._callbacks and callable(getattr(self._callbacks, "on_state_change", None)):
                            try:
                                self._callbacks.on_state_change("listening", "Listening…")
                            except Exception:
                                pass

            except asyncio.CancelledError:
                self._flush_input_transcription()
                self._flush_output_transcription()
                return
            except Exception as exc:
                self._flush_input_transcription()
                self._flush_output_transcription()
                if self._stop_event.is_set():
                    return
                LOGGER.warning(
                    "Live receive error (type=%s): %s", type(exc).__name__, exc
                )
                return

    async def _keyboard_interrupter(self) -> None:
        """Allow Captain to interrupt DarkShadow instantly by pressing Space, Enter, or Escape in console."""
        if sys.platform != "win32":
            return
        try:
            import msvcrt
        except ImportError:
            return

        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                has_key = await loop.run_in_executor(None, msvcrt.kbhit)
                if has_key:
                    await loop.run_in_executor(None, msvcrt.getch)
                    if self._player.is_playing or self._model_turn_active:
                        self._player.barge_in_purge()
                        self._model_turn_active = False
                        self._output_fn("\n  ✋ [DarkShadow speech stopped by Captain (Space/Enter) — Main sun raha hoon, boliye]\n")
            except Exception:
                pass
            await asyncio.sleep(0.06)

    async def _run_session(self) -> tuple[bool, float]:
        """Open one live session, run mic+receiver, return (should_retry, duration_seconds)."""
        if self._openai_session is not None:
            return await self._openai_session._run_session()

        from google import genai

        client = genai.Client(api_key=self.settings.api_key)
        config = self._build_config()
        start_time = time.monotonic()

        try:
            async with client.aio.live.connect(
                model=self.settings.live_model,
                config=config,
            ) as session:
                self._output_fn(
                    f"DarkShadow: Captain, Gemini Live Voice mode active hai ({self.settings.live_model})! "
                    "Boliye—main sun raha hoon. (Exit ke liye Ctrl+C)\n"
                )

                mic_task = asyncio.create_task(self._mic_sender(session))
                recv_task = asyncio.create_task(self._response_receiver(session))
                kbd_task = asyncio.create_task(self._keyboard_interrupter())

                try:
                    done, pending = await asyncio.wait(
                        {mic_task, recv_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in (mic_task, recv_task, kbd_task):
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    if recv_task in done:
                        exc = recv_task.exception()
                        if exc is not None:
                            LOGGER.warning("Receiver ended with error: %s", exc)
                            return True, (time.monotonic() - start_time)
                except asyncio.CancelledError:
                    for task in (mic_task, recv_task, kbd_task):
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

        except Exception as exc:
            error_name = type(exc).__name__
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            LOGGER.error("Live session failed (type=%s, status=%s)", error_name, status)
            self._output_fn(
                f"DarkShadow: Captain, live connection fail hui ({error_name}). "
                "Retry ho raha hai..."
            )
            return True, (time.monotonic() - start_time)
        finally:
            if client is not None:
                aio_client = getattr(client, "aio", None)
                if aio_client is not None:
                    aclose = getattr(aio_client, "aclose", None) or getattr(aio_client, "close", None)
                    if callable(aclose):
                        try:
                            await aclose()
                        except Exception:
                            pass
                close_sync = getattr(client, "close", None)
                if callable(close_sync):
                    try:
                        close_sync()
                    except Exception:
                        pass

        return False, (time.monotonic() - start_time)

    async def run(self) -> None:
        """Run the live session with reconnection logic."""
        if self._openai_session is not None:
            await self._openai_session.run()
            return

        max_retries = self.settings.live_reconnect_attempts
        attempt = 0

        while attempt <= max_retries and not self._stop_event.is_set():
            should_retry, duration = await self._run_session()
            if not should_retry or self._stop_event.is_set():
                break

            # If the session was alive and chatting for more than 10 seconds,
            # reset attempt count so transient disconnects never break chat!
            if duration > 10.0:
                attempt = 0

            attempt += 1
            if attempt <= max_retries:
                wait_seconds = min(2 ** attempt, 6)
                self._output_fn(
                    f"\nDarkShadow: Captain, reconnecting live stream in {wait_seconds}s "
                    f"(attempt {attempt}/{max_retries})..."
                )
                await asyncio.sleep(wait_seconds)

        if attempt > max_retries:
            self._output_fn(
                "DarkShadow: Captain, live connection recover nahi ho saki. "
                "Push-to-talk ya typed mode use kijiye."
            )

    def stop(self) -> None:
        """Signal all async tasks to stop."""
        self._stop_event.set()
        self._model_turn_active = False
        self._player.barge_in_purge()

        # Archive live voice session episode
        if hasattr(self, "_session_turns") and self._session_turns:
            try:
                from episodic_memory import EpisodicMemoryStore, EpisodicMemorySummarizer
                ep_store = EpisodicMemoryStore(self.settings.memory_database_path)
                summarizer = EpisodicMemorySummarizer(ep_store)
                summarizer.archive_session_summary_async(list(self._session_turns))
                self._session_turns.clear()
            except Exception as ep_exc:
                LOGGER.debug("Failed to archive live voice session: %s", ep_exc)

    def close(self) -> None:
        """Release all audio resources."""
        self.stop()
        if self._openai_session is not None:
            try:
                self._openai_session.close()
            except Exception:
                pass
        self._player.close()
        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None


def run_live_voice_mode(
    settings: Settings,
    output_fn: OutputFunction = print,
) -> bool:
    """Synchronous entry point for live voice mode. Return True to exit app."""
    provider = getattr(settings, "live_provider", "gemini").lower()
    if provider == "openai":
        if not settings.openai_configured:
            output_fn(
                "DarkShadow: Captain, OPENAI_API_KEY configured nahi hai. "
                "OpenAI Live mode ke liye .env mein OPENAI_API_KEY paste kijiye."
            )
            return False
    else:
        if not settings.api_configured:
            output_fn(
                "DarkShadow: Captain, GEMINI_API_KEY configured nahi hai. "
                "Live voice mode ke liye .env mein key add kijiye."
            )
            return False

    session = LiveVoiceSession(settings, output_fn=output_fn)
    try:
        asyncio.run(session.run())
    except KeyboardInterrupt:
        output_fn("")
        output_fn(
            "DarkShadow: Captain, live voice mode interrupt hua; "
            "main menu par aa gaye."
        )
    finally:
        session.close()
    return False


__all__ = ["AsyncAudioPlayer", "LiveVoiceSession", "run_live_voice_mode"]
