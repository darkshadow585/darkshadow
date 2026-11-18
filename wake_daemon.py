import io
import os
import re
import sys
import time
import winsound
import logging

# Ensure UTF-8 output on Windows consoles to prevent UnicodeEncodeError on Hindi/Devanagari characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import speech_recognition as sr
from config import load_settings
from live_voice import run_live_voice_mode
from networking import install_ipv4_first_dns

install_ipv4_first_dns()
logging.basicConfig(level=logging.WARNING)
LOGGER = logging.getLogger("wake_daemon")

WAKE_PATTERNS = [
    # Hindi Devanagari patterns (डार्क शैडो, डार्क, शैडो)
    re.compile(r"(?:हे\s*)?डार्क\s*(?:शैडो|शैड|शैडौ|शैडों|शाडो)?", re.IGNORECASE),
    re.compile(r"(?:हे\s*)?डक\s*शैडो", re.IGNORECASE),
    # English patterns
    re.compile(r"\b(?:hey\s+)?(?:dark|doctor|dak|dhark)\s*(?:shadow|shado|shedu|shedo|shedow)?\b", re.I),
    re.compile(r"\b(?:dark\s*shadow|darkshadow|hey\s*shadow)\b", re.I),
]


def _init_local_whisper(settings):
    """Attempt to load a lightweight local Whisper model for offline, zero-data wake detection."""
    try:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from faster_whisper import WhisperModel
        model_name = getattr(settings, "wake_whisper_model", "tiny")
        return WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception as exc:
        LOGGER.debug("Local faster-whisper unavailable for wake daemon: %s", exc)
        return None


def main():
    print("==========================================================")
    print("   DARKSHADOW GEMINI LIVE VOICE-TO-VOICE WAKE SYSTEM      ")
    print("  Initializing engines and audio devices...               ")
    print("==========================================================")
    sys.stdout.flush()

    settings = load_settings()
    recognizer = sr.Recognizer()

    print("[1/2] Loading Wake-Word detection engine...")
    sys.stdout.flush()
    whisper_model = _init_local_whisper(settings)
    engine_desc = "Local Faster-Whisper (Offline / 0 Data / Fast)" if whisper_model is not None else "Google Web Speech API (Online Fallback)"

    print(f"      Engine active: {engine_desc}")
    print("[2/2] Checking microphone...")
    sys.stdout.flush()

    try:
        mic = sr.Microphone(device_index=settings.stt_device_index)
        with mic as source:
            print("      Calibrating for ambient room noise (0.8s)...")
            sys.stdout.flush()
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
            recognizer.energy_threshold = max(80.0, recognizer.energy_threshold * 1.15)
            recognizer.dynamic_energy_threshold = True
            recognizer.dynamic_energy_adjustment_damping = 0.15
            recognizer.pause_threshold = 0.5
            print(f"      Microphone Ready! Ambient threshold: {recognizer.energy_threshold:.1f}")
    except Exception as mic_err:
        print("\n[ERROR] Microphone initialization failed:")
        print(f"        {mic_err}")
        print("Please check your microphone connection or device index in .env.")
        return

    print("\n----------------------------------------------------------")
    print("  STATUS: ACTIVE & LISTENING IN STANDBY")
    print("  Say 'Dark Shadow' or 'डार्क शैडो' to wake me up!")
    print("  Press Ctrl+C in this window to stop.")
    print("----------------------------------------------------------\n")
    sys.stdout.flush()

    while True:
        try:
            with mic as source:
                print("[Zzz...] Listening... (Say 'Dark Shadow' to wake)")
                sys.stdout.flush()
                audio = recognizer.listen(source, timeout=None, phrase_time_limit=5.0)

            # 1. Primary: Fast local Whisper transcription (0 network data, ~100ms)
            text = ""
            if whisper_model is not None:
                try:
                    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
                    segments, _ = whisper_model.transcribe(
                        io.BytesIO(wav_bytes),
                        beam_size=1,
                        initial_prompt="DarkShadow, Hey Dark Shadow, डार्क शैडो",
                    )
                    text = " ".join(seg.text for seg in segments).strip()
                except Exception as w_exc:
                    LOGGER.debug("Local wake whisper failed: %s", w_exc)

            # 2. Fallback: Google Web Speech if local Whisper was unavailable or gave empty text
            if not text:
                for lang in ["hi-IN", "en-IN", "en-US"]:
                    try:
                        text = recognizer.recognize_google(audio, language=lang).strip()
                        if text:
                            break
                    except Exception:
                        pass

            if not text:
                continue

            print(f"Heard: \"{text}\"")
            sys.stdout.flush()

            matched = any(pat.search(text) for pat in WAKE_PATTERNS)

            if matched:
                try:
                    winsound.Beep(1400, 200)
                except Exception:
                    pass

                print("\n" + "="*60)
                provider_lbl = "OpenAI Realtime Live" if getattr(settings, "live_provider", "gemini").lower() == "openai" else "Gemini Live"
                print(f">>> WAKE-UP TRIGGERED! Launching {provider_lbl} Voice-to-Voice...")
                print(f"    (Model: '{settings.live_model}' | Voice: '{settings.live_voice}' Active)")
                print("    (Say 'bye' or 'stop' to put DarkShadow back to sleep)")
                print("="*60 + "\n")
                sys.stdout.flush()

                # Release the mic before starting Live Voice
                try:
                    run_live_voice_mode(settings, print)
                except Exception as live_err:
                    print(f"Live voice session ended: {live_err}")

                print("\n[Zzz...] Returning to silent sleep mode.")
                sys.stdout.flush()
                time.sleep(1.0)

        except KeyboardInterrupt:
            print("\nWake daemon stopped by Captain.")
            break
        except Exception as e:
            LOGGER.debug("Wake loop notice: %s", e)
            time.sleep(0.3)


if __name__ == "__main__":
    main()
