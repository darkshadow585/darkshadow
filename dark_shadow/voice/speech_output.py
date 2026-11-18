"""
DARK SHADOW® - Gemini AI Speech Synthesis & Synchronized Vocal Waveform Tracker
Synthesizes speech using Google Gemini API (gemini-3.1-flash-tts-preview / Charon voice)
and streams real-time RMS amplitudes to vibrate the orb particles in exact sync with the speech.
"""

import os
import time
import wave
import tempfile
import logging
import numpy as np
from typing import Optional
from PySide6.QtCore import QThread, Signal
import pyaudio

from ..config import VoiceConfig

logger = logging.getLogger("dark_shadow.voice.speech_output")

# Check for Google GenAI SDK
GENAI_TTS_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GENAI_TTS_AVAILABLE = True
except ImportError:
    pass


class SpeechOutputSpeaker(QThread):
    """
    Synthesizes speech via Google Gemini API (Charon voice) and falls back to pyttsx3.
    Streams 24000 Hz PCM audio directly through PyAudio and emits real-time RMS amplitudes.
    """
    amplitude_changed = Signal(float)
    speech_started = Signal()
    speech_finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, voice_cfg: VoiceConfig, parent=None):
        super().__init__(parent)
        self.cfg = voice_cfg
        self.text_to_speak = ""
        self.running = False
        self._interrupted = False
        self.client = None
        self._init_gemini_client()

    def _init_gemini_client(self):
        """Initialize Google GenAI client for TTS."""
        api_key = os.getenv("GEMINI_API_KEY", "")
        if GENAI_TTS_AVAILABLE and api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                logger.info(f"Gemini TTS initialized with model '{self.cfg.tts_gemini_model}' and voice '{self.cfg.tts_gemini_voice}'.")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini TTS Client: {e}")
                self.client = None

    def speak(self, text: str):
        """Queue text to synthesize and start speaker thread."""
        if not text or not text.strip():
            return
        self.text_to_speak = text.strip()
        self._interrupted = False
        if not self.isRunning():
            self.start()

    def interrupt(self):
        """Abort ongoing speech."""
        self._interrupted = True
        self.running = False

    def run(self):
        """Synthesize and stream audio."""
        if not self.text_to_speak:
            return

        self.running = True
        self.speech_started.emit()
        logger.info(f"Speaking: '{self.text_to_speak}'")

        # Try Gemini API TTS first
        tts_success = False
        if self.client:
            try:
                tts_success = self._speak_with_gemini(self.text_to_speak)
            except Exception as e:
                logger.warning(f"Gemini TTS synthesis error: {e}. Falling back to local engine...")
                tts_success = False

        # Fallback to local pyttsx3 if Gemini TTS fails or offline
        if not tts_success and not self._interrupted:
            try:
                self._speak_with_pyttsx3(self.text_to_speak)
            except Exception as e:
                logger.error(f"pyttsx3 fallback error: {e}")
                self.error_occurred.emit(str(e))

        self.amplitude_changed.emit(0.0)
        self.speech_finished.emit()
        self.running = False
        logger.info("Speech playback completed.")

    def _speak_with_gemini(self, text: str) -> bool:
        """Query Gemini API for audio modality and stream PCM to speakers."""
        logger.info(f"Generating voice via Gemini TTS model '{self.cfg.tts_gemini_model}' (Voice: {self.cfg.tts_gemini_voice})...")

        # Request AUDIO modality from Gemini
        response = self.client.models.generate_content(
            model=self.cfg.tts_gemini_model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=['AUDIO'],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self.cfg.tts_gemini_voice
                        )
                    )
                )
            )
        )

        audio_bytes = None
        sample_rate = 24000

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                audio_bytes = part.inline_data.data
                # Check mime type for sample rate
                mime = part.inline_data.mime_type or ""
                if "rate=" in mime:
                    try:
                        rate_part = mime.split("rate=")[1].split(";")[0].strip()
                        sample_rate = int(rate_part)
                    except Exception:
                        pass
                break

        if not audio_bytes:
            logger.warning("No audio bytes returned by Gemini TTS.")
            return False

        logger.info(f"Gemini TTS generated {len(audio_bytes)} bytes of PCM audio at {sample_rate} Hz. Streaming to speakers...")
        self._stream_pcm_audio(audio_bytes, sample_rate)
        return True

    def _stream_pcm_audio(self, pcm_bytes: bytes, sample_rate: int = 24000):
        """Stream raw 16-bit mono PCM audio in chunks through PyAudio while tracking RMS."""
        p = pyaudio.PyAudio()
        chunk_frames = 1024
        bytes_per_sample = 2  # 16-bit
        chunk_bytes = chunk_frames * bytes_per_sample

        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                output=True,
                frames_per_buffer=chunk_frames
            )

            total_bytes = len(pcm_bytes)
            offset = 0

            while offset < total_bytes and self.running and not self._interrupted:
                chunk = pcm_bytes[offset:offset + chunk_bytes]
                offset += chunk_bytes

                # Play audio
                stream.write(chunk)

                # Compute RMS amplitude of this chunk
                samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                if len(samples) > 0:
                    rms = float(np.sqrt(np.mean(samples * samples)))
                    # Normalize amplitude for particle pulsation [0.0, 1.0]
                    norm_amp = min(1.0, (rms / 4200.0) ** 0.82)
                    self.amplitude_changed.emit(norm_amp)

            stream.stop_stream()
            stream.close()

        except Exception as e:
            logger.error(f"PyAudio playback error: {e}")
        finally:
            p.terminate()

    def _speak_with_pyttsx3(self, text: str):
        """Offline fallback using pyttsx3."""
        import pyttsx3
        logger.info("Using local pyttsx3 fallback voice.")
        temp_wav = os.path.join(tempfile.gettempdir(), f"ds_fallback_{int(time.time()*1000)}.wav")

        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', self.cfg.tts_rate)
            engine.setProperty('volume', self.cfg.tts_volume)
            engine.save_to_file(text, temp_wav)
            engine.runAndWait()
            engine.stop()

            if os.path.exists(temp_wav):
                p = pyaudio.PyAudio()
                with wave.open(temp_wav, 'rb') as wf:
                    stream = p.open(
                        format=p.get_format_from_width(wf.getsampwidth()),
                        channels=wf.getnchannels(),
                        rate=wf.getframerate(),
                        output=True,
                        frames_per_buffer=512
                    )
                    data = wf.readframes(512)
                    while data and self.running and not self._interrupted:
                        stream.write(data)
                        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                        rms = float(np.sqrt(np.mean(samples * samples)))
                        self.amplitude_changed.emit(min(1.0, (rms / 3500.0) ** 0.8))
                        data = wf.readframes(512)
                    stream.stop_stream()
                    stream.close()
                p.terminate()
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass
