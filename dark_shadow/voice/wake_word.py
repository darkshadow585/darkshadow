"""
DARK SHADOW® - Wake Word Detection Service
Continuously listens in background for the activation phrase "Dark Shadow".
"""

import time
import logging
from typing import List, Optional
from PySide6.QtCore import QThread, Signal
import speech_recognition as sr

from ..config import VoiceConfig

logger = logging.getLogger("dark_shadow.voice.wake_word")


class WakeWordDetector(QThread):
    """
    Background listener that continuously monitors the microphone for
    the activation phrase 'Dark Shadow' and variants.
    """
    wake_word_detected = Signal()
    listening_status_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, voice_cfg: VoiceConfig, parent=None):
        super().__init__(parent)
        self.cfg = voice_cfg
        self.running = False
        self.paused = False
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = self.cfg.energy_threshold
        self.recognizer.dynamic_energy_threshold = self.cfg.dynamic_energy_threshold
        self.recognizer.pause_threshold = 0.6
        self.microphone: Optional[sr.Microphone] = None

    def pause(self):
        """Temporarily pause wake word scanning (e.g. during active conversation)."""
        self.paused = True

    def resume(self):
        """Resume wake word scanning."""
        self.paused = False

    def stop(self):
        """Stop detector thread."""
        self.running = False
        self.wait(2000)

    def run(self):
        """Main detection loop."""
        self.running = True
        logger.info("Starting Wake Word Detector...")

        # Initialize microphone
        try:
            self.microphone = sr.Microphone(sample_rate=self.cfg.sample_rate)
            with self.microphone as source:
                logger.info("Calibrating ambient noise for wake word detector...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)
        except Exception as e:
            logger.error(f"Failed to access microphone: {e}")
            self.error_occurred.emit(str(e))
            return

        self.listening_status_changed.emit(True)

        while self.running:
            if self.paused:
                time.sleep(0.15)
                continue

            try:
                with self.microphone as source:
                    # Listen with timeout
                    try:
                        audio = self.recognizer.listen(
                            source,
                            timeout=2.0,
                            phrase_time_limit=3.0
                        )
                    except sr.WaitTimeoutError:
                        continue

                if not self.running or self.paused:
                    continue

                # Recognize speech
                try:
                    text = self.recognizer.recognize_google(audio).strip().lower()
                    logger.debug(f"Wake detector heard: '{text}'")

                    if self._matches_wake_word(text):
                        logger.info(f"Wake phrase triggered by: '{text}'")
                        self.wake_word_detected.emit()
                        # Short pause to prevent re-triggering on echo
                        time.sleep(1.0)

                except sr.UnknownValueError:
                    # Inaudible / noise
                    pass
                except sr.RequestError as re:
                    logger.warning(f"Speech recognition service unavailable: {re}")
                    time.sleep(1.0)

            except Exception as e:
                logger.error(f"Error in wake word loop: {e}")
                time.sleep(0.5)

        self.listening_status_changed.emit(False)
        logger.info("Wake Word Detector stopped.")

    def _matches_wake_word(self, text: str) -> bool:
        """Check if recognized text matches any wake word variant."""
        text = text.lower().strip()
        for variant in self.cfg.wake_words:
            if variant in text:
                return True
        return False
