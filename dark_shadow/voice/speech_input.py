"""
DARK SHADOW® - Active Speech Input and Real-Time Audio Amplitude Tracker
Captures spoken input while streaming live RMS amplitude to make particles pulse in real time.
"""

import time
import logging
import numpy as np
from typing import Optional
from PySide6.QtCore import QThread, Signal
import speech_recognition as sr
import pyaudio

from ..config import VoiceConfig

logger = logging.getLogger("dark_shadow.voice.speech_input")


class ActiveSpeechListener(QThread):
    """
    Active listener thread for the LISTENING state:
    - Streams live audio chunks from PyAudio
    - Emits normalized real-time audio amplitude [0.0, 1.0] to drive particle expansion & vibration
    - Performs voice-activity detection (VAD) and silence cutoff
    - Transcribes captured user query and emits result
    """
    amplitude_changed = Signal(float)
    transcription_complete = Signal(str)
    listening_timed_out = Signal()
    error_occurred = Signal(str)

    def __init__(self, voice_cfg: VoiceConfig, parent=None):
        super().__init__(parent)
        self.cfg = voice_cfg
        self.running = False
        self.p: Optional[pyaudio.PyAudio] = None
        self.stream: Optional[pyaudio.Stream] = None
        self.recognizer = sr.Recognizer()

        # Dynamic sensitivity parameters
        self.noise_floor = 300.0
        self.speech_threshold = 700.0
        self.silence_timeout = 0.9      # Seconds of silence after speech to finish
        self.max_listen_time = 8.0      # Max recording window

    def stop(self):
        """Abort listening."""
        self.running = False
        self.wait(1500)

    def run(self):
        """Stream audio, calculate live RMS, and transcribe on silence."""
        self.running = True
        logger.info("ActiveSpeechListener started listening...")

        chunk_size = 512
        rate = self.cfg.sample_rate
        audio_frames = []

        has_speech_started = False
        speech_start_time = 0.0
        last_speech_time = time.perf_counter()
        session_start_time = time.perf_counter()

        try:
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=rate,
                input=True,
                frames_per_buffer=chunk_size
            )
        except Exception as e:
            logger.error(f"Cannot initialize audio input stream: {e}")
            self.error_occurred.emit(str(e))
            self._cleanup()
            return

        # Adaptive background calibration in first few chunks
        ambient_samples = []
        for _ in range(6):
            if not self.running:
                break
            try:
                data = self.stream.read(chunk_size, exception_on_overflow=False)
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(arr * arr)))
                ambient_samples.append(rms)
            except Exception:
                pass

        if ambient_samples:
            avg_ambient = float(np.mean(ambient_samples))
            self.noise_floor = max(100.0, avg_ambient)
            self.speech_threshold = self.noise_floor * 1.8 + 250.0

        logger.debug(f"Calibrated noise floor: {self.noise_floor:.1f}, speech threshold: {self.speech_threshold:.1f}")

        # Main active recording loop
        while self.running:
            now = time.perf_counter()

            # Global timeout
            if (now - session_start_time) > self.max_listen_time:
                logger.info("Listening session reached maximum duration.")
                break

            # Read microphone chunk
            try:
                data = self.stream.read(chunk_size, exception_on_overflow=False)
            except Exception as e:
                logger.warning(f"Audio read warning: {e}")
                continue

            audio_frames.append(data)

            # Compute RMS amplitude
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples)))

            # Normalize amplitude [0.0, 1.0] with soft sigmoid curve
            raw_amp = max(0.0, (rms - self.noise_floor) / 4500.0)
            norm_amp = min(1.0, raw_amp ** 0.85)

            # Emit amplitude to animate particles in real time
            self.amplitude_changed.emit(norm_amp)

            # Voice activity detection
            if rms > self.speech_threshold:
                if not has_speech_started:
                    has_speech_started = True
                    speech_start_time = now
                    logger.debug("Speech activity detected!")
                last_speech_time = now
            else:
                # If speech has started and silence threshold reached, stop recording
                if has_speech_started and (now - last_speech_time) > self.silence_timeout:
                    logger.debug(f"Silence detected after speech ({(now - last_speech_time):.2f}s). Finalizing input.")
                    break

            # If user hasn't spoken at all after 3.5s, timeout
            if not has_speech_started and (now - session_start_time) > 4.0:
                logger.info("No speech detected within initial timeout.")
                self.listening_timed_out.emit()
                self._cleanup()
                return

        self._cleanup()

        # Emit zero amplitude to settle particles
        self.amplitude_changed.emit(0.0)

        # Transcribe audio if speech was captured
        if has_speech_started and audio_frames:
            raw_audio_bytes = b"".join(audio_frames)
            audio_data = sr.AudioData(raw_audio_bytes, rate, 2)
            try:
                logger.info("Transcribing user speech...")
                text = self.recognizer.recognize_google(audio_data).strip()
                logger.info(f"User said: '{text}'")
                self.transcription_complete.emit(text)
            except sr.UnknownValueError:
                logger.info("Speech was unintelligible.")
                self.transcription_complete.emit("")
            except Exception as e:
                logger.error(f"Speech transcription error: {e}")
                self.error_occurred.emit(str(e))
        else:
            self.listening_timed_out.emit()

    def _cleanup(self):
        """Release audio resources."""
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self.p is not None:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None
