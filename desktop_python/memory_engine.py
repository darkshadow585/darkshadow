"""
Upgrade #3: Long-Term Semantic Memory, Notes, Reminders & Episodic Summaries
Backed by local SQLite + Gemini Vector Embeddings (gemini-embedding-2) with
offline keyword fallback and strict sensitive-data filtering.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SENSITIVE_LABELS = re.compile(
    r"\b(?:api\s*key|password|passcode|otp|cvv|credit\s*card|debit\s*card|"
    r"bank\s*account|upi\s*pin|private\s*key|secret\s*key|access\s*token)\b",
    re.IGNORECASE,
)
SECRET_SHAPES = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{16,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
)


def contains_sensitive_data(text: str) -> bool:
    cleaned = str(text).strip()
    if SENSITIVE_LABELS.search(cleaned):
        return True
    return any(p.search(cleaned) for p in SECRET_SHAPES)


@dataclass(frozen=True)
class ReminderRecord:
    id: int
    message: str
    due_at: str


class SemanticMemoryEngine:
    """SQLite semantic memory + vector embeddings + episodic session archive."""

    def __init__(self, db_path: Path, genai_client: Any = None) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = genai_client
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK (kind IN ('preference', 'note')),
                    content TEXT NOT NULL,
                    embedding BLOB,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    due_at_iso TEXT NOT NULL,
                    delivered_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding BLOB,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _embed(self, text: str) -> bytes | None:
        if self._client is None:
            return None
        try:
            resp = self._client.models.embed_content(
                model="gemini-embedding-2",
                contents=text,
            )
            values = resp.embeddings[0].values
            return np.asarray(values, dtype=np.float32).tobytes()
        except Exception:
            return None

    @staticmethod
    def _cosine(a_blob: bytes | None, b_vec: np.ndarray | None) -> float:
        if not a_blob or b_vec is None:
            return 0.0
        a_vec = np.frombuffer(a_blob, dtype=np.float32)
        if a_vec.shape != b_vec.shape:
            return 0.0
        denom = float(np.linalg.norm(a_vec) * np.linalg.norm(b_vec))
        return float(np.dot(a_vec, b_vec) / denom) if denom > 1e-8 else 0.0

    def save_memory(self, kind: str, content: str) -> tuple[bool, str]:
        cleaned = content.strip()
        if not cleaned:
            return False, "Empty memory save nahi ki ja sakti."
        if contains_sensitive_data(cleaned):
            return False, "Privacy shield: API keys, passwords, OTPs, aur payment data save karna blocked hai."
        norm_kind = "note" if kind.lower() == "note" else "preference"
        emb = self._embed(cleaned)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO memories (kind, content, embedding, created_at) VALUES (?, ?, ?, ?)",
                (norm_kind, cleaned, emb, now),
            )
            item_id = cur.lastrowid
        return True, f"Captain, {norm_kind} #{item_id} semantic memory mein save ho gaya."

    def recall_relevant(self, query: str, limit: int = 4) -> list[str]:
        q_blob = self._embed(query)
        q_vec = np.frombuffer(q_blob, dtype=np.float32) if q_blob else None
        q_words = set(re.findall(r"[a-z0-9]{3,}", query.lower()))

        scored: list[tuple[float, str]] = []
        with self._connect() as conn:
            for row in conn.execute("SELECT kind, content, embedding FROM memories").fetchall():
                sim = self._cosine(row["embedding"], q_vec)
                words = set(re.findall(r"[a-z0-9]{3,}", str(row["content"]).lower()))
                kw = len(q_words & words) * 0.18
                score = sim + kw
                if score >= 0.35:
                    scored.append((score, f"[{row['kind']}] {row['content']}"))

            for row in conn.execute("SELECT session_date, summary, embedding FROM episodes ORDER BY id DESC LIMIT 20").fetchall():
                sim = self._cosine(row["embedding"], q_vec)
                words = set(re.findall(r"[a-z0-9]{3,}", str(row["summary"]).lower()))
                kw = len(q_words & words) * 0.15
                score = sim + kw
                if score >= 0.38:
                    scored.append((score, f"[past session {row['session_date']}] {row['summary']}"))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def archive_episode(self, turns: list[tuple[str, str]]) -> None:
        if len(turns) < 2:
            return
        transcript = "\n".join(f"Captain: {u}\nDarkShadow: {a}" for u, a in turns[-8:])
        summary = f"Discussed: {turns[-1][0][:120]}"
        if self._client is not None:
            try:
                resp = self._client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"Summarize this conversation in 1-2 short factual sentences for long-term memory:\n{transcript}",
                )
                if resp.text and resp.text.strip():
                    summary = resp.text.strip()[:280]
            except Exception:
                pass
        if contains_sensitive_data(summary):
            return
        now = datetime.now(timezone.utc)
        emb = self._embed(summary)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO episodes (session_date, summary, embedding, created_at) VALUES (?, ?, ?, ?)",
                (now.strftime("%Y-%m-%d"), summary, emb, now.isoformat()),
            )

    def add_reminder(self, message: str, due_at: datetime) -> tuple[bool, str]:
        cleaned = message.strip()
        if not cleaned:
            return False, "Reminder message empty nahi ho sakta."
        if contains_sensitive_data(cleaned):
            return False, "Privacy shield: Sensitive data reminder mein blocked hai."
        now = datetime.now(timezone.utc).isoformat()
        due_utc = due_at.astimezone(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (message, due_at_iso, created_at) VALUES (?, ?, ?)",
                (cleaned, due_utc, now),
            )
            rid = cur.lastrowid
        return True, f"Captain, reminder #{rid} set ho gaya ({due_at.strftime('%d %b %H:%M')}): {cleaned}"

    def pop_due_reminders(self) -> list[ReminderRecord]:
        now_iso = datetime.now(timezone.utc).isoformat()
        due: list[ReminderRecord] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, message, due_at_iso FROM reminders WHERE delivered_at IS NULL AND due_at_iso <= ?",
                (now_iso,),
            ).fetchall()
            for row in rows:
                conn.execute("UPDATE reminders SET delivered_at = ? WHERE id = ?", (now_iso, row["id"]))
                due.append(ReminderRecord(id=int(row["id"]), message=str(row["message"]), due_at=str(row["due_at_iso"])))
        return due
