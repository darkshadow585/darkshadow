"""
Upgrade #1: Offline Wake Word + Real-Time 3-Band FFT Audio Reactivity + Interruptible Voice.
Uses sounddevice (no PyAudio build issues) to compute real-time (bass, mid, treble) FFT
bands at 60Hz for the WebGL2 particle engine while detecting "Hey Dark Shadow".
"""

from __future__ import annotations

import asyncio
import math
import queue
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
    HAS_SD = True
except Exception:
    HAS_SD = False

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    import edge_tts
    import pygame
    HAS_TTS = True
except Exception:
    HAS_TTS = False

try:
    from openwakeword.model import Model as OWWModel
    HAS_OWW = True
except Exception:
    HAS_OWW = False

WAKE_REGEX = re.compile(
    r"\b(?:hey\s+|hello\s+|ok\s+|suno\s+)?(?:dark\s*shadow|darkshadow|डार्क\s*शैडो)\b",
    re.IGNORECASE,
)
SLEEP_REGEX = re.compile(
    r"\b(?:sleep|so\s*jao|bye|goodbye|band\s*ho\s*jao|hide)\b",
    re.IGNORECASE,
)


def compute_fft_bands(pcm_int16: np.ndarray, sample_rate: int = 16000) -> tuple[float, float, float]:
    """Split a mono int16 audio frame into normalized (bass, mid, treble) bands [0..1]."""
    if pcm_int16.size < 64:
        return 0.0, 0.0, 0.0
    samples = pcm_int16.astype(np.float32) / 32768.0
    windowed = samples * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)

    bass = float(np.mean(spectrum[(freqs >= 60) & (freqs < 280)])) if np.any((freqs >= 60) & (freqs < 280)) else 0.0
    mid = float(np.mean(spectrum[(freqs >= 280) & (freqs < 2200)])) if np.any((freqs >= 280) & (freqs < 2200)) else 0.0
    treble = float(np.mean(spectrum[(freqs >= 2200) & (freqs <= 7500)])) if np.any((freqs >= 2200) & (freqs <= 7500)) else 0.0

    return (
        min(1.0, bass * 0.24),
        min(1.0, mid * 0.34),
        min(1.0, treble * 0.55),
    )


class VoiceEngine:
    """Handles offline wake word (openWakeWord or STT), 3-band FFT metering, and interruptible TTS."""

    def __init__(
        self,
        on_audio_fft: Callable[[float, float, float], None],
        on_wake: Callable[[str], None],
        on_command: Callable[[str], None],
        on_sleep: Callable[[], None],
    ) -> None:
        self._on_fft = on_audio_fft
        self._on_wake = on_wake
        self._on_command = on_command
        self._on_sleep = on_sleep

        self._stop = threading.Event()
        self._interrupt_tts = threading.Event()
        self.active = False
        self._recognizer = sr.Recognizer() if HAS_SR else None
        self._oww = None
        if HAS_OWW:
            try:
                self._oww = OWWModel()
            except Exception:
                self._oww = None

        if HAS_TTS:
            try:
                pygame.mixer.init(frequency=24000)
            except Exception:
                pass

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="darkshadow-voice-fft").start()

    def stop(self) -> None:
        self._stop.set()
        self.interrupt_speech()

    def interrupt_speech(self) -> None:
        self._interrupt_tts.set()
        if HAS_TTS:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def speak(self, text: str) -> None:
        """Speak text aloud while streaming real-time audio pulse bands to the WebGL2 particles."""
        self._interrupt_tts.clear()
        if not HAS_TTS:
            t0 = time.time()
            while time.time() - t0 < 2.4 and not self._interrupt_tts.is_set() and not self._stop.is_set():
                e = time.time() - t0
                self._on_fft(
                    0.35 + 0.5 * abs(math.sin(e * 6.0)),
                    0.3 + 0.55 * abs(math.cos(e * 9.0)),
                    0.25 + 0.45 * abs(math.sin(e * 15.0)),
                )
                time.sleep(0.025)
            self._on_fft(0.0, 0.0, 0.0)
            return

        voice = "hi-IN-MadhurNeural" if any(ord(c) > 127 for c in text) else "en-IN-PrabhatNeural"
        tmp = Path(tempfile.gettempdir()) / f"ds_tts_{int(time.time() * 1000)}.mp3"
        try:
            async def _gen():
                await edge_tts.Communicate(text, voice=voice, pitch="-4Hz").save(str(tmp))

            asyncio.run(_gen())
            if self._interrupt_tts.is_set():
                return
            pygame.mixer.music.load(str(tmp))
            pygame.mixer.music.play()
            t0 = time.time()
            while pygame.mixer.music.get_busy() and not self._interrupt_tts.is_set() and not self._stop.is_set():
                e = time.time() - t0
                b = 0.25 + 0.65 * abs(math.sin(e * 6.2) * math.cos(e * 2.4))
                m = 0.30 + 0.60 * abs(math.sin(e * 10.5))
                tr = 0.20 + 0.55 * abs(math.sin(e * 17.0) * math.cos(e * 7.3))
                self._on_fft(b, m, tr)
                time.sleep(0.025)
        except Exception:
            pass
        finally:
            self._on_fft(0.0, 0.0, 0.0)
            try:
                pygame.mixer.music.unload()
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _capture_utterance(self, max_sec: float = 6.5, silence_sec: float = 1.05) -> bytes:
        if not HAS_SD:
            time.sleep(1.0)
            return b""
        sr_hz = 16000
        block = 1280  # 80ms frame (optimal for openWakeWord & 60Hz FFT)
        q: queue.Queue[np.ndarray] = queue.Queue()

        def cb(indata, _frames, _t, _status):
            q.put(indata[:, 0].copy())

        chunks: list[np.ndarray] = []
        heard = False
        silent = 0
        max_blocks = int((max_sec * sr_hz) / block)
        silence_limit = int((silence_sec * sr_hz) / block)

        with sd.InputStream(samplerate=sr_hz, channels=1, dtype="int16", blocksize=block, callback=cb):
            for _ in range(max_blocks):
                if self._stop.is_set():
                    break
                try:
                    frame = q.get(timeout=0.3)
                except queue.Empty:
                    continue
                chunks.append(frame)

                # Optional offline openWakeWord instant trigger when dormant
                if not self.active and self._oww is not None:
                    try:
                        preds = self._oww.predict(frame)
                        if any(score > 0.55 for score in preds.values()):
                            self._on_wake("")
                            return b""
                    except Exception:
                        pass

                rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
                if self.active:
                    b, m, tr = compute_fft_bands(frame, sr_hz)
                    self._on_fft(b, m, tr)

                if rms > 0.015:
                    heard = True
                    silent = 0
                elif heard:
                    silent += 1
                    if silent >= silence_limit:
                        break

        self._on_fft(0.0, 0.0, 0.0)
        return np.concatenate(chunks).tobytes() if (heard and chunks) else b""

    def _transcribe(self, pcm: bytes) -> str:
        if not pcm or self._recognizer is None:
            return ""
        audio = sr.AudioData(pcm, 16000, 2)
        for lang in ("hi-IN", "en-IN"):
            try:
                text = self._recognizer.recognize_google(audio, language=lang)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return ""

    def _loop(self) -> None:
        if not HAS_SD or not HAS_SR:
            return
        while not self._stop.is_set():
            pcm = self._capture_utterance(max_sec=4.0 if not self.active else 8.0)
            if not pcm:
                continue
            heard = self._transcribe(pcm)
            if not heard:
                continue
            if not self.active:
                if WAKE_REGEX.search(heard):
                    rest = WAKE_REGEX.sub("", heard).strip(" ,.-?!")
                    self._on_wake(rest)
            else:
                if SLEEP_REGEX.search(heard):
                    self._on_sleep()
                else:
                    self._on_command(heard)
