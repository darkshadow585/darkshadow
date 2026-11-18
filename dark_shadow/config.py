"""
DARK SHADOW® - Configuration Module
Centralized settings for visual aesthetics, particle physics, voice, and AI.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os
import sys

# Base directories
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ASSETS_DIR = BASE_DIR / "assets"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables if available
try:
    from dotenv import load_dotenv
    # Look for .env in project root or parent
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass


class OrbState(Enum):
    """Core operating states for DARK SHADOW."""
    IDLE = "idle"                    # Hidden or dormant
    ACTIVATING = "activating"        # Particles rising from screen bottom & assembling
    LISTENING = "listening"          # Voice-reactive pulsing
    THINKING = "thinking"            # Counter-rotating vortex & cosmic patterns
    SPEAKING = "speaking"            # Vocal waveform particle pulsation
    INTERACTING = "interacting"      # Mouse hover, drag, and click reactions
    DEACTIVATING = "deactivating"    # Particles dissolve, fall, and fade away


@dataclass
class VisualConfig:
    """Aesthetic and rendering settings."""
    # Target frame rate
    target_fps: int = 60
    frame_interval_ms: int = 16  # ~60 fps (1000/60)

    # Particle properties
    particle_count: int = 750
    min_particle_size: float = 0.9
    max_particle_size: float = 1.8
    trail_length: int = 3
    enable_constellation_lines: bool = False
    constellation_max_distance: float = 0.0

    # Orb geometry
    base_radius: float = 72.0
    breathing_amplitude: float = 2.5
    breathing_speed: float = 1.4     # Calm, gentle breathing
    float_amplitude_x: float = 0.0   # Perfectly stable, no wandering
    float_amplitude_y: float = 0.0   # Perfectly stable, no wandering
    float_speed: float = 0.0

    # Particle Colors (RGBA tuples in 0-255 range)
    # Minimal futuristic palette: soft white, ice blue, subtle cyan
    color_white: tuple = (255, 255, 255, 230)
    color_soft_blue: tuple = (186, 220, 248, 220)
    color_ice_blue: tuple = (147, 197, 253, 200)
    color_subtle_cyan: tuple = (56, 189, 248, 190)
    color_cyan_glow: tuple = (34, 211, 238, 160)
    color_core_glow: tuple = (240, 249, 255, 140)

    # Bloom / glow settings
    glow_layers: int = 3
    glow_sigma: float = 1.4

    # Animation durations (seconds)
    activate_duration: float = 2.0
    deactivate_duration: float = 1.3
    ripple_duration: float = 1.0


@dataclass
class PhysicsConfig:
    """Particle dynamics, forces, and kinetic equations."""
    spring_cohesion: float = 0.045     # Pull toward equilibrium
    damping: float = 0.925             # Air resistance / friction
    brownian_strength: float = 0.45    # Subtle organic jitter

    # Mouse repulsion & attraction
    mouse_repel_radius: float = 110.0
    mouse_repel_force: float = 4.0
    mouse_attract_radius: float = 190.0
    mouse_attract_force: float = 0.8
    mouse_max_speed: float = 8.5

    # Scroll ripple physics
    ripple_speed: float = 180.0        # Px per second expansion
    ripple_wave_width: float = 28.0
    ripple_amplitude: float = 18.0

    # Audio reactivity factors
    audio_radius_scale: float = 26.0    # Extra radius when shouting/loud
    audio_jitter_scale: float = 3.5     # Waveform vibration multiplier


@dataclass
class VoiceConfig:
    """Speech recognition and synthesis settings."""
    wake_words: list = field(default_factory=lambda: [
        "dark shadow",
        "darkshadow",
        "hey dark shadow",
        "ok dark shadow",
        "shadow"
    ])
    sample_rate: int = 16000
    chunk_size: int = 1024
    energy_threshold: int = 350
    dynamic_energy_threshold: bool = True
    pause_threshold: float = 0.85
    tts_rate: int = 175
    tts_volume: float = 0.95
    tts_gemini_model: str = field(default_factory=lambda: os.getenv("DARKSHADOW_TTS_GEMINI_MODEL", "gemini-3.1-flash-tts-preview"))
    tts_gemini_voice: str = field(default_factory=lambda: os.getenv("DARKSHADOW_TTS_GEMINI_VOICE", "Charon"))
    enabled: bool = True


@dataclass
class AIConfig:
    """Gemini AI API configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model_name: str = field(default_factory=lambda: os.getenv("DARKSHADOW_CASUAL_MODEL", os.getenv("DARKSHADOW_MODEL", "gemini-3.5-flash-lite")))
    system_prompt: str = (
        "You are DARK SHADOW, a minimal, elegant, highly intelligent living desktop AI overlay "
        "for Windows 11. Your visual form is a floating, breathing particle orb. "
        "Your personality is calm, poised, concise, insightful, and futuristic. "
        "Keep your verbal responses natural, elegant, and concise (1 to 3 sentences maximum), "
        "unless explicitly asked for an in-depth breakdown."
    )
    request_timeout: float = 12.0


@dataclass
class WindowConfig:
    """Desktop overlay window geometry and interaction."""
    initial_width: int = 420
    initial_height: int = 420
    always_on_top: bool = True
    draggable: bool = True
    tray_enabled: bool = True
    global_hotkey: str = "Ctrl+Shift+D"


@dataclass
class AppConfig:
    """Master configuration container."""
    visual: VisualConfig = field(default_factory=VisualConfig)
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    window: WindowConfig = field(default_factory=WindowConfig)


# Global config instance
CONFIG = AppConfig()
