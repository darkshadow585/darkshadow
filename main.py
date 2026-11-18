"""DarkShadow CLI with typed, voice, automation, and opt-in memory."""

from __future__ import annotations

import logging
import re
import sys
import threading
from collections.abc import Callable

# Ensure UTF-8 output on Windows consoles to prevent UnicodeEncodeError on Hindi/Devanagari characters and symbols
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from automation import (
    AutomationContext,
    AutomationResult,
    execute_automation_plan,
    handle_automation_command,
    looks_like_automation_request,
)
from chatbot import ChatResponse, DarkShadowChatbot
from config import Settings, load_settings
from spoken_output import speak_response
from memory import (
    MemoryResult,
    Reminder,
    ReminderMonitor,
    SQLiteMemoryStore,
    handle_memory_command,
    recall_memory,
)
from networking import install_ipv4_first_dns
from realtimeinfo import RealtimeInfoService, requires_fresh_information
from safety import ensure_captain_address, speech_friendly_text
from stt import PushToTalkSTT
from tts import EdgeTTSPlayer, TTSResult
from tts_router import TTSRouter


InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]


BANNER = r"""
  ____    _    ____  _  ______  _   _    _    ____   _____        __
 |  _ \  / \  |  _ \| |/ / ___|| | | |  / \  |  _ \ / _ \ \      / /
 | | | |/ _ \ | |_) | ' /\___ \| |_| | / _ \ | | | | | | \ \ /\ / /
 | |_| / ___ \|  _ <| . \ ___) |  _  |/ ___ \| |_| | |_| |\ V  V /
 |____/_/   \_\_| \_\_|\_\____/|_| |_/_/   \_\____/ \___/  \_/\_/
"""


def _print_response(response_text: str, output_fn: OutputFunction) -> None:
    output_fn(f"DarkShadow: {response_text}")


def _automation_response(result: AutomationResult) -> ChatResponse:
    """Convert a verified structured tool result into a user-facing response."""

    display_text = ensure_captain_address(result.message)
    return ChatResponse(
        display_text=display_text,
        speech_text=speech_friendly_text(display_text),
        intent=result.action,
        error=result.error,
    )


def _memory_response(result: MemoryResult) -> ChatResponse:
    """Convert a verified local memory result into a chat response."""

    display_text = ensure_captain_address(result.message)
    return ChatResponse(
        display_text=display_text,
        speech_text=speech_friendly_text(display_text),
        intent=result.action,
        error=result.error,
    )


def _emit_due_reminders(
    memory_store: SQLiteMemoryStore | None,
    output_fn: OutputFunction,
) -> None:
    """Print each due reminder once without exposing database internals."""

    if memory_store is None:
        return
    try:
        reminders = memory_store.pop_due_reminders()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Due reminder check failed (type=%s)", type(exc).__name__
        )
        return
    for reminder in reminders:
        _print_response(
            ensure_captain_address(f"Reminder: {reminder.message}"),
            output_fn,
        )


def _wake_phrase_command(text: str, wake_phrase: str) -> str | None:
    """Strip wake phrase variations (dark shadow, darkshadow, hey dark shadow, etc.) from speech."""

    cleaned = text.strip()
    # Normalize variants like "dark shadow", "darkshadow", "hey dark shadow", "dark"
    regex_wake = r"(?:hey\s+|hello\s+|suno\s+)?(?:dark\s*shadow|darkshadow|dark)"
    match = re.match(rf"^(?:{regex_wake})(?:(?:\s*[,;:-]\s*|\s+)(.*))?$", cleaned, re.IGNORECASE)
    if match:
        return (match.group(1) or "").strip()
    if wake_phrase:
        pattern = rf"^(?:hey\s+|hello\s+)?{re.escape(wake_phrase)}(?:(?:\s*[,;:-]\s*|\s+)(.*))?$"
        match_custom = re.match(pattern, cleaned, re.IGNORECASE)
        if match_custom:
            return (match_custom.group(1) or "").strip()
    return None


def _route_message(
    assistant: DarkShadowChatbot,
    realtime_service: RealtimeInfoService | None,
    message: str,
    stream_callback: Callable[[str], None] | None = None,
    memory_store: SQLiteMemoryStore | None = None,
    automation_context: AutomationContext | None = None,
) -> ChatResponse:
    """Route deterministic, fresh, then conversational requests in that order."""

    memory_result = handle_memory_command(message, memory_store)
    if memory_result is not None:
        response = _memory_response(memory_result)
        if automation_context is not None:
            automation_context.observe(message, response.display_text)
        return response
    recalled_memory = recall_memory(message, memory_store)
    if recalled_memory is not None:
        return _memory_response(recalled_memory)
    if message.lstrip().startswith("/"):
        automation_result = None
    elif automation_context is None:
        automation_result = handle_automation_command(message)
    else:
        automation_result = handle_automation_command(message, automation_context)
    if automation_result is not None:
        return _automation_response(automation_result)
    if (
        looks_like_automation_request(message)
        and callable(getattr(assistant, "plan_automation", None))
    ):
        commands = assistant.plan_automation(message)
        planned_result = execute_automation_plan(commands, automation_context)
        if planned_result is not None:
            return _automation_response(planned_result)
    if (
        realtime_service is not None
        and not message.lstrip().startswith("/")
        and requires_fresh_information(message)
    ):
        response = realtime_service.answer(message)
    else:
        import inspect
        sig = inspect.signature(assistant.respond)
        if "memory_store" in sig.parameters:
            response = assistant.respond(
                message,
                stream_callback=stream_callback,
                memory_store=memory_store,
            )
        else:
            response = assistant.respond(
                message,
                stream_callback=stream_callback,
            )
    if automation_context is not None:
        automation_context.observe(message, response.display_text)
    return response


def run_typed_mode(
    assistant: DarkShadowChatbot,
    realtime_service: RealtimeInfoService | None = None,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    memory_store: SQLiteMemoryStore | None = None,
    speaker: EdgeTTSPlayer | None = None,
    automation_context: AutomationContext | None = None,
) -> bool:
    """Run typed chat until /exit or Ctrl+C. Return True to exit the app."""

    _print_response(
        "Captain, typed mode online. Fresh queries auto-verified hain; /help "
        "se commands dekh sakte hain.",
        output_fn,
    )
    while True:
        _emit_due_reminders(memory_store, output_fn)
        try:
            message = input_fn("Captain > ")
        except EOFError:
            _print_response("Captain, input stream close hui. Signing off.", output_fn)
            return True
        except KeyboardInterrupt:
            output_fn("")
            _print_response(
                "Captain, Ctrl+C received. Clean exit kar raha hoon.", output_fn
            )
            return True

        streamed_chunks: list[str] = []
        console_stream_started = False

        def collect_stream(chunk: str) -> None:
            nonlocal console_stream_started
            streamed_chunks.append(chunk)
            if output_fn is print:
                prefix = "" if console_stream_started else "DarkShadow: "
                print(f"{prefix}{chunk}", end="", flush=True)
                console_stream_started = True

        try:
            response = _route_message(
                assistant,
                realtime_service,
                message,
                stream_callback=collect_stream,
                memory_store=memory_store,
                automation_context=automation_context,
            )
        except KeyboardInterrupt:
            output_fn("")
            _print_response(
                "Captain, active request cancel hui. Clean exit kar raha hoon.",
                output_fn,
            )
            return True
        if console_stream_started:
            print()
            streamed_text = "".join(streamed_chunks).strip()
            if streamed_text != response.display_text:
                # Usually only needed if the model omitted the required address.
                _print_response(response.display_text, output_fn)
        else:
            _print_response(response.display_text, output_fn)
        speech_text = getattr(response, "speech_text", response.display_text)
        if speaker is not None:
            speaker.speak(speech_text)
        else:
            speak_response(speech_text)
        if response.intent == "exit":
            return True


def run_voice_mode(
    assistant: DarkShadowChatbot,
    realtime_service: RealtimeInfoService | None,
    listener: PushToTalkSTT,
    speaker: EdgeTTSPlayer,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    memory_store: SQLiteMemoryStore | None = None,
    wake_phrase: str | None = None,
    automation_context: AutomationContext | None = None,
) -> bool:
    """Run bounded push-to-talk voice mode with typed fallback."""

    _print_response(
        "Captain, push-to-talk voice mode online. ENTER dabate hi normal volume "
        "mein boliye; /mic input devices ke liye, /back menu ke liye, "
        "/stop speech rokne ke liye, /exit close ke liye.",
        output_fn,
    )
    while True:
        _emit_due_reminders(memory_store, output_fn)
        try:
            control = input_fn(
                "Captain, ENTER = speak | /mic | /back | /stop | /exit > "
            ).strip().lower()
        except EOFError:
            speaker.stop()
            _print_response("Captain, input stream close hui. Signing off.", output_fn)
            return True
        except KeyboardInterrupt:
            speaker.stop()
            output_fn("")
            _print_response(
                "Captain, voice mode interrupt hua; menu par aa gaye.", output_fn
            )
            return False

        if control in {"/back", "back", "menu"}:
            speaker.stop()
            _print_response("Captain, voice mode se main menu par aa gaye.", output_fn)
            return False
        if control in {"/exit", "exit"}:
            speaker.stop()
            _print_response("Captain, DarkShadow signing off.", output_fn)
            return True
        if control in {"/stop", "stop"}:
            stopped = speaker.stop()
            status = "speech rok di" if stopped else "koi speech active nahi thi"
            _print_response(f"Captain, {status}.", output_fn)
            continue
        if control in {"/mic", "mic", "/devices"}:
            devices = listener.input_devices()
            if not devices:
                _print_response(
                    "Captain, microphone devices enumerate nahi ho sake.", output_fn
                )
            else:
                selected = listener.settings.stt_device_index
                output_fn("Available microphone inputs:")
                for index, name in devices:
                    marker = " *selected" if index == selected else ""
                    output_fn(f"  {index}: {name}{marker}")
                _print_response(
                    "Captain, `.env` mein DARKSHADOW_STT_DEVICE_INDEX=<number> "
                    "set karke app restart kijiye.",
                    output_fn,
                )
            continue
        if control:
            _print_response(
                "Captain, voice capture ke liye sirf ENTER dabaiye.", output_fn
            )
            continue

        if speaker.is_speaking:
            speaker.stop()
            _print_response(
                "Captain, previous speech interrupt kar di—ab boliye.", output_fn
            )
        else:
            _print_response("Captain, listening...", output_fn)

        cancel_event = threading.Event()
        try:
            speech = listener.listen_once(cancel_event)
        except KeyboardInterrupt:
            cancel_event.set()
            output_fn("")
            _print_response("Captain, listening cancel kar di.", output_fn)
            continue

        if not speech.success:
            message = ensure_captain_address(speech.message)
            _print_response(message, output_fn)
            if speech.error in {"microphone_unavailable", "missing_dependency"}:
                speaker.stop()
                _print_response(
                    "Captain, automatic typed fallback start kar raha hoon.",
                    output_fn,
                )
                return run_typed_mode(
                    assistant,
                    realtime_service,
                    input_fn,
                    output_fn,
                    memory_store,
                    speaker,
                    automation_context,
                )
            continue

        command_text = speech.text
        if wake_phrase:
            gated_command = _wake_phrase_command(command_text, wake_phrase)
            if gated_command is None:
                _print_response(
                    (
                        f"Captain, wake phrase '{wake_phrase}' nahi mili; "
                        "command ignore ki."
                    ),
                    output_fn,
                )
                continue
            if not gated_command:
                wake_reply = "Haanji Captain! DarkShadow active hai, bataiye kya hukum hai?"
                _print_response(wake_reply, output_fn)
                speaker.speak(wake_reply)
                continue
            command_text = gated_command

        output_fn(f"Captain (voice): {command_text}")
        try:
            response = _route_message(
                assistant,
                realtime_service,
                command_text,
                memory_store=memory_store,
                automation_context=automation_context,
            )
        except KeyboardInterrupt:
            speaker.stop()
            output_fn("")
            _print_response(
                "Captain, active request cancel hui; main menu par aa gaye.",
                output_fn,
            )
            return False
        _print_response(response.display_text, output_fn)
        queued = speaker.speak(response.speech_text)
        if not queued.success:
            _print_response(
                ensure_captain_address(queued.message),
                output_fn,
            )
        if response.intent == "exit":
            speaker.stop()
            return True


def run(
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    settings: Settings | None = None,
    realtime_service: RealtimeInfoService | None = None,
    stt_service: PushToTalkSTT | None = None,
    tts_service: EdgeTTSPlayer | None = None,
    memory_service: SQLiteMemoryStore | None = None,
) -> int:
    """Run typed/voice modes and keep recoverable failures inside the app."""

    active_settings = settings or load_settings()
    if active_settings.ipv4_first:
        install_ipv4_first_dns()
    logging.basicConfig(
        level=getattr(logging, active_settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    output_fn(BANNER)
    output_fn("DARKSHADOW — Phase 5")
    output_fn("Captain, DarkShadow initialize ho raha hai...")
    if not active_settings.env_file_found:
        _print_response(
            "Captain, `.env` file nahi mili. Setup ke liye `.env.example` copy "
            "kijiye; local commands phir bhi kaam karenge.",
            output_fn,
        )
    elif not active_settings.api_configured:
        _print_response(
            "Captain, `.env` mili lekin GEMINI_API_KEY empty hai. Key add karne "
            "tak local commands available rahenge.",
            output_fn,
        )

    tts_router = TTSRouter(
        active_settings.tts_usage_file,
        fish_segment_words=active_settings.tts_fish_segment_words,
    )
    assistant = DarkShadowChatbot(active_settings, tts_router=tts_router)
    active_realtime = realtime_service or RealtimeInfoService(active_settings)
    active_stt = stt_service
    active_tts = tts_service
    active_memory = memory_service
    active_automation_context = AutomationContext(
        confirm_whatsapp_send=active_settings.whatsapp_confirm_send
    )
    active_reminder_monitor: ReminderMonitor | None = None
    if active_memory is None and active_settings.memory_enabled:
        try:
            active_memory = SQLiteMemoryStore(
                active_settings.memory_database_path
            )
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Memory initialization failed (type=%s)", type(exc).__name__
            )
            _print_response(
                "Captain, local memory initialize nahi hui; baaki app available hai.",
                output_fn,
            )

    if active_memory is not None:
        def deliver_reminder(reminder: Reminder) -> None:
            _print_response(
                ensure_captain_address(f"Reminder: {reminder.message}"),
                output_fn,
            )

        active_reminder_monitor = ReminderMonitor(
            active_memory,
            deliver_reminder,
        )
        active_reminder_monitor.start()

    def report_tts_result(result: TTSResult) -> None:
        if not result.success and not result.interrupted:
            _print_response(ensure_captain_address(result.message), output_fn)

    auto_mode_arg: str | None = None
    import sys
    if len(sys.argv) > 1:
        raw_arg = sys.argv[1].strip().lower().lstrip("-")
        if raw_arg in {"5", "live", "vtv", "live_voice"}:
            auto_mode_arg = "5"
        elif raw_arg in {"2", "voice"}:
            auto_mode_arg = "2"
        elif raw_arg in {"4", "gui", "ui"}:
            auto_mode_arg = "4"
        elif raw_arg in {"1", "type", "text"}:
            auto_mode_arg = "1"
        elif raw_arg in {"6", "bridge", "avatar", "fur"}:
            auto_mode_arg = "6"

    try:
        while True:
            if auto_mode_arg is not None:
                choice = auto_mode_arg
                auto_mode_arg = None
            else:
                output_fn("\n1. Type mode\n2. Voice mode (push-to-talk)\n3. Exit\n4. Desktop GUI mode\n5. Live Voice mode (Gemini VTV)\n6. 3D Fur Avatar Bridge Server (ws://127.0.0.1:8765)")
                try:
                    choice = input_fn("Captain, select > ").strip().lower()
                except EOFError:
                    _print_response(
                        "Captain, input stream close hui. Signing off.", output_fn
                    )
                    return 0
                except KeyboardInterrupt:
                    output_fn("")
                    _print_response(
                        "Captain, Ctrl+C received. Clean exit complete.", output_fn
                    )
                    return 0

            if choice in {"1", "type", "typed", "text"}:
                active_tts = active_tts or EdgeTTSPlayer(
                    active_settings,
                    router=tts_router,
                    callback=report_tts_result,
                )
                if run_typed_mode(
                    assistant,
                    active_realtime,
                    input_fn,
                    output_fn,
                    active_memory,
                    active_tts,
                    active_automation_context,
                ):
                    return 0
            elif choice in {"2", "voice"}:
                active_stt = active_stt or PushToTalkSTT(active_settings)
                active_tts = active_tts or EdgeTTSPlayer(
                    active_settings,
                    router=tts_router,
                    callback=report_tts_result,
                )
                if run_voice_mode(
                    assistant,
                    active_realtime,
                    active_stt,
                    active_tts,
                    input_fn,
                    output_fn,
                    active_memory,
                    (
                        active_settings.wake_phrase
                        if active_settings.wake_phrase_enabled
                        else None
                    ),
                    active_automation_context,
                ):
                    return 0
            elif choice in {"3", "exit", "/exit"}:
                _print_response("Captain, DarkShadow signing off.", output_fn)
                return 0
            elif choice in {"4", "gui", "ui"}:
                import ui
                _print_response("Captain, launching DarkShadow GUI...", output_fn)
                ui.main(
                    demo=False,
                    integrated=True,
                    settings=active_settings,
                    chatbot=assistant,
                    realtime=active_realtime,
                    memory=active_memory,
                )
                return 0
            elif choice in {"5", "live", "vtv", "voice live"}:
                from live_voice import run_live_voice_mode
                _print_response(
                    "Captain, Gemini Live Voice-to-Voice mode launch ho raha hai...",
                    output_fn,
                )
                if run_live_voice_mode(active_settings, output_fn):
                    return 0
            elif choice in {"6", "bridge", "avatar", "fur"}:
                import bridge_server
                _print_response(
                    "Captain, 3D Fur Avatar Bridge Server start ho raha hai (ws://127.0.0.1:8765)...",
                    output_fn,
                )
                bridge_server.main()
                return 0
            else:
                _print_response(
                    "Captain, please 1, 2, 3, 4, 5, ya 6 select kijiye.", output_fn
                )
    finally:
        if active_tts is not None:
            active_tts.close()
        if active_reminder_monitor is not None:
            active_reminder_monitor.stop()
        if active_memory is not None:
            active_memory.close()
        active_realtime.close()
        assistant.close()


def main() -> int:
    """Console-script compatible entry point."""

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
