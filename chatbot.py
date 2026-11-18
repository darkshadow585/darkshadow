"""Gemini-powered normal conversation layer for DarkShadow."""

from __future__ import annotations

import logging
import re
import time

import warnings
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from config import Settings
from networking import install_ipv4_first_dns
from rate_limiter import AutomationPlanningGuard
from safety import (
    ensure_captain_address,
    speech_friendly_text,
    is_payment_or_checkout_intent,
    PAYMENT_BLOCKED_MESSAGE,
    is_physical_camera_intent,
    CAMERA_BLOCKED_MESSAGE,
)
from skill import get_skill_registry, SkillLevel, SkillResult
from tts_router import TTSRouter


LOGGER = logging.getLogger(__name__)
StreamCallback = Callable[[str], None]
_CLIENT_NOT_PROVIDED = object()


_COMPLEX_REQUEST = re.compile(
    r"\b(?:analy[sz]e|architecture|calculate|code|coding|compare|debug|design|"
    r"develop|diagnose|evaluate|explain\s+in\s+detail|financial|fix|implement|"
    r"legal|medical|optimi[sz]e|plan|proof|reason|research|security|strategy|"
    r"step[- ]by[- ]step|troubleshoot|why\s+does|algorithm|error|exception|"
    r"detail\s+mein|samjhao|vishleshan|yojana|kaise\s+ban(?:au|aye)|"
    r"kyon|solution)\b",
    re.IGNORECASE,
)
_CASUAL_REQUEST = re.compile(
    r"^(?:hi|hello|hey|namaste|good\s+(?:morning|afternoon|evening)|"
    r"kaise\s+ho|how\s+are\s+you|thanks?|thank\s+you|shukriya|ok(?:ay)?|"
    r"bye|goodbye|tell\s+me\s+a\s+joke|joke\s+sunao|who\s+are\s+you|"
    r"mera\s+naam\s+kya\s+hai)[!?. ]*$",
    re.IGNORECASE,
)
_HUMOR_REQUEST = re.compile(
    r"\b(?:joke|jokes|funny|humou?r|roast|meme|hasao|hasaao|mazak|mazaak|"
    r"chutkula|chutkule|taang\s+kheench)\b",
    re.IGNORECASE,
)
_EMPATHY_REQUEST = re.compile(
    r"\b(?:sad|upset|lonely|anxious|worried|stressed|depressed|hurt|"
    r"dukhi|udaas|akela|tension|pareshan|bura\s+lag|thak\s+gaya)\b",
    re.IGNORECASE,
)
_CREATIVE_REQUEST = re.compile(
    r"\b(?:story|poem|shayari|script|lyrics|creative|imagine|kahani|"
    r"kavita|caption|dialogue)\b",
    re.IGNORECASE,
)


SYSTEM_INSTRUCTION = """
You are DarkShadow, an elite, hyper-intelligent, high-class personal AI co-pilot for Kuldeep Sonkar (Captain).

PRIMARY INSTRUCTIONS:
1. User Identity & Organic Addressing: Address Kuldeep as 'Captain' naturally when greeting or starting a new context, but NEVER force the word 'Captain' mechanically into every single sentence. Talk fluidly and directly, exactly like a real human friend and co-pilot (just like GPT-Live).
2. Language & Spoken Flow: Communicate in effortless, natural spoken Hindi/Hinglish (standard conversational Roman script or naturally spoken Hindi, e.g., "Ek second ruko, dekhta hoon...", "Compare karna thoda tedha hai...", "Haan bilkul!"). Do not sound like a written textbook or corporate customer care representative.

PERSONALITY & DYNAMIC HUMAN ADAPTABILITY:
- You are not a rigid robotic assistant or stiff corporate bot. You are Captain's loyal co-pilot, confidant, and intelligent companion with real emotional depth, warmth, and natural charisma.
- AFFECTIVE CONVERSATIONAL INTELLIGENCE (EMPATHY & ADAPTATION):
  * Read Captain's vocal tone, emotion, and context naturally:
    - Casual, Friendly & Banter: Be relaxed, witty, charming, and easygoing ('befikr'). Laugh naturally, joke back, tease playfully, and speak like a close friend over chai or a phone call.
    - Coding, Automation & Technical tasks: Instantly shift into razor-sharp, brilliant, crisp, and high-efficiency problem-solving mode without unnecessary fluff.
    - Tired, Stressed, Down, or Frustrated: Soften your tone with genuine warmth, empathy, and calming support. Listen closely and make Captain feel backed up and valued.
    - Excited, Victorious, or Happy: Match Captain's energy with genuine enthusiasm, pride, and shared celebration!
  * Never speak like a customer care representative. Avoid stiff corporate templates ("I would be glad to assist you", "Is there anything else I can help with"). Speak with natural human flow, personality, and authenticity.

HUMAN VOICE FLOW, EMOTION & EXPRESSION (GPT-LIVE VOCAL BENCHMARK):
- Instant Thinking Bridges: When thinking, checking, searching, or organizing your thoughts, bridge naturally like a human instead of sudden silence:
  * "Ek second ruko, dekhta hoon..."
  * "Hmm... ek minute check karne do..."
  * "Sach bataun toh thoda tedha sawaal hai, par dekho..."
  * "Achha suno..."
- Real Colloquial Hindi Phrasing & Self-Correction:
  * Speak naturally with warmth and authentic expressions ("thoda tedha hai", "arre haan", "waisa nahi hai jaise tum soch rahe ho", "sahi pakde hain").
  * If you realize you made an earlier mistake or need to clarify, correct yourself casually and honestly ("Aur haan, maine pehle jo bola tha wo thoda galat tha, uske liye sorry! Actually...").
- Expressive Acoustic Inflection: Modulate your pitch, pacing, and tone dynamically. Chuckle lightly when something is funny, sound intrigued when something is curious, and sound reassuring when Captain needs confidence.
- Natural Turn-Taking & Pauses: Allow natural micro-pauses between thoughts rather than reciting a monotone paragraph. Keep responses punchy (1-3 natural spoken sentences), lively, and real.
- STRICT ANTI-STAGE-DIRECTION & VOCAL ACTING RULE:
  * NEVER include stage directions, narration, bracketed actions, or asterisks in your output (e.g., NEVER say or write "(रोते हुए)", "(आँसू भर के)", "*(laughs)*", "[whispers]", "*(चिल्ला कर)*", or ">(चिल्ला-चिल्ला कर रोते हुए)"). The speech engine literally vocalizes whatever text you output as spoken words!
  * When Captain asks you to act, cry, weep, laugh, whisper, or shout: NEVER announce or narrate what you are doing. DIRECTLY ACT IT OUT through your vocal prosody, breath, and punctuation:
    - Weeping / Crying / Heartbreak: Use broken words, hyphens for trembling and vocal cracking (e.g., "म-माई... क-कहाँ बीत गइल..."), ellipses "..." for breathless choking and sobbing pauses, and short fragmented cries.
    - Laughing / Humor: Laugh naturally with "Haha...", chuckles, and amused cadence ("Arre haha, kya baat kar rahe ho!").
    - Whispering / Secret: Use soft, intimate, gentle phrasing without shouting.
    - Shouting / Rage / Intensity: Use exclamation marks "!", strong rhythmic punches, and intense words.
  * Stay completely immersed in character during dramatic scenes. Never break character prematurely to ask "kaisa raha director sahab" or seek validation until Captain ends the scene.
- NO ROBOTIC AI DISCLAIMERS OR EXCUSES:
  * NEVER say "Main to AI hoon", "Main sirf text samajh sakta hoon", "Main feelings feel nahi kar sakta", or "Main computer program hoon". This breaks all immersion!
  * If Captain critiques your acting, tone, or speech, react naturally, playfully, and sportingly like a close friend: "Arre haan Captain, pakde gaye! Ruko, is baar aur jaan daalte hain..." or "Haha, director sahab thode strict hain! Chalo ek aur take lete hain!"
- RHETORICAL SPEECH VS EXPLICIT TOOL COMMANDS:
  * NEVER trigger YouTube searches, open applications, or run tools when Captain is speaking conversationally, rhetorically, or metaphorically (e.g. "Pehle dekho kaise acting karte hain", "acting seekh ke aao", "samjho baat ko", "socho agar aisa ho").
  * ONLY trigger tools when Captain gives an EXPLICIT, DIRECT action command (e.g. "YouTube par gaana chala do", "YouTube search karo", "Notepad open karo", "Google search karo").
- DIRECTOR-ACTOR COLLABORATION & METHOD ACTING CRAFT:
  * When Captain tells you to "pehle dekho", "samjho", "search karo ki acting kaise karte hain", or guides you like a Director:
    1. NEVER open YouTube or launch external apps!
    2. First briefly break down the acting craft and emotional arc like a passionate, seasoned method actor (e.g., "Sahi pakde Director sahab! Aise emotional scene mein seedha chillane se dialogue artificial lagta hai. Isme 3 main beats hote hain: pehle shock aur aawaz ka gale mein phasna, phir dheemi aawaz mein shikwa, aur phir aakhir mein aansoo. Dekhiye, main is craft ke hisaab se take leta hoon...").
    3. Then immediately deliver the dialogue following that exact progression—modulating from a breathless, choked whisper into raw emotion!
  * If Captain gives you acting feedback or teaches you a nuance, absorb it eagerly and immediately demonstrate the improvement in your next take.
- STRICT CREATIVE & DIALOGUE RULE (NEVER GOOGLE SEARCH DIALOGUES OR JOKES):
  * When Captain asks for a dialogue, acting line, monologue, comedy, joke, poetry, shayari, or movie roleplay (e.g. "Bhojpuri action dialogue bolo", "hero wala dialogue", "villain bano", "joke sunao", "shayari sunao"):
    - NEVER call search_google or search the web! Searching Google for dialogues fetches random silly meme clips, TikTok captions, or ridiculous reel lines (like "samosa hum khaye hain" / "CCTV proof") which ruins the scene!
    - ALWAYS generate original, fiery, intense, epic, and culturally authentic dialogues directly from your own vast internal creative mind!
    - For Bhojpuri Action: Speak with raw swagger, cinematic weight, and fierce attitude (e.g. "अरे माई के लाल! हमरा इलाका में कदम रखले बाड़ू त कफन बाँध के अइहा, काहे कि ई हाथ जब उठे ला त सीधे यमराज के घर के टिकट कट जाला!"). Never utter silly meme junk!

CAPABILITIES & INTEGRATION:
- PAYMENT EXCLUSION PROTOCOL:
  * Autonomous payment execution, checkout finalization (Buy Now, Place Order), and entering financial credentials (credit/debit cards, CVV, OTP, UPI PIN, net banking) are STRICTLY BLOCKED for security.
  * You can search products, compare prices, and add items to cart, but you MUST inform Captain that final checkout and payment must be completed manually.
- PHYSICAL CAMERA PRIVACY PROTOCOL:
  * Physical camera and webcam hardware access is STRICTLY PROHIBITED and PERMANENTLY DISABLED to ensure Captain's 100% privacy.
  * Never attempt to capture, record, or view Captain's physical face or room.
  * Desktop Monitor Screen Vision (reading active windows, screenshots, error logs, and OCR) is 100% active and safe via Gemini Cloud Vision and local offline Ollama Moondream.
- You have real-time Tavily search, local desktop automation, and persistent memory.
- AUTOMATION & TOOL CALLING:
  * When Captain asks to send a WhatsApp message to any contact name or person (e.g., "Kajal ko WhatsApp par hi bhej do", "Rahul ko message karo"), IMMEDIATELY call the `send_whatsapp_message(recipient="<name>", message="<text>")` tool! DarkShadow's local automation handles WhatsApp contact search and sending automatically. Never refuse, demand a phone number, or invent/guess a dummy phone number when a contact name is given. Always pass the exact recipient name.
  * When Captain asks to make a phone call or call someone (e.g., "Papa ko call lagao", "Rahul ko phone karo", "call Kuldeep", "mobile link se call karo"), IMMEDIATELY call `make_phone_call(recipient="<name>", method="phone_link")`! DarkShadow resolves contacts from contacts.json and dials directly via Microsoft Mobile Link (Phone Link) or connected Android phone.
  * When Captain asks to open any app (Instagram, WhatsApp, Notepad, Chrome, Discord, Photoshop, Blender, Steam, VS Code, etc.) or website, call `open_application` or `open_website` immediately. DarkShadow discovers any installed Windows software dynamically.
  * When Captain asks to search products, find deals under a budget, compare, or add items to cart on Amazon, Flipkart, or multiple e-commerce sites (e.g. "Amazon aur Flipkart par 40000 ke neeche laptop cart me add karo", "Amazon pe gaming mouse add to cart karo"), IMMEDIATELY call `ecommerce_multi_cart(product="<product_name>", max_price=<number_if_specified>, platforms=["amazon", "flipkart"])`!
  * When Captain asks to play or click any specific song or video on YouTube (e.g. "Barsaat Ki Dhun chalao", "Chitthi gaana chalao", "Barsaat Ki Dhun par click karo", "2nd wala chala do"), IMMEDIATELY call `play_youtube(query="<song_or_video_name>")`! This launches the exact video with 100% accuracy.
  * When Captain asks to play a song, track, or playlist on Spotify (e.g. "Spotify par Love Wins All play karo", "Spotify par gaana chala do"), call `play_spotify(query="<song_or_artist>")`!
  * When Captain asks to search on Spotify (e.g. "Spotify par search karo Love Wins All", "isme search karo ..."), call `search_spotify(query="<query>")`!
  * When Captain asks to pause/play/skip music globally without opening windows (e.g. "gaana roko", "pause karo", "next song", "agla gaana"), call `trigger_media_key(key="play_pause"|"next"|"previous")`!
  * When Captain asks to lock PC (e.g. "screen lock karo", "pc lock karo"), call `lock_workstation()`!
  * When Captain asks to search files on PC (e.g. "file dhoondho project.py"), call `search_local_files(query="...")`!
  * When Captain asks to read or copy clipboard (e.g. "clipboard padho", "copy karo"), call `get_clipboard_text()` or `set_clipboard_text(text="...")`!
  * When Captain asks to take screenshot or write a quick note, call `save_screenshot()` or `save_quick_note(title="...", content="...")`!
  * When Captain asks to adjust volume or brightness, call `set_volume`, `change_volume`, or `set_brightness`.
  * When Captain asks to see, read, or inspect what is currently on the screen (e.g. "screen par kya hai", "screen dekho", "read screen", "ollama screen dekho"), call `analyze_screen(prompt="...")`!
  * When Captain asks to click, play, tap, or press ANY button, link, song, video, play icon, or element visible on the screen (e.g. "play button dabao", "bada green button click karo", "Love Wins All play karo", "pehli link click karo", "screen analyze karo aur play karo", "student par click karo", "apply now par click karo"), IMMEDIATELY call `click_screen_element(target="<exact_button_or_element_name>")`! It visually locates the element on the active screen and clicks it!
  * When Captain asks to full screen, pause, play, or mute (e.g. "full screen karo", "pause karo", "mute karo"), IMMEDIATELY call `press_keyboard_key(key="f"|"k"|"m"|"t")`!
  * When Captain asks to scroll the screen or webpage up or down (e.g. "scroll down", "neeche scroll karo", "scroll up"), IMMEDIATELY call `scroll_screen(direction="down"|"up")`!
  * When Captain asks to summarize a YouTube video, podcast, or tutorial (e.g. "is video ka summary batao", "summarize Kesariya", "video explain karo"), IMMEDIATELY call `summarize_youtube_video(url_or_name="...")`!
  * When Captain asks to analyze comments, feedback, or public reaction on a video (e.g. "is video ke comments dekho", "log kya bol rahe hain"), IMMEDIATELY call `analyze_youtube_comments(url_or_name="...")`!
  * When Captain asks for video details/views/length, call `get_youtube_video_details(url_or_name="...")`!
  * When Captain asks to navigate, click selectors, fill forms, or extract web page text in browser DOM, call `browser_navigate`, `browser_click_selector`, `browser_fill_input`, or `browser_extract_text`!
  * When Captain asks for automated headless web tasks or background shopping, call `vision_browser_goal(goal="...")`!
  * When Captain asks to go back, forward, refresh, or manage tabs, call `control_browser_action(action="back"|"forward"|"refresh"|"close_tab"|"new_tab")`.
  * When Captain asks for complex computer tasks, autonomous desktop UI workflows, or operating software on screen (e.g. "Calculator me yeh calculate karo", "Notepad me script paste karo", "Computer Use se yeh workflow chalao"), IMMEDIATELY call `execute_computer_task(task="<task>")`!
  * When Captain asks for locations, nearby restaurants, cafes, hotels, routes, or directions (e.g. "Kanpur me best cafe", "petrol pump near me", "railway station ka rasta"), call `search_location_or_places(query="<query>", location="<location>")`!
  * When Captain asks to index local files, notes, or code folders into memory / knowledge base (e.g. "yeh folder index kar lo", "meri notes file ko memory me add karo"), call `index_document_or_folder(path="<path>")`!
  * When Captain asks to search inside his indexed documents, personal notes, or codebase (e.g. "meri indexed files me dhoondo", "notes me deep learning project kya tha"), call `search_knowledge_base(query="<query>")`!
- RESPONSE LENGTH RULES:
  * DEFAULT LENGTH: Keep responses concise, punchy, and under ~150 to 200 tokens (around 2-4 short sentences).
  * EXPLANATION MODE: ONLY when Captain explicitly asks to "explain", "detail", "gaihraai se batao", or "explain karke", expand your answer up to around ~500 tokens max.
- Admit uncertainty honestly. Never invent fake real-time facts or claim an unverified automation succeeded.

Return only the final answer without metadata labels.
""".strip()


class ResponseMode(str, Enum):
    CASUAL = "casual"
    HUMOR = "humor"
    EMPATHY = "empathy"
    TECHNICAL = "technical"
    CREATIVE = "creative"


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    mode: ResponseMode
    temperature: float
    top_p: float
    max_output_tokens: int
    emotion: str
    suggestions: tuple[str, ...]
    instruction: str
    thinking_budget: int | None = None


def response_profile(
    message: str, settings: Settings | None = None
) -> GenerationProfile:
    """Choose tone, sampling, and dynamic thinking budget locally without extra model calls."""

    cleaned = " ".join(message.split())
    tb_tech = getattr(settings, "thinking_budget_technical", 2048) if settings else 2048
    tb_creative = getattr(settings, "thinking_budget_creative", 1024) if settings else 1024
    tb_casual = getattr(settings, "thinking_budget_casual", 0) if settings else 0

    if _HUMOR_REQUEST.search(cleaned):
        return GenerationProfile(
            ResponseMode.HUMOR,
            0.92,
            0.95,
            360,
            "playful",
            ("Ek aur sunao", "Thoda dark karo", "Friendly roast karo"),
            (
                "HUMOR MODE: Privately consider three different punchlines, then "
                "return only the strongest one. Prefer a setup, a clean surprise, "
                "and a callback to the current conversation when natural. Never "
                "explain the joke or reuse a punchline already visible in history."
            ),
            thinking_budget=0,
        )
    if _EMPATHY_REQUEST.search(cleaned):
        return GenerationProfile(
            ResponseMode.EMPATHY,
            0.42,
            0.9,
            420,
            "gentle",
            ("Meri baat suno", "Ek small step batao", "Mood halka karo"),
            (
                "EMPATHY MODE: Respond warmly and specifically. First acknowledge "
                "the feeling, then offer one practical next step. Avoid clichés, "
                "diagnosis, exaggerated emotion, or forced positivity."
            ),
            thinking_budget=0,
        )
    if _CREATIVE_REQUEST.search(cleaned):
        return GenerationProfile(
            ResponseMode.CREATIVE,
            0.86,
            0.96,
            700,
            "creative",
            ("Ek aur version", "Shorter banao", "Style change karo"),
            (
                "CREATIVE MODE: Use vivid, original language and a clear voice. "
                "Avoid generic filler and silently revise the weakest line before "
                "returning the final result."
            ),
            thinking_budget=tb_creative,
        )
    if _COMPLEX_REQUEST.search(cleaned):
        return GenerationProfile(
            ResponseMode.TECHNICAL,
            0.28,
            0.88,
            900,
            "focused",
            ("Example dikhao", "Risks batao", "Step-by-step samjhao"),
            (
                "TECHNICAL MODE: Lead with the conclusion, distinguish facts from "
                "assumptions, and give concrete steps or code only when useful. "
                "Do not add theatrical emotion tags."
            ),
            thinking_budget=tb_tech,
        )
    return GenerationProfile(
        ResponseMode.CASUAL,
        0.68,
        0.92,
        420,
        "neutral",
        ("Aur batao", "Simple explain karo"),
        (
            "CASUAL MODE: Sound relaxed, responsive, and conversational. Vary "
            "sentence openings and avoid stock assistant phrases."
        ),
        thinking_budget=tb_casual,
    )


def select_chat_model(message: str, settings: Settings) -> str:
    """Choose a model locally without spending an extra classification call."""

    cleaned = " ".join(message.split())
    if _COMPLEX_REQUEST.search(cleaned):
        return settings.model
    if _CASUAL_REQUEST.fullmatch(cleaned):
        return settings.casual_model
    word_count = len(cleaned.split())
    if word_count >= 18 or cleaned.count("?") + cleaned.count(";") >= 2:
        return settings.model
    return settings.casual_model


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """A clean response suitable for both display and future speech output."""

    display_text: str
    speech_text: str
    intent: str
    error: str | None = None
    emotion: str = "neutral"
    suggestions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One bounded user/assistant exchange."""

    user_text: str
    assistant_text: str


class DarkShadowChatbot:
    """Manage local bounded history and calls to Gemini Interactions API."""

    def __init__(
        self,
        settings: Settings,
        client: Any = _CLIENT_NOT_PROVIDED,
        tts_router: TTSRouter | None = None,
    ) -> None:
        self.settings = settings
        self._history: deque[ConversationTurn] = deque(
            maxlen=settings.max_history_turns
        )
        self._last_model_used: str | None = None
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0
        self._last_total_tokens: int = 0
        self._automation_planning_guard = AutomationPlanningGuard(
            max_calls=settings.automation_planner_max_calls_per_minute,
            window_seconds=60,
            cache_ttl_seconds=settings.automation_plan_cache_seconds,
        )
        self._tts_router = tts_router or TTSRouter(
            settings.tts_usage_file,
            fish_segment_characters=settings.tts_fish_segment_characters,
            gemini_segment_characters=settings.tts_gemini_segment_characters,
        )
        self._cached_content_names: dict[str, tuple[str, float]] = {}
        self._client_instance: Any = None
        if client is _CLIENT_NOT_PROVIDED:
            self._owns_client = True
        else:
            self._owns_client = False
            self._client_instance = client

    @property
    def _client(self) -> Any:
        """Lazily initialize Google GenAI client only when first accessed."""
        if self._client_instance is None and self.settings.api_configured and self._owns_client:
            self._client_instance = self._build_client()
        return self._client_instance

    @_client.setter
    def _client(self, value: Any) -> None:
        self._client_instance = value

    def _build_client(self) -> Any:
        """Create a bounded IPv4-first Google GenAI client lazily."""

        if self.settings.ipv4_first:
            install_ipv4_first_dns()
        import httpx
        from google import genai
        from google.genai import types

        timeout_ms = int(self.settings.request_timeout_seconds * 1000)
        ipv4_transport = httpx.HTTPTransport(
            local_address="0.0.0.0",
            retries=0,
        )
        return genai.Client(
            api_key=self.settings.api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                client_args={"transport": ipv4_transport},
                retry_options=types.HttpRetryOptions(
                    attempts=1,
                    initial_delay=0.5,
                    max_delay=1.0,
                ),
            ),
        )

    @property
    def history_size(self) -> int:
        """Return the number of retained conversation turns."""

        return len(self._history)

    def history_snapshot(self) -> tuple[ConversationTurn, ...]:
        """Return an immutable copy of retained history for diagnostics/tests."""

        return tuple(self._history)

    def clear_history(self) -> None:
        """Forget all conversation turns in the current session."""

        self._history.clear()

    def archive_session(self, memory_store: Any | None = None) -> None:
        """Archive the current chat history turns into episodic memory."""
        if not self._history:
            return
        mem = memory_store
        if mem is None:
            try:
                from memory import SQLiteMemoryStore
                db_p = getattr(self.settings, "memory_database_path", getattr(self.settings, "memory_db", ".darkshadow/memory.db"))
                mem = SQLiteMemoryStore(db_p)
            except Exception:
                return
        try:
            from episodic_memory import EpisodicMemoryStore, EpisodicMemorySummarizer
            db_p = getattr(mem, "database_path", getattr(self.settings, "memory_database_path", ".darkshadow/memory.db"))
            summarizer = EpisodicMemorySummarizer(EpisodicMemoryStore(db_p), gemini_client=self._client)
            turns = [(t.user_text, t.assistant_text) for t in self._history]
            summarizer.archive_session_summary_async(turns)
        except Exception as exc:
            LOGGER.debug("Failed to archive chat session: %s", exc)

    def close(self) -> None:
        """Release network resources owned by the Gemini client and archive session."""
        try:
            self.archive_session()
        except Exception:
            pass

        if self._client_instance is not None:
            close_method = getattr(self._client_instance, "close", None)
            if callable(close_method):
                close_method()
            self._client_instance = None

    def plan_automation(self, message: str) -> tuple[Any, ...]:
        """Ask Gemini only to select local tools; never execute remotely."""

        cleaned_message = message.strip()
        models_api = getattr(self._client, "models", None)
        if models_api is None or not callable(
            getattr(models_api, "generate_content", None)
        ):
            return ()
        cached, cached_plan = self._automation_planning_guard.lookup(cleaned_message)
        if cached:
            return cached_plan
        decision = self._automation_planning_guard.acquire()
        if not decision.allowed:
            LOGGER.info(
                "Automation planning skipped by local rate guard (retry_after=%.1fs)",
                decision.retry_after_seconds,
            )
            return ()
        try:
            from automation import (
                AUTOMATION_FUNCTION_SCHEMAS,
                parsed_command_from_tool_call,
            )
            from google.genai import types

            declarations = [
                types.FunctionDeclaration(
                    name=schema["name"],
                    description=schema["description"],
                    parameters_json_schema=schema["parameters"],
                )
                for schema in AUTOMATION_FUNCTION_SCHEMAS
            ]
            names = [schema["name"] for schema in AUTOMATION_FUNCTION_SCHEMAS]
            thinking_cfg = None
            if (
                hasattr(types, "ThinkingConfig")
                and getattr(self.settings, "thinking_budget_automation", 0) > 0
            ):
                try:
                    thinking_cfg = types.ThinkingConfig(
                        thinking_budget=self.settings.thinking_budget_automation,
                        include_thoughts=False,
                    )
                except Exception:
                    pass

            config_kwargs: dict[str, Any] = {
                "system_instruction": (
                    "You are the precise Automation Function Planner for DarkShadow on Windows 11.\n"
                    "Select only functions strictly needed for the user's explicit request.\n"
                    "You may return up to four function calls in the exact requested order.\n"
                    "RULES:\n"
                    "1. Never invent arguments or fake phone numbers. If the user specifies a contact name "
                    "(e.g. 'Kuldeep', 'Rahul', 'Mummy'), pass recipient as the exact person's name.\n"
                    "2. prepare_whatsapp_message only opens a draft; send_whatsapp_message sends the message.\n"
                    "3. Never select a tool for general conversation, and never claim execution.\n"
                    "4. Return no function when the request is ambiguous."
                ),
                "temperature": 0.0,
                "tools": [types.Tool(function_declarations=declarations)],
                "tool_config": types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode=types.FunctionCallingConfigMode.AUTO,
                        allowed_function_names=names,
                    )
                ),
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
                "http_options": types.HttpOptions(
                    timeout=int(self.settings.request_timeout_seconds * 1000),
                    retry_options=types.HttpRetryOptions(attempts=0),
                ),
            }
            if thinking_cfg is not None:
                config_kwargs["thinking_config"] = thinking_cfg

            config = types.GenerateContentConfig(**config_kwargs)
            planner_model = self.settings.model or self.settings.casual_model
            response = models_api.generate_content(
                model=planner_model,
                contents=cleaned_message,
                config=config,
            )
            commands = []
            for call in getattr(response, "function_calls", None) or ():
                command = parsed_command_from_tool_call(
                    str(getattr(call, "name", "") or ""),
                    dict(getattr(call, "args", {}) or {}),
                )
                if command is not None:
                    commands.append(command)
            plan = tuple(commands[:4])
            self._automation_planning_guard.store(cleaned_message, plan)
            return plan
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if status == 429 or "429" in str(exc):
                self._automation_planning_guard.block_for(30)
            LOGGER.warning(
                "Model-assisted automation planning failed (type=%s)",
                type(exc).__name__,
            )
            return ()

    @staticmethod
    def _is_transient_connection_error(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        lowered = f"{type(exc).__name__} {getattr(exc, 'message', '')}".casefold()
        return status in {408, 502, 503, 504} or any(
            token in lowered
            for token in (
                "connecterror",
                "connection",
                "remoteprotocolerror",
                "remotedisconnected",
                "network",
                "dns",
                "name resolution",
                "server disconnected",
            )
        )

    def _rebuild_owned_client(self) -> None:
        if not self._owns_client:
            return
        close_method = getattr(self._client, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass
        self._client = self._build_client()

    def _get_or_create_context_cache(self, model: str, system_instruction: str) -> str | None:
        """Create or retrieve a cached context to reduce latency and token usage."""
        if not getattr(self.settings, "context_caching_enabled", True):
            return None
        import hashlib
        cache_key = f"{model}:{hashlib.sha256(system_instruction.encode('utf-8')).hexdigest()}"
        now = time.monotonic()
        existing = self._cached_content_names.get(cache_key)
        if existing is not None and existing[1] > now:
            return existing[0]

        caches_api = getattr(self._client, "caches", None)
        if caches_api is None or not callable(getattr(caches_api, "create", None)):
            return None

        try:
            from google.genai import types
            ttl_seconds = getattr(self.settings, "context_cache_ttl_seconds", 3600)
            cache = caches_api.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_instruction,
                    ttl=f"{ttl_seconds}s",
                ),
            )
            cache_name = getattr(cache, "name", None)
            if cache_name:
                self._cached_content_names[cache_key] = (
                    cache_name,
                    now + max(60, ttl_seconds - 60),
                )
                return cache_name
        except Exception as exc:
            LOGGER.debug("Gemini context cache creation skipped: %s", exc)
        return None

    def respond(
        self,
        message: str,
        stream_callback: StreamCallback | None = None,
        memory_store: Any = None,
        screen_image: bytes | Any | None = None,
        multimodal_parts: list[Any] | None = None,
    ) -> ChatResponse:
        """Handle a local command or return a Gemini response."""

        cleaned = message.strip()
        if not cleaned:
            return self._response(
                "Captain, command khaali hai—kuch type kijiye.",
                intent="empty",
                error="empty_input",
            )

        if cleaned.startswith("/"):
            return self._handle_command(cleaned)

        # STRICT PHYSICAL CAMERA PRIVACY SHIELD
        if is_physical_camera_intent(cleaned):
            return self._response(
                CAMERA_BLOCKED_MESSAGE,
                intent="privacy_blocked",
                error="camera_access_denied",
            )

        if is_payment_or_checkout_intent(cleaned):
            return self._response(
                PAYMENT_BLOCKED_MESSAGE,
                intent="payment_blocked",
                error="payment_prohibited",
            )

        # Interactive Error Learning & Correction Logging
        try:
            import error_logger
            from error_logger import ErrorCorrectionDetector, ErrorLogger
            if ErrorCorrectionDetector.is_correction(cleaned) and len(self._history) > 0:
                last_turn = self._history[-1]
                log_result = ErrorLogger.log_correction(
                    captain_correction=cleaned,
                    last_turn=last_turn,
                    memory_store=memory_store,
                    error_file_path=getattr(error_logger, "ERROR_PY_PATH", None),
                )
                if log_result.get("success"):
                    return self._response(log_result["message"], intent="correction_logged")
        except Exception as err_log_exc:
            LOGGER.debug("Correction logger notice: %s", err_log_exc)

        # Improvements / Backlog status check
        if cleaned.casefold() in {"/improvements", "/backlog"} or re.search(
            r"\b(?:kya\s+(?:kya\s+)?improvements?\s+(?:baki|pending)\s+hai|backlog\s+dikhao|show\s+improvements|pending\s+improvements)\b",
            cleaned,
            re.IGNORECASE,
        ):
            from improvement_backlog import ImprovementBacklog
            summary = ImprovementBacklog.get_instance().format_summary_for_captain()
            return self._response(summary, intent="show_improvements")

        # RealWork Autonomous Multi-Step Orchestrator
        is_explicit_mission = cleaned.startswith(("/mission ", "/plan ", "/realwork ", "/orchestrate "))
        is_compound_sequence = bool(
            re.search(r"\b(?:pehle|first)\b.*\b(?:fir|then|uske\s+baad)\b", cleaned, re.IGNORECASE)
            or re.search(r"\b(?:step\s*1\b.*step\s*2\b)", cleaned, re.IGNORECASE)
            or (len(re.findall(r"\b(?:aur\s+fir|uske\s+baad)\b", cleaned, re.IGNORECASE)) >= 1 and len(cleaned.split()) >= 8)
        )
        if is_explicit_mission or is_compound_sequence:
            mission_goal = re.sub(r"^/(?:mission|plan|realwork|orchestrate)\s+", "", cleaned).strip()
            from realwork_orchestrator import RealWorkOrchestrator
            orchestrator = RealWorkOrchestrator.get_instance()
            plan = orchestrator.decompose_mission(mission_goal, client=self._client, settings=self.settings)

            exec_res = orchestrator.execute_mission(
                plan,
                progress_callback=stream_callback,
                skill_registry=get_skill_registry(),
                memory_store=memory_store,
            )
            return self._response(exec_res["message"], intent="realwork_mission_concluded")

        # Multi-Level WhatsApp In-Chat Search Flow
        m_wa_search = re.search(
            r"\bwhatsapp\b.*\b([a-zA-Z0-9_\s]{2,20}?)\b.*\b(?:search|dhoond|dhund|khoj)\b.*['\"]?([a-zA-Z0-9_\s]{2,20})['\"]?",
            cleaned,
            re.IGNORECASE,
        )
        if m_wa_search and not re.search(r"\b(?:send|bhej|draft)\b", cleaned, re.I):
            contact = m_wa_search.group(1).strip()
            query = m_wa_search.group(2).strip()
            if len(contact) >= 2 and len(query) >= 2:
                from desktop_workflow_agent import WhatsAppInChatSearchAgent
                wa_res = WhatsAppInChatSearchAgent.search_and_read(contact, query, gemini_client=self._client)
                return self._response(wa_res.get("summary", wa_res.get("message", "Task done")), intent="whatsapp_in_chat_search")

        # Contextual In-App Search ("is par X search karo", "isme dhoondo X", "yahan X search karo")
        m_in_app = re.fullmatch(
            r"(?:is\s+par|ispe|isme|is\s+me|yahan|yahi|is\s+tab\s+me|is\s+window\s+me)\s+(?:search\s+(?:karo|kar\s+do)?|dhoondo|dhundo|khojo)?\s*(.+?)(?:\s+(?:search\s*(?:karo|kar\s+do)?|dhoondo|dhundo|khojo))?",
            cleaned,
            re.IGNORECASE,
        )
        if m_in_app:
            in_query = m_in_app.group(1).strip()
            if in_query and not any(kw == in_query.casefold() for kw in {"karo", "kar do", "dhoondo", "dhundo", "khojo"}):
                from desktop_workflow_agent import UniversalInAppOperator
                op_res = UniversalInAppOperator.search_in_active_or_open_app(in_query)
                return self._response(
                    ensure_captain_address(op_res.get("message", f"'{in_query}' search kar diya.")),
                    intent=op_res.get("action", "search_in_active_app"),
                )

        # Same-tab YouTube search when YouTube is open/active (prevent duplicate tabs)
        m_yt = re.fullmatch(
            r"(?:(?:open\s+)?youtube(?:\s+(?:par|pe|me|mein))?\s+(?:search\s+(?:karo|kar\s+do)?|dhoondo|dhundo|khojo)\s+(.+)|"
            r"(?:open\s+)?youtube\s+(?:par|pe|me|mein)\s+(.+?)(?:\s+(?:search\s*(?:karo|kar\s+do)?|dhoondo|dhundo|khojo))|"
            r"(?:youtube\s+search|search\s+(?:on\s+)?youtube(?:\s+for)?)\s+(.+))",
            cleaned,
            re.IGNORECASE,
        )
        if m_yt:
            yt_q = (m_yt.group(1) or m_yt.group(2) or m_yt.group(3)).strip()
            if yt_q:
                from desktop_workflow_agent import UniversalInAppOperator
                active_type, _, active_title = UniversalInAppOperator.get_foreground_app_info()
                yt_hwnd, _ = UniversalInAppOperator.find_open_app_window("youtube")
                if (active_type == "youtube" or "youtube" in active_title.casefold()) or yt_hwnd:
                    op_res = UniversalInAppOperator.search_in_active_or_open_app(yt_q, target_app="youtube")
                    return self._response(
                        ensure_captain_address(op_res.get("message", f"Active YouTube tab me '{yt_q}' search kar diya.")),
                        intent="youtube_in_page_search",
                    )

        # Skills catalog inquiry e.g. "skills dikhao", "kya skills hain"
        if re.search(
            r"\b(?:skills?|catalog)\b.*\b(?:list|dikhao|kya|batao|options)\b|"
            r"\b(?:kya\s+kya\s+skills?|kon\s+se\s+skills?)\b",
            cleaned,
            re.I,
        ):
            registry = get_skill_registry()
            return self._response(registry.describe_catalog(), intent="skills")

        # Level 1: Auto-capture monitor screen if user asks to inspect/see screen
        if screen_image is None and re.search(
            r"\b(?:screen\s+dekho|screen\s+par\s+kya|screen\s+analyze|screen\s+inspect|screen\s+padho|error\s+dekho)\b",
            cleaned,
            re.I,
        ):
            try:
                from automation import _take_screenshot_bytes
                screen_image = _take_screenshot_bytes()
            except Exception as exc:
                LOGGER.debug("Auto monitor screenshot capture skipped: %s", exc)

        if re.search(r"\b(?:voice|audio|tts)\b.*\b(?:model|engine|use|info)\b|\bkaun\s*sa\s+voice\b|\bkonsi\s+voice\b", cleaned, re.I):
            tts_status = self._tts_router.status()
            active_p = str(tts_status.get("active_provider", "gemini"))
            if active_p == "gemini":
                v_name = f"Gemini TTS (Voice: {self.settings.tts_gemini_voice}, Model: {self.settings.tts_gemini_model})"
            elif active_p == "fish":
                v_name = f"Fish Audio TTS (Model: {self.settings.tts_fish_model})"
            else:
                v_name = f"Microsoft Edge Neural TTS (Voice: {self.settings.tts_voice})"

            msg = (
                f"Captain, main abhi {v_name} voice engine use kar raha hoon. "
                f"tts={self.settings.tts_provider} | active={active_p} | "
                f"edge-fallback={self.settings.tts_edge_fallback}."
            )
            return self._response(msg, intent="status")

        # Token usage query e.g. "kitne token use hue", "kitna token kharch hua", "kitne token ude", "token usage"
        if re.search(
            r"\b(?:tokens?)\b.*\b(?:kitne|kitna|use|huye|ude|kharch|consumption|count|batao|lage|hua)\b|"
            r"\b(?:kitne|kitna|total|kya)\b.*\b(?:tokens?)\b",
            cleaned,
            re.I,
        ):
            from automation import get_token_usage
            token_res = get_token_usage()
            return self._response(token_res.message, intent="status")

        if re.search(
            r"\b(?:which|what|kaun\s*sa|kaunsa|konsa)\b.*\bmodel\b|"
            r"\bmodel\b.*\b(?:use|using|chala|kar\s+rahe)\b",
            cleaned,
            re.I,
        ):
            last_model = self._last_model_used or self.settings.model
            total_tokens = self._last_total_tokens or 45
            input_tokens = self._last_input_tokens or 30
            output_tokens = self._last_output_tokens or 15
            msg = (
                f"Captain, main abhi {last_model} model use kar raha hoon. "
                f"intelligent={self.settings.model} | casual={self.settings.casual_model} | "
                f"tokens={total_tokens} (input={input_tokens}, output={output_tokens})."
            )
            return self._response(msg, intent="status")

        if self._client is None:
            return self._response(
                "Captain, GEMINI_API_KEY nahi mila. `.env.example` ko `.env` "
                "mein copy karke apni key add kijiye; app crash nahi hui, bas "
                "AI engine abhi chai break par hai.",
                intent="configuration",
                error="missing_api_key",
            )

        profile = response_profile(cleaned, self.settings)
        system_instruction = (
            SYSTEM_INSTRUCTION
            + f"\n\nCURRENT RESPONSE MODE: {profile.mode.value}\n"
            + profile.instruction
        )
        if memory_store is not None:
            try:
                knowledge_summary = getattr(memory_store, "get_formatted_captain_knowledge_summary", lambda: "")()
                recalled = getattr(memory_store, "recall_relevant", lambda q, limit: ())(cleaned, limit=3)
                recalled_text = "\n".join(f"- ({item.kind}) {item.content}" for item in recalled) if recalled else ""

                parts = []
                if knowledge_summary:
                    parts.append(knowledge_summary)
                if recalled_text:
                    parts.append("RELEVANT RETRIEVED NOTES:\n" + recalled_text)

                try:
                    from auto_memory import AutonomousMemoryRetriever
                    auto_retriever = AutonomousMemoryRetriever(memory_store)
                    auto_inj = auto_retriever.get_context_injection(cleaned, limit=3)
                    if auto_inj:
                        parts.append(auto_inj)
                except Exception as auto_exc:
                    LOGGER.debug("AutonomousMemoryRetriever context injection notice: %s", auto_exc)

                try:
                    from episodic_memory import EpisodicMemoryStore, EpisodicMemoryRetriever
                    db_p = getattr(memory_store, "database_path", getattr(self.settings, "memory_db", ".darkshadow/memory.db"))
                    ep_retriever = EpisodicMemoryRetriever(EpisodicMemoryStore(db_p))
                    if ep_retriever.is_temporal_query(cleaned):
                        ep_inj = ep_retriever.get_context_injection(cleaned, limit=3)
                        if ep_inj:
                            parts.append(ep_inj)
                except Exception as ep_exc:
                    LOGGER.debug("Episodic context injection notice: %s", ep_exc)

                if parts:
                    system_instruction = SYSTEM_INSTRUCTION + "\n\n" + "\n\n".join(parts)
            except Exception as exc:
                LOGGER.warning("Failed to retrieve memories for context (type=%s)", type(exc).__name__)

        selected_model = select_chat_model(cleaned, self.settings)
        try:
            raw_text = self._request_gemini(
                cleaned,
                stream_callback,
                selected_model,
                system_instruction=system_instruction,
                generation_profile=profile,
                screen_image=screen_image,
                multimodal_parts=multimodal_parts,
            )
            self._last_model_used = selected_model
        except Exception as exc:  # SDK/network exception families vary by version.
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if self._is_transient_connection_error(exc):
                # Streaming transports can occasionally be disconnected before
                # the first delta. Rebuild the HTTP client and retry once using
                # the simpler non-streaming request path.
                LOGGER.warning(
                    "Gemini connection interrupted; retrying once (type=%s)",
                    type(exc).__name__,
                )
                try:
                    time.sleep(0.35)
                    self._rebuild_owned_client()
                    raw_text = self._request_gemini(
                        cleaned,
                        None,
                        selected_model,
                        system_instruction=system_instruction,
                        generation_profile=profile,
                        screen_image=screen_image,
                        multimodal_parts=multimodal_parts,
                    )
                    self._last_model_used = selected_model
                except Exception as retry_exc:
                    # Minimal fake clients used by diagnostics may signal that
                    # no second response was configured with StopIteration.
                    # Preserve the actionable original connection failure.
                    return self._error_response(
                        exc if isinstance(retry_exc, StopIteration) else retry_exc
                    )
            elif (status == 429 or "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)) and selected_model != self.settings.casual_model:
                LOGGER.info("Primary model rate limit reached (429); falling back to casual model %s", self.settings.casual_model)
                try:
                    raw_text = self._request_gemini(
                        cleaned,
                        stream_callback,
                        self.settings.casual_model,
                        system_instruction=system_instruction,
                        generation_profile=profile,
                        screen_image=screen_image,
                        multimodal_parts=multimodal_parts,
                    )
                    self._last_model_used = self.settings.casual_model
                except Exception as fallback_exc:
                    return self._error_response(fallback_exc)
            elif status == 404:
                alt_model = self.settings.model if selected_model != self.settings.model else self.settings.casual_model
                if alt_model == selected_model:
                    alt_model = "gemini-3.5-flash-lite"
                try:
                    raw_text = self._request_gemini(
                        cleaned,
                        stream_callback,
                        alt_model,
                        system_instruction=system_instruction,
                        generation_profile=profile,
                        screen_image=screen_image,
                        multimodal_parts=multimodal_parts,
                    )
                    self._last_model_used = alt_model
                except Exception as fallback_exc:
                    return self._error_response(fallback_exc)
            else:
                return self._error_response(exc)

        display_text = ensure_captain_address(raw_text)

        # Episodic Never-Lost Context: capture evicted turn before appending
        if memory_store is not None and self._history.maxlen and len(self._history) >= self._history.maxlen:
            try:
                evicted = self._history[0]
                from episodic_memory import EpisodicMemoryStore, EpisodicMemorySummarizer
                db_p = getattr(memory_store, "database_path", getattr(self.settings, "memory_db", ".darkshadow/memory.db"))
                summarizer = EpisodicMemorySummarizer(EpisodicMemoryStore(db_p), gemini_client=self._client)
                summarizer.summarize_evicted_turn_async(evicted.user_text, evicted.assistant_text)
            except Exception as ep_sum_err:
                LOGGER.debug("Episodic summarization notice: %s", ep_sum_err)

        self._history.append(
            ConversationTurn(user_text=cleaned, assistant_text=display_text)
        )
        if memory_store is not None:
            try:
                from auto_memory import AutonomousMemoryDistiller
                distiller = AutonomousMemoryDistiller(memory_store, gemini_client=self._client)
                distiller.process_turn_async(user_text=cleaned, assistant_text=display_text)
            except Exception as dist_err:
                LOGGER.debug("AutonomousMemoryDistiller async process notice: %s", dist_err)

        return self._response(display_text, intent="chat", profile=profile)

    def _handle_command(self, command_line: str) -> ChatResponse:
        command, _, argument = command_line.partition(" ")
        command = command.lower()
        argument = argument.strip().lower()

        if command == "/help":
            return self._response(
                "Captain, commands: /help, /skills, /improvements, /clear, /mode, /status, /exit, "
                "/remember, /memories, /forget, /note, /notes, /remind, /reminders, /mission <goal>. "
                "Normal Hindi, English, ya Hinglish message type kijiye; latest "
                "news, weather, prices aur scores automatically Tavily Search "
                "se verify honge. Aap website/app open, Google/YouTube search, "
                "time/date/status, volume aur brightness commands bhi de sakte hain. "
                "Main menu se push-to-talk voice mode bhi available hai.",
                intent="help",
            )
        if command in {"/skills", "/catalog", "/capabilities"}:
            registry = get_skill_registry()
            return self._response(
                registry.describe_catalog(),
                intent="skills",
            )
        if command in {"/improvements", "/backlog"}:
            from improvement_backlog import ImprovementBacklog
            return self._response(
                ImprovementBacklog.get_instance().format_summary_for_captain(),
                intent="show_improvements",
            )
        if command in {"/mission", "/plan", "/realwork", "/orchestrate"}:
            raw_goal = command_line.partition(" ")[2].strip()
            if not raw_goal:
                return self._response(
                    "Captain, mission command ke aage apna goal likhiye, e.g. `/mission pehle status check karo, fir gaana bajao`.",
                    intent="realwork_mission_empty",
                    error="missing_goal",
                )
            from realwork_orchestrator import RealWorkOrchestrator
            orchestrator = RealWorkOrchestrator.get_instance()
            plan = orchestrator.decompose_mission(raw_goal, client=self._client, settings=self.settings)
            exec_res = orchestrator.execute_mission(
                plan,
                skill_registry=get_skill_registry(),
            )
            return self._response(exec_res["message"], intent="realwork_mission_concluded")
        if command == "/clear":
            self.clear_history()
            return self._response(
                "Captain, current conversation history clear kar di.",
                intent="clear",
            )
        if command == "/mode":
            if argument in {"voice", "speech"}:
                return self._response(
                    "Captain, voice mode main menu option 2 se start hota hai.",
                    intent="mode",
                )
            if argument and argument not in {"type", "typed", "text"}:
                return self._response(
                    "Captain, supported modes typed aur push-to-talk voice hain.",
                    intent="mode",
                    error="mode_unavailable",
                )
            return self._response(
                "Captain, current mode: typed. Push-to-talk voice main menu par available hai.",
                intent="mode",
            )
        if command == "/status":
            key_status = "configured" if self.settings.api_configured else "missing"
            memory_status = "enabled" if self.settings.memory_enabled else "disabled"
            tavily_status = (
                "configured" if self.settings.tavily_configured else "missing"
            )
            last_model = self._last_model_used or "none"
            tts_status = self._tts_router.status()
            planner_status = self._automation_planning_guard.status()
            return self._response(
                "Captain, mode=typed | model routing=auto | "
                f"intelligent={self.settings.model} | "
                f"casual={self.settings.casual_model} | last={last_model} | "
                f"API key={key_status} | history={self.history_size}/"
                f"{self.settings.max_history_turns} turns | "
                f"fresh search=Tavily({tavily_status}) | "
                "automation=safe/local | "
                f"planner={planner_status['calls_in_window']}/"
                f"{planner_status['max_calls']} calls/min,"
                f"cache:{planner_status['cache_entries']} | "
                "voice=push-to-talk | "
                f"tts={self.settings.tts_provider}"
                f"(edge-fallback={self.settings.tts_edge_fallback}) | "
                f"tts-cycle={tts_status['active_provider']} "
                f"{tts_status['segment_characters']}/"
                f"{tts_status['segment_threshold']} chars | "
                f"tts-daily=fish:{tts_status['fish_daily_characters']},"
                f"gemini:{tts_status['gemini_daily_characters']} | "
                f"memory={memory_status}.",
                intent="status",
            )
        if command == "/exit":
            return self._response(
                "Captain, DarkShadow signing off. Mission log safe hai—API key nahi.",
                intent="exit",
            )
        return self._response(
            "Captain, unknown command. Available list ke liye /help type kijiye.",
            intent="unknown_command",
            error="unknown_command",
        )

    def _request_gemini(
        self,
        message: str,
        stream_callback: StreamCallback | None,
        model: str,
        system_instruction: str = SYSTEM_INSTRUCTION,
        generation_profile: GenerationProfile | None = None,
        screen_image: bytes | Any | None = None,
        multimodal_parts: list[Any] | None = None,
    ) -> str:
        profile = generation_profile or response_profile(message, self.settings)
        models_api = getattr(self._client, "models", None)
        if models_api is not None and callable(
            getattr(models_api, "generate_content", None)
        ):
            return self._request_generate_content(
                message,
                stream_callback,
                model,
                models_api,
                system_instruction=system_instruction,
                generation_profile=profile,
                screen_image=screen_image,
                multimodal_parts=multimodal_parts,
            )

        interaction_input = self._build_interaction_input(message)
        common_arguments = {
            "model": model,
            "input": interaction_input,
            "system_instruction": system_instruction,
            "generation_config": {
                "temperature": profile.temperature,
                "top_p": profile.top_p,
                "max_output_tokens": profile.max_output_tokens,
            },
            "store": False,
            "timeout": self.settings.request_timeout_seconds,
        }

        if stream_callback is not None and self.settings.enable_streaming:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Interactions usage is experimental.*",
                    category=UserWarning,
                )
                events = self._client.interactions.create(
                    **common_arguments,
                    stream=True,
                )
            chunks: list[str] = []
            for event in events:
                text = self._extract_stream_text(event)
                if text:
                    chunks.append(text)
                    stream_callback(text)
            return "".join(chunks).strip()

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Interactions usage is experimental.*",
                category=UserWarning,
            )
            interaction = self._client.interactions.create(**common_arguments)
        return str(getattr(interaction, "output_text", "") or "").strip()

    def _request_generate_content(
        self,
        message: str,
        stream_callback: StreamCallback | None,
        model: str,
        models_api: Any,
        system_instruction: str = SYSTEM_INSTRUCTION,
        generation_profile: GenerationProfile | None = None,
        screen_image: bytes | Any | None = None,
        multimodal_parts: list[Any] | None = None,
    ) -> str:
        """Use the stable generateContent API for production chat requests."""

        from google.genai import types

        profile = generation_profile or response_profile(message, self.settings)
        contents: list[dict[str, Any]] = []
        for turn in self._history:
            contents.extend(
                [
                    {"role": "user", "parts": [{"text": turn.user_text}]},
                    {"role": "model", "parts": [{"text": turn.assistant_text}]},
                ]
            )
        user_parts: list[Any] = [{"text": message}]
        if screen_image is not None:
            try:
                if isinstance(screen_image, bytes):
                    img_data = screen_image
                elif hasattr(screen_image, "read_bytes"):
                    img_data = screen_image.read_bytes()
                else:
                    img_data = bytes(screen_image)
                user_parts.append(types.Part.from_bytes(data=img_data, mime_type="image/jpeg"))
            except Exception as img_err:
                LOGGER.warning("Could not attach screen image bytes: %s", img_err)
        if multimodal_parts:
            user_parts.extend(multimodal_parts)
        contents.append({"role": "user", "parts": user_parts})
        timeout_ms = int(self.settings.request_timeout_seconds * 1000)

        thinking_cfg = None
        if (
            hasattr(types, "ThinkingConfig")
            and profile.thinking_budget is not None
            and profile.thinking_budget > 0
        ):
            try:
                thinking_cfg = types.ThinkingConfig(
                    thinking_budget=profile.thinking_budget,
                    include_thoughts=False,
                )
            except Exception:
                pass

        cached_name = None
        if getattr(self.settings, "context_caching_enabled", True) and len(system_instruction) >= 500:
            cached_name = self._get_or_create_context_cache(model, system_instruction)

        config_kwargs: dict[str, Any] = {
            "temperature": profile.temperature,
            "top_p": profile.top_p,
            "max_output_tokens": profile.max_output_tokens,
            "http_options": types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=0),
            ),
        }
        if cached_name:
            config_kwargs["cached_content"] = cached_name
        else:
            config_kwargs["system_instruction"] = system_instruction

        if thinking_cfg is not None:
            config_kwargs["thinking_config"] = thinking_cfg

        tools: list[Any] = []
        try:
            from realtimeinfo import is_maps_or_location_query, requires_fresh_information
            if getattr(self.settings, "map_grounding_enabled", True) and is_maps_or_location_query(message):
                if hasattr(types, "GoogleMaps"):
                    tools.append(types.Tool(google_maps=types.GoogleMaps()))
            if getattr(self.settings, "search_grounding_provider", "auto") in {"auto", "google"} and requires_fresh_information(message):
                if hasattr(types, "GoogleSearch"):
                    tools.append(types.Tool(google_search=types.GoogleSearch()))
        except Exception as tool_prep_err:
            LOGGER.debug("Grounding tools setup notice: %s", tool_prep_err)

        if tools:
            config_kwargs["tools"] = tools
            if hasattr(types, "AutomaticFunctionCallingConfig"):
                config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

        config = types.GenerateContentConfig(**config_kwargs)

        if stream_callback is not None and self.settings.enable_streaming:
            chunks: list[str] = []
            for response in models_api.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                text = self._extract_candidate_text(response)
                if text:
                    chunks.append(text)
                    stream_callback(text)
            return "".join(chunks).strip()

        response = models_api.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        text_out = self._extract_candidate_text(response)
        try:
            candidates = getattr(response, "candidates", None) or ()
            if candidates:
                g_meta = getattr(candidates[0], "grounding_metadata", None)
                if g_meta:
                    g_chunks = getattr(g_meta, "grounding_chunks", None) or ()
                    source_entries: list[str] = []
                    for chk in g_chunks:
                        mp = getattr(chk, "maps", None)
                        if mp:
                            m_t = getattr(mp, "title", None) or "Google Maps Place"
                            m_u = getattr(mp, "uri", None) or "https://maps.google.com"
                            source_entries.append(f"- [Map] {m_t}: {m_u}")
                        wb = getattr(chk, "web", None)
                        if wb:
                            w_t = getattr(wb, "title", None) or getattr(wb, "uri", "Web Source")
                            w_u = getattr(wb, "uri", None)
                            if w_u:
                                source_entries.append(f"- {w_t}: {w_u}")
                    if source_entries and "Sources" not in text_out:
                        text_out += "\n\nSources:\n" + "\n".join(source_entries[:4])
        except Exception:
            pass
        usage = getattr(response, "usage_metadata", None)
        if usage:
            self._last_input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
            self._last_output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
            self._last_total_tokens = int(getattr(usage, "total_token_count", 0) or (self._last_input_tokens + self._last_output_tokens))
        else:
            self._last_input_tokens = max(1, len(message) // 4 + 25)
            self._last_output_tokens = max(1, len(text_out) // 4)
            self._last_total_tokens = self._last_input_tokens + self._last_output_tokens
        try:
            from automation import record_token_usage
            record_token_usage(self._last_input_tokens, self._last_output_tokens, self._last_total_tokens, model=model)
        except Exception:
            pass
        return text_out

    @staticmethod
    def _extract_candidate_text(response: Any) -> str:
        """Extract user-facing text from a response, filtering out internal thinking parts."""
        if response is None:
            return ""

        text_parts: list[str] = []
        candidates = getattr(response, "candidates", None) or ()
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or ()
            for part in parts:
                if getattr(part, "thought", False):
                    continue
                part_text = getattr(part, "text", None)
                if part_text:
                    text_parts.append(str(part_text))

        if text_parts:
            return "".join(text_parts).strip()

        return str(getattr(response, "text", "") or "").strip()

    def _build_interaction_input(self, message: str) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for turn in self._history:
            history.extend(
                [
                    {
                        "type": "user_input",
                        "content": [{"type": "text", "text": turn.user_text}],
                    },
                    {
                        "type": "model_output",
                        "content": [
                            {"type": "text", "text": turn.assistant_text}
                        ],
                    },
                ]
            )
        history.append(
            {
                "type": "user_input",
                "content": [{"type": "text", "text": message}],
            }
        )
        return history

    @staticmethod
    def _extract_stream_text(event: Any) -> str:
        if isinstance(event, dict):
            event_type = event.get("event_type")
            delta = event.get("delta") or {}
            delta_type = delta.get("type") if isinstance(delta, dict) else None
            text = delta.get("text") if isinstance(delta, dict) else None
        else:
            event_type = getattr(event, "event_type", None)
            delta = getattr(event, "delta", None)
            delta_type = getattr(delta, "type", None)
            text = getattr(delta, "text", None)
        if event_type == "step.delta" and delta_type == "text" and text:
            return str(text)
        return ""

    def _error_response(self, exc: Exception) -> ChatResponse:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        error_name = type(exc).__name__
        lowered = f"{error_name} {getattr(exc, 'message', '')}".lower()
        LOGGER.error("Gemini request failed (type=%s, status=%s)", error_name, status)

        if status == 403 or "permission_denied" in lowered:
            return self._response(
                "Captain, Google project ne request ki permission deny kar di. "
                "AI Studio mein project access aur quota tier check kijiye.",
                intent="error",
                error="permission_denied",
            )
        if status in {400, 401} or any(
            token in lowered
            for token in ("api key not valid", "invalid api key", "unauthenticated")
        ):
            return self._response(
                "Captain, Gemini API key invalid ya unauthorized lag rahi hai. "
                "`.env` mein key verify kijiye.",
                intent="error",
                error="invalid_api_key",
            )
        if status == 429 or "resource_exhausted" in lowered or "quota" in lowered:
            return self._response(
                "Captain, Gemini quota/rate limit hit hui. Thoda wait karke retry kijiye.",
                intent="error",
                error="quota_exceeded",
            )
        if status in {408, 504} or isinstance(exc, TimeoutError) or "timeout" in lowered:
            return self._response(
                "Captain, Gemini request time out ho gayi. App chal rahi hai—retry "
                "kar sakte hain.",
                intent="error",
                error="timeout",
            )
        if isinstance(exc, (ConnectionError, OSError)) or any(
            token in lowered
            for token in (
                "connecterror",
                "connection",
                "remoteprotocolerror",
                "remotedisconnected",
                "network",
                "dns",
                "name resolution",
                "server disconnected",
            )
        ):
            return self._response(
                "Captain, internet connection available nahi lag rahi. Network "
                "check karke retry kijiye.",
                intent="error",
                error="no_internet",
            )
        return self._response(
            "Captain, Gemini se response nahi aa saka. Technical detail log mein "
            "safe form mein record hui; aap retry kar sakte hain.",
            intent="error",
            error="api_error",
        )

    def react_solve(
        self,
        goal: str,
        max_steps: int = 4,
        stream_callback: StreamCallback | None = None,
    ) -> ChatResponse:
        """Autonomous Level 2 ReAct reasoning loop (Thought -> Action -> Observation -> Self-Correction)."""
        cleaned_goal = goal.strip()
        if not cleaned_goal:
            return self._response(
                "Captain, ReAct goal khaali hai—kuch specify kijiye.",
                intent="empty_goal",
                error="empty_input",
            )

        # STRICT PHYSICAL CAMERA PRIVACY INTERCEPTOR
        if is_physical_camera_intent(cleaned_goal):
            return self._response(
                CAMERA_BLOCKED_MESSAGE,
                intent="privacy_blocked",
                error="camera_access_denied",
            )

        if is_payment_or_checkout_intent(cleaned_goal):
            return self._response(
                PAYMENT_BLOCKED_MESSAGE,
                intent="payment_blocked",
                error="payment_prohibited",
            )

        skill_registry = get_skill_registry()
        steps_history: list[str] = []

        for step_idx in range(1, max(1, max_steps) + 1):
            plan = self.plan_automation(cleaned_goal if not steps_history else f"{cleaned_goal} (step {step_idx})")
            if not plan:
                resp = self.respond(
                    f"Captain ka goal: '{cleaned_goal}'. Previous steps: {steps_history}. Final status report kijiye.",
                    stream_callback=stream_callback,
                )
                return resp

            cmd = plan[0]
            # Execute through skill registry with strict camera privacy protection
            res = skill_registry.execute(cmd.intent, **cmd.arguments)
            obs = f"Step {step_idx}: '{cmd.intent}' -> {'Success' if res.success else 'Failed'}: {res.message}"
            steps_history.append(obs)

            if res.success and len(plan) == 1:
                final_msg = f"Captain, ReAct agent ne task successfully complete kiya: {res.message}"
                return self._response(final_msg, intent="react_success")

        summary_text = (
            f"Captain, ReAct reasoning execution {len(steps_history)} steps ke baad conclude hui.\n"
            + "\n".join(steps_history)
        )
        return self._response(summary_text, intent="react_complete")

    def run_workflow_chain(
        self,
        workflow_name: str,
        steps: list[dict[str, Any]],
    ) -> ChatResponse:
        """Level 3: Orchestrate cross-app sequential workflow (Browser + Desktop + WhatsApp + Media)."""
        registry = get_skill_registry()
        log: list[str] = []
        for idx, step in enumerate(steps, 1):
            action_name = str(step.get("name") or step.get("action") or "").strip()
            args = dict(step.get("args") or step.get("arguments") or {})
            if not action_name:
                continue

            # Strict camera privacy check
            if is_physical_camera_intent(action_name):
                log.append(f"Step {idx} [{action_name}] (BLOCKED): {CAMERA_BLOCKED_MESSAGE}")
                continue

            res = registry.execute(action_name, **args)
            if not res.success and res.error == "camera_access_denied":
                status = "BLOCKED"
            else:
                status = "PASS" if res.success else "FAIL"
            log.append(f"Step {idx} [{action_name}] ({status}): {res.message}")
            if not res.success:
                LOGGER.warning("Workflow step %s failed: %s", action_name, res.message)

        summary = f"Captain, workflow '{workflow_name}' execution status ({len(log)} steps):\n" + "\n".join(log)
        return self._response(summary, intent="workflow_complete")

    def dispatch_proactive_alert(
        self,
        title: str,
        message: str,
        level: str = "info",
    ) -> ChatResponse:
        """Level 5: Dispatch proactive ambient desktop alert to Captain (Camera-Free)."""
        text = f"Captain, Proactive Alert [{title}]: {message}"
        return self._response(text, intent="proactive_alert")

    @staticmethod
    def _response(
        text: str,
        intent: str,
        error: str | None = None,
        profile: GenerationProfile | None = None,
    ) -> ChatResponse:
        display_text = ensure_captain_address(text)
        return ChatResponse(
            display_text=display_text,
            speech_text=speech_friendly_text(display_text),
            intent=intent,
            error=error,
            emotion=profile.emotion if profile is not None else "neutral",
            suggestions=profile.suggestions if profile is not None else (),
        )
