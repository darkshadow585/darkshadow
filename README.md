# DarkShadow

DarkShadow is a personal AI co-pilot web application for Captain, migrated from the original Python/PySide6 Windows desktop assistant to a Node.js + React + TypeScript full-stack web app.

## Features

- **Panoramic Single-Orb Cyber HUD**: Preserves DarkShadow's pure obsidian theme (`#000000` / `#070A10` / `#765CFF` / `#00D2FF`), fluid orb core (`darkshadow_core.gif`), state-aware canvas rings, blinking glowing eyes, and 25-bar live audio waveform.
- **Typed & Push-to-Talk Voice Modes**: Supports Hindi, English, and Hinglish via browser Web Speech Recognition (`hi-IN` / `en-IN`), press `Space` or click the orb to speak, plus interruptible Gemini TTS (`gemini-3.8-flash-lite-tts` with `Charon` voice) with automatic browser speech synthesis fallback.
- **Dual-Model Gemini Routing**: Server-side `@google/genai` integration automatically routes complex/technical prompts to `gemini-4-hydrogen` and casual prompts to `gemini-3.1-flash-lite`.
- **Fresh Information Grounding**: Time-sensitive queries (weather, news, prices, scores, locations) route through Tavily Search (when `TAVILY_API_KEY` is configured) or Gemini Google Search Grounding with verified source citations.
- **Opt-In Memory, Notes & Reminders**: Deterministic commands (`/remember`, `/note`, `/memories`, `/notes`, `/forget`, `/remind`, `/reminders`, `/delete-reminder`) with sensitive-data filtering and a session Privacy Mode toggle in Settings.
- **Safety & Privacy Shields**: Payment/checkout exclusion, zero-camera privacy enforcement, and dangerous shell command blocking run deterministically before any LLM call.

## Setup & Commands

```bash
npm install
npm run dev      # Starts Express + Vite dev server on http://0.0.0.0:3000
npm run build    # Builds production frontend bundle to dist/
npm run start    # Runs production server on port 3000
npm run lint     # Runs TypeScript type checking
```

Configure environment variables in `.env` (see `.env.example`):

- `GEMINI_API_KEY` — Gemini API key (configured via AI Studio Secrets)
- `TAVILY_API_KEY` — Optional Tavily Search API key
