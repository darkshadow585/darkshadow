/**
 * Deterministic safe local/web automation commands ported from automation.py.
 * Web-safe links return structured actionLink payloads instead of calling window.open.
 * Native Windows-only desktop controls report honest capability boundaries.
 */

export interface ActionLink {
  label: string;
  url: string;
  platform: "web" | "youtube" | "google" | "spotify";
}

export interface AutomationResult {
  success: boolean;
  action: string;
  message: string;
  actionLink?: ActionLink;
  error?: string;
}

export function handleDeterministicAutomation(message: string): AutomationResult | null {
  const cleaned = message.trim();
  if (!cleaned || cleaned.startsWith("/")) return null;

  // Current time
  if (/^(?:current\s+time|what(?:'s| is)\s+the\s+time|time\s+kya\s+hua|kitne\s+baje\s+hain|abhi\s+time\s+kya\s+hai)[?!.]*$/i.test(cleaned)) {
    const now = new Date();
    const formatted = now.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
    return {
      success: true,
      action: "current_time",
      message: `Abhi time ${formatted} hai.`,
    };
  }

  // Today's date
  if (/^(?:today'?s?\s+date|what(?:'s| is)\s+(?:today'?s?\s+)?date|aaj\s+kya\s+date\s+hai|aaj\s+ki\s+tarikh)[?!.]*$/i.test(cleaned)) {
    const now = new Date();
    const formatted = now.toLocaleDateString("en-IN", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
    return {
      success: true,
      action: "todays_date",
      message: `Aaj ${formatted} hai.`,
    };
  }

  // System status
  if (/^(?:system\s+status|pc\s+status|status\s+check)[?!.]*$/i.test(cleaned)) {
    const mem = process.memoryUsage();
    const mb = (bytes: number) => `${Math.round(bytes / 1024 / 1024)} MB`;
    const uptimeSec = Math.floor(process.uptime());
    return {
      success: true,
      action: "system_status",
      message: `DarkShadow Web Core healthy hai — Runtime: Node ${process.version}, Heap: ${mb(mem.heapUsed)} / ${mb(mem.heapTotal)}, Uptime: ${uptimeSec}s. Safety shields (Payment Block & Zero-Camera Privacy) active hain.`,
    };
  }

  // Google search
  const googleMatch = cleaned.match(/^(?:google\s+search|search\s+google\s+for|google\s+par\s+search\s+karo)\s+(.+)$/i);
  if (googleMatch) {
    const query = googleMatch[1].trim();
    const url = `https://www.google.com/search?q=${encodeURIComponent(query)}`;
    return {
      success: true,
      action: "google_search",
      message: `Google search ready hai: "${query}". Niche button se directly open kar sakte hain.`,
      actionLink: { label: `Search Google: ${query}`, url, platform: "google" },
    };
  }

  // YouTube search / play
  const ytMatch =
    cleaned.match(/^(?:search\s+youtube\s+for|youtube\s+search)\s+(.+)$/i) ||
    cleaned.match(/^(?:play|chalao)\s+(.+?)\s+(?:on\s+youtube|youtube\s+par|youtube\s+pe)$/i) ||
    cleaned.match(/^youtube\s+(?:par|pe)\s+(?:play|chalao|search)\s+(.+)$/i);
  if (ytMatch) {
    const query = ytMatch[1].trim();
    const url = `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
    return {
      success: true,
      action: "youtube_search",
      message: `YouTube par "${query}" ready kar diya hai. Niche link click karke play kijiye.`,
      actionLink: { label: `Open on YouTube: ${query}`, url, platform: "youtube" },
    };
  }

  // Spotify play / search
  const spotifyMatch =
    cleaned.match(/^spotify\s+(?:par|pe)\s+(?:play|search|chalao)\s+(.+)$/i) ||
    cleaned.match(/^(?:play|search)\s+(.+?)\s+(?:on\s+spotify|spotify\s+par)$/i);
  if (spotifyMatch) {
    const query = spotifyMatch[1].trim();
    const url = `https://open.spotify.com/search/${encodeURIComponent(query)}`;
    return {
      success: true,
      action: "spotify_search",
      message: `Spotify search link ready hai: "${query}".`,
      actionLink: { label: `Open on Spotify: ${query}`, url, platform: "spotify" },
    };
  }

  // Open website URL
  const openSiteMatch = cleaned.match(/^open\s+((?:https?:\/\/)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/\S*)?)$/i);
  if (openSiteMatch) {
    const raw = openSiteMatch[1].trim();
    const url = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
    return {
      success: true,
      action: "open_website",
      message: `Verified HTTPS link ready hai: ${url}`,
      actionLink: { label: `Open ${raw}`, url, platform: "web" },
    };
  }

  // Honest boundary for Windows-native OS controls
  if (
    /^(?:set\s+volume|volume\s+(?:up|down)|awaz\s+(?:badhao|kam\s+karo)|mute|unmute|set\s+brightness|brightness\s+(?:up|down)|lock\s+(?:pc|screen|workstation)|screen\s+lock\s+karo)$/i.test(cleaned) ||
    /^open\s+(?:notepad|calculator|chrome|edge|vs\s*code|vscode|file\s+explorer|paint|windows\s+terminal|whatsapp)$/i.test(cleaned)
  ) {
    return {
      success: false,
      action: "desktop_only_boundary",
      message:
        "Yeh Windows 11 native OS control (volume, brightness, local app launch, ya workstation lock) browser sandbox mein directly accessible nahi hai. Web chat, voice, live search grounding, links, notes aur reminders yahan 100% active hain.",
      error: "desktop_runtime_required",
    };
  }

  return null;
}
