# DARK SHADOW®
### A Minimal Living AI Desktop Interface for Windows 11

**DARK SHADOW®** is an interactive, visual desktop AI entity that floats gracefully over your Windows 11 desktop. Rather than a conventional chatbot window or clunky taskbar widget, DARK SHADOW exists as a living, glowing particle orb that seamlessly breathes, responds to cursor proximity, ripples under scroll gestures, and pulsates in real time with human speech and Gemini AI responses.

---

## 🌌 Core Features & Visual Entity

- **Living Particle Physics Engine:** Vectorized physics with NumPy for fluid, organic particle dynamics at a smooth 60 FPS with near-zero CPU/GPU overhead.
- **Cinematic Emergence Animation:** When activated, hundreds of particles erupt from the bottom edge of your screen, soar upward with spiral fanning, and coalesce into a floating orb.
- **Dynamic Window Masking:** Outside the circular aura of the orb, all Windows clicks pass through to background apps, browsers, and desktop icons.
- **Interactive Fluid Dynamics:**
  - **Mouse Repulsion & Tendrils:** Cursor proximity gently parts particles, while outer magnetic tendrils reach out toward your pointer.
  - **Click-to-Listen:** Clicking the orb detonates a circular shockwave ripple and enters voice listening mode.
  - **Drag-to-Reposition:** Click and drag the orb to move it anywhere across multi-monitor or 4K/QHD/FHD desktop setups.
  - **Scroll Ripples:** Mouse wheel scrolling triggers expanding kinetic ripples and rotational momentum.
- **Voice-Reactive Pulsation:**
  - **Wake Phrase:** Runs quietly in the background; say **"Dark Shadow"** to wake it.
  - **Real-Time Vocal Waveform Tracking:** Streams live RMS audio chunks to pulse and vibrate the orb in synchrony with speech.
  - **Vocal Synthesis:** Microsoft David / Zira SAPI5 TTS with live phoneme amplitude tracking.
- **Modular Gemini AI:**
  - Powered by Google Gemini (e.g., `gemini-3.5-flash-lite`, `gemini-3.8-flash`).
  - Automatic model failover on load spikes.
  - Built-in offline intelligence for system status (CPU, RAM, battery, time, date) when offline.

---

## 📐 Architecture

```
dark_shadow/
├── main.py                     # Master application orchestrator and lifecycle manager
├── config.py                   # Centralized visual, physics, voice, and AI settings
├── requirements.txt            # Python dependencies
├── ui/
│   ├── overlay.py              # Transparent frameless PySide6 overlay with Windows mask
│   ├── orb.py                  # State machine, coordinates, hit-testing, and controller
│   ├── particles.py            # Vectorized NumPy particle physics & rendering engine
│   └── animations.py           # Easing curves and expanding shockwave ripple manager
├── interaction/
│   ├── mouse.py                # Cursor hover repulsion, tendrils, and drag handler
│   ├── scroll.py               # Scroll wheel kinetic ripple generator
│   └── keyboard.py             # Global Windows hotkey (RegisterHotKey) & shortcuts
├── voice/
│   ├── wake_word.py            # Background listener for "Dark Shadow" wake phrase
│   ├── speech_input.py         # PyAudio live RMS streaming & SpeechRecognition STT
│   └── speech_output.py        # pyttsx3 vocal synthesis with amplitude tracking
├── ai/
│   └── gemini.py               # Google Gemini client with multi-model failover & offline mode
├── assets/                     # Tray icons and assets
├── logs/                       # Application logs (dark_shadow.log)
└── README.md                   # Documentation
```

---

## ⚡ Animation States

| State | Orb Visual Behavior |
| :--- | :--- |
| **IDLE** | Dormant and concealed; releases all mouse input to Windows. |
| **ACTIVATING** | Particles erupt from the screen bottom, fanning and homing into the circular orb. |
| **INTERACTING** | Calm breathing animation (sine-modulated radius and floating motion). Reacts to mouse. |
| **LISTENING** | Rapid breathing; particle radius expands and vibrates with real-time mic volume. |
| **THINKING** | Particles split into dual counter-rotating celestial vortex rings. |
| **SPEAKING** | Particles pulsate in real time to the phoneme amplitudes of the assistant's voice. |
| **DEACTIVATING** | Particles break cohesion, gently drifting downward and dissolving into the desktop. |

---

## 💻 Hardware & Performance Target

Tested and optimized for:
- **Processor:** Intel Core i5 11th Gen
- **Graphics:** Intel Iris Xe Graphics
- **Memory:** 16 GB RAM
- **OS:** Windows 11 (High-DPI scaling 100%, 125%, 150%, 175%, 200%)
- **Target Performance:** 60 FPS (16ms frame budget; physics step executes in under 0.1ms).

---

## 🚀 Installation & Setup

### 1. Requirements
Ensure Python 3.11+ is installed.

```bash
# Clone or navigate to the darkshadow repository
cd f:\darkshadow

# Activate your virtual environment
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies
```bash
pip install -r dark_shadow/requirements.txt
```

### 3. Configure API Key
Create or update `.env` in the project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
DARKSHADOW_MODEL=gemini-3.5-flash-lite
```
*(Note: If no API key is provided, DARK SHADOW gracefully falls back to local offline desktop intelligence.)*

---

## 🎮 Execution & Controls

### Launching DARK SHADOW

#### Normal Background Mode (Quiet in System Tray):
```bash
python -m dark_shadow.main
```
Say **"Dark Shadow"** or press **Ctrl+Shift+D** to summon the orb!

#### Launch Directly Visible (Immediate Emergence):
```bash
python -m dark_shadow.main --show
```

#### Visual Only (Disable Microphone / Audio Subsystem):
```bash
python -m dark_shadow.main --show --no-voice
```

#### Preview Specific State:
```bash
python -m dark_shadow.main --state thinking
```

---

## 🖱️ Controls & Shortcuts

| Action | Control | Description |
| :--- | :--- | :--- |
| **Global Wake/Hide** | `Ctrl + Shift + D` | Summon or dismiss the orb from anywhere in Windows. |
| **Voice Wake** | *"Dark Shadow"* | Speak wake phrase to summon the orb. |
| **Listen Toggle** | `Left Click` on Orb | Starts voice listening mode or cancels it. |
| **Reposition Orb** | `Left Click + Drag` | Drag the orb to any position on your desktop. |
| **Ripple Shockwave** | `Mouse Scroll Wheel` | Scroll over the orb to generate particle waves. |
| **Dismiss / Hide** | `Escape` key | Instantly starts the dissolution animation into IDLE. |
| **System Tray** | Right-click Tray Icon | Quick menu to trigger states, reset position, or exit. |

---

## 🛠️ Diagnostics & Logs

Log files are automatically stored under:
```
dark_shadow/logs/dark_shadow.log
```
To view real-time diagnostics in PowerShell:
```powershell
Get-Content -Path dark_shadow\logs\dark_shadow.log -Wait -Tail 30
```

---

*DARK SHADOW® is built with PySide6, NumPy, SpeechRecognition, PyAudio, pyttsx3, and Google Gemini.*
