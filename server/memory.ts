/**
 * Opt-in in-memory preferences, notes, and reminders store
 * ported from DarkShadow memory.py.
 */

import { containsSensitiveData } from "./safety.ts";

export interface MemoryItem {
  id: number;
  kind: "preference" | "note";
  content: string;
  createdAt: string;
}

export interface ReminderItem {
  id: number;
  message: string;
  dueAt: string; // ISO string
  createdAt: string;
  deliveredAt: string | null;
}

export interface MemoryCommandResult {
  success: boolean;
  action: string;
  message: string;
  error?: string;
}

const TOKEN_ALIASES: Record<string, string> = {
  favourite: "favorite",
  colour: "color",
  pasand: "favorite",
  pasandida: "favorite",
  dost: "friend",
  yaar: "friend",
  janamdin: "birthday",
  bday: "birthday",
};

const STOP_WORDS = new Set([
  "the", "this", "that", "what", "who", "when", "tell", "about",
  "hai", "hain", "kaun", "kon", "kau", "kya", "kab", "mera", "meri",
  "mere", "mujhe", "batao", "bata", "ye",
]);

function normalizeContent(text: string): string {
  return text.toLowerCase().trim().replace(/\s+/g, " ");
}

function memoryTokens(text: string): Set<string> {
  const tokens = new Set<string>();
  const matches = normalizeContent(text).match(/[a-z0-9]+/g) ?? [];
  for (const raw of matches) {
    const mapped = TOKEN_ALIASES[raw] ?? raw;
    if (mapped.length >= 2 && !STOP_WORDS.has(mapped)) {
      tokens.add(mapped);
    }
  }
  return tokens;
}

export class MemoryStore {
  private items: MemoryItem[] = [];
  private reminders: ReminderItem[] = [];
  private nextItemId = 1;
  private nextReminderId = 1;

  listItems(kind?: "preference" | "note"): MemoryItem[] {
    if (!kind) return [...this.items];
    return this.items.filter((i) => i.kind === kind);
  }

  listPendingReminders(): ReminderItem[] {
    return this.reminders
      .filter((r) => r.deliveredAt === null)
      .sort((a, b) => new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime());
  }

  popDueReminders(now = new Date()): ReminderItem[] {
    const due: ReminderItem[] = [];
    const nowMs = now.getTime();
    for (const r of this.reminders) {
      if (r.deliveredAt === null && new Date(r.dueAt).getTime() <= nowMs) {
        r.deliveredAt = now.toISOString();
        due.push({ ...r });
      }
    }
    return due;
  }

  addItem(kind: "preference" | "note", rawContent: string): MemoryCommandResult {
    const content = rawContent.trim();
    if (!content) {
      return {
        success: false,
        action: "remember",
        message: "Empty content save nahi kiya.",
        error: "empty_content",
      };
    }
    if (content.length > 400) {
      return {
        success: false,
        action: "remember",
        message: "Content maximum 400 characters ka ho sakta hai.",
        error: "content_too_long",
      };
    }
    if (containsSensitiveData(content)) {
      return {
        success: false,
        action: "remember",
        message:
          "Sensitive data memory mein save nahi kiya. API keys, passwords, OTPs, payment data aur private clipboard blocked hain.",
        error: "sensitive_data",
      };
    }

    const normalized = normalizeContent(content);
    const existing = this.items.find(
      (i) => i.kind === kind && normalizeContent(i.content) === normalized
    );
    if (existing) {
      return {
        success: true,
        action: kind === "note" ? "note" : "remember",
        message: `Yeh ${kind} pehle se saved hai (#${existing.id}): ${existing.content}`,
      };
    }

    const item: MemoryItem = {
      id: this.nextItemId++,
      kind,
      content,
      createdAt: new Date().toISOString(),
    };
    this.items.push(item);
    return {
      success: true,
      action: kind === "note" ? "note" : "remember",
      message: `${kind === "note" ? "Note" : "Preference"} save kar liya (#${item.id}): ${item.content}`,
    };
  }

  forgetItem(id?: number, content?: string): MemoryCommandResult {
    if (typeof id === "number") {
      const idx = this.items.findIndex((i) => i.id === id);
      if (idx === -1) {
        return {
          success: false,
          action: "forget",
          message: `Memory #${id} nahi mili.`,
          error: "not_found",
        };
      }
      const [removed] = this.items.splice(idx, 1);
      return {
        success: true,
        action: "forget",
        message: `Memory #${removed.id} delete kar di: ${removed.content}`,
      };
    }

    if (content && content.trim()) {
      const target = normalizeContent(content);
      const idx = this.items.findIndex((i) => normalizeContent(i.content) === target);
      if (idx === -1) {
        return {
          success: false,
          action: "forget",
          message: `"${content.trim()}" se match karne wali memory nahi mili.`,
          error: "not_found",
        };
      }
      const [removed] = this.items.splice(idx, 1);
      return {
        success: true,
        action: "forget",
        message: `Memory #${removed.id} delete kar di: ${removed.content}`,
      };
    }

    return {
      success: false,
      action: "forget",
      message: "Delete karne ke liye `/forget <id>` ya `forget this: <text>` use kijiye.",
      error: "missing_target",
    };
  }

  addReminder(message: string, dueAt: Date): MemoryCommandResult {
    const cleaned = message.trim();
    if (!cleaned) {
      return {
        success: false,
        action: "remind",
        message: "Reminder message empty nahi ho sakta.",
        error: "empty_content",
      };
    }
    if (containsSensitiveData(cleaned)) {
      return {
        success: false,
        action: "remind",
        message:
          "Sensitive data reminder mein save nahi kiya. API keys, passwords, OTPs aur payment data blocked hain.",
        error: "sensitive_data",
      };
    }

    const reminder: ReminderItem = {
      id: this.nextReminderId++,
      message: cleaned,
      dueAt: dueAt.toISOString(),
      createdAt: new Date().toISOString(),
      deliveredAt: null,
    };
    this.reminders.push(reminder);
    const formattedTime = dueAt.toLocaleString("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    });
    return {
      success: true,
      action: "remind",
      message: `Reminder #${reminder.id} set kar diya (${formattedTime}): ${reminder.message}`,
    };
  }

  deleteReminder(id: number): MemoryCommandResult {
    const idx = this.reminders.findIndex((r) => r.id === id);
    if (idx === -1) {
      return {
        success: false,
        action: "delete_reminder",
        message: `Reminder #${id} nahi mila.`,
        error: "not_found",
      };
    }
    const [removed] = this.reminders.splice(idx, 1);
    return {
      success: true,
      action: "delete_reminder",
      message: `Reminder #${removed.id} delete kar diya: ${removed.message}`,
    };
  }

  recallRelevant(query: string, limit = 3): MemoryItem[] {
    const qTokens = memoryTokens(query);
    if (qTokens.size === 0 || this.items.length === 0) return [];
    const scored = this.items
      .map((item) => {
        const iTokens = memoryTokens(item.content);
        let overlap = 0;
        for (const t of qTokens) {
          if (iTokens.has(t)) overlap++;
        }
        return { item, overlap };
      })
      .filter((entry) => entry.overlap > 0)
      .sort((a, b) => b.overlap - a.overlap);

    return scored.slice(0, limit).map((e) => e.item);
  }
}

function parseReminderCommand(text: string, now: Date): { message: string; dueAt: Date } | { error: string } | null {
  const prefix = text.match(/^(?:\/remind|remind\s+me)\s+(.+)$/i);
  if (!prefix) return null;
  const body = prefix[1].trim();

  // Relative reminder: "in 10 minutes to call Rahul" / "in 2 hours drink water"
  const relMatch = body.match(/^in\s+(\d+)\s+(min(?:ute)?s?|hours?|hrs?|sec(?:ond)?s?)\s+(?:to\s+)?(.+)$/i);
  if (relMatch) {
    const amount = Number.parseInt(relMatch[1], 10);
    const unit = relMatch[2].toLowerCase();
    const message = relMatch[3].trim();
    if (amount > 0 && message) {
      const ms = unit.startsWith("h")
        ? amount * 3600_000
        : unit.startsWith("m")
          ? amount * 60_000
          : amount * 1000;
      return { message, dueAt: new Date(now.getTime() + ms) };
    }
  }

  // Absolute reminder: "tomorrow at 09:00 to call Rahul" / "today at 19:30 gym" / "2026-12-01 at 09:00 ..."
  const absMatch =
    body.match(/^(?:on\s+)?(today|tomorrow|\d{4}-\d{2}-\d{2})\s+(?:at\s+)?(\d{1,2}):(\d{2})(?:\s*(am|pm))?\s+(?:to\s+)?(.+)$/i) ||
    body.match(/^at\s+(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?:\s*(am|pm))?\s+(?:to\s+)?(.+)$/i);

  if (!absMatch) {
    return { error: "Format: remind me tomorrow at 09:00 to call Rahul (ya: remind me in 10 minutes to stretch)" };
  }

  const dateToken = absMatch[1].toLowerCase();
  let hour = Number.parseInt(absMatch[2], 10);
  const minute = Number.parseInt(absMatch[3], 10);
  const meridiem = absMatch[4]?.toLowerCase();
  const message = absMatch[5].trim();

  if (meridiem === "pm" && hour < 12) hour += 12;
  if (meridiem === "am" && hour === 12) hour = 0;

  if (hour > 23 || minute > 59 || !message) {
    return { error: "Reminder date/time invalid hai." };
  }

  const dueAt = new Date(now);
  if (dateToken === "tomorrow") {
    dueAt.setDate(dueAt.getDate() + 1);
  } else if (dateToken !== "today") {
    const [y, m, d] = dateToken.split("-").map((n) => Number.parseInt(n, 10));
    dueAt.setFullYear(y, m - 1, d);
  }
  dueAt.setHours(hour, minute, 0, 0);
  return { message, dueAt };
}

export function handleMemoryCommand(
  text: string,
  store: MemoryStore | null
): MemoryCommandResult | null {
  const cleaned = text.trim();
  if (!cleaned) return null;

  const isMemoryIntent =
    /^\/(?:memories|notes|reminders|remember|note|forget|remind|delete-reminder)\b/i.test(cleaned) ||
    /^(?:what do you remember\??|kya yaad hai\??|show notes|list notes|show reminders|list reminders|remember\b|yaad\s+rakho\b|note\s*:|save\s+(?:a\s+)?note\b|forget\b|delete\s+reminder\b|remind\s+me\b)/i.test(cleaned) ||
    /\byaad\s+rakh(?:o|na|ana)\b/i.test(cleaned);

  if (!isMemoryIntent) return null;

  if (!store) {
    return {
      success: false,
      action: "memory_paused",
      message: "Privacy mode active hai — persistent memory access is session ke liye paused hai. Settings se toggle kar sakte hain.",
      error: "privacy_mode",
    };
  }

  if (/^(?:\/memories|what do you remember\??|kya yaad hai\??)$/i.test(cleaned)) {
    const items = store.listItems();
    if (items.length === 0) {
      return {
        success: true,
        action: "list_memories",
        message: "Abhi koi explicit preference ya note saved nahi hai. Save karne ke liye `remember this: ...` ya `/note ...` bolein.",
      };
    }
    const formatted = items.map((i) => `#${i.id} [${i.kind}] ${i.content}`).join("\n");
    return {
      success: true,
      action: "list_memories",
      message: `Saved memories (${items.length}):\n${formatted}`,
    };
  }

  if (/^(?:\/notes|show notes|list notes)$/i.test(cleaned)) {
    const notes = store.listItems("note");
    if (notes.length === 0) {
      return {
        success: true,
        action: "list_notes",
        message: "Abhi koi notes saved nahi hain. Try: `/note Call the school office`",
      };
    }
    const formatted = notes.map((n) => `#${n.id} ${n.content}`).join("\n");
    return {
      success: true,
      action: "list_notes",
      message: `Saved notes (${notes.length}):\n${formatted}`,
    };
  }

  if (/^(?:\/reminders|show reminders|list reminders)$/i.test(cleaned)) {
    const pending = store.listPendingReminders();
    if (pending.length === 0) {
      return {
        success: true,
        action: "list_reminders",
        message: "Koi pending reminders nahi hain. Try: `remind me tomorrow at 09:00 to call Rahul`",
      };
    }
    const formatted = pending
      .map((r) => {
        const when = new Date(r.dueAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
        return `#${r.id} [${when}] ${r.message}`;
      })
      .join("\n");
    return {
      success: true,
      action: "list_reminders",
      message: `Pending reminders (${pending.length}):\n${formatted}`,
    };
  }

  const rememberMatch = cleaned.match(/^(?:\/remember\s+|remember\s+(?:this|that)(?::|\s+)|yaad\s+rakho(?:\s+ki)?\s+|remember\s+)(.+)$/i);
  if (rememberMatch) {
    return store.addItem("preference", rememberMatch[1]);
  }

  const hindiRemember = cleaned.match(/^(.+?)\s+yaad\s+rakh(?:o|na|ana)(?:\s+(?:hai|na))?(?:\s+(?:ok|okay))?[.!?]*$/i);
  if (hindiRemember) {
    const content = hindiRemember[1].trim();
    if (/^(?:ye|yeh|this|woh|wo)\b/i.test(content)) {
      return {
        success: false,
        action: "remember",
        message: "Kya yaad rakhna hai woh clearly bataiye, e.g. `remember this: I prefer concise answers`.",
        error: "missing_subject",
      };
    }
    return store.addItem("preference", content);
  }

  const noteMatch = cleaned.match(/^(?:\/note\s+|note\s*:\s*|save\s+(?:a\s+)?note\s+)(.+)$/i);
  if (noteMatch) {
    return store.addItem("note", noteMatch[1]);
  }

  const forgetIdMatch = cleaned.match(/^(?:\/forget|forget)(?:\s+(?:memory|note))?\s+#?(\d+)$/i);
  if (forgetIdMatch) {
    return store.forgetItem(Number.parseInt(forgetIdMatch[1], 10));
  }

  const forgetTextMatch = cleaned.match(/^forget\s+this\s*:\s*(.+)$/i);
  if (forgetTextMatch) {
    return store.forgetItem(undefined, forgetTextMatch[1]);
  }

  const deleteReminderMatch = cleaned.match(/^(?:\/delete-reminder|delete\s+reminder)\s+#?(\d+)$/i);
  if (deleteReminderMatch) {
    return store.deleteReminder(Number.parseInt(deleteReminderMatch[1], 10));
  }

  const reminderParsed = parseReminderCommand(cleaned, new Date());
  if (reminderParsed) {
    if ("error" in reminderParsed) {
      return {
        success: false,
        action: "invalid_reminder",
        message: reminderParsed.error,
        error: "invalid_reminder",
      };
    }
    return store.addReminder(reminderParsed.message, reminderParsed.dueAt);
  }

  return null;
}
