"""Rolling Episodic Memory & Session Journaling for DarkShadow.

Captures conversational context before it drops out of the short-term
history deque, distilling past interactions into timeline-based episodic journals.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vector_memory import VectorMemoryStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EpisodicRecord:
    """Represents a timeline snapshot of a past conversation."""

    id: int
    session_date: str
    summary: str
    topics: str
    turn_count: int
    created_at: str


class EpisodicMemoryStore:
    """Manages SQLite storage for episodic session memories."""

    def __init__(self, db_path: Path | str, vector_store: VectorMemoryStore | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.vector_store = vector_store or VectorMemoryStore(self.db_path)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """Ensure episodic_sessions table exists so the store is self-contained."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS episodic_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_date TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        topics TEXT DEFAULT '',
                        turn_count INTEGER DEFAULT 1,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception as exc:
            LOGGER.debug("Episodic table ensure notice: %s", exc)

    def store_episode(
        self,
        summary: str,
        topics: str = "",
        turn_count: int = 1,
    ) -> int:
        """Persist one episodic summary and update its vector embedding."""
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        created_at = now.isoformat()

        clean_summary = str(summary).strip()
        if not clean_summary:
            return 0

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO episodic_sessions (session_date, summary, topics, turn_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (date_str, clean_summary, str(topics).strip(), turn_count, created_at),
            )
            episode_id = cursor.lastrowid or 0

        # Upsert vector embedding for semantic search
        if episode_id > 0:
            try:
                self.vector_store.upsert_embedding(
                    item_id=episode_id,
                    item_type="episodic",
                    text=f"{clean_summary} {topics}",
                )
            except Exception as exc:
                LOGGER.debug("Episodic vector embedding notice: %s", exc)

        return episode_id

    def get_recent_episodes(self, limit: int = 5) -> list[EpisodicRecord]:
        """Fetch latest episodic session summaries."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, session_date, summary, topics, turn_count, created_at
                    FROM episodic_sessions
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [
                    EpisodicRecord(
                        id=int(r["id"]),
                        session_date=str(r["session_date"]),
                        summary=str(r["summary"]),
                        topics=str(r["topics"]),
                        turn_count=int(r["turn_count"]),
                        created_at=str(r["created_at"]),
                    )
                    for r in rows
                ]
        except Exception:
            return []

    def search_episodes(self, query: str, limit: int = 3) -> list[EpisodicRecord]:
        """Search episodes using vector similarity with keyword fallback."""
        # 1. Hybrid semantic & FTS5 search
        if hasattr(self.vector_store, "hybrid_search"):
            sim_matches = self.vector_store.hybrid_search(query, item_type="episodic", limit=limit, min_similarity=0.35)
        else:
            sim_matches = self.vector_store.search_similar(query, item_type="episodic", limit=limit, min_similarity=0.45)
        if sim_matches:
            ids = [m[0] for m in sim_matches]
            placeholders = ",".join("?" for _ in ids)
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT id, session_date, summary, topics, turn_count, created_at FROM episodic_sessions WHERE id IN ({placeholders})",
                        tuple(ids),
                    ).fetchall()
                    row_map = {int(r["id"]): r for r in rows}
                    ordered = []
                    for ep_id in ids:
                        if ep_id in row_map:
                            r = row_map[ep_id]
                            ordered.append(
                                EpisodicRecord(
                                    id=int(r["id"]),
                                    session_date=str(r["session_date"]),
                                    summary=str(r["summary"]),
                                    topics=str(r["topics"]),
                                    turn_count=int(r["turn_count"]),
                                    created_at=str(r["created_at"]),
                                )
                            )
                    return ordered
            except Exception as exc:
                LOGGER.debug("Episodic vector lookup error: %s", exc)

        # 2. Fallback to recent episodes
        return self.get_recent_episodes(limit=limit)


class EpisodicMemorySummarizer:
    """Extracts and archives conversational milestones in the background."""

    def __init__(self, store: EpisodicMemoryStore, gemini_client: Any = None) -> None:
        self.store = store
        self.gemini_client = gemini_client
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="DarkShadow-Episodic",
        )

    def summarize_evicted_turn_async(self, user_text: str, assistant_text: str) -> None:
        """Process an evicted conversation turn asynchronously into episodic memory."""
        self._executor.submit(self._summarize, user_text, assistant_text)

    def _summarize(self, user_text: str, assistant_text: str) -> None:
        """Distill turn into a compact 1-sentence episodic memory."""
        u = str(user_text).strip()
        a = str(assistant_text).strip()
        if len(u) < 10 or len(a) < 10:
            return

        summary: str = ""

        # 1. LLM summarization if available
        if self.gemini_client is not None:
            try:
                from config import load_settings
                settings = load_settings()
                model_name = getattr(settings, "casual_model", getattr(settings, "model", "gemini-2.5-flash"))
                prompt = (
                    "Summarize this dialogue exchange between Captain and DarkShadow into ONE crisp sentence "
                    "capturing what was discussed, decided, or resolved.\n"
                    f"Captain: {u[:200]}\n"
                    f"DarkShadow: {a[:200]}\n"
                    "Output one sentence only:"
                )
                resp = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                summary = (resp.text or "").strip()
            except Exception as exc:
                LOGGER.debug("LLM episodic summarization notice: %s", exc)

        # 2. Heuristic fallback
        if not summary or len(summary) > 300:
            summary = f"Captain discussed '{u[:60]}...' and assistant resolved '{a[:60]}...'"

        self.store.store_episode(summary=summary, topics="", turn_count=1)
        LOGGER.info("Archived episodic memory: %s", summary[:70])

    def archive_session_summary_async(self, conversation_turns: list[tuple[str, str]]) -> None:
        """Process full session turns asynchronously when a live voice or text session ends."""
        if not conversation_turns:
            return
        self._executor.submit(self._summarize_session, conversation_turns)

    def _summarize_session(self, turns: list[tuple[str, str]]) -> None:
        if not turns:
            return
        turn_lines = []
        for u, a in turns[-10:]:
            u_clean = str(u).strip()
            a_clean = str(a).strip()
            if u_clean:
                turn_lines.append(f"Captain: {u_clean[:120]}")
            if a_clean:
                turn_lines.append(f"DarkShadow: {a_clean[:120]}")

        full_dialogue = "\n".join(turn_lines)
        summary = ""
        if self.gemini_client is not None and len(full_dialogue) > 20:
            try:
                from config import load_settings
                settings = load_settings()
                model_name = getattr(settings, "casual_model", getattr(settings, "model", "gemini-2.5-flash"))
                prompt = (
                    "Summarize this conversation session between Captain and DarkShadow into ONE crisp, informative sentence "
                    "capturing key topics, questions asked, and actions performed.\n"
                    f"Dialogue:\n{full_dialogue[:1500]}\n"
                    "Output one sentence summary only:"
                )
                resp = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                summary = (resp.text or "").strip()
            except Exception as exc:
                LOGGER.debug("LLM session summarization notice: %s", exc)

        if not summary:
            first_u = turns[0][0][:50] if turns else "chat"
            last_u = turns[-1][0][:50] if turns else "session"
            summary = f"Captain and DarkShadow conversed about '{first_u}' to '{last_u}' ({len(turns)} turns)."

        self.store.store_episode(summary=summary, topics="", turn_count=len(turns))
        LOGGER.info("Archived session episode: %s", summary[:70])


class EpisodicMemoryRetriever:
    """Retrieves relevant past timeline episodes to answer past-session questions."""

    _TEMPORAL_PATTERNS = [
        re.compile(
            r"\b(?:pichhle|pichle|pichhli|pichli|pichhla|pichla|past|yesterday|kal|pehle|history|session|discuss|baat\s+ki\s+thi|bataya\s+tha)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:what\s+did\s+we|remember\s+when|last\s+time|previous\s+conversation|last\s+chat|previous\s+chat)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:पिछला|पिछले|पिछली|कल|पहले|चैट|सेशन|बात\s*की\s*थी|बताया\s*था)",
            re.IGNORECASE,
        ),
    ]

    def __init__(self, store: EpisodicMemoryStore) -> None:
        self.store = store

    def is_temporal_query(self, query: str) -> bool:
        """Check if Captain is asking about past sessions or timeline history."""
        return any(pat.search(query) for pat in self._TEMPORAL_PATTERNS)

    def get_context_injection(self, query: str, limit: int = 3) -> str:
        """Generate context injection string of relevant past episodes."""
        episodes = self.store.search_episodes(query, limit=limit)
        if not episodes:
            return ""

        lines = ["PAST EPISODIC SESSIONS (CONVERSATION TIMELINE):"]
        for ep in episodes:
            lines.append(f" - [{ep.session_date}]: {ep.summary}")
        return "\n".join(lines)


__all__ = [
    "EpisodicRecord",
    "EpisodicMemoryStore",
    "EpisodicMemorySummarizer",
    "EpisodicMemoryRetriever",
]
