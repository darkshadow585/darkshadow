/**
 * Fresh-information routing backed by Tavily Search (when TAVILY_API_KEY is set)
 * with automatic fallback to Gemini Google Search Grounding (gemini-4-hydrogen).
 * Ported from DarkShadow realtimeinfo.py.
 */

import { generateGroundedAnswer } from "./gemini.ts";
import { ensureCaptainAddress, speechFriendlyText } from "./safety.ts";

export interface SourceCitation {
  title: string;
  url: string;
}

export interface RealtimeAnswer {
  displayText: string;
  speechText: string;
  intent: string;
  sources: SourceCitation[];
  provider: "tavily" | "gemini_grounding";
  error?: string;
}

const FRESH_TERMS = [
  "latest", "today", "tonight", "current", "currently", "recent",
  "right now", "this week", "this month", "tomorrow", "yesterday",
  "abhi", "aaj", "kal", "taaza", "taza", "आज", "अभी", "कल",
  "ताज़ा", "ताजा", "news", "headline", "breaking", "khabar",
  "samachar", "खबर", "समाचार", "politics", "political", "election",
  "president", "prime minister", "chief minister", "government",
  "minister", "chunav", "चुनाव", "राष्ट्रपति", "प्रधानमंत्री",
  "मुख्यमंत्री", "weather", "forecast", "temperature", "rainfall",
  "mausam", "baarish", "barish", "मौसम", "बारिश", "price", "cost",
  "exchange rate", "stock", "share market", "crypto", "bitcoin",
  "gold rate", "silver rate", "petrol", "diesel", "daam", "bhaav",
  "कीमत", "दाम", "भाव", "score", "fixture", "schedule", "standings",
  "points table", "match result", "ipl", "cricket match",
  "football match", "स्कोर", "मैच", "कार्यक्रम", "version",
  "release date", "software update",
];

const MAPS_TERMS = [
  "near me", "nearby", "paas", "hotel", "hotels", "restaurant", "restaurants",
  "cafe", "cafes", "hospital", "hospitals", "petrol pump", "ev charging",
  "gas station", "route", "direction", "directions", "rashta", "rasta",
  "distance", "kahan hai", "kidhar hai", "location", "map", "maps",
  "dhaba", "cinema", "theatre", "theater", "mall", "railway station",
  "bus stand", "airport", "navigate", "traffic",
];

function containsTerm(text: string, term: string): boolean {
  if (/[^\u0000-\u007f]/.test(term)) {
    return text.includes(term);
  }
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<!\\w)${escaped}(?!\\w)`, "i").test(text);
}

export function requiresFreshInformation(query: string): boolean {
  const normalized = query.toLowerCase().trim().replace(/\s+/g, " ");
  if (!normalized) return false;
  if (
    /\b(what|which|kaun|konsa|kaunsa)\b.*\b(model|api|assistant)\b|\b(model|api)\b.*\b(use|using|chala|kar rahe|status)\b|\b(tum|aap|you)\b.*\b(kaun|who)\b/i.test(
      normalized
    )
  ) {
    return false;
  }
  return (
    FRESH_TERMS.some((term) => containsTerm(normalized, term)) ||
    MAPS_TERMS.some((term) => containsTerm(normalized, term))
  );
}

function topicForQuery(query: string): "finance" | "news" | "general" {
  const lower = query.toLowerCase();
  if (/(stock|share market|crypto|bitcoin|gold rate|finance)/.test(lower)) return "finance";
  if (/(news|headline|breaking|khabar|samachar|election)/.test(lower)) return "news";
  return "general";
}

const cache = new Map<string, { expiresAt: number; value: RealtimeAnswer }>();

export async function answerFreshQuery(query: string): Promise<RealtimeAnswer> {
  const cacheKey = query.toLowerCase().trim().replace(/\s+/g, " ");
  const ttlMs = Number(process.env.DARKSHADOW_REALTIME_CACHE_SECONDS || 300) * 1000;
  const cached = cache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.value;
  }

  const tavilyKey = process.env.TAVILY_API_KEY?.trim();
  if (tavilyKey) {
    try {
      const response = await fetch("https://api.tavily.com/search", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${tavilyKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          search_depth: process.env.DARKSHADOW_TAVILY_SEARCH_DEPTH || "basic",
          max_results: Number(process.env.DARKSHADOW_TAVILY_MAX_RESULTS || 5),
          topic: topicForQuery(query),
          include_answer: "basic",
          include_raw_content: false,
          include_images: false,
        }),
      });
      if (response.ok) {
        const data = (await response.json()) as {
          answer?: string;
          results?: Array<{ title?: string; url?: string; content?: string }>;
        };
        const sources: SourceCitation[] = (data.results ?? [])
          .filter((r) => typeof r.url === "string" && /^https?:\/\//i.test(r.url))
          .slice(0, 5)
          .map((r) => ({
            title: (r.title || r.url || "Source").trim(),
            url: r.url!.trim(),
          }));

        if (sources.length > 0) {
          const rawText =
            data.answer?.trim() ||
            data.results?.[0]?.content?.trim() ||
            "Verified live sources mil gaye hain.";
          const displayText = ensureCaptainAddress(rawText);
          const result: RealtimeAnswer = {
            displayText,
            speechText: speechFriendlyText(displayText),
            intent: "realtime_info",
            sources,
            provider: "tavily",
          };
          cache.set(cacheKey, { expiresAt: Date.now() + ttlMs, value: result });
          return result;
        }
      }
    } catch {
      // Fall through to Gemini Search Grounding below
    }
  }

  // Fallback to Gemini Google Search Grounding so live info works out-of-the-box
  const grounded = await generateGroundedAnswer(query);
  const displayText = ensureCaptainAddress(grounded.text);
  const result: RealtimeAnswer = {
    displayText,
    speechText: speechFriendlyText(displayText),
    intent: "realtime_info",
    sources: grounded.sources,
    provider: "gemini_grounding",
  };
  if (grounded.sources.length > 0) {
    cache.set(cacheKey, { expiresAt: Date.now() + ttlMs, value: result });
  }
  return result;
}
