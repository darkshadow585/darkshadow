# DarkShadow

DarkShadow is a lightweight personal desktop assistant for Windows 11. Phases
1 through 5 provide typed and push-to-talk modes, bounded conversation context,
Hindi/English/Hinglish personality, Gemini chat, grounded current information,
safe deterministic automation, speech recognition, interruptible speech, and
opt-in local memory with reminders.

The assistant always addresses Kuldeep as **Captain**. Persistent memory is
disabled by default and saves only explicit requests.

## Requirements

- Windows 11
- Python 3.11
- A microphone for voice input (typed mode works without it)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
- A Murf API key for low-latency Falcon 2 speech (optional; Gemini starts if absent)
- A Tavily API key for current web information
- Internet for Gemini, Tavily, Google speech recognition, and Edge TTS

## Exact Windows PowerShell setup

Open PowerShell in this project directory, then run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

In `.env`, set your key without quotes:

```dotenv
GEMINI_API_KEY=your_real_key_here
MURF_API_KEY=your_real_murf_key_here
```

Never commit `.env`; it is ignored by Git.

## Run

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Choose `1` for typed mode, `2` for push-to-talk voice mode, or `3` to exit.
The microphone and audio libraries load only after voice mode is selected.

### Voice mode

In voice mode:

1. Press `ENTER` when the prompt appears.
2. Wait for `Captain, listening...`, then speak one Hindi, English, or Hinglish
   phrase.
3. DarkShadow prints the recognized text and its answer, then speaks the answer
   without blocking the application.
4. Press `ENTER` again to interrupt current speech and give the next command.

Voice controls typed at the push-to-talk prompt:

- `/mic` - list Windows microphone input indexes

- `/stop` — interrupt current speech
- `/back` — return to the main menu
- `/exit` — close DarkShadow

The microphone is calibrated briefly before each phrase. Listening has both a
start timeout and phrase-length limit. If microphone access or its dependency
fails, DarkShadow automatically opens typed mode. TTS failure never hides the
printed answer or terminates the assistant.

Voice settings in `.env`:

```dotenv
DARKSHADOW_STT_LANGUAGES=hi-IN,en-IN
DARKSHADOW_IPV4_FIRST=true
DARKSHADOW_STT_CALIBRATION_SECONDS=0.6
DARKSHADOW_STT_TIMEOUT_SECONDS=5
DARKSHADOW_STT_PHRASE_LIMIT_SECONDS=15
DARKSHADOW_STT_DEVICE_INDEX=
DARKSHADOW_TTS_PROVIDER=auto
DARKSHADOW_MURF_MODEL=falcon-2
DARKSHADOW_MURF_VOICE=hi-IN-karan
DARKSHADOW_MURF_LOCALE=hi-IN
DARKSHADOW_MURF_REGION=in
DARKSHADOW_TTS_MURF_SEGMENT_CHARS=500
DARKSHADOW_TTS_GEMINI_SEGMENT_CHARS=1000
DARKSHADOW_TTS_USAGE_FILE=.darkshadow/tts_usage.json
DARKSHADOW_TTS_GEMINI_MODEL=gemini-3.8-flash-tts-preview
DARKSHADOW_TTS_GEMINI_VOICE=Orus
DARKSHADOW_TTS_GEMINI_TIMEOUT_SECONDS=10
DARKSHADOW_TTS_EDGE_FALLBACK=true
DARKSHADOW_TTS_VOICE=hi-IN-MadhurNeural
DARKSHADOW_TTS_ENGLISH_VOICE=en-IN-PrabhatNeural
DARKSHADOW_TTS_RATE=+0%
DARKSHADOW_TTS_PITCH=+0Hz
DARKSHADOW_TTS_VOLUME=+0%
```

In `auto` mode, each complete response uses one provider. The persisted daily
cycle starts with roughly 500 spoken characters through Murf, then roughly
1,000 through Gemini, and repeats. Crossing a threshold changes the *next*
response, so speech is never split or switched mid-response. The cycle and safe
aggregate counters reset at midnight in the Asia/Kolkata timezone. `/status`
shows the active provider and counters; `.darkshadow/tts_usage.json` stores no
text, prompts, keys, or personal content.

Murf Falcon 2 uses the configured native `hi-IN-karan` Hindi voice, `hi-IN` locale,
India region, and streams 24 kHz mono PCM directly to PyAudio. Obtain a key from
the Murf API dashboard, copy `.env.example` to `.env`, and paste it only after
`MURF_API_KEY=`. Never put the key in source code or commit `.env`. If the key
is absent or Murf fails, DarkShadow immediately tries Gemini, then Edge, then
the offline Windows voice.

Gemini TTS uses the existing `GEMINI_API_KEY` and
`gemini-3.8-flash-tts-preview`. Its preferred Interactions API path requests
`stream=True`, decodes each audio delta, and writes PCM to PyAudio as soon as
the first chunk arrives, avoiding the former full-response WAV wait. Older SDK
behavior retains a non-streaming WAV compatibility path. Printed answers are
never hidden by a voice failure.
DarkShadow prefers IPv4 DNS candidates inside this process because broken
Windows IPv6 routes can otherwise stall Gemini and Edge TTS. If both cloud
voices fail, the local Windows SAPI/pyttsx3 voice is queued as a final offline
fallback.

View TTS requests and token usage in Google AI Studio under **Usage**, after
selecting the same project as the API key:
https://aistudio.google.com/app/usage?timeRange=last-28-days

Leave `DARKSHADOW_STT_DEVICE_INDEX` blank for the Windows default microphone.
If recognition fails, enter `/mic`, choose the index for your active Realtek or
Bluetooth microphone, set it in `.env`, and restart DarkShadow.

Responses automatically use the Hindi voice for Hindi/Hinglish text and the
English voice for English text. If text prints but audio is not audible, check
the selected Windows output speaker, app volume mixer, and mute state.

An optional wake phrase can gate commands inside push-to-talk mode:

```dotenv
DARKSHADOW_WAKE_PHRASE_ENABLED=true
DARKSHADOW_WAKE_PHRASE=dark shadow
```

After pressing `ENTER`, say something like `Dark Shadow, open Chrome`. This is
not continuous listening; the microphone still activates only after the
push-to-talk prompt.

## Fresh information

Fresh queries are routed automatically to Tavily Search. Try:

```text
Delhi weather today
Latest India news
Bitcoin price abhi
Current Python version
IPL score
```

DarkShadow displays current answers only when a valid source URL is present.
Add the following settings to `.env`:

```env
TAVILY_API_KEY=tvly-your-key-here
DARKSHADOW_TAVILY_SEARCH_DEPTH=basic
DARKSHADOW_TAVILY_MAX_RESULTS=5
DARKSHADOW_REALTIME_CACHE_SECONDS=300
```

`basic` costs one Tavily credit per new search. Identical queries are cached for
five minutes by default, so repeated questions do not spend another credit.

## Memory, notes, and reminders

Persistent memory is opt-in. Enable it in `.env`, then restart DarkShadow:

```dotenv
DARKSHADOW_MEMORY_ENABLED=true
DARKSHADOW_MEMORY_DB=.darkshadow/memory.db
```

Examples:

```text
remember this: I prefer concise answers
/note Call the school office
/memories
/notes
/forget 3
forget this: I prefer concise answers
remind me tomorrow at 09:00 to call Rahul
/reminders
/delete-reminder 2
```

Only explicit preferences, notes, and reminders are stored. Ordinary
conversation is never copied into SQLite. Due reminders are delivered while
DarkShadow is running; a reminder that becomes due while it is closed appears
after the next launch. API keys, passwords, OTPs, payment data, access tokens,
private keys, and private clipboard content are rejected.

## Automation

Automation is routed locally before Gemini. These commands work in both typed
and voice modes:

```text
open Chrome
open github.com
google search Python decorators
search YouTube for Python automation
play lofi beats on YouTube
heey jarvis oepn youtube and play love wins all
Arijit Singh kaun hai
unka koi song chalao
spotify par play Kesariya
WhatsApp par Mummy ko message bhejo: Main 10 minute late hounga and YouTube par play lofi
current time
today's date
system status
set volume to 40
awaz badhao
mute
volume down by 10
set brightness to 60
```

Browser and device commands have real side effects when you run the assistant.
Tests mock all of them.

### Multi-step automation and planning limits

DarkShadow executes up to four validated actions in order. It first tries the
deterministic local parser, so known commands use zero Gemini requests. Only an
unrecognized action-like command reaches the Gemini tool planner, which makes
at most one request for the complete plan. Duplicate plans are cached briefly,
and a local sliding-window guard stops request bursts before they reach the
provider.

```dotenv
DARKSHADOW_AUTOMATION_PLANNER_MAX_CALLS_PER_MINUTE=6
DARKSHADOW_AUTOMATION_PLAN_CACHE_SECONDS=300
```

WhatsApp automation uses the installed Windows desktop app through the
`whatsapp://` protocol and Windows UI Automation, not WhatsApp Web. It accepts
either an exact saved contact name or an international number beginning with
`+`. For a contact name, DarkShadow opens New Chat, searches the exact name,
rejects missing or duplicate matches, opens the result, finds the message
composer, types, and sends. It verifies the foreground process as the installed
WhatsApp package before the final Enter; if verification fails, it does not
send or continue the sequence. OTPs, passwords, PINs, private keys, and access
tokens are blocked. A successful result means the Send command was dispatched
to WhatsApp, not that network delivery or reading was verified.

Confirmation is enabled by default. This installation opts out with:

```dotenv
DARKSHADOW_WHATSAPP_CONFIRM_SEND=false
```

Use `draft` instead of `send` to open the desktop draft without pressing Send:

```text
WhatsApp par +91 98765 43210 ko message draft karo: Main late hounga
```

## Commands

- `/help` — show available commands and capabilities
- `/clear` — clear bounded in-memory conversation history
- `/mode` — show mode information
- `/status` — show safe configuration, search, automation, and voice status
- `/remember TEXT` — save one explicit preference
- `/note TEXT` — save one explicit note
- `/memories` and `/notes` — list saved items
- `/forget ID` — delete one saved item
- `/reminders` — list pending reminders
- `/delete-reminder ID` — delete one pending reminder
- `/exit` — close DarkShadow cleanly

## Automation safety

- Website URLs must use HTTP or HTTPS; all search text is URL-encoded.
- App launch is restricted to Chrome, Edge, Notepad, Calculator, File Explorer,
  VS Code, Paint, Spotify, and Windows Terminal from trusted Windows install
  locations.
- User/model text is never passed to `cmd.exe`, PowerShell, `eval`, `exec`, or
  `shell=True`.
- Shutdown/restart, closing apps, file deletion/moves, software installation,
  purchases/payments, unknown executables, and important system settings require
  explicit confirmation. WhatsApp Desktop sending is the only implemented
  outbound message executor; its confirmation can be explicitly disabled with
  `DARKSHADOW_WHATSAPP_CONFIRM_SEND=false`.
- Every tool returns a structured result. DarkShadow reports success only when
  the tool result confirms it.

## Gemini model choice

Normal chat uses deterministic automatic model routing. Complex reasoning,
coding, debugging, planning, and detailed requests use the intelligent model;
casual conversation and short simple questions use the faster budget model.
No extra Gemini request is spent deciding the route.

```dotenv
DARKSHADOW_MODEL=gemini-3.5-flash
DARKSHADOW_CASUAL_MODEL=gemini-3.1-flash-lite
```

Use `/status` to see both configured models, Tavily readiness, and the model
used for the last successful normal-chat request. Fresh-information requests
use Tavily directly and therefore do not consume Gemini Search-grounding RPM.
Changing either Gemini model does not require a new API key. Review current
model details and pricing in the
[official Gemini documentation](https://ai.google.dev/gemini-api/docs/pricing).

## Test

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Tests use fake Gemini/Tavily clients, temporary SQLite databases, and mocked
automation/audio. They do not spend API quota, record from a microphone, create
TTS network requests, play audio, open apps/tabs, or alter volume/brightness.

## Phase status

- Phase 1: typed foundation and Gemini chat — implemented
- Phase 2: current information with Tavily Search and short-lived cache — implemented
- Phase 3: safe Windows/browser automation — implemented
- Phase 4: push-to-talk STT and interruptible Edge TTS — implemented
- Phase 5: opt-in SQLite notes, reminders, and preferences — implemented
- Phase 6: optional Gemini Live API — not implemented

- Level 2: bounded multi-step automation, cached/rate-limited planning, and
  confirmed WhatsApp Desktop sending — implemented

## Privacy and error handling

Conversation history is held only in RAM and is capped by
`DARKSHADOW_HISTORY_TURNS`. If memory is enabled, explicitly saved items use a
local, unencrypted SQLite file under `.darkshadow/`; protect the Windows account
and never store secrets there. Push-to-talk audio is sent to Google's speech
recognition service, and answer text may be sent to Murf, Gemini TTS, or
Microsoft's Edge TTS service according to the configured routing mode.
The optional offline faster-whisper backend is not active. Streaming Murf and
Gemini audio does not use temporary files; the Edge and compatibility paths use
short temporary files that are deleted after completion or interruption.

Missing or invalid keys, quota limits, timeouts, network failures, microphone
errors, TTS errors, missing optional device support, and rejected automation
return friendly errors without terminating the CLI. Logs record exception
type/status only, not API keys or complete private conversations.
