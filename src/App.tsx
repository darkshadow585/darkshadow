import { useCallback, useEffect, useRef, useState } from "react";
import {
  Copy,
  ExternalLink,
  Mic,
  MicOff,
  Moon,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  User,
  Zap,
} from "lucide-react";
import { AudioWaveform } from "./components/AudioWaveform.tsx";
import { ControlCenterModal } from "./components/ControlCenterModal.tsx";
import { DesktopExportModal } from "./components/DesktopExportModal.tsx";
import { ParticleOrbWebGL } from "./components/ParticleOrbWebGL.tsx";
import type { AudioBands, ParticlePhase, ParticleShape } from "./components/ParticleOrbWebGL.tsx";
import { RemindersModal } from "./components/RemindersModal.tsx";
import { TitleBar } from "./components/TitleBar.tsx";
import { STATE_LABEL_COLOR, STATE_TEXT } from "./types.ts";
import type {
  ActionLink,
  AssistantState,
  ChatApiResponse,
  ChatTurn,
  MemoryItem,
  ReminderItem,
  RuntimeStatus,
  SourceCitation,
} from "./types.ts";

interface BrowserSpeechRecognitionEvent {
  results: {
    length: number;
    [index: number]: {
      isFinal: boolean;
      [altIndex: number]: { transcript: string };
    };
  };
}

interface BrowserSpeechRecognition {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  continuous: boolean;
  onresult: ((ev: BrowserSpeechRecognitionEvent) => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => BrowserSpeechRecognition;
    webkitSpeechRecognition?: new () => BrowserSpeechRecognition;
  }
}

const WAKE_REGEX = /\b(?:hey\s+|hello\s+|ok\s+|suno\s+)?(?:dark\s*shadow|darkshadow|डार्क\s*शैडो)\b/i;
const SLEEP_REGEX = /\b(?:sleep|so\s*jao|bye|goodbye|band\s*ho\s*jao|hide)\b/i;

const SHAPE_OPTIONS: Array<{ id: ParticleShape; label: string }> = [
  { id: "sphere", label: "Sphere" },
  { id: "helix", label: "DNA Helix" },
  { id: "torus", label: "Plasma Torus" },
  { id: "shield", label: "Shield Cube" },
];

export default function App() {
  const [particlePhase, setParticlePhase] = useState<ParticlePhase>("rising");
  const [particleShape, setParticleShape] = useState<ParticleShape>("sphere");
  const [assistantState, setAssistantState] = useState<AssistantState>("idle");
  const [statusMessage, setStatusMessage] = useState<string>("Summoning 6,000 particles…");
  const [audioBands, setAudioBands] = useState<AudioBands>({ bass: 0, mid: 0, treble: 0 });

  const [commandText, setCommandText] = useState("");
  const [currentPrompt, setCurrentPrompt] = useState("");
  const [currentResponse, setCurrentResponse] = useState(
    'Captain, Option B + 5 Upgrades ready hain! Neeche Sphere / DNA Helix / Plasma Torus / Shield Cube morph test kijiye, aur upar "Windows Python (.py)" se poora Desktop ZIP download kijiye.'
  );
  const [sources, setSources] = useState<SourceCitation[]>([]);
  const [actionLink, setActionLink] = useState<ActionLink | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([
    "Namaste DarkShadow",
    "Delhi weather today",
    "/help",
  ]);
  const [history, setHistory] = useState<ChatTurn[]>([]);

  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [privacyMode, setPrivacyMode] = useState(false);
  const [sttLanguage, setSttLanguage] = useState<"hi-IN" | "en-IN">("hi-IN");

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [remindersOpen, setRemindersOpen] = useState(false);
  const [desktopModalOpen, setDesktopModalOpen] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [reminders, setReminders] = useState<ReminderItem[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [copiedNotice, setCopiedNotice] = useState(false);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const returnTimerRef = useRef<number | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const speechAnimRef = useRef<number | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micMeterRafRef = useRef<number | null>(null);
  const isListeningRef = useRef(false);
  const voiceEnabledRef = useRef(voiceEnabled);
  const phaseRef = useRef<ParticlePhase>(particlePhase);
  voiceEnabledRef.current = voiceEnabled;
  phaseRef.current = particlePhase;

  const setHudState = useCallback((next: AssistantState, customMessage?: string) => {
    if (returnTimerRef.current !== null) {
      window.clearTimeout(returnTimerRef.current);
      returnTimerRef.current = null;
    }
    setAssistantState(next);
    setStatusMessage(customMessage?.trim() || STATE_TEXT[next]);

    if (next === "listening") {
      setParticlePhase("listening");
      setParticleShape("sphere");
    } else if (next === "processing") {
      setParticlePhase("processing");
      setParticleShape("helix");
    } else if (next === "speaking") {
      setParticlePhase("speaking");
      setParticleShape("torus");
    } else if (next === "error") {
      setParticlePhase("alert");
      setParticleShape("shield");
    } else if (next === "idle" || next === "success") {
      setParticlePhase((prev) =>
        prev === "dormant" || prev === "dissolving" || prev === "rising" ? prev : "listening"
      );
      setParticleShape("sphere");
    }

    if (next === "success") {
      returnTimerRef.current = window.setTimeout(() => {
        setAssistantState("idle");
        setStatusMessage(STATE_TEXT.idle);
      }, 1800);
    } else if (next === "error") {
      returnTimerRef.current = window.setTimeout(() => {
        setAssistantState("idle");
        setStatusMessage(STATE_TEXT.idle);
        setParticlePhase("listening");
        setParticleShape("sphere");
      }, 4200);
    }
  }, []);

  const stopSpeech = useCallback(() => {
    if (speechAnimRef.current !== null) {
      cancelAnimationFrame(speechAnimRef.current);
      speechAnimRef.current = null;
    }
    if (audioElRef.current) {
      audioElRef.current.pause();
      audioElRef.current.src = "";
      audioElRef.current = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setAudioBands({ bass: 0, mid: 0, treble: 0 });
    setAssistantState((prev) => {
      if (prev === "speaking") {
        setStatusMessage(STATE_TEXT.idle);
        setParticlePhase((p) => (p === "speaking" ? "listening" : p));
        setParticleShape("sphere");
        return "idle";
      }
      return prev;
    });
  }, []);

  const stopMicMeter = useCallback(() => {
    if (micMeterRafRef.current !== null) {
      cancelAnimationFrame(micMeterRafRef.current);
      micMeterRafRef.current = null;
    }
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }
    setAudioBands({ bass: 0, mid: 0, treble: 0 });
  }, []);

  const summonParticles = useCallback(() => {
    stopSpeech();
    setParticleShape("sphere");
    setParticlePhase("rising");
    setAssistantState("idle");
    setStatusMessage("Hey Dark Shadow — Forming sphere…");
  }, [stopSpeech]);

  const dismissParticles = useCallback(() => {
    stopSpeech();
    if (isListeningRef.current) {
      recognitionRef.current?.stop();
      isListeningRef.current = false;
      stopMicMeter();
    }
    setParticlePhase("dissolving");
    setAssistantState("idle");
    setStatusMessage("Dissolving to standby…");
  }, [stopMicMeter, stopSpeech]);

  const speakWithBrowserFallback = useCallback(
    (text: string) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        setHudState("success");
        return;
      }
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      const hasDevanagari = /[\u0900-\u097F]/.test(text);
      const targetLang = hasDevanagari ? "hi-IN" : sttLanguage;
      utterance.lang = targetLang;
      utterance.rate = 1.02;
      utterance.pitch = 0.92;

      const voices = window.speechSynthesis.getVoices();
      const match =
        voices.find((v) => v.lang.toLowerCase() === targetLang.toLowerCase()) ||
        voices.find((v) => v.lang.toLowerCase().startsWith(hasDevanagari ? "hi" : "en"));
      if (match) utterance.voice = match;

      let t = 0;
      const pulse = () => {
        t += 0.16;
        setAudioBands({
          bass: 0.25 + 0.62 * Math.abs(Math.sin(t * 1.1) * Math.cos(t * 0.45)),
          mid: 0.3 + 0.58 * Math.abs(Math.sin(t * 1.9)),
          treble: 0.2 + 0.55 * Math.abs(Math.sin(t * 3.1) * Math.cos(t * 1.3)),
        });
        speechAnimRef.current = requestAnimationFrame(pulse);
      };

      utterance.onstart = () => {
        setHudState("speaking");
        pulse();
      };
      utterance.onend = () => {
        if (speechAnimRef.current !== null) cancelAnimationFrame(speechAnimRef.current);
        speechAnimRef.current = null;
        setAudioBands({ bass: 0, mid: 0, treble: 0 });
        setHudState("idle");
      };
      utterance.onerror = () => {
        if (speechAnimRef.current !== null) cancelAnimationFrame(speechAnimRef.current);
        speechAnimRef.current = null;
        setAudioBands({ bass: 0, mid: 0, treble: 0 });
        setHudState("idle");
      };
      window.speechSynthesis.speak(utterance);
    },
    [setHudState, sttLanguage]
  );

  const speakResponse = useCallback(
    async (speechText: string) => {
      if (!voiceEnabledRef.current || !speechText.trim()) return;
      stopSpeech();
      setHudState("speaking");

      try {
        const res = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: speechText }),
        });
        if (!res.ok) {
          speakWithBrowserFallback(speechText);
          return;
        }
        const data = (await res.json()) as { audioBase64?: string; mimeType?: string };
        if (!data.audioBase64) {
          speakWithBrowserFallback(speechText);
          return;
        }

        const audio = new Audio(`data:${data.mimeType || "audio/wav"};base64,${data.audioBase64}`);
        audioElRef.current = audio;

        let t = 0;
        const animateSpeech = () => {
          if (!audioElRef.current || audioElRef.current.paused) return;
          t += 0.2;
          setAudioBands({
            bass: 0.28 + 0.64 * Math.abs(Math.sin(t * 1.0) * Math.cos(t * 0.4)),
            mid: 0.32 + 0.58 * Math.abs(Math.sin(t * 1.85)),
            treble: 0.22 + 0.52 * Math.abs(Math.sin(t * 3.0) * Math.cos(t * 1.2)),
          });
          speechAnimRef.current = requestAnimationFrame(animateSpeech);
        };

        audio.onplay = () => animateSpeech();
        audio.onended = () => {
          if (speechAnimRef.current !== null) cancelAnimationFrame(speechAnimRef.current);
          speechAnimRef.current = null;
          audioElRef.current = null;
          setAudioBands({ bass: 0, mid: 0, treble: 0 });
          setHudState("idle");
        };
        audio.onerror = () => speakWithBrowserFallback(speechText);

        await audio.play();
      } catch {
        speakWithBrowserFallback(speechText);
      }
    },
    [setHudState, speakWithBrowserFallback, stopSpeech]
  );

  const refreshStatusAndStores = useCallback(async () => {
    try {
      const [statusRes, remRes, memRes] = await Promise.all([
        fetch("/api/status"),
        fetch("/api/reminders"),
        fetch("/api/memories"),
      ]);
      if (statusRes.ok) setRuntimeStatus((await statusRes.json()) as RuntimeStatus);
      if (remRes.ok) {
        const remData = (await remRes.json()) as {
          pending: ReminderItem[];
          due: ReminderItem[];
        };
        setReminders(remData.pending ?? []);
        if (remData.due && remData.due.length > 0) {
          const msg = remData.due.map((r) => `Captain, Reminder: ${r.message}`).join("\n");
          setParticleShape("shield");
          setParticlePhase(phaseRef.current === "dormant" ? "rising" : "alert");
          setCurrentResponse(msg);
          setStatusMessage("Sentinel • Reminder Due");
          void speakResponse(msg);
        }
      }
      if (memRes.ok) {
        const memData = (await memRes.json()) as { items: MemoryItem[] };
        setMemories(memData.items ?? []);
      }
    } catch {
      // Retry next poll
    }
  }, [speakResponse]);

  useEffect(() => {
    void refreshStatusAndStores();
    const id = window.setInterval(() => void refreshStatusAndStores(), 10000);
    return () => window.clearInterval(id);
  }, [refreshStatusAndStores]);

  const submitCommand = useCallback(
    async (rawText: string) => {
      const cleaned = rawText.trim();
      if (!cleaned) return;

      if (WAKE_REGEX.test(cleaned)) {
        const rest = cleaned.replace(WAKE_REGEX, "").replace(/^[,.\-?!\s]+/, "").trim();
        summonParticles();
        setCommandText("");
        setCurrentPrompt(cleaned);
        if (!rest) {
          const greet = "Haanji Captain! DarkShadow active hai, bataiye kya hukum hai?";
          setCurrentResponse(greet);
          window.setTimeout(() => void speakResponse(greet), 1100);
          return;
        }
      }

      if (SLEEP_REGEX.test(cleaned)) {
        setCommandText("");
        setCurrentPrompt(cleaned);
        setCurrentResponse("Theek hai Captain, standby par ja raha hoon.");
        dismissParticles();
        return;
      }

      if (phaseRef.current === "dormant") setParticlePhase("rising");

      stopSpeech();
      setCommandText("");
      setCurrentPrompt(cleaned);
      setSources([]);
      setActionLink(null);
      setSuggestions([]);
      setHudState("processing", "Thinking • DNA Helix");

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: cleaned, privacyMode }),
        });
        const data = (await res.json()) as ChatApiResponse;

        setCurrentResponse(data.displayText || "Captain, response empty mila.");
        setSources(data.sources ?? []);
        setActionLink(data.actionLink ?? null);
        setSuggestions(data.suggestions ?? []);

        if (data.clearHistory) {
          setHistory([]);
        } else {
          setHistory((prev) => [
            {
              id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
              prompt: cleaned,
              response: data.displayText,
              intent: data.intent,
              sources: data.sources ?? [],
              actionLink: data.actionLink,
              modelUsed: data.modelUsed,
              timestamp: new Date().toLocaleTimeString("en-IN", {
                hour: "2-digit",
                minute: "2-digit",
              }),
            },
            ...prev.slice(0, 15),
          ]);
        }

        if (data.reminders) setReminders(data.reminders);

        if (!res.ok || data.error) {
          setHudState("error", "Shield • Alert");
        } else if (voiceEnabledRef.current && data.speechText) {
          void speakResponse(data.speechText);
        } else {
          setHudState("success");
        }

        void refreshStatusAndStores();
      } catch {
        setCurrentResponse(
          "Captain, DarkShadow server se connection nahi ban paya. Kripya dobara try kijiye."
        );
        setHudState("error", "Connection issue");
      }
    },
    [
      dismissParticles,
      privacyMode,
      refreshStatusAndStores,
      setHudState,
      speakResponse,
      stopSpeech,
      summonParticles,
    ]
  );

  const toggleListening = useCallback(async () => {
    if (phaseRef.current === "dormant") summonParticles();

    if (isListeningRef.current) {
      recognitionRef.current?.stop();
      isListeningRef.current = false;
      stopMicMeter();
      setHudState("idle");
      return;
    }

    stopSpeech();

    const SpeechRecCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecCtor) {
      setCurrentResponse(
        "Captain, is browser mein Web Speech Recognition available nahi hai. Typed mode 100% active hai — niche command type kijiye."
      );
      setHudState("error", "Mic unsupported");
      inputRef.current?.focus();
      return;
    }

    // Real-Time 3-Band FFT Microphone Metering (Bass / Mid / Treble)
    try {
      if (navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        micStreamRef.current = stream;
        const audioCtx = new AudioContext();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        const bins = new Uint8Array(analyser.frequencyBinCount);
        const updateFFT = () => {
          if (!isListeningRef.current) {
            void audioCtx.close();
            return;
          }
          analyser.getByteFrequencyData(bins);
          let bSum = 0, mSum = 0, tSum = 0;
          for (let i = 1; i < 8; i++) bSum += bins[i];
          for (let i = 8; i < 36; i++) mSum += bins[i];
          for (let i = 36; i < 96; i++) tSum += bins[i];
          setAudioBands({
            bass: Math.min(1, bSum / (7 * 150)),
            mid: Math.min(1, mSum / (28 * 130)),
            treble: Math.min(1, tSum / (60 * 95)),
          });
          micMeterRafRef.current = requestAnimationFrame(updateFFT);
        };
        micMeterRafRef.current = requestAnimationFrame(updateFFT);
      }
    } catch {
      // Proceed even if analyser fails
    }

    const recognition = new SpeechRecCtor();
    recognition.lang = sttLanguage;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    let finalTranscript = "";
    isListeningRef.current = true;
    recognitionRef.current = recognition;
    setHudState("listening", "Listening • 3-Band FFT Sphere");

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) finalTranscript += text;
        else interim += text;
      }
      const preview = (finalTranscript || interim).trim();
      if (preview) setCurrentPrompt(preview);
    };

    recognition.onerror = (ev) => {
      isListeningRef.current = false;
      stopMicMeter();
      if (ev.error === "not-allowed") {
        setCurrentResponse(
          "Captain, microphone permission deny hui hai. Browser permissions allow kijiye ya typed mode use kijiye."
        );
        setHudState("error", "Mic blocked");
      } else if (ev.error === "no-speech") {
        setHudState("idle", "No speech detected");
      } else {
        setHudState("error", "Voice capture issue");
      }
    };

    recognition.onend = () => {
      isListeningRef.current = false;
      stopMicMeter();
      const spoken = finalTranscript.trim();
      if (spoken) {
        void submitCommand(spoken);
      } else {
        setAssistantState((prev) => (prev === "listening" ? "idle" : prev));
        setStatusMessage((prev) => (prev.startsWith("Listening") ? STATE_TEXT.idle : prev));
      }
    };

    try {
      recognition.start();
    } catch {
      isListeningRef.current = false;
      stopMicMeter();
      setHudState("error", "Mic start failed");
    }
  }, [setHudState, stopMicMeter, stopSpeech, sttLanguage, submitCommand, summonParticles]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isInputFocused =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT";

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "l") {
        e.preventDefault();
        inputRef.current?.focus();
        return;
      }

      if (e.key === "Escape") {
        if (desktopModalOpen) setDesktopModalOpen(false);
        else if (settingsOpen) setSettingsOpen(false);
        else if (remindersOpen) setRemindersOpen(false);
        else if (assistantState === "speaking") stopSpeech();
        else if (isListeningRef.current) void toggleListening();
        else if (phaseRef.current !== "dormant") dismissParticles();
        return;
      }

      if (isInputFocused || settingsOpen || remindersOpen || desktopModalOpen) return;

      if (e.code === "Space") {
        e.preventDefault();
        void toggleListening();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    assistantState,
    desktopModalOpen,
    dismissParticles,
    remindersOpen,
    settingsOpen,
    stopSpeech,
    toggleListening,
  ]);

  const handleCopy = async () => {
    if (!currentResponse.trim()) return;
    try {
      await navigator.clipboard.writeText(currentResponse);
      setCopiedNotice(true);
      setStatusMessage("Copied to clipboard");
      window.setTimeout(() => {
        setCopiedNotice(false);
        setStatusMessage(STATE_TEXT[assistantState]);
      }, 1600);
    } catch {
      // Ignore clipboard failures
    }
  };

  const handleClearChat = async () => {
    stopSpeech();
    await fetch("/api/clear", { method: "POST" });
    setHistory([]);
    setCurrentPrompt("");
    setSources([]);
    setActionLink(null);
    setCurrentResponse("Captain, in-memory conversation context clear kar diya hai.");
    setHudState("idle");
    void refreshStatusAndStores();
  };

  const handleDeleteReminder = async (id: number) => {
    const res = await fetch(`/api/reminders/${id}`, { method: "DELETE" });
    if (res.ok) {
      const data = (await res.json()) as { pending: ReminderItem[] };
      setReminders(data.pending ?? []);
      void refreshStatusAndStores();
    }
  };

  const handleDeleteMemory = async (id: number) => {
    const res = await fetch(`/api/memories/${id}`, { method: "DELETE" });
    if (res.ok) {
      const data = (await res.json()) as { items: MemoryItem[] };
      setMemories(data.items ?? []);
      void refreshStatusAndStores();
    }
  };

  const combinedAudioLevel = Math.min(1, audioBands.bass * 0.4 + audioBands.mid * 0.4 + audioBands.treble * 0.3);

  return (
    <div className="relative h-screen w-screen bg-[#000000] text-[#F8F9FD] flex flex-col overflow-hidden">
      {/* Full-Viewport GPU WebGL2 6,000-Particle Layer (Option B Exact Engine) */}
      <div className="absolute inset-0 z-0">
        <ParticleOrbWebGL
          phase={particlePhase}
          shape={particleShape}
          audioBands={audioBands}
          reducedMotion={reducedMotion}
          onRiseComplete={() => {
            setParticlePhase("listening");
            setStatusMessage("Ready • 6,000 WebGL2 Particles");
          }}
          onDissolveComplete={() => {
            setParticlePhase("dormant");
            setStatusMessage('Standby — Say "Hey Dark Shadow" or Summon');
          }}
          onClick={() => {
            if (particlePhase === "dormant") summonParticles();
            else void toggleListening();
          }}
        />
      </div>

      {/* Top Custom TitleBar */}
      <TitleBar
        pendingReminders={reminders.length}
        privacyMode={privacyMode}
        onOpenReminders={() => {
          void refreshStatusAndStores();
          setRemindersOpen(true);
        }}
        onOpenSettings={() => {
          void refreshStatusAndStores();
          setSettingsOpen(true);
        }}
        onOpenDesktopDownload={() => setDesktopModalOpen(true)}
      />

      {/* 3-Column Panoramic Cyber HUD */}
      <main className="relative z-10 pointer-events-none flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[3fr_4fr_3fr] gap-4 lg:gap-6 px-5 sm:px-8 py-4 overflow-y-auto lg:overflow-hidden">
        {/* Left Column: Captain's Prompt */}
        <section className="flex flex-col min-h-0 py-2 pointer-events-auto">
          <div className="flex items-center gap-2 text-[11px] font-bold tracking-[1.5px] uppercase text-[#80D8FF] mb-3 shrink-0">
            <User className="w-3.5 h-3.5" />
            <span>Captain&apos;s Prompt</span>
          </div>

          <div className="text-[14px] leading-relaxed text-[#80D8FF] whitespace-pre-wrap break-words min-h-[48px] shrink-0">
            {currentPrompt || (
              <span className="text-[#80D8FF]/45 italic text-[13px]">
                Say &ldquo;Hey Dark Shadow&rdquo; or morph shapes below…
              </span>
            )}
          </div>

          {history.length > 1 && (
            <div className="mt-6 pt-4 border-t border-[#181E2C]/60 flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
              <div className="text-[10px] uppercase tracking-[1.4px] text-[#8A90A4]/80 font-semibold">
                Recent Session
              </div>
              {history.slice(1, 8).map((turn) => (
                <button
                  key={turn.id}
                  type="button"
                  onClick={() => {
                    setCurrentPrompt(turn.prompt);
                    setCurrentResponse(turn.response);
                    setSources(turn.sources);
                    setActionLink(turn.actionLink ?? null);
                  }}
                  className="w-full text-left group rounded-lg px-2.5 py-2 hover:bg-[#070A10]/80 transition-colors cursor-pointer"
                >
                  <div className="flex items-center justify-between gap-2 text-[11px] text-[#80D8FF]/75 group-hover:text-[#80D8FF] truncate">
                    <span className="truncate">{turn.prompt}</span>
                    <span className="text-[10px] text-[#8A90A4] shrink-0">
                      {turn.timestamp}
                    </span>
                  </div>
                  <div className="text-[11px] text-[#8A90A4] truncate mt-0.5">
                    {turn.response}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Center Column: Controls floating beneath the 3D Morphing Particle Sphere */}
        <section className="flex flex-col items-center justify-end pb-2 shrink-0 min-h-[260px]">
          <div className="pointer-events-auto flex flex-col items-center gap-2">
            <div
              className="text-[12.5px] font-semibold tracking-[1px] min-h-[22px] transition-colors duration-200 text-center"
              style={{ color: STATE_LABEL_COLOR[assistantState] }}
            >
              {statusMessage}
            </div>

            <AudioWaveform
              state={assistantState}
              audioLevel={combinedAudioLevel}
              reducedMotion={reducedMotion}
            />

            {/* Upgrade #5: Live 3D Shape Morphing Selector */}
            <div className="flex flex-wrap items-center justify-center gap-1.5">
              {SHAPE_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => {
                    if (particlePhase === "dormant") setParticlePhase("rising");
                    setParticleShape(opt.id);
                    setStatusMessage(`Morphed • ${opt.label}`);
                  }}
                  className={`h-[26px] px-2.5 rounded-md text-[10.5px] font-medium border transition-colors cursor-pointer ${
                    particleShape === opt.id && particlePhase !== "dormant"
                      ? "bg-[#765CFF]/25 border-[#765CFF] text-white"
                      : "bg-[#070A10]/80 border-[#181E2C] text-[#8A90A4] hover:text-white hover:border-[#765CFF]/60"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Summon / Sleep Controls */}
            <div className="flex items-center gap-2 pt-0.5">
              <button
                type="button"
                onClick={summonParticles}
                className="inline-flex items-center gap-1.5 h-[30px] px-3.5 rounded-full bg-[#070A10]/90 border border-[#00D2FF]/50 hover:border-[#00D2FF] hover:bg-[#0F1422] text-[11px] font-medium text-[#80D8FF] transition-colors cursor-pointer"
              >
                <Sparkles className="w-3 h-3" />
                <span>Summon (&ldquo;Hey Dark Shadow&rdquo;)</span>
              </button>

              {particlePhase !== "dormant" && (
                <button
                  type="button"
                  onClick={dismissParticles}
                  className="inline-flex items-center gap-1.5 h-[30px] px-3 rounded-full bg-[#070A10]/90 border border-[#181E2C] hover:border-[#765CFF] text-[11px] text-[#8A90A4] hover:text-white transition-colors cursor-pointer"
                >
                  <Moon className="w-3 h-3" />
                  <span>Sleep</span>
                </button>
              )}
            </div>
          </div>
        </section>

        {/* Right Column: DarkShadow's Response & Actions */}
        <section className="flex flex-col min-h-0 py-2 pointer-events-auto">
          <div className="flex items-center justify-between mb-3 shrink-0">
            <div className="flex items-center gap-2 text-[11px] font-bold tracking-[1.5px] uppercase text-[#FFFFFF]">
              <Zap className="w-3.5 h-3.5 text-[#00D2FF]" />
              <span>DarkShadow AI</span>
            </div>
            {history[0]?.modelUsed && (
              <span className="text-[10.5px] text-[#8A90A4] font-mono">
                {history[0].modelUsed}
              </span>
            )}
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-3">
            <div className="text-[14px] leading-[1.55] text-[#FFFFFF] whitespace-pre-wrap break-words select-text">
              {currentResponse}
            </div>

            {sources.length > 0 && (
              <div className="pt-2 space-y-1.5">
                <div className="text-[11px] font-semibold text-[#80D8FF]">
                  Live • {sources.length} verified{" "}
                  {sources.length === 1 ? "source" : "sources"}
                </div>
                <div className="flex flex-col gap-1">
                  {sources.map((src) => (
                    <a
                      key={src.url}
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-[11.5px] text-[#8A90A4] hover:text-[#00D2FF] transition-colors truncate"
                    >
                      <ExternalLink className="w-3 h-3 shrink-0" />
                      <span className="truncate">{src.title}</span>
                    </a>
                  ))}
                </div>
              </div>
            )}

            {actionLink && (
              <div className="pt-1">
                <a
                  href={actionLink.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-[#070A10]/90 border border-[#765CFF]/60 hover:border-[#00D2FF] hover:bg-[#0F1422] text-[12px] font-medium text-[#F8F9FD] transition-colors"
                >
                  <ExternalLink className="w-3.5 h-3.5 text-[#00D2FF]" />
                  <span>{actionLink.label}</span>
                </a>
              </div>
            )}
          </div>

          <div className="pt-3 mt-2 flex flex-wrap items-center gap-2 shrink-0">
            {assistantState === "speaking" ? (
              <button
                type="button"
                onClick={stopSpeech}
                className="inline-flex items-center gap-1.5 h-[32px] px-4 rounded-full bg-[#070A10] border border-[#5A2630] hover:bg-[#3A1720] hover:border-[#FF4560] text-[11px] font-semibold text-[#FF4560] hover:text-white transition-colors cursor-pointer"
              >
                <Square className="w-2.5 h-2.5 fill-current" />
                <span>Stop speaking</span>
              </button>
            ) : (
              <>
                {suggestions.slice(0, 3).map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => void submitCommand(item)}
                    className="h-[30px] px-3 rounded-full bg-[#070A10]/90 border border-[#181E2C] hover:border-[#765CFF] hover:bg-[#0F1422] text-[11px] text-[#8A90A4] hover:text-[#F8F9FD] transition-colors cursor-pointer"
                  >
                    {item}
                  </button>
                ))}

                {currentResponse.trim() && (
                  <button
                    type="button"
                    onClick={() => void handleCopy()}
                    className="inline-flex items-center gap-1 h-[30px] px-3 rounded-full bg-black/50 border border-[#181E2C] hover:border-[#765CFF] text-[11px] text-[#8A90A4] hover:text-[#F8F9FD] transition-colors cursor-pointer"
                  >
                    <Copy className="w-3 h-3" />
                    <span>{copiedNotice ? "Copied" : "Copy"}</span>
                  </button>
                )}

                {currentPrompt.trim() && (
                  <button
                    type="button"
                    onClick={() => void submitCommand(currentPrompt)}
                    className="inline-flex items-center gap-1 h-[30px] px-3 rounded-full bg-black/50 border border-[#181E2C] hover:border-[#765CFF] text-[11px] text-[#8A90A4] hover:text-[#F8F9FD] transition-colors cursor-pointer"
                  >
                    <RotateCcw className="w-3 h-3" />
                    <span>Regenerate</span>
                  </button>
                )}
              </>
            )}
          </div>
        </section>
      </main>

      {/* Bottom Command Input */}
      <footer className="relative z-10 shrink-0 px-4 pb-5 pt-2 flex justify-center">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submitCommand(commandText);
          }}
          className="w-full max-w-[620px] h-[54px] flex items-center gap-2 px-3.5 rounded-[17px] bg-[#0B0F19]/90 border border-[#181E2C] focus-within:border-[#765CFF]/80 backdrop-blur-xs transition-colors"
        >
          <input
            ref={inputRef}
            type="text"
            value={commandText}
            onChange={(e) => setCommandText(e.target.value)}
            placeholder='Type a command or "Hey Dark Shadow"…'
            aria-label="Command"
            className="flex-1 bg-transparent border-none text-[13.5px] text-[#F8F9FD] placeholder:text-[#8A90A4]/75 focus:outline-none px-1"
          />

          {commandText.trim() && (
            <button
              type="submit"
              aria-label="Send command"
              className="flex items-center justify-center w-9 h-9 rounded-full text-[#00D2FF] hover:bg-[#0F1422] transition-colors cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
          )}

          <button
            type="button"
            onClick={() => void toggleListening()}
            aria-label="Use microphone"
            title="Use microphone (Space)"
            className={`flex items-center justify-center w-10 h-10 rounded-full transition-colors cursor-pointer ${
              assistantState === "listening"
                ? "bg-[#765CFF]/25 text-[#00D2FF]"
                : "text-[#A9B0C5] hover:bg-[#0F1422] hover:text-white"
            }`}
          >
            {assistantState === "listening" ? (
              <MicOff className="w-[18px] h-[18px]" />
            ) : (
              <Mic className="w-[18px] h-[18px]" />
            )}
          </button>
        </form>
      </footer>

      <DesktopExportModal
        open={desktopModalOpen}
        onClose={() => setDesktopModalOpen(false)}
      />

      <ControlCenterModal
        open={settingsOpen}
        voiceEnabled={voiceEnabled}
        reducedMotion={reducedMotion}
        privacyMode={privacyMode}
        sttLanguage={sttLanguage}
        status={runtimeStatus}
        onClose={() => setSettingsOpen(false)}
        onApply={(prefs) => {
          setVoiceEnabled(prefs.voiceEnabled);
          setReducedMotion(prefs.reducedMotion);
          setPrivacyMode(prefs.privacyMode);
          setSttLanguage(prefs.sttLanguage);
          if (!prefs.voiceEnabled) stopSpeech();
        }}
        onClearChat={() => void handleClearChat()}
      />

      <RemindersModal
        open={remindersOpen}
        reminders={reminders}
        memories={memories}
        privacyMode={privacyMode}
        onClose={() => setRemindersOpen(false)}
        onDeleteReminder={(id) => void handleDeleteReminder(id)}
        onDeleteMemory={(id) => void handleDeleteMemory(id)}
      />
    </div>
  );
}
