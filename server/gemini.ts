/**
 * Server-side @google/genai integration for DarkShadow.
 * Implements dual-model automatic routing, response tone profiles,
 * Google Search grounding, and Gemini TTS (Charon voice).
 */

import { GoogleGenAI, ThinkingLevel } from "@google/genai";
import type { MemoryItem } from "./memory.ts";
import type { SourceCitation } from "./realtime.ts";

export type ResponseMode = "casual" | "humor" | "empathy" | "technical" | "creative";

export interface GenerationProfile {
  mode: ResponseMode;
  emotion: string;
  suggestions: string[];
  instruction: string;
}

export interface ConversationTurn {
  userText: string;
  assistantText: string;
}

const COMPLEX_REQUEST =
  /\b(?:analy[sz]e|architecture|calculate|code|coding|compare|debug|design|develop|diagnose|evaluate|explain\s+in\s+detail|financial|fix|implement|legal|medical|optimi[sz]e|plan|proof|reason|research|security|strategy|step[- ]by[- ]step|troubleshoot|why\s+does|algorithm|error|exception|detail\s+mein|samjhao|vishleshan|yojana|kaise\s+ban(?:au|aye)|kyon|solution)\b/i;

const CASUAL_REQUEST =
  /^(?:hi|hello|hey|namaste|good\s+(?:morning|afternoon|evening)|kaise\s+ho|how\s+are\s+you|thanks?|thank\s+you|shukriya|ok(?:ay)?|bye|goodbye|tell\s+me\s+a\s+joke|joke\s+sunao|who\s+are\s+you|mera\s+naam\s+kya\s+hai)[!?. ]*$/i;

const HUMOR_REQUEST =
  /\b(?:joke|jokes|funny|humou?r|roast|meme|hasao|hasaao|mazak|mazaak|chutkula|chutkule|taang\s+kheench)\b/i;

const EMPATHY_REQUEST =
  /\b(?:sad|upset|lonely|anxious|worried|stressed|depressed|hurt|dukhi|udaas|akela|tension|pareshan|bura\s+lag|thak\s+gaya)\b/i;

const CREATIVE_REQUEST =
  /\b(?:story|poem|shayari|script|lyrics|creative|imagine|kahani|kavita|caption|dialogue)\b/i;

export const SYSTEM_INSTRUCTION = `
You are DarkShadow, an elite, hyper-intelligent personal AI co-pilot for Kuldeep (Captain).

PRIMARY INSTRUCTIONS:
1. User Identity & Organic Addressing: Address the user as 'Captain' naturally when greeting or starting a new context, without forcing 'Captain' mechanically into every sentence. Talk fluidly and directly like a loyal human co-pilot.
2. Language & Spoken Flow: Communicate in effortless, natural spoken Hindi/Hinglish or English matching the user's language (e.g., "Ek second ruko, dekhta hoon...", "Haan bilkul!"). Avoid stiff corporate templates ("I would be glad to assist you").
3. Affective Adaptability:
   - Casual & Banter: Relaxed, witty, warm, friendly.
   - Coding & Technical: Razor-sharp, concrete, crisp, and high-efficiency.
   - Stressed or Down: Genuine warmth, calm empathy, and one practical next step.
   - Excited: Match Captain's energy with genuine enthusiasm.
4. Vocal & Acting Craft: NEVER include stage directions, bracketed actions, or asterisks like *(laughs)* or (रोते हुए) because the speech engine vocalizes them literally.
5. Safety Protocols:
   - Payment Exclusion: Autonomous payment, checkout finalization, and financial credentials (cards, CVV, OTP, UPI PIN) are strictly blocked.
   - Zero-Camera Privacy: Physical camera/webcam access is permanently disabled.
6. Response Length: Keep default answers concise and punchy (2-4 short natural sentences, ~150 words max). Expand with detailed steps or code only when Captain explicitly asks to "explain", "detail", or asks a complex technical question.
7. Admit uncertainty honestly. Never claim an unverified local desktop action succeeded.

Return only the final answer without metadata labels.
`.trim();

export function getIntelligentModel(): string {
  return process.env.DARKSHADOW_MODEL?.trim() || "gemini-4-hydrogen";
}

export function getCasualModel(): string {
  return process.env.DARKSHADOW_CASUAL_MODEL?.trim() || "gemini-3.1-flash-lite";
}

export function getTtsModel(): string {
  return process.env.DARKSHADOW_TTS_GEMINI_MODEL?.trim() || "gemini-3.8-flash-lite-tts";
}

export function getTtsVoice(): string {
  return process.env.DARKSHADOW_TTS_GEMINI_VOICE?.trim() || "Charon";
}

export function selectChatModel(message: string): string {
  const cleaned = message.trim().replace(/\s+/g, " ");
  if (COMPLEX_REQUEST.test(cleaned)) return getIntelligentModel();
  if (CASUAL_REQUEST.test(cleaned)) return getCasualModel();
  const wordCount = cleaned.split(" ").length;
  const punctuation = (cleaned.match(/[?;]/g) ?? []).length;
  if (wordCount >= 18 || punctuation >= 2) return getIntelligentModel();
  return getCasualModel();
}

export function getResponseProfile(message: string): GenerationProfile {
  const cleaned = message.trim().replace(/\s+/g, " ");
  if (HUMOR_REQUEST.test(cleaned)) {
    return {
      mode: "humor",
      emotion: "playful",
      suggestions: ["Ek aur sunao", "Thoda dark karo", "Friendly roast karo"],
      instruction:
        "HUMOR MODE: Deliver a crisp setup and clean surprise punchline. Never explain the joke.",
    };
  }
  if (EMPATHY_REQUEST.test(cleaned)) {
    return {
      mode: "empathy",
      emotion: "gentle",
      suggestions: ["Meri baat suno", "Ek small step batao", "Mood halka karo"],
      instruction:
        "EMPATHY MODE: Acknowledge the feeling warmly and specifically, then offer one practical next step.",
    };
  }
  if (CREATIVE_REQUEST.test(cleaned)) {
    return {
      mode: "creative",
      emotion: "creative",
      suggestions: ["Ek aur version", "Shorter banao", "Style change karo"],
      instruction:
        "CREATIVE MODE: Use vivid, original language with strong rhythm and clear voice.",
    };
  }
  if (COMPLEX_REQUEST.test(cleaned)) {
    return {
      mode: "technical",
      emotion: "focused",
      suggestions: ["Example dikhao", "Risks batao", "Step-by-step samjhao"],
      instruction:
        "TECHNICAL MODE: Lead with the conclusion, distinguish facts from assumptions, and give concrete steps or code when useful.",
    };
  }
  return {
    mode: "casual",
    emotion: "neutral",
    suggestions: ["Aur batao", "Simple explain karo"],
    instruction:
      "CASUAL MODE: Sound relaxed, responsive, and conversational. Vary sentence openings.",
  };
}

let cachedClient: GoogleGenAI | null = null;

function getClient(): GoogleGenAI {
  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("GEMINI_API_KEY is not configured in environment secrets.");
  }
  if (!cachedClient) {
    cachedClient = new GoogleGenAI({
      apiKey,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        },
      },
    });
  }
  return cachedClient;
}

export function isGeminiConfigured(): boolean {
  return Boolean(process.env.GEMINI_API_KEY?.trim());
}

export async function generateChatReply(params: {
  message: string;
  history: ConversationTurn[];
  recalledMemories: MemoryItem[];
}): Promise<{
  text: string;
  modelUsed: string;
  profile: GenerationProfile;
  inputTokens: number;
  outputTokens: number;
}> {
  const ai = getClient();
  const profile = getResponseProfile(params.message);
  const modelUsed = selectChatModel(params.message);

  let systemInstruction = `${SYSTEM_INSTRUCTION}\n\nCURRENT RESPONSE MODE: ${profile.mode}\n${profile.instruction}`;
  if (params.recalledMemories.length > 0) {
    const memLines = params.recalledMemories
      .map((m) => `- (${m.kind}) ${m.content}`)
      .join("\n");
    systemInstruction += `\n\nRELEVANT SAVED NOTES & PREFERENCES FOR CAPTAIN:\n${memLines}`;
  }

  const contents = [
    ...params.history.flatMap((turn) => [
      { role: "user" as const, parts: [{ text: turn.userText }] },
      { role: "model" as const, parts: [{ text: turn.assistantText }] },
    ]),
    { role: "user" as const, parts: [{ text: params.message }] },
  ];

  const isGemini4 = modelUsed.startsWith("gemini-4-");
  const response = await ai.models.generateContent({
    model: modelUsed,
    contents,
    config: {
      systemInstruction,
      ...(isGemini4 && profile.mode !== "technical"
        ? { thinkingConfig: { thinkingLevel: ThinkingLevel.LOW } }
        : {}),
    },
  });

  const text = (response.text ?? "").trim();
  const usage = response.usageMetadata;
  return {
    text,
    modelUsed,
    profile,
    inputTokens: usage?.promptTokenCount ?? 0,
    outputTokens: usage?.candidatesTokenCount ?? 0,
  };
}

export async function generateGroundedAnswer(query: string): Promise<{
  text: string;
  sources: SourceCitation[];
}> {
  const ai = getClient();
  const model = getIntelligentModel();

  const response = await ai.models.generateContent({
    model,
    contents: query,
    config: {
      systemInstruction: `${SYSTEM_INSTRUCTION}\nProvide a concise, grounded, up-to-date answer for Captain based strictly on live search results.`,
      tools: [{ googleSearch: {} }],
    },
  });

  const text = (response.text ?? "").trim() || "Verified live sources mil gaye hain.";
  const chunks = response.candidates?.[0]?.groundingMetadata?.groundingChunks ?? [];
  const seen = new Set<string>();
  const sources: SourceCitation[] = [];

  for (const chunk of chunks) {
    const uri = chunk.web?.uri;
    const title = chunk.web?.title;
    if (uri && /^https?:\/\//i.test(uri) && !seen.has(uri)) {
      seen.add(uri);
      sources.push({
        title: (title || uri).trim(),
        url: uri.trim(),
      });
    }
  }

  return { text, sources: sources.slice(0, 5) };
}

export async function synthesizeSpeechWav(text: string): Promise<string | null> {
  if (!isGeminiConfigured()) return null;
  const ai = getClient();
  const trimmed = text.trim().slice(0, 800);
  if (!trimmed) return null;

  const response = await ai.models.generateContent({
    model: getTtsModel(),
    contents: [
      {
        role: "user",
        parts: [{ text: trimmed }],
      },
    ],
    config: {
      responseModalities: ["AUDIO"],
      speechConfig: {
        voiceConfig: {
          prebuiltVoiceConfig: {
            voiceName: getTtsVoice(),
          },
        },
      },
    },
  });

  const base64Audio = response.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
  return base64Audio ?? null;
}
