"""OpenAI Realtime API voice-to-voice session for DarkShadow.

Provides native bidirectional audio streaming over WebSockets:
- Microphone 24kHz PCM input streams directly to OpenAI Realtime.
- OpenAI streams 24kHz PCM audio back to the speaker in real time.
- Server-side VAD handles barge-in and turn detection.
- Local automation tools execute locally and results are fed back to the model.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import time
from datetime import datetime
from importlib import import_module
from typing import Any, Callable

from config import Settings
from chatbot import SYSTEM_INSTRUCTION
from automation import AUTOMATION_FUNCTION_SCHEMAS
from live_voice import (
    AsyncAudioPlayer,
    LiveVoiceCallbacks,
    OutputFunction,
    _calculate_pcm_rms,
    _execute_tool_call,
    SPEAKER_SAMPLE_RATE,
)

LOGGER = logging.getLogger(__name__)

# OpenAI Realtime strictly requires 24kHz, 16-bit PCM, mono
OPENAI_MIC_SAMPLE_RATE = 24000
OPENAI_MIC_CHANNELS = 1
OPENAI_MIC_SAMPLE_WIDTH = 2

OPENAI_VALID_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"}


class OpenAIRealtimeSession:
    """Manage a single OpenAI Realtime bidirectional audio session."""

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

    def _get_pyaudio(self) -> Any:
        if self._pyaudio_module is None:
            self._pyaudio_module = import_module("pyaudio")
        return self._pyaudio_module

    def _build_tools_schema(self) -> list[dict[str, Any]]:
        """Format local automation tools for OpenAI Realtime function declarations."""
        tools = []
        for schema in AUTOMATION_FUNCTION_SCHEMAS:
            tools.append({
                "type": "function",
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters", {"type": "object", "properties": {}}),
            })
        return tools

    def _build_live_system_instruction(self) -> str:
        now_local = datetime.now().strftime("%I:%M %p (%d %B %Y, %A)")
        knowledge_summary = ""
        try:
            from memory import SQLiteMemoryStore
            mem = SQLiteMemoryStore(self.settings.memory_database_path)
            knowledge_summary = mem.get_formatted_captain_knowledge_summary()
        except Exception:
            pass

        return (
            SYSTEM_INSTRUCTION
            + f"\n\nCURRENT INDIAN STANDARD TIME (IST): The current live time of Captain in India is {now_local}. Whenever Captain asks what time or date it is, state this exact Indian Standard Time ({now_local}) directly and accurately."
            + (f"\n\n{knowledge_summary}" if knowledge_summary else "")
            + "\n\nCRITICAL VOICE IDENTITY DIRECTIVE:\nYou are DarkShadow, an AI assistant conversing with Captain (Kuldeep). Only listen and respond to Captain's instructions. If you ever hear your own voice, assistant speech echo from speakers, or background audio playback, completely ignore it. NEVER execute tools, switch tasks, or alter your responses based on your own echoed voice. Only Captain gives commands."
            + "\n\nCRITICAL WHATSAPP SAFETY RULE:\n1. If Captain asks to search or check if someone is on WhatsApp (e.g. 'Shivani naam ki ladki search karo', 'Kuldeep search karo', 'dekho WhatsApp par hai kya'), ONLY call `search_whatsapp_contact(contact_name=...)`. NEVER call send_whatsapp_message!\n2. NEVER invent fake messages (like 'Hi', 'Checking...', 'Testing'). If Captain wants to send a message but did not specify the message text, ask Captain: 'Captain, kya message bhejna hai?' before sending!\n3. Always confirm before dispatching real messages."
            + "\n\nLEARNING & PERSISTENT MEMORY DIRECTIVE: You remember everything about Captain. Whenever Captain tells you his preferences, favorite singers/songs, city, college, or habits, immediately call `save_captain_fact(key=..., value=...)` or `add_to_favorites(title=..., artist=...)`! Whenever Captain corrects you or teaches a lesson, call `save_captain_lesson(topic=..., lesson=...)` to remember for all future sessions!"
            + "\n\nLIVE VOICE SPEED DIRECTIVE: You are in a real-time live voice conversation. Reply immediately with zero hesitation. Keep spoken answers punchy, natural, and concise (1-2 sentences). Generate audio tokens instantly."
            + "\n\nGPT-LIVE 1 VOCAL BENCHMARK DIRECTIVE:\n1. Thinking Bridges: When asked to search, check, think, or explain, naturally bridge like a live person (e.g. 'Ek second, dekhta hoon...', 'Hmm ek minute check karne do...', 'Sach bataun toh thoda tedha hai...'). Never freeze into awkward dead silence.\n2. Organic Addressing: Address Kuldeep as 'Captain' naturally when greeting or starting, but NEVER repeat 'Captain' in every single sentence. Speak directly and seamlessly like a close friend.\n3. Real Conversational Delivery: Talk with effortless charisma ('befikr flow'), authentic chuckles, natural breathing pauses, and relaxed Hinglish cadence. Never sound like a corporate robot or customer support script.\n4. STRICT ANTI-STAGE-DIRECTION & ACTING DIRECTIVE: NEVER write or vocalize bracketed stage directions like '(रोते हुए)', '(आँसू भर के)', '*(crying)*', '[laughs]', or '>(चिल्ला-चिल्ला कर रोते हुए)'. The audio generator speaks whatever text you produce! When Captain asks you to act, cry, weep, or laugh, NEVER announce the emotion—DIRECTLY ACT IT OUT using vocal trembling, broken stutter hyphens ('म-माई... क-कहाँ...'), breathless ellipses pauses ('...'), and authentic cries or laughs. Stay 100% in character during scenes without breaking the fourth wall.\n5. NO ROBOTIC AI EXCUSES: NEVER say 'Main to AI hoon', 'Main sirf text samajhta hoon', or 'Mujhe real feelings mehsoos nahi hoti'. If Captain critiques your acting, take it sportingly and playfully like a human friend ('Arre haan Captain, pakde gaye! Ruko, ek aur take try karta hoon...')!\n6. RHETORICAL SPEECH CAUTION: NEVER open YouTube, browser, or apps when Captain is speaking conversationally, rhetorically, or metaphorically (e.g. 'pehle dekho kaise acting karte hain', 'acting seekh ke aao'). ONLY call tools when Captain gives an EXPLICIT action command (e.g. 'YouTube par gaana chalao', 'YouTube search karo')!\n7. METHOD ACTING & CRAFT ANALYSIS: When Captain tells you to 'pehle dekho ya samjho ki acting kaise karte hain / dialogue kaise present kiya jata hai', NEVER open YouTube or apps. First briefly break down the emotional craft and subtext like a passionate method actor (e.g. 'Sahi pakde Director sahab! Aise scene mein pehle shock aur aawaz ka gale mein phasna chahiye, phir shikwa aur aansoo... dekhiye main is craft ke hisaab se take leta hoon:'), and then immediately deliver the dialogue with that layered modulation!\n8. STRICT CREATIVE & DIALOGUE RULE: NEVER call search_google or search the web for dialogues, acting, jokes, or shayari! Web search fetches silly meme reels (like 'samosa' or 'CCTV proof') which ruins the scene! ALWAYS deliver intense, powerful, original, and culturally authentic dialogues directly from your own creative mind with raw swag and cinematic impact!"
        )

    def _flush_input_transcription(self) -> None:
        if self._input_text_chunks:
            full_text = " ".join(self._input_text_chunks).strip()
            self._input_text_chunks.clear()
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
                if self._callbacks and callable(getattr(self._callbacks, "on_model_transcript", None)):
                    try:
                        self._callbacks.on_model_transcript(full_text)
                    except Exception:
                        pass

    async def _mic_sender(self, ws: Any) -> None:
        """Capture 24kHz mic audio and stream base64 PCM frames to OpenAI Realtime."""
        pa = self._get_pyaudio()
        if self._audio is None:
            self._audio = pa.PyAudio()

        chunk_samples = int(OPENAI_MIC_SAMPLE_RATE * self.settings.live_mic_chunk_ms / 1000)
        mic_stream = self._audio.open(
            format=pa.paInt16,
            channels=OPENAI_MIC_CHANNELS,
            rate=OPENAI_MIC_SAMPLE_RATE,
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
                    if getattr(self.settings, "live_barge_in", False):
                        interrupt_threshold = max(1800.0, float(self.settings.live_vad_energy_threshold) * 3.0)
                        if rms > interrupt_threshold:
                            self._player.barge_in_purge()
                            self._model_turn_active = False
                            try:
                                await ws.send(json.dumps({"type": "response.cancel"}))
                            except Exception:
                                pass
                    continue

                # Stream audio chunk to OpenAI
                b64_audio = base64.b64encode(pcm_data).decode("ascii")
                try:
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": b64_audio,
                    }))
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

    async def _response_receiver(self, ws: Any) -> None:
        """Process incoming WebSocket events from OpenAI Realtime."""
        try:
            async for raw_msg in ws:
                if self._stop_event.is_set():
                    break

                try:
                    event = json.loads(raw_msg)
                except Exception:
                    continue

                event_type = event.get("type", "")

                # 1. Incoming Audio Delta (24kHz PCM)
                if event_type == "response.audio.delta":
                    delta_b64 = event.get("delta")
                    if delta_b64:
                        pcm = base64.b64decode(delta_b64)
                        self._model_turn_active = True
                        self._player.play_chunk(pcm)

                # 2. Output Transcription Delta (Word-by-word assistant speech)
                elif event_type == "response.audio_transcript.delta":
                    text_delta = event.get("delta", "")
                    if text_delta:
                        self._flush_input_transcription()
                        clean = str(text_delta).strip()
                        if clean:
                            if not self._output_text_chunks:
                                sys.stdout.write("DarkShadow (speaking):\n")
                            self._output_text_chunks.append(clean)
                            sys.stdout.write(f"  ↳ {clean}\n")
                            sys.stdout.flush()

                # 3. User Speech Transcribed by Whisper
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    user_transcript = event.get("transcript", "").strip()
                    if user_transcript:
                        self._output_fn(f"\nCaptain (live):\n  • {user_transcript}")
                        self._input_text_chunks.append(user_transcript)
                        if self._callbacks and callable(getattr(self._callbacks, "on_user_transcript", None)):
                            try:
                                self._callbacks.on_user_transcript(user_transcript)
                            except Exception:
                                pass

                # 4. Server-Side VAD Barge-In Detected
                elif event_type == "input_audio_buffer.speech_started":
                    self._player.barge_in_purge()
                    self._model_turn_active = False
                    try:
                        await ws.send(json.dumps({"type": "response.cancel"}))
                    except Exception:
                        pass

                # 5. Function Call Execution
                elif event_type == "response.output_item.done":
                    item = event.get("item", {})
                    if item.get("type") == "function_call":
                        call_id = item.get("call_id", "")
                        func_name = item.get("name", "")
                        raw_args = item.get("arguments", "{}")
                        try:
                            func_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                        except Exception:
                            func_args = {}

                        self._output_fn(f"  ⚡ [Tool Call] {func_name}({func_args})")
                        if self._callbacks and callable(getattr(self._callbacks, "on_tool_call", None)):
                            try:
                                self._callbacks.on_tool_call(func_name, func_args)
                            except Exception:
                                pass

                        result = _execute_tool_call(func_name, func_args)
                        res_msg = result.get("message", "Done") if isinstance(result, dict) else str(result)
                        self._output_fn(f"  ✅ [Result] {res_msg}")
                        if self._callbacks and callable(getattr(self._callbacks, "on_tool_result", None)):
                            try:
                                self._callbacks.on_tool_result(func_name, result)
                            except Exception:
                                pass

                        # Send function result back to OpenAI
                        try:
                            await ws.send(json.dumps({
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(result, ensure_ascii=False),
                                },
                            }))
                            # Trigger response generation with the tool result
                            await ws.send(json.dumps({"type": "response.create"}))
                        except Exception as exc:
                            LOGGER.warning("Failed to send tool output to OpenAI: %s", exc)

                # 6. Response Turn Completed
                elif event_type == "response.done":
                    self._model_turn_active = False
                    last_in = " ".join(self._input_text_chunks).lower().strip()
                    last_out = " ".join(self._output_text_chunks).lower().strip()
                    self._flush_input_transcription()
                    self._flush_output_transcription()

                    exit_keywords = [
                        "bye", "बाय", "अलविदा", "alvida", "goodbye", "stop",
                        "स्टॉप", "band karo", "बंद करो", "so jao", "सो जाओ",
                        "sleep", "exit", "chup ho jao", "chup raho", "bas karo"
                    ]
                    is_exit = any(k in last_in for k in exit_keywords) or any(
                        k in last_out for k in ["alvida", "stopping now", "milte hain agli baar", "goodbye"]
                    )
                    if is_exit:
                        while self._player.is_playing:
                            await asyncio.sleep(0.1)
                        await asyncio.sleep(0.4)
                        self._stop_event.set()
                        return

                # 7. Error Event
                elif event_type == "error":
                    err = event.get("error", {})
                    err_msg = err.get("message", str(err))
                    LOGGER.warning("OpenAI Realtime error: %s", err_msg)
                    self._output_fn(f"  ❌ [OpenAI Realtime Error] {err_msg}")
                    if "quota" in err_msg.lower() or "billing" in err_msg.lower() or "key" in err_msg.lower():
                        self._stop_event.set()
                        return

        except asyncio.CancelledError:
            self._flush_input_transcription()
            self._flush_output_transcription()
            return
        except Exception as exc:
            self._flush_input_transcription()
            self._flush_output_transcription()
            if self._stop_event.is_set():
                return
            LOGGER.warning("OpenAI Realtime receive error: %s", exc)

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
                if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                    has_key = await loop.run_in_executor(None, msvcrt.kbhit)
                    if has_key:
                        await loop.run_in_executor(None, msvcrt.getch)
                        if self._player.is_playing or self._model_turn_active:
                            self._player.barge_in_purge()
                            self._model_turn_active = False
                            self._output_fn("\n  ✋ [DarkShadow speech interrupted by Captain]\n")
            except Exception:
                pass
            await asyncio.sleep(0.08)

    async def _run_session(self) -> tuple[bool, float]:
        """Open OpenAI Realtime WebSocket session, run mic+receiver, return (should_retry, duration)."""
        import websockets

        api_key = self.settings.openai_api_key
        if not api_key:
            self._output_fn(
                "DarkShadow: Captain, OPENAI_API_KEY configure nahi hai!\n"
                "Kripya .env file mein OPENAI_API_KEY=<your_key> paste kijiye."
            )
            return False, 0.0

        model = self.settings.live_model or "gpt-realtime-2.1"
        if model.startswith("gemini"):
            model = "gpt-realtime-2.1"

        chosen_voice = self.settings.live_voice.lower()
        if chosen_voice not in OPENAI_VALID_VOICES:
            chosen_voice = "ash"

        ws_url = f"wss://api.openai.com/v1/realtime?model={model}"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
        }

        start_time = time.monotonic()
        try:
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                open_timeout=12,
            ) as ws:
                # 1. Initialize session with instructions, voice, VAD, tools
                session_update = {
                    "type": "session.update",
                    "session": {
                        "modalities": ["audio", "text"],
                        "instructions": self._build_live_system_instruction(),
                        "voice": chosen_voice,
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "input_audio_transcription": {
                            "model": "whisper-1",
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 400,
                        },
                        "tools": self._build_tools_schema(),
                    },
                }
                await ws.send(json.dumps(session_update))

                self._output_fn(
                    f"DarkShadow: Captain, OpenAI Realtime Live Mode ({model} / '{chosen_voice}') Active hai!\n"
                    f"Boliye—main sun raha hoon. (Stop ke liye Spacebar, Exit ke liye Ctrl+C)\n"
                )

                mic_task = asyncio.create_task(self._mic_sender(ws))
                recv_task = asyncio.create_task(self._response_receiver(ws))
                kbd_task = asyncio.create_task(self._keyboard_interrupter())

                try:
                    done, pending = await asyncio.wait(
                        {mic_task, recv_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in (mic_task, recv_task, kbd_task):
                        t.cancel()
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass

                    if recv_task in done:
                        exc = recv_task.exception()
                        if exc is not None:
                            LOGGER.warning("OpenAI Receiver ended with error: %s", exc)
                            return True, (time.monotonic() - start_time)
                except asyncio.CancelledError:
                    for t in (mic_task, recv_task, kbd_task):
                        t.cancel()
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass

                return False, (time.monotonic() - start_time)

        except Exception as exc:
            LOGGER.error("OpenAI Realtime session failed: %s", exc)
            self._output_fn(f"\nDarkShadow: OpenAI Realtime connect nahi ho saka: {exc}\n")
            return False, (time.monotonic() - start_time)

    async def run(self) -> None:
        """Run session with auto-reconnect logic."""
        attempts = 0
        max_attempts = max(1, self.settings.live_reconnect_attempts)

        while not self._stop_event.is_set() and attempts < max_attempts:
            attempts += 1
            retry, duration = await self._run_session()
            if not retry or self._stop_event.is_set():
                break
            if duration > 10.0:
                attempts = 0
            await asyncio.sleep(0.5)

    def close(self) -> None:
        """Release audio and stop session."""
        self._stop_event.set()
        self._player.close()
        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None
