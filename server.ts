/**
 * DarkShadow Web Server (Express + Vite dev middleware / static production server)
 * Listens on 0.0.0.0:3000.
 */

import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import type { Request, Response } from "express";
import { buildZipBuffer } from "./server/zip.ts";
import { handleDeterministicAutomation } from "./server/automation.ts";
import {
  generateChatReply,
  getCasualModel,
  getIntelligentModel,
  getTtsModel,
  getTtsVoice,
  isGeminiConfigured,
  synthesizeSpeechWav,
} from "./server/gemini.ts";
import type { ConversationTurn } from "./server/gemini.ts";
import { handleMemoryCommand, MemoryStore } from "./server/memory.ts";
import { answerFreshQuery, requiresFreshInformation } from "./server/realtime.ts";
import {
  CAMERA_BLOCKED_MESSAGE,
  ensureCaptainAddress,
  isDangerousTerminalCommand,
  isPaymentOrCheckoutIntent,
  isPhysicalCameraIntent,
  PAYMENT_BLOCKED_MESSAGE,
  speechFriendlyText,
} from "./server/safety.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT || 3000);
const MAX_HISTORY_TURNS = Math.max(2, Number(process.env.DARKSHADOW_HISTORY_TURNS || 8));

const memoryStore = new MemoryStore();
let conversationHistory: ConversationTurn[] = [];
let lastModelUsed: string | null = null;
let totalInputTokens = 0;
let totalOutputTokens = 0;

function buildHelpText(): string {
  return [
    "Captain, DarkShadow commands:",
    "• /help — show available commands and capabilities",
    "• /status — show safe runtime, model, search & shield status",
    "• /clear — clear bounded in-memory conversation history",
    "• /remember <text> or 'remember this: ...' — save one explicit preference",
    "• /note <text> or 'note: ...' — save one explicit note",
    "• /memories & /notes — list saved items",
    "• /forget <id> — delete one saved item",
    "• remind me tomorrow at 09:00 to ... — schedule a reminder",
    "• /reminders & /delete-reminder <id> — manage pending reminders",
    "• Web actions: current time, today's date, system status, google search <q>, play <q> on YouTube, open <site.com>",
  ].join("\n");
}

function buildStatusSummary(): string {
  const geminiReady = isGeminiConfigured() ? "connected" : "missing key";
  const searchMode = process.env.TAVILY_API_KEY?.trim()
    ? "Tavily Search + Gemini Grounding"
    : "Gemini Google Search Grounding";
  return [
    `Models: intelligent=${getIntelligentModel()} | casual=${getCasualModel()}`,
    `Last model: ${lastModelUsed ?? "none yet"} | Tokens: ${totalInputTokens + totalOutputTokens} (in=${totalInputTokens}, out=${totalOutputTokens})`,
    `Gemini API: ${geminiReady} | Live info: ${searchMode}`,
    `Voice TTS: ${getTtsModel()} (${getTtsVoice()}) + Browser Web Speech fallback`,
    `History turns: ${conversationHistory.length}/${MAX_HISTORY_TURNS} | Saved memories: ${memoryStore.listItems().length} | Pending reminders: ${memoryStore.listPendingReminders().length}`,
    "Shields: Payment Exclusion ACTIVE | Zero-Camera Privacy ACTIVE | Dangerous Shell Shield ACTIVE",
  ].join("\n");
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: "1mb" }));

  // Serve DarkShadow's core orb GIF & public assets
  app.use("/assets", express.static(path.join(__dirname, "public", "assets")));

  // Download endpoints for the Option B Windows 11 Python + WebGL2 Desktop Suite (all 5 upgrades)
  const desktopFiles: Record<string, string> = {
    "darkshadow_desktop.py": "text/x-python; charset=utf-8",
    "particle_engine.html": "text/html; charset=utf-8",
    "voice_engine.py": "text/x-python; charset=utf-8",
    "windows_tools.py": "text/x-python; charset=utf-8",
    "memory_engine.py": "text/x-python; charset=utf-8",
    "sentinel_monitor.py": "text/x-python; charset=utf-8",
    "windows_requirements.txt": "text/plain; charset=utf-8",
    "run_darkshadow_desktop.bat": "application/x-bat; charset=utf-8",
    ".env.example": "text/plain; charset=utf-8",
  };

  app.get("/api/desktop-files/DarkShadow-Desktop-Python.zip", (_req: Request, res: Response) => {
    const dir = path.join(__dirname, "desktop_python");
    const entries = Object.keys(desktopFiles)
      .filter((name) => fs.existsSync(path.join(dir, name)))
      .map((name) => ({
        name: `DarkShadow-Desktop/${name}`,
        data: fs.readFileSync(path.join(dir, name)),
      }));
    const zip = buildZipBuffer(entries);
    res.setHeader("Content-Type", "application/zip");
    res.setHeader("Content-Disposition", 'attachment; filename="DarkShadow-Desktop-Python.zip"');
    res.send(zip);
  });

  app.get("/api/desktop-files/:filename", (req: Request, res: Response) => {
    const filename = String(req.params.filename || "");
    const contentType = desktopFiles[filename];
    if (!contentType) {
      res.status(404).json({ error: "File not found" });
      return;
    }
    const filePath = path.join(__dirname, "desktop_python", filename);
    res.setHeader("Content-Type", contentType);
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    res.sendFile(filePath);
  });

  app.get("/api/status", (_req: Request, res: Response) => {
    res.json({
      geminiConfigured: isGeminiConfigured(),
      intelligentModel: getIntelligentModel(),
      casualModel: getCasualModel(),
      lastModelUsed,
      ttsModel: getTtsModel(),
      ttsVoice: getTtsVoice(),
      searchMode: process.env.TAVILY_API_KEY?.trim() ? "tavily" : "gemini_grounding",
      historyTurns: conversationHistory.length,
      maxHistoryTurns: MAX_HISTORY_TURNS,
      memoryCount: memoryStore.listItems().length,
      pendingReminderCount: memoryStore.listPendingReminders().length,
      summary: buildStatusSummary(),
    });
  });

  app.get("/api/reminders", (_req: Request, res: Response) => {
    const due = memoryStore.popDueReminders();
    const pending = memoryStore.listPendingReminders();
    res.json({ pending, due });
  });

  app.delete("/api/reminders/:id", (req: Request, res: Response) => {
    const id = Number.parseInt(String(req.params.id), 10);
    if (Number.isNaN(id)) {
      res.status(400).json({ error: "Invalid reminder id" });
      return;
    }
    const result = memoryStore.deleteReminder(id);
    res.json({ result, pending: memoryStore.listPendingReminders() });
  });

  app.get("/api/memories", (_req: Request, res: Response) => {
    res.json({ items: memoryStore.listItems() });
  });

  app.delete("/api/memories/:id", (req: Request, res: Response) => {
    const id = Number.parseInt(String(req.params.id), 10);
    if (Number.isNaN(id)) {
      res.status(400).json({ error: "Invalid memory id" });
      return;
    }
    const result = memoryStore.forgetItem(id);
    res.json({ result, items: memoryStore.listItems() });
  });

  app.post("/api/clear", (_req: Request, res: Response) => {
    conversationHistory = [];
    res.json({
      displayText: "Captain, in-memory conversation context clear kar diya hai.",
      speechText: speechFriendlyText("Captain, in-memory conversation context clear kar diya hai."),
      intent: "clear",
    });
  });

  app.post("/api/tts", async (req: Request, res: Response) => {
    const text = typeof req.body?.text === "string" ? req.body.text.trim() : "";
    if (!text) {
      res.status(400).json({ error: "Text is required" });
      return;
    }
    try {
      const audioBase64 = await synthesizeSpeechWav(text);
      if (!audioBase64) {
        res.status(503).json({ error: "Cloud TTS unavailable" });
        return;
      }
      res.json({ audioBase64, mimeType: "audio/wav", voice: getTtsVoice() });
    } catch (err) {
      const detail = err instanceof Error ? err.message : "TTS failed";
      res.status(502).json({ error: detail });
    }
  });

  app.post("/api/chat", async (req: Request, res: Response) => {
    const rawMessage = typeof req.body?.message === "string" ? req.body.message.trim() : "";
    const privacyMode = Boolean(req.body?.privacyMode);

    if (!rawMessage) {
      res.status(400).json({ error: "Message is required" });
      return;
    }

    // 1. Hard Safety Shields (zero LLM tokens spent)
    if (isPaymentOrCheckoutIntent(rawMessage)) {
      const displayText = ensureCaptainAddress(PAYMENT_BLOCKED_MESSAGE);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "payment_blocked",
        emotion: "serious",
        suggestions: ["Compare features instead", "Show /help"],
        sources: [],
        error: "payment_blocked",
      });
      return;
    }

    if (isPhysicalCameraIntent(rawMessage)) {
      const displayText = ensureCaptainAddress(CAMERA_BLOCKED_MESSAGE);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "camera_blocked",
        emotion: "serious",
        suggestions: ["Show /status", "Show /help"],
        sources: [],
        error: "camera_blocked",
      });
      return;
    }

    const terminalCheck = isDangerousTerminalCommand(rawMessage);
    if (terminalCheck.blocked) {
      const displayText = ensureCaptainAddress(terminalCheck.reason);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "security_blocked",
        emotion: "serious",
        suggestions: [],
        sources: [],
        error: "security_blocked",
      });
      return;
    }

    // 2. Core Slash Commands
    const lower = rawMessage.toLowerCase();
    if (lower === "/help") {
      const displayText = buildHelpText();
      res.json({
        displayText,
        speechText: speechFriendlyText("Captain, commands list screen par dikha di hai."),
        intent: "help",
        emotion: "neutral",
        suggestions: ["/status", "/memories", "/reminders"],
        sources: [],
      });
      return;
    }

    if (lower === "/clear") {
      conversationHistory = [];
      const displayText = "Captain, in-memory conversation history clear kar di hai.";
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "clear",
        emotion: "neutral",
        suggestions: ["Namaste DarkShadow", "/status"],
        sources: [],
        clearHistory: true,
      });
      return;
    }

    if (lower === "/status") {
      const displayText = ensureCaptainAddress(buildStatusSummary());
      res.json({
        displayText,
        speechText: speechFriendlyText("Captain, DarkShadow status report ready hai."),
        intent: "status",
        emotion: "neutral",
        suggestions: ["/help", "/reminders"],
        sources: [],
      });
      return;
    }

    if (lower === "/mode") {
      const displayText =
        "Captain, aap DarkShadow Web HUD mein hain — typed aur push-to-talk voice dono active hain. Space dabakar ya Orb click karke bol sakte hain.";
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "mode",
        emotion: "neutral",
        suggestions: ["/status", "/help"],
        sources: [],
      });
      return;
    }

    // 3. Deterministic Memory, Notes & Reminders
    const activeMemory = privacyMode ? null : memoryStore;
    const memoryRes = handleMemoryCommand(rawMessage, activeMemory);
    if (memoryRes) {
      const displayText = ensureCaptainAddress(memoryRes.message);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: memoryRes.action,
        emotion: memoryRes.success ? "neutral" : "serious",
        suggestions: memoryRes.action === "remind" ? ["/reminders"] : ["/memories", "/reminders"],
        sources: [],
        reminders: memoryStore.listPendingReminders(),
        error: memoryRes.error,
      });
      return;
    }

    // 4. Deterministic Safe Automation
    const autoRes = handleDeterministicAutomation(rawMessage);
    if (autoRes) {
      const displayText = ensureCaptainAddress(autoRes.message);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: autoRes.action,
        emotion: autoRes.success ? "neutral" : "serious",
        suggestions: [],
        sources: [],
        actionLink: autoRes.actionLink,
        error: autoRes.error,
      });
      return;
    }

    // Model-info quick deterministic query (matches chatbot.py)
    if (
      /\b(?:which|what|kaun\s*sa|kaunsa|konsa)\b.*\bmodel\b|\bmodel\b.*\b(?:use|using|chala|kar\s+rahe)\b/i.test(
        rawMessage
      )
    ) {
      const activeM = lastModelUsed ?? getIntelligentModel();
      const displayText = `Captain, main abhi ${activeM} model use kar raha hoon. intelligent=${getIntelligentModel()} | casual=${getCasualModel()} | tokens=${totalInputTokens + totalOutputTokens} (in=${totalInputTokens}, out=${totalOutputTokens}).`;
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "status",
        emotion: "neutral",
        suggestions: ["/status"],
        sources: [],
      });
      return;
    }

    // 5. Fresh Information Routing (Tavily or Gemini Google Search Grounding)
    if (!isGeminiConfigured() && !process.env.TAVILY_API_KEY?.trim()) {
      const displayText =
        "Captain, GEMINI_API_KEY configured nahi mila. Settings > Secrets mein apni Gemini API key check kijiye; local commands (/help, /status, notes, reminders, time) tab tak available rahenge.";
      res.status(503).json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "configuration",
        emotion: "serious",
        suggestions: ["/help", "/status"],
        sources: [],
        error: "missing_api_key",
      });
      return;
    }

    try {
      if (requiresFreshInformation(rawMessage)) {
        const fresh = await answerFreshQuery(rawMessage);
        conversationHistory.push({ userText: rawMessage, assistantText: fresh.displayText });
        if (conversationHistory.length > MAX_HISTORY_TURNS) {
          conversationHistory = conversationHistory.slice(-MAX_HISTORY_TURNS);
        }
        res.json({
          displayText: fresh.displayText,
          speechText: fresh.speechText,
          intent: fresh.intent,
          emotion: "neutral",
          suggestions: ["Aur detail batao", "Latest update check karo"],
          sources: fresh.sources,
          modelUsed: fresh.provider === "tavily" ? "tavily-search" : getIntelligentModel(),
        });
        return;
      }

      // 6. Dual-Model Conversational Gemini Reply
      const recalled = activeMemory ? activeMemory.recallRelevant(rawMessage, 3) : [];
      const reply = await generateChatReply({
        message: rawMessage,
        history: conversationHistory,
        recalledMemories: recalled,
      });

      const displayText = ensureCaptainAddress(reply.text);
      lastModelUsed = reply.modelUsed;
      totalInputTokens += reply.inputTokens;
      totalOutputTokens += reply.outputTokens;

      conversationHistory.push({ userText: rawMessage, assistantText: displayText });
      if (conversationHistory.length > MAX_HISTORY_TURNS) {
        conversationHistory = conversationHistory.slice(-MAX_HISTORY_TURNS);
      }

      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: `chat_${reply.profile.mode}`,
        emotion: reply.profile.emotion,
        suggestions: reply.profile.suggestions,
        sources: [],
        modelUsed: reply.modelUsed,
      });
    } catch (err) {
      const rawError = err instanceof Error ? err.message : String(err);
      let friendly =
        "Captain, AI engine se connect karte waqt error aaya. Kripya thodi der baad dobara try kijiye.";
      if (/API_KEY_INVALID|PERMISSION_DENIED|403|401/i.test(rawError)) {
        friendly =
          "Captain, Gemini API key invalid ya unauthorized lag rahi hai. Kripya Settings > Secrets panel mein key check kijiye.";
      } else if (/RESOURCE_EXHAUSTED|429/i.test(rawError)) {
        friendly =
          "Captain, Gemini API rate limit hit ho gayi hai. Ek minute ruk kar dobara try kijiye.";
      }
      res.status(502).json({
        displayText: friendly,
        speechText: speechFriendlyText(friendly),
        intent: "error",
        emotion: "serious",
        suggestions: ["Retry"],
        sources: [],
        error: rawError,
      });
    }
  });

  // Frontend middleware (Vite in dev, dist/ static in production)
  if (process.env.NODE_ENV === "production") {
    const distDir = path.join(__dirname, "dist");
    app.use(express.static(distDir));
    app.get("*", (_req: Request, res: Response) => {
      res.sendFile(path.join(distDir, "index.html"));
    });
  } else {
    const { createServer: createViteServer } = await import("vite");
    const vite = await createViteServer({
      server: { middlewareMode: true, hmr: false },
      appType: "spa",
    });
    app.use(vite.middlewares);
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`DarkShadow Web Server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error("Failed to start DarkShadow server:", err);
  process.exit(1);
});
