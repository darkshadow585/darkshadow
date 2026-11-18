"""
DARK SHADOW® - Main Application Entrypoint
A Minimal Living AI Desktop Interface for Windows 11.
Orchestrates the visual overlay, particle physics, voice activation, and Gemini AI.
"""

import sys
import os
import signal
import logging
import argparse
from typing import Optional
from pathlib import Path

# Add project root to sys.path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from dark_shadow.config import CONFIG, OrbState, LOGS_DIR
from dark_shadow.ui.overlay import DarkShadowOverlay
from dark_shadow.voice.wake_word import WakeWordDetector
from dark_shadow.voice.speech_input import ActiveSpeechListener
from dark_shadow.voice.speech_output import SpeechOutputSpeaker
from dark_shadow.ai.gemini import GeminiAssistant, GeminiWorker


# Configure Logging
log_file = LOGS_DIR / "dark_shadow.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger("dark_shadow.main")


class DarkShadowApp:
    """
    Master application coordinator.
    Wires together UI, physics, voice wake detection, STT, TTS, and Gemini AI.
    """

    def __init__(self, start_visible: bool = False, enable_voice: bool = True):
        self.enable_voice = enable_voice
        self.gemini_worker: Optional[GeminiWorker] = None

        # 1. Initialize Visual Overlay & Living Orb
        logger.info("Initializing DarkShadowOverlay...")
        self.overlay = DarkShadowOverlay(CONFIG)

        # 2. Initialize Gemini AI Client
        logger.info("Initializing Gemini AI assistant...")
        self.ai = GeminiAssistant(CONFIG.ai)

        # 3. Initialize Voice Subsystems
        self.speaker = SpeechOutputSpeaker(CONFIG.voice)
        self.listener: Optional[ActiveSpeechListener] = None
        self.wake_detector: Optional[WakeWordDetector] = None

        if self.enable_voice:
            logger.info("Setting up voice subsystems...")
            self.wake_detector = WakeWordDetector(CONFIG.voice)
            self._connect_voice_signals()
        else:
            logger.info("Voice subsystem disabled via command flag.")

        # 4. Connect UI Signals
        self.overlay.request_toggle_listen.connect(self.start_listening)
        self.overlay.request_toggle_activate.connect(self.overlay.toggle_activation)
        self.overlay.quit_requested.connect(self.shutdown)

        # Speaker amplitude drives particle vibration during speech output
        self.speaker.amplitude_changed.connect(self.overlay.orb.set_audio_amplitude)
        self.speaker.speech_finished.connect(self._on_speech_output_finished)

        # Inactivity auto-dismiss timer (e.g. 45 seconds of silence)
        self.inactivity_timer = QTimer()
        self.inactivity_timer.setInterval(45000)
        self.inactivity_timer.setSingleShot(True)
        self.inactivity_timer.timeout.connect(self._on_inactivity_timeout)

        # Start services
        self.overlay.start()

        if self.wake_detector:
            self.wake_detector.start()

        if start_visible:
            # Launch appearance animation immediately
            QTimer.singleShot(300, self.overlay.activate_orb)

    def _connect_voice_signals(self):
        """Wire wake detector events."""
        if self.wake_detector:
            self.wake_detector.wake_word_detected.connect(self._on_wake_word_triggered)

    def _on_wake_word_triggered(self):
        """Called when user says 'Dark Shadow'."""
        logger.info("Wake word 'Dark Shadow' detected by acoustic sensor!")
        if self.overlay.orb.state in (OrbState.IDLE, OrbState.DEACTIVATING):
            self.overlay.activate_orb()

        # Pause wake detector while interacting
        if self.wake_detector:
            self.wake_detector.pause()

        # Automatically enter listening state once assembled
        QTimer.singleShot(int(CONFIG.visual.activate_duration * 1000) + 100, self.start_listening)

    def start_listening(self):
        """Initiate voice capture in LISTENING state."""
        if self.speaker.isRunning():
            self.speaker.interrupt()

        logger.info("Transitioning to LISTENING state...")
        self.overlay.orb.set_state(OrbState.LISTENING)

        # Pause wake detector
        if self.wake_detector:
            self.wake_detector.pause()

        # Stop previous listener if any
        if self.listener is not None and self.listener.isRunning():
            self.listener.stop()

        # Launch active listener
        self.listener = ActiveSpeechListener(CONFIG.voice)
        self.listener.amplitude_changed.connect(self.overlay.orb.set_audio_amplitude)
        self.listener.transcription_complete.connect(self._on_user_transcription)
        self.listener.listening_timed_out.connect(self._on_listening_timeout)
        self.listener.start()

        # Reset inactivity timer
        self.inactivity_timer.stop()

    def _on_user_transcription(self, user_text: str):
        """User finished speaking. Dispatch query to Gemini in THINKING state."""
        self.overlay.orb.set_audio_amplitude(0.0)

        if not user_text:
            logger.info("No speech recognized; returning to calm interaction.")
            self.overlay.orb.set_state(OrbState.INTERACTING)
            self._resume_wake_detector()
            self.inactivity_timer.start()
            return

        logger.info(f"Dispatching query: '{user_text}' -> THINKING state.")
        self.overlay.orb.set_state(OrbState.THINKING)

        # Query Gemini in background worker thread
        self.gemini_worker = GeminiWorker(self.ai, user_text)
        self.gemini_worker.response_ready.connect(self._on_ai_response_ready)
        self.gemini_worker.error_occurred.connect(self._on_ai_error)
        self.gemini_worker.start()

    def _on_ai_response_ready(self, response_text: str):
        """Gemini response arrived. Transition to SPEAKING state and vocalize."""
        logger.info(f"AI Response arrived: '{response_text}' -> SPEAKING state.")
        self.overlay.orb.set_state(OrbState.SPEAKING)
        self.speaker.speak(response_text)

    def _on_ai_error(self, err_msg: str):
        """Handle AI query failure."""
        logger.error(f"AI query failed: {err_msg}")
        self.overlay.orb.set_state(OrbState.SPEAKING)
        self.speaker.speak("I encountered an anomaly processing that request.")

    def _on_speech_output_finished(self):
        """TTS finished speaking. Return to INTERACTING calm breathing."""
        logger.info("Speech playback completed; returning to INTERACTING state.")
        self.overlay.orb.set_state(OrbState.INTERACTING)
        self._resume_wake_detector()
        self.inactivity_timer.start()

    def _on_listening_timeout(self):
        """Listening expired with no speech detected."""
        logger.info("Listening timed out.")
        self.overlay.orb.set_state(OrbState.INTERACTING)
        self._resume_wake_detector()
        self.inactivity_timer.start()

    def _on_inactivity_timeout(self):
        """Gently dissolve orb after prolonged user inactivity."""
        logger.info("Inactivity threshold reached. Returning to dormant state.")
        if self.overlay.orb.state == OrbState.INTERACTING:
            self.overlay.deactivate_orb()

    def _resume_wake_detector(self):
        """Resume acoustic wake word scanner."""
        if self.wake_detector:
            self.wake_detector.resume()

    def shutdown(self):
        """Gracefully release all resources."""
        logger.info("Shutting down DARK SHADOW...")
        self.inactivity_timer.stop()
        if self.wake_detector:
            self.wake_detector.stop()
        if self.listener:
            self.listener.stop()
        if self.speaker:
            self.speaker.interrupt()
        self.overlay.stop()


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(description="DARK SHADOW® - Minimal Living AI Desktop Interface")
    parser.add_argument("--show", action="store_true", help="Launch and show orb immediately on start")
    parser.add_argument("--no-voice", action="store_true", help="Run without microphone/voice subsystem (visual mode)")
    parser.add_argument("--state", type=str, default="activating",
                        choices=["activating", "listening", "thinking", "speaking", "interacting", "idle"],
                        help="Start directly in a specific state for preview/testing")
    args = parser.parse_args()

    # Enable High-DPI support on Windows 11
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("DarkShadow")
    app.setOrganizationName("DarkShadow")
    # Keep application alive in system tray even if overlay is hidden
    app.setQuitOnLastWindowClosed(False)

    # Handle Ctrl+C in terminal
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    # Create app instance
    start_visible = args.show or (args.state != "idle")
    dark_shadow_app = DarkShadowApp(
        start_visible=start_visible,
        enable_voice=not args.no_voice
    )

    if args.state != "activating" and args.state != "idle":
        # Force specific state if requested via CLI flag
        target_state = OrbState(args.state)
        QTimer.singleShot(400, lambda: dark_shadow_app.overlay.orb.set_state(target_state))

    logger.info("DARK SHADOW® initialized. Operating system: Windows 11.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
