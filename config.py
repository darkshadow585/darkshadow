"""Configuration loading for DarkShadow.

Only non-secret configuration is ever included in status output or logs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for the lightweight typed and voice assistant."""

    api_key: str | None
    model: str = "gemini-3.8-flash"
    casual_model: str = "gemini-3.5-flash-lite"
    tavily_api_key: str | None = None
    youtube_api_key: str | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    spotify_redirect_uri: str = "http://127.0.0.1:8888/callback"
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 5
    realtime_cache_seconds: int = 300
    automation_planner_max_calls_per_minute: int = 6
    automation_plan_cache_seconds: int = 300
    whatsapp_confirm_send: bool = True
    max_history_turns: int = 8
    request_timeout_seconds: float = 15.0
    enable_streaming: bool = True
    ipv4_first: bool = True
    log_level: str = "WARNING"
    env_file_found: bool = False
    stt_backend: str = "whisper"
    whisper_model: str = "base"
    whisper_device: str = "auto"
    stt_languages: tuple[str, ...] = ("hi-IN", "en-IN")
    stt_calibration_seconds: float = 0.6
    stt_timeout_seconds: float = 5.0
    stt_phrase_time_limit_seconds: float = 15.0
    stt_device_index: int | None = None
    fish_api_key: str | None = None
    tts_provider: str = "auto"
    tts_fish_model: str = "s2.1-pro"
    tts_fish_reference_id: str | None = None
    tts_fish_latency: str = "normal"
    tts_gemini_model: str = "gemini-3.1-flash-tts-preview"
    tts_gemini_voice: str = "Charon"
    tts_gemini_timeout_seconds: float = 10.0
    tts_fish_segment_words: int = 1000
    tts_fish_segment_characters: int = 500
    tts_gemini_segment_characters: int = 1000
    tts_usage_file: Path = PROJECT_ROOT / ".darkshadow" / "tts_usage.json"
    tts_edge_fallback: bool = True
    tts_voice: str = "hi-IN-MadhurNeural"
    tts_english_voice: str = "en-IN-PrabhatNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "-5Hz"
    tts_volume: str = "+0%"
    memory_enabled: bool = False
    memory_database_path: Path = PROJECT_ROOT / ".darkshadow" / "memory.db"
    wake_phrase_enabled: bool = False
    wake_phrase: str = "dark shadow"
    openai_api_key: str | None = None
    live_provider: str = "gemini"
    live_model: str = "gemini-3.8-live"
    live_voice: str = "Charon"
    live_reconnect_attempts: int = 3
    live_mic_chunk_ms: int = 40
    live_vad_energy_threshold: int = 350
    live_echo_gate_multiplier: float = 2.5
    live_audio_gain: float = 1.6
    live_barge_in: bool = False
    live_echo_gate_cooldown_seconds: float = 0.65
    live_vision_keyframe_enabled: bool = True
    live_vision_delta_threshold: float = 0.08
    live_vision_auto_mode: str = "smart"

    notes_directory: Path = PROJECT_ROOT / ".darkshadow" / "notes"
    browser_user_data_dir: Path = PROJECT_ROOT / ".darkshadow" / "browser_profile"
    browser_stealth_enabled: bool = True
    browser_vision_enabled: bool = True
    whatsapp_provider: str = "auto"
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None

    # Next-Gen AI Capabilities
    youtube_agentic_video_enabled: bool = True
    agentic_video_model: str = "gemini-3.7-flash"
    thinking_budget_technical: int = 2048
    thinking_budget_creative: int = 1024
    thinking_budget_casual: int = 0
    thinking_budget_automation: int = 1024
    context_caching_enabled: bool = True
    context_cache_ttl_seconds: int = 3600
    search_grounding_provider: str = "auto"
    map_grounding_enabled: bool = True
    embedding_model: str = "gemini-embedding-2"
    computer_use_enabled: bool = True
    computer_use_max_steps: int = 10
    allow_camera_access: bool = False  # Strictly False by Captain's order (Zero webcam/face-recording hardware access)
    react_max_steps: int = 4
    workflow_max_chain_length: int = 5

    # Local Ollama AI & Vision Capabilities
    ollama_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_vision_model: str = "moondream"
    vision_provider: str = "auto"
    ollama_timeout_seconds: float = 40.0

    @property
    def api_configured(self) -> bool:
        """Return whether a non-empty Gemini API key is available."""

        return bool(self.api_key)

    @property
    def tavily_configured(self) -> bool:
        """Return whether a non-empty Tavily API key is available."""

        return bool(self.tavily_api_key)

    @property
    def fish_configured(self) -> bool:
        """Return whether a non-empty Fish Audio API key is available."""

        return bool(self.fish_api_key)

    @property
    def spotify_configured(self) -> bool:
        """Return whether Spotify Web API credentials are provided."""

        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def whatsapp_cloud_configured(self) -> bool:
        """Return whether WhatsApp Cloud API credentials are provided."""

        return bool(self.whatsapp_phone_number_id and self.whatsapp_access_token)

    @property
    def twilio_whatsapp_configured(self) -> bool:
        """Return whether Twilio WhatsApp credentials are provided."""

        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def openai_configured(self) -> bool:
        """Return whether OpenAI API key is configured."""

        return bool(self.openai_api_key and self.openai_api_key.strip())


def _pick(
    name: str,
    environment: Mapping[str, str],
    file_values: Mapping[str, str | None],
    default: str,
) -> str:
    value = environment.get(name)
    if value is None:
        value = file_values.get(name)
    return default if value is None else str(value).strip()


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _bounded_float(
    value: str, default: float, minimum: float, maximum: float
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _as_bool(value: str, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _language_codes(value: str) -> tuple[str, ...]:
    languages = tuple(
        item.strip()
        for item in value.split(",")
        if re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}", item.strip())
    )
    return languages[:4] or ("hi-IN", "en-IN")


def _optional_nonnegative_int(value: str) -> int | None:
    if not value.strip():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _prosody_value(
    value: str,
    suffix: str,
    default: str,
    minimum: int,
    maximum: int,
) -> str:
    cleaned = value.strip()
    match = re.fullmatch(
        rf"([+-]?)(\d+)(?:{re.escape(suffix)})?",
        cleaned,
        re.IGNORECASE,
    )
    if match is None:
        return default
    amount = int(match.group(2))
    if match.group(1) == "-":
        amount *= -1
    amount = min(max(amount, minimum), maximum)
    return f"{amount:+d}{suffix}"


def _safe_wake_phrase(value: str) -> str:
    cleaned = " ".join(value.casefold().split())
    if not re.fullmatch(r"[a-z0-9 -]{2,40}", cleaned):
        return "dark shadow"
    return cleaned


def load_settings(
    env_file: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Settings:
    """Load settings from process environment and a local ``.env`` file.

    Process environment values take precedence. The function never prints or
    logs the API key and does not mutate ``os.environ``.
    """

    selected_file = env_file or DEFAULT_ENV_FILE
    file_values = dotenv_values(selected_file) if selected_file.is_file() else {}
    current_environment = os.environ if environment is None else environment

    api_key = _pick("GEMINI_API_KEY", current_environment, file_values, "")
    stt_backend = _pick(
        "DARKSHADOW_STT_BACKEND", current_environment, file_values, "whisper"
    ).casefold()
    if stt_backend not in {"whisper", "google", "auto"}:
        stt_backend = "whisper"
    whisper_model = _pick(
        "DARKSHADOW_WHISPER_MODEL", current_environment, file_values, "base"
    ).lower()
    whisper_device = _pick(
        "DARKSHADOW_WHISPER_DEVICE", current_environment, file_values, "auto"
    ).lower()
    model = _pick(
        "DARKSHADOW_MODEL",
        current_environment,
        file_values,
        "gemini-3.8-flash",
    )
    casual_model = _pick(
        "DARKSHADOW_CASUAL_MODEL",
        current_environment,
        file_values,
        "gemini-3.5-flash-lite",
    )
    tavily_api_key = _pick("TAVILY_API_KEY", current_environment, file_values, "")
    youtube_api_key = _pick("YOUTUBE_API_KEY", current_environment, file_values, "")
    spotify_client_id = _pick("SPOTIFY_CLIENT_ID", current_environment, file_values, "")
    spotify_client_secret = _pick("SPOTIFY_CLIENT_SECRET", current_environment, file_values, "")
    spotify_redirect_uri = _pick("SPOTIFY_REDIRECT_URI", current_environment, file_values, "http://127.0.0.1:8888/callback")
    tavily_search_depth = _pick(
        "DARKSHADOW_TAVILY_SEARCH_DEPTH",
        current_environment,
        file_values,
        "basic",
    ).lower()
    if tavily_search_depth not in {"basic", "fast", "ultra-fast", "advanced"}:
        tavily_search_depth = "basic"
    tavily_max_results = _bounded_int(
        _pick("DARKSHADOW_TAVILY_MAX_RESULTS", current_environment, file_values, "5"),
        default=5,
        minimum=1,
        maximum=10,
    )
    realtime_cache_seconds = _bounded_int(
        _pick("DARKSHADOW_REALTIME_CACHE_SECONDS", current_environment, file_values, "300"),
        default=300,
        minimum=0,
        maximum=3600,
    )
    automation_planner_max_calls = _bounded_int(
        _pick(
            "DARKSHADOW_AUTOMATION_PLANNER_MAX_CALLS_PER_MINUTE",
            current_environment,
            file_values,
            "6",
        ),
        default=6,
        minimum=1,
        maximum=60,
    )
    automation_plan_cache_seconds = _bounded_int(
        _pick(
            "DARKSHADOW_AUTOMATION_PLAN_CACHE_SECONDS",
            current_environment,
            file_values,
            "300",
        ),
        default=300,
        minimum=0,
        maximum=3600,
    )
    whatsapp_confirm_send = _as_bool(
        _pick(
            "DARKSHADOW_WHATSAPP_CONFIRM_SEND",
            current_environment,
            file_values,
            "true",
        ),
        default=True,
    )
    history = _bounded_int(
        _pick("DARKSHADOW_HISTORY_TURNS", current_environment, file_values, "8"),
        default=8,
        minimum=1,
        maximum=20,
    )
    timeout = _bounded_float(
        _pick("DARKSHADOW_TIMEOUT_SECONDS", current_environment, file_values, "15"),
        default=15.0,
        minimum=5.0,
        maximum=120.0,
    )
    streaming = _as_bool(
        _pick("DARKSHADOW_STREAM", current_environment, file_values, "true"),
        default=True,
    )
    ipv4_first = _as_bool(
        _pick(
            "DARKSHADOW_IPV4_FIRST",
            current_environment,
            file_values,
            "true",
        ),
        default=True,
    )
    log_level = _pick(
        "DARKSHADOW_LOG_LEVEL", current_environment, file_values, "WARNING"
    ).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        log_level = "WARNING"

    stt_languages = _language_codes(
        _pick(
            "DARKSHADOW_STT_LANGUAGES",
            current_environment,
            file_values,
            "hi-IN,en-IN",
        )
    )
    stt_calibration = _bounded_float(
        _pick(
            "DARKSHADOW_STT_CALIBRATION_SECONDS",
            current_environment,
            file_values,
            "0.6",
        ),
        default=0.6,
        minimum=0.0,
        maximum=3.0,
    )
    stt_timeout = _bounded_float(
        _pick("DARKSHADOW_STT_TIMEOUT_SECONDS", current_environment, file_values, "5"),
        default=5.0,
        minimum=1.0,
        maximum=15.0,
    )
    stt_phrase_limit = _bounded_float(
        _pick(
            "DARKSHADOW_STT_PHRASE_LIMIT_SECONDS",
            current_environment,
            file_values,
            "15",
        ),
        default=15.0,
        minimum=3.0,
        maximum=30.0,
    )
    stt_device_index = _optional_nonnegative_int(
        _pick("DARKSHADOW_STT_DEVICE_INDEX", current_environment, file_values, "")
    )
    fish_api_key = _pick("FISH_AUDIO_API_KEY", current_environment, file_values, "")
    tts_provider = _pick(
        "DARKSHADOW_TTS_PROVIDER", current_environment, file_values, "auto"
    ).casefold()
    if tts_provider not in {"auto", "gemini", "fish", "edge", "offline"}:
        tts_provider = "auto"

    tts_fish_model = _pick(
        "DARKSHADOW_FISH_MODEL", current_environment, file_values, "s2.1-pro"
    ) or "s2.1-pro"
    tts_fish_reference_id = _pick(
        "DARKSHADOW_FISH_REFERENCE_ID",
        current_environment,
        file_values,
        "",
    ) or None
    tts_fish_latency = _pick(
        "DARKSHADOW_FISH_LATENCY", current_environment, file_values, "normal"
    ) or "normal"

    tts_gemini_model = _pick(
        "DARKSHADOW_TTS_GEMINI_MODEL",
        current_environment,
        file_values,
        "gemini-3.1-flash-tts-preview",
    )
    # Regular Gemini chat models return text only and cause an HTTP 400 when
    # requested with AUDIO modality. Keep TTS on a dedicated speech model even
    # when an old .env still contains e.g. "gemini-2.0-flash".
    if "tts" not in tts_gemini_model.casefold():
        tts_gemini_model = "gemini-3.1-flash-tts-preview"
    tts_gemini_voice = _pick(
        "DARKSHADOW_TTS_GEMINI_VOICE",
        current_environment,
        file_values,
        "Charon",
    )
    tts_gemini_timeout = _bounded_float(
        _pick("DARKSHADOW_TTS_GEMINI_TIMEOUT_SECONDS", current_environment, file_values, "10"),
        default=10.0,
        minimum=1.0,
        maximum=30.0,
    )
    tts_fish_segment_characters = _bounded_int(
        _pick("DARKSHADOW_TTS_FISH_SEGMENT_CHARS", current_environment, file_values, "500"),
        default=500,
        minimum=1,
        maximum=100_000,
    )
    tts_gemini_segment_characters = _bounded_int(
        _pick("DARKSHADOW_TTS_GEMINI_SEGMENT_CHARS", current_environment, file_values, "1000"),
        default=1000,
        minimum=1,
        maximum=100_000,
    )

    raw_usage_path = _pick(
        "DARKSHADOW_TTS_USAGE_FILE",
        current_environment,
        file_values,
        ".darkshadow/tts_usage.json",
    ) or ".darkshadow/tts_usage.json"
    tts_usage_file = Path(raw_usage_path).expanduser()
    if not tts_usage_file.is_absolute():
        tts_usage_file = PROJECT_ROOT / tts_usage_file

    try:
        tts_fish_segment_words = int(
            _pick(
                "DARKSHADOW_TTS_FISH_SEGMENT_WORDS",
                current_environment,
                file_values,
                "1000",
            )
        )
    except ValueError:
        tts_fish_segment_words = 1000

    tts_edge_fallback = _as_bool(
        _pick(
            "DARKSHADOW_TTS_EDGE_FALLBACK",
            current_environment,
            file_values,
            "true",
        ),
        default=True,
    )
    tts_voice = _pick(
        "DARKSHADOW_TTS_VOICE", current_environment, file_values, "hi-IN-MadhurNeural"
    ) or "hi-IN-MadhurNeural"
    tts_english_voice = _pick(
        "DARKSHADOW_TTS_ENGLISH_VOICE",
        current_environment,
        file_values,
        "en-IN-PrabhatNeural",
    ) or "en-IN-PrabhatNeural"
    tts_rate = _prosody_value(
        _pick("DARKSHADOW_TTS_RATE", current_environment, file_values, "+0%"),
        "%",
        "+0%",
        -50,
        100,
    )
    tts_pitch = _prosody_value(
        _pick("DARKSHADOW_TTS_PITCH", current_environment, file_values, "-5Hz"),
        "Hz",
        "-5Hz",
        -50,
        50,
    )
    tts_volume = _prosody_value(
        _pick("DARKSHADOW_TTS_VOLUME", current_environment, file_values, "+0%"),
        "%",
        "+0%",
        -100,
        100,
    )
    memory_enabled = _as_bool(
        _pick(
            "DARKSHADOW_MEMORY_ENABLED",
            current_environment,
            file_values,
            "false",
        ),
        default=False,
    )
    raw_database_path = _pick(
        "DARKSHADOW_MEMORY_DB",
        current_environment,
        file_values,
        ".darkshadow/memory.db",
    )
    database_path = Path(raw_database_path).expanduser()
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    wake_phrase_enabled = _as_bool(
        _pick(
            "DARKSHADOW_WAKE_PHRASE_ENABLED",
            current_environment,
            file_values,
            "false",
        ),
        default=False,
    )
    wake_phrase = _safe_wake_phrase(
        _pick(
            "DARKSHADOW_WAKE_PHRASE",
            current_environment,
            file_values,
            "dark shadow",
        )
    )

    openai_api_key = _pick(
        "OPENAI_API_KEY",
        current_environment,
        file_values,
        "",
    ) or None
    live_provider = _pick(
        "DARKSHADOW_LIVE_PROVIDER",
        current_environment,
        file_values,
        "gemini",
    ).strip().lower()

    default_live_model = "gpt-realtime-2.1" if live_provider == "openai" else "gemini-3.8-live"
    default_live_voice = "ash" if live_provider == "openai" else "Charon"

    live_model = _pick(
        "DARKSHADOW_LIVE_MODEL",
        current_environment,
        file_values,
        default_live_model,
    )
    live_voice = _pick(
        "DARKSHADOW_LIVE_VOICE",
        current_environment,
        file_values,
        default_live_voice,
    )
    live_reconnect_attempts = _bounded_int(
        _pick(
            "DARKSHADOW_LIVE_RECONNECT_ATTEMPTS",
            current_environment,
            file_values,
            "3",
        ),
        default=3,
        minimum=0,
        maximum=10,
    )
    live_mic_chunk_ms = _bounded_int(
        _pick(
            "DARKSHADOW_LIVE_MIC_CHUNK_MS",
            current_environment,
            file_values,
            "100",
        ),
        default=100,
        minimum=20,
        maximum=500,
    )
    live_vad_energy_threshold = _bounded_int(
        _pick(
            "DARKSHADOW_LIVE_VAD_ENERGY_THRESHOLD",
            current_environment,
            file_values,
            "350",
        ),
        default=350,
        minimum=50,
        maximum=5000,
    )
    live_echo_gate_multiplier = _bounded_float(
        _pick(
            "DARKSHADOW_LIVE_ECHO_GATE_MULTIPLIER",
            current_environment,
            file_values,
            "2.5",
        ),
        default=2.5,
        minimum=1.0,
        maximum=10.0,
    )
    live_audio_gain = _bounded_float(
        _pick(
            "DARKSHADOW_LIVE_AUDIO_GAIN",
            current_environment,
            file_values,
            "1.6",
        ),
        default=1.6,
        minimum=0.5,
        maximum=5.0,
    )
    live_barge_in = _as_bool(
        _pick(
            "DARKSHADOW_LIVE_BARGE_IN",
            current_environment,
            file_values,
            "false",
        ),
        default=False,
    )
    live_echo_gate_cooldown_seconds = _bounded_float(
        _pick(
            "DARKSHADOW_LIVE_ECHO_GATE_COOLDOWN_SECONDS",
            current_environment,
            file_values,
            "0.65",
        ),
        default=0.65,
        minimum=0.2,
        maximum=3.0,
    )
    live_vision_keyframe_enabled = _as_bool(
        _pick(
            "DARKSHADOW_LIVE_VISION_KEYFRAME",
            current_environment,
            file_values,
            "true",
        ),
        default=True,
    )
    live_vision_delta_threshold = _bounded_float(
        _pick(
            "DARKSHADOW_LIVE_VISION_DELTA_THRESHOLD",
            current_environment,
            file_values,
            "0.08",
        ),
        default=0.08,
        minimum=0.01,
        maximum=0.90,
    )
    live_vision_auto_mode = _pick(
        "DARKSHADOW_LIVE_VISION_AUTO_MODE",
        current_environment,
        file_values,
        "smart",
    ).lower()
    if live_vision_auto_mode not in {"smart", "vad_end", "tool_only"}:
        live_vision_auto_mode = "smart"

    whatsapp_provider = _pick(
        "DARKSHADOW_WHATSAPP_PROVIDER", current_environment, file_values, "auto"
    ).lower()
    if whatsapp_provider not in {"auto", "cloud_api", "twilio", "desktop_gui"}:
        whatsapp_provider = "auto"
    whatsapp_phone_number_id = _pick("WHATSAPP_PHONE_NUMBER_ID", current_environment, file_values, "")
    whatsapp_access_token = _pick("WHATSAPP_ACCESS_TOKEN", current_environment, file_values, "")
    twilio_account_sid = _pick("TWILIO_ACCOUNT_SID", current_environment, file_values, "")
    twilio_auth_token = _pick("TWILIO_AUTH_TOKEN", current_environment, file_values, "")
    twilio_whatsapp_from = _pick("TWILIO_WHATSAPP_FROM", current_environment, file_values, "")

    raw_notes_dir = _pick(
        "DARKSHADOW_NOTES_DIR",
        current_environment,
        file_values,
        ".darkshadow/notes",
    ) or ".darkshadow/notes"
    notes_directory = Path(raw_notes_dir).expanduser()
    if not notes_directory.is_absolute():
        notes_directory = PROJECT_ROOT / notes_directory

    raw_browser_profile = _pick(
        "DARKSHADOW_BROWSER_PROFILE_DIR",
        current_environment,
        file_values,
        ".darkshadow/browser_profile",
    ) or ".darkshadow/browser_profile"
    browser_user_data_dir = Path(raw_browser_profile).expanduser()
    if not browser_user_data_dir.is_absolute():
        browser_user_data_dir = PROJECT_ROOT / browser_user_data_dir

    browser_stealth_enabled = _as_bool(
        _pick("DARKSHADOW_BROWSER_STEALTH", current_environment, file_values, "true"),
        True,
    )
    browser_vision_enabled = _as_bool(
        _pick("DARKSHADOW_BROWSER_VISION", current_environment, file_values, "true"),
        True,
    )

    youtube_agentic_video_enabled = _as_bool(
        _pick("DARKSHADOW_AGENTIC_VIDEO_ENABLED", current_environment, file_values, "true"),
        True,
    )
    agentic_video_model = _pick(
        "DARKSHADOW_AGENTIC_VIDEO_MODEL", current_environment, file_values, "gemini-3.7-flash"
    ) or "gemini-3.7-flash"
    thinking_budget_technical = _bounded_int(
        _pick("DARKSHADOW_THINKING_BUDGET_TECHNICAL", current_environment, file_values, "2048"),
        default=2048,
        minimum=0,
        maximum=32768,
    )
    thinking_budget_creative = _bounded_int(
        _pick("DARKSHADOW_THINKING_BUDGET_CREATIVE", current_environment, file_values, "1024"),
        default=1024,
        minimum=0,
        maximum=32768,
    )
    thinking_budget_casual = _bounded_int(
        _pick("DARKSHADOW_THINKING_BUDGET_CASUAL", current_environment, file_values, "0"),
        default=0,
        minimum=0,
        maximum=32768,
    )
    thinking_budget_automation = _bounded_int(
        _pick("DARKSHADOW_THINKING_BUDGET_AUTOMATION", current_environment, file_values, "1024"),
        default=1024,
        minimum=0,
        maximum=32768,
    )
    context_caching_enabled = _as_bool(
        _pick("DARKSHADOW_CONTEXT_CACHING_ENABLED", current_environment, file_values, "true"),
        True,
    )
    context_cache_ttl_seconds = _bounded_int(
        _pick("DARKSHADOW_CONTEXT_CACHE_TTL_SECONDS", current_environment, file_values, "3600"),
        default=3600,
        minimum=60,
        maximum=86400,
    )
    search_grounding_provider = _pick(
        "DARKSHADOW_SEARCH_GROUNDING_PROVIDER", current_environment, file_values, "auto"
    ).lower()
    if search_grounding_provider not in {"auto", "google", "tavily"}:
        search_grounding_provider = "auto"
    embedding_model = _pick(
        "DARKSHADOW_EMBEDDING_MODEL", current_environment, file_values, "gemini-embedding-2"
    ) or "gemini-embedding-2"
    map_grounding_enabled = _as_bool(
        _pick("DARKSHADOW_MAP_GROUNDING_ENABLED", current_environment, file_values, "true"),
        True,
    )
    computer_use_enabled = _as_bool(
        _pick("DARKSHADOW_COMPUTER_USE_ENABLED", current_environment, file_values, "true"),
        True,
    )
    computer_use_max_steps = _bounded_int(
        _pick("DARKSHADOW_COMPUTER_USE_MAX_STEPS", current_environment, file_values, "10"),
        default=10,
        minimum=1,
        maximum=30,
    )

    ollama_enabled = _as_bool(
        _pick("DARKSHADOW_OLLAMA_ENABLED", current_environment, file_values, "true"),
        True,
    )
    ollama_base_url = _pick(
        "DARKSHADOW_OLLAMA_BASE_URL", current_environment, file_values, "http://127.0.0.1:11434"
    ).rstrip("/") or "http://127.0.0.1:11434"
    ollama_vision_model = _pick(
        "DARKSHADOW_OLLAMA_VISION_MODEL", current_environment, file_values, "moondream"
    ) or "moondream"
    vision_provider = _pick(
        "DARKSHADOW_VISION_PROVIDER", current_environment, file_values, "auto"
    ).lower()
    if vision_provider not in {"auto", "gemini", "ollama"}:
        vision_provider = "auto"
    ollama_timeout_seconds = _bounded_float(
        _pick("DARKSHADOW_OLLAMA_TIMEOUT_SECONDS", current_environment, file_values, "40.0"),
        default=40.0,
        minimum=5.0,
        maximum=300.0,
    )

    return Settings(
        api_key=api_key or None,
        model=model or "gemini-3.8-flash",
        casual_model=casual_model or "gemini-3.5-flash-lite",
        tavily_api_key=tavily_api_key or None,
        youtube_api_key=youtube_api_key or None,
        spotify_client_id=spotify_client_id or None,
        spotify_client_secret=spotify_client_secret or None,
        spotify_redirect_uri=spotify_redirect_uri or "http://127.0.0.1:8888/callback",
        tavily_search_depth=tavily_search_depth,
        tavily_max_results=tavily_max_results,
        realtime_cache_seconds=realtime_cache_seconds,
        automation_planner_max_calls_per_minute=automation_planner_max_calls,
        automation_plan_cache_seconds=automation_plan_cache_seconds,
        whatsapp_confirm_send=whatsapp_confirm_send,
        max_history_turns=history,
        request_timeout_seconds=timeout,
        enable_streaming=streaming,
        ipv4_first=ipv4_first,
        log_level=log_level,
        env_file_found=selected_file.is_file(),
        stt_backend=stt_backend,
        whisper_model=whisper_model,
        whisper_device=whisper_device,
        stt_languages=stt_languages,
        stt_calibration_seconds=stt_calibration,
        stt_timeout_seconds=stt_timeout,
        stt_phrase_time_limit_seconds=stt_phrase_limit,
        stt_device_index=stt_device_index,
        fish_api_key=fish_api_key or None,
        tts_provider=tts_provider,
        tts_fish_model=tts_fish_model,
        tts_fish_reference_id=tts_fish_reference_id,
        tts_fish_latency=tts_fish_latency,
        tts_gemini_model=tts_gemini_model,
        tts_gemini_voice=tts_gemini_voice,
        tts_gemini_timeout_seconds=tts_gemini_timeout,
        tts_fish_segment_words=tts_fish_segment_words,
        tts_fish_segment_characters=tts_fish_segment_characters,
        tts_gemini_segment_characters=tts_gemini_segment_characters,
        tts_usage_file=tts_usage_file.resolve(),
        tts_edge_fallback=tts_edge_fallback,
        tts_voice=tts_voice,
        tts_english_voice=tts_english_voice,
        tts_rate=tts_rate,
        tts_pitch=tts_pitch,
        tts_volume=tts_volume,
        memory_enabled=memory_enabled,
        memory_database_path=database_path.resolve(),
        wake_phrase_enabled=wake_phrase_enabled,
        wake_phrase=wake_phrase,
        openai_api_key=openai_api_key or None,
        live_provider=live_provider or "gemini",
        live_model=live_model or default_live_model,
        live_voice=live_voice or default_live_voice,
        live_reconnect_attempts=live_reconnect_attempts,
        live_mic_chunk_ms=live_mic_chunk_ms,
        live_vad_energy_threshold=live_vad_energy_threshold,
        live_echo_gate_multiplier=live_echo_gate_multiplier,
        live_audio_gain=live_audio_gain,
        live_barge_in=live_barge_in,
        live_echo_gate_cooldown_seconds=live_echo_gate_cooldown_seconds,
        live_vision_keyframe_enabled=live_vision_keyframe_enabled,
        live_vision_delta_threshold=live_vision_delta_threshold,
        live_vision_auto_mode=live_vision_auto_mode,
        notes_directory=notes_directory.resolve(),
        browser_user_data_dir=browser_user_data_dir.resolve(),
        browser_stealth_enabled=browser_stealth_enabled,
        browser_vision_enabled=browser_vision_enabled,
        whatsapp_provider=whatsapp_provider,
        whatsapp_phone_number_id=whatsapp_phone_number_id or None,
        whatsapp_access_token=whatsapp_access_token or None,
        twilio_account_sid=twilio_account_sid or None,
        twilio_auth_token=twilio_auth_token or None,
        twilio_whatsapp_from=twilio_whatsapp_from or None,
        youtube_agentic_video_enabled=youtube_agentic_video_enabled,
        agentic_video_model=agentic_video_model,
        thinking_budget_technical=thinking_budget_technical,
        thinking_budget_creative=thinking_budget_creative,
        thinking_budget_casual=thinking_budget_casual,
        thinking_budget_automation=thinking_budget_automation,
        context_caching_enabled=context_caching_enabled,
        context_cache_ttl_seconds=context_cache_ttl_seconds,
        search_grounding_provider=search_grounding_provider,
        map_grounding_enabled=map_grounding_enabled,
        embedding_model=embedding_model,
        computer_use_enabled=computer_use_enabled,
        computer_use_max_steps=computer_use_max_steps,
        allow_camera_access=False,
        react_max_steps=4,
        workflow_max_chain_length=5,
        ollama_enabled=ollama_enabled,
        ollama_base_url=ollama_base_url,
        ollama_vision_model=ollama_vision_model,
        vision_provider=vision_provider,
        ollama_timeout_seconds=ollama_timeout_seconds,
    )
