"""Opt-in SQLite preferences, notes, and reminders for DarkShadow Phase 5."""

from __future__ import annotations

import re
import sqlite3
import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable


NowFunction = Callable[[], datetime]
ReminderCallback = Callable[["Reminder"], None]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryResult:
    """Structured result returned by deterministic memory operations."""

    success: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """One explicitly saved preference or note."""

    id: int
    kind: str
    content: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Reminder:
    """One local reminder stored with an absolute UTC due time."""

    id: int
    message: str
    due_at: datetime
    created_at: str
    delivered_at: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedMemoryCommand:
    """A deterministic memory intent and its validated arguments."""

    action: str
    arguments: dict[str, Any] = field(default_factory=dict)


_SENSITIVE_LABELS = re.compile(
    r"\b(?:api\s*key|password|passcode|passwd|otp|one[- ]time password|"
    r"cvv|card\s*(?:number|no)|credit\s*card|debit\s*card|bank\s*account|"
    r"upi\s*pin|private\s*key|secret\s*key|access\s*token|refresh\s*token|"
    r"private\s*clipboard|clipboard\s*content)\b",
    re.IGNORECASE,
)
_SECRET_SHAPES = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAQ[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{16,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
)
_ALLOWED_ITEM_KINDS = frozenset({"preference", "note"})


def contains_sensitive_data(content: str) -> bool:
    """Return whether content resembles a secret or prohibited private data."""

    cleaned = str(content).strip()
    if _SENSITIVE_LABELS.search(cleaned):
        return True
    return any(pattern.search(cleaned) for pattern in _SECRET_SHAPES)


def _normalize_content(content: str) -> str:
    return " ".join(content.casefold().split())


_MEMORY_TOKEN_ALIASES = {
    "favourite": "favorite",
    "colour": "color",
    "pasand": "favorite",
    "pasandida": "favorite",
    "dost": "friend",
    "yaar": "friend",
    "janamdin": "birthday",
    "bday": "birthday",
}
_MEMORY_STOP_WORDS = {
    "the", "this", "that", "what", "who", "when", "tell", "about",
    "hai", "hain", "kaun", "kon", "kau", "kya", "kab", "mera", "meri",
    "mere", "mujhe", "batao", "bata", "ye",
}


def _memory_tokens(content: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", _normalize_content(content)):
        token = _MEMORY_TOKEN_ALIASES.get(raw, raw)
        if len(token) >= 2 and token not in _MEMORY_STOP_WORDS:
            tokens.add(token)
    return tokens


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value.astimezone(timezone.utc)


class SQLiteMemoryStore:
    """Persist only explicit preferences, notes, and reminders in SQLite."""

    def __init__(
        self,
        database_path: Path,
        *,
        now_fn: NowFunction = _utc_now,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._now_fn = now_fn
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK (kind IN ('preference', 'note')),
                    content TEXT NOT NULL,
                    normalized_content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(kind, normalized_content)
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    due_at_utc TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );

                CREATE TABLE IF NOT EXISTS user_profile (
                    key TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist_or_author TEXT,
                    url TEXT,
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learned_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS autonomous_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'active',
                    superseded_by INTEGER,
                    last_accessed_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(category, subject, fact)
                );

                CREATE INDEX IF NOT EXISTS idx_autonomous_facts_cat
                ON autonomous_facts(category, subject);

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    item_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, item_type)
                );

                CREATE TABLE IF NOT EXISTS episodic_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    topics TEXT,
                    turn_count INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_episodic_date
                ON episodic_sessions(session_date);

                CREATE INDEX IF NOT EXISTS idx_reminders_due
                ON reminders(delivered_at, due_at_utc);
                """
            )

    def add_item(self, kind: str, content: str) -> MemoryResult:
        """Save one explicit preference or note after privacy validation."""

        normalized_kind = str(kind).strip().casefold()
        cleaned = str(content).strip()
        if normalized_kind not in _ALLOWED_ITEM_KINDS:
            return MemoryResult(
                False,
                "remember",
                "Memory type sirf preference ya note ho sakta hai.",
                error="invalid_kind",
            )
        validation = self._validate_content(cleaned, maximum=500)
        if validation is not None:
            return validation

        normalized = _normalize_content(cleaned)
        created_at = _aware_utc(self._now_fn()).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO memory_items
                        (kind, content, normalized_content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (normalized_kind, cleaned, normalized, created_at),
                )
                if cursor.rowcount == 0:
                    row = connection.execute(
                        """
                        SELECT id FROM memory_items
                        WHERE kind = ? AND normalized_content = ?
                        """,
                        (normalized_kind, normalized),
                    ).fetchone()
                    return MemoryResult(
                        False,
                        "remember",
                        "Yeh item pehle se memory mein hai.",
                        {"id": int(row["id"]) if row else None},
                        "duplicate",
                    )
                item_id = int(cursor.lastrowid)
        except sqlite3.Error as exc:
            return self._database_error("remember", exc)
        label = "Preference" if normalized_kind == "preference" else "Note"
        return MemoryResult(
            True,
            "remember",
            f"{label} #{item_id} safely yaad rakh li.",
            {"id": item_id, "kind": normalized_kind},
        )

    # Convenient alias
    remember = add_item

    def list_items(
        self,
        kind: str | None = None,
        *,
        limit: int = 50,
    ) -> tuple[MemoryItem, ...]:
        """Return a bounded list of explicit memory items, newest first."""

        safe_limit = min(max(int(limit), 1), 100)
        normalized_kind = str(kind).casefold() if kind else None
        if normalized_kind and normalized_kind not in _ALLOWED_ITEM_KINDS:
            return ()
        query = (
            "SELECT id, kind, content, created_at FROM memory_items "
            "WHERE kind = ? ORDER BY id DESC LIMIT ?"
            if normalized_kind
            else "SELECT id, kind, content, created_at FROM memory_items "
            "ORDER BY id DESC LIMIT ?"
        )
        arguments: tuple[Any, ...] = (
            (normalized_kind, safe_limit)
            if normalized_kind
            else (safe_limit,)
        )
        with self._connect() as connection:
            rows = connection.execute(query, arguments).fetchall()
        return tuple(
            MemoryItem(
                id=int(row["id"]),
                kind=str(row["kind"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        )

    def search_items(self, query: str, *, limit: int = 5) -> tuple[MemoryItem, ...]:
        """Return locally ranked memories with typo and Hinglish tolerance."""

        normalized_query = _normalize_content(query).strip(" .?!")
        query_tokens = _memory_tokens(normalized_query)
        if not normalized_query:
            return ()
        scored: list[tuple[float, MemoryItem]] = []
        for item in self.list_items(limit=100):
            normalized_content = _normalize_content(item.content)
            content_tokens = _memory_tokens(normalized_content)
            overlap = query_tokens & content_tokens
            score = 12.0 if normalized_query in normalized_content else 0.0
            score += len(overlap) * 3.0
            if (
                item.kind == "preference"
                and query_tokens & {"favorite", "prefer", "like", "color", "birthday"}
            ):
                score += 2.0
            similarity = SequenceMatcher(
                None,
                " ".join(sorted(query_tokens)),
                " ".join(sorted(content_tokens)),
            ).ratio()
            if similarity >= 0.42:
                score += similarity * 4.0
            if score >= 2.5:
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].id), reverse=True)
        safe_limit = min(max(int(limit), 1), 10)
        return tuple(item for _score, item in scored[:safe_limit])

    def search_semantic_memories(
        self, query: str, limit: int = 5, api_key: str | None = None
    ) -> tuple[MemoryItem, ...]:
        """Level 4: Semantic vector/embedding search over stored preferences and notes.

        Uses pre-computed embeddings from VectorMemoryStore (1 API call for the
        query vector only) instead of embedding every item on every search.
        Falls back to fuzzy token matching if vector search is unavailable.
        """
        cleaned_q = str(query).strip()
        if not cleaned_q:
            return ()

        # Try VectorMemoryStore with pre-computed embeddings (0 per-item API calls)
        try:
            from vector_memory import VectorEmbedder, VectorMemoryStore

            embedder = VectorEmbedder(api_key=api_key)
            vec_store = VectorMemoryStore(str(self._db_path), embedder)

            # Search using pre-computed embeddings (only 1 API call for the query)
            results = vec_store.search_similar(
                cleaned_q, item_type="memory", top_k=limit, min_similarity=0.4
            )
            if results:
                # Map vector results back to MemoryItems by content matching
                items = self.list_items(limit=200)
                content_to_item = {it.content.strip().casefold(): it for it in items}
                matched: list[MemoryItem] = []
                for sim_score, content_text, _meta in results:
                    key = content_text.strip().casefold()
                    if key in content_to_item:
                        matched.append(content_to_item[key])
                if matched:
                    return tuple(matched[:limit])
        except Exception as vec_exc:
            LOGGER.debug("Vector semantic search notice: %s", vec_exc)

        # High-accuracy token-semantic fuzzy fallback
        return self.search_items(cleaned_q, limit=limit)

    def forget_item(
        self,
        *,
        item_id: int | None = None,
        content: str | None = None,
        kind: str | None = None,
    ) -> MemoryResult:
        """Delete an explicit memory by numeric ID or exact normalized text."""

        if item_id is None and not str(content or "").strip():
            return MemoryResult(
                False,
                "forget",
                "Forget ke liye memory ID ya exact text chahiye.",
                error="missing_target",
            )
        normalized_kind = str(kind).casefold() if kind else None
        if normalized_kind and normalized_kind not in _ALLOWED_ITEM_KINDS:
            return MemoryResult(
                False,
                "forget",
                "Memory type invalid hai.",
                error="invalid_kind",
            )
        try:
            with self._connect() as connection:
                if item_id is not None:
                    cursor = connection.execute(
                        "DELETE FROM memory_items WHERE id = ?",
                        (int(item_id),),
                    )
                elif normalized_kind:
                    cursor = connection.execute(
                        """
                        DELETE FROM memory_items
                        WHERE normalized_content = ? AND kind = ?
                        """,
                        (_normalize_content(str(content)), normalized_kind),
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM memory_items WHERE normalized_content = ?",
                        (_normalize_content(str(content)),),
                    )
                deleted = int(cursor.rowcount)
        except (sqlite3.Error, ValueError, TypeError) as exc:
            return self._database_error("forget", exc)
        if deleted == 0:
            return MemoryResult(
                False,
                "forget",
                "Matching memory item nahi mila.",
                error="not_found",
            )
        return MemoryResult(
            True,
            "forget",
            f"{deleted} memory item forget kar diya.",
            {"deleted": deleted},
        )

    def add_reminder(self, message: str, due_at: datetime) -> MemoryResult:
        """Store one non-sensitive future reminder in UTC."""

        cleaned = str(message).strip()
        validation = self._validate_content(cleaned, maximum=300)
        if validation is not None:
            return MemoryResult(
                validation.success,
                "reminder",
                validation.message,
                validation.data,
                validation.error,
            )
        due_utc = _aware_utc(due_at)
        now_utc = _aware_utc(self._now_fn())
        if due_utc <= now_utc:
            return MemoryResult(
                False,
                "reminder",
                "Reminder ka time future mein hona chahiye.",
                error="invalid_due_time",
            )
        created_at = now_utc.isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO reminders
                        (message, due_at_utc, created_at, delivered_at)
                    VALUES (?, ?, ?, NULL)
                    """,
                    (cleaned, due_utc.isoformat(), created_at),
                )
                reminder_id = int(cursor.lastrowid)
        except sqlite3.Error as exc:
            return self._database_error("reminder", exc)
        local_due = due_utc.astimezone()
        return MemoryResult(
            True,
            "reminder",
            (
                f"Reminder #{reminder_id} set: "
                f"{local_due.strftime('%d %b %Y, %I:%M %p')}."
            ),
            {"id": reminder_id, "due_at": due_utc.isoformat()},
        )

    def list_reminders(
        self,
        *,
        include_delivered: bool = False,
        limit: int = 50,
    ) -> tuple[Reminder, ...]:
        """Return bounded pending reminders, or all when explicitly requested."""

        safe_limit = min(max(int(limit), 1), 100)
        query = (
            "SELECT id, message, due_at_utc, created_at, delivered_at "
            "FROM reminders ORDER BY due_at_utc ASC LIMIT ?"
            if include_delivered
            else "SELECT id, message, due_at_utc, created_at, delivered_at "
            "FROM reminders WHERE delivered_at IS NULL "
            "ORDER BY due_at_utc ASC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, (safe_limit,)).fetchall()
        return tuple(self._reminder_from_row(row) for row in rows)

    def delete_reminder(self, reminder_id: int) -> MemoryResult:
        """Delete one reminder by numeric ID."""

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM reminders WHERE id = ?",
                    (int(reminder_id),),
                )
                deleted = int(cursor.rowcount)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            return self._database_error("delete_reminder", exc)
        if deleted == 0:
            return MemoryResult(
                False,
                "delete_reminder",
                "Reminder ID nahi mila.",
                error="not_found",
            )
        return MemoryResult(
            True,
            "delete_reminder",
            f"Reminder #{int(reminder_id)} delete kar diya.",
            {"deleted": int(reminder_id)},
        )

    def pop_due_reminders(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> tuple[Reminder, ...]:
        """Atomically mark and return reminders due at or before ``now``."""

        now_utc = _aware_utc(now or self._now_fn())
        safe_limit = min(max(int(limit), 1), 50)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT id, message, due_at_utc, created_at, delivered_at
                FROM reminders
                WHERE delivered_at IS NULL AND due_at_utc <= ?
                ORDER BY due_at_utc ASC
                LIMIT ?
                """,
                (now_utc.isoformat(), safe_limit),
            ).fetchall()
            if rows:
                connection.executemany(
                    "UPDATE reminders SET delivered_at = ? WHERE id = ?",
                    ((now_utc.isoformat(), int(row["id"])) for row in rows),
                )
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            try:
                connection.close()
            except Exception:
                pass
        return tuple(
            Reminder(
                id=int(row["id"]),
                message=str(row["message"]),
                due_at=datetime.fromisoformat(str(row["due_at_utc"])),
                created_at=str(row["created_at"]),
                delivered_at=now_utc.isoformat(),
            )
            for row in rows
        )

    def save_profile_fact(self, key: str, value: str, category: str = "general") -> MemoryResult:
        """Save or update a personal fact/preference about Captain."""
        k = str(key).strip().casefold()
        v = str(value).strip()
        c = str(category).strip().casefold() or "general"
        if not k or not v:
            return MemoryResult(False, "save_profile", "Key aur value required hain.", error="invalid_fact")
        if contains_sensitive_data(v):
            return MemoryResult(False, "save_profile", "Sensitive data save nahi kiya gaya.", error="sensitive_data")
        now_str = _aware_utc(self._now_fn()).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO user_profile (key, category, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        category=excluded.category,
                        updated_at=excluded.updated_at
                    """,
                    (k, c, v, now_str),
                )
            return MemoryResult(True, "save_profile", f"Captain, '{k}' save kar liya hai: {v}", {"key": k, "value": v})
        except Exception as exc:
            return MemoryResult(False, "save_profile", f"Fact save nahi ho saka: {exc}", error="db_error")

    # Convenient alias
    save_profile = save_profile_fact

    def get_full_profile(self) -> dict[str, str]:
        """Fetch all learned facts about Captain."""
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT key, value FROM user_profile ORDER BY category, key").fetchall()
                return {str(r["key"]): str(r["value"]) for r in rows}
        except Exception:
            return {}

    def add_favorite(self, title: str, item_type: str = "song", artist_or_author: str = "", url: str = "") -> MemoryResult:
        """Save a favorite song, artist, video, or channel."""
        t = str(title).strip()
        itype = str(item_type).strip().casefold() or "song"
        art = str(artist_or_author).strip()
        u = str(url).strip()
        if not t:
            return MemoryResult(False, "add_favorite", "Favorite title required hai.", error="empty_title")
        now_str = _aware_utc(self._now_fn()).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO user_favorites (item_type, title, artist_or_author, url, added_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (itype, t, art, u, now_str),
                )
            return MemoryResult(True, "add_favorite", f"Captain, '{t}' aapke favorites me save ho gaya!", {"title": t, "type": itype})
        except Exception as exc:
            return MemoryResult(False, "add_favorite", f"Favorite save nahi ho saka: {exc}", error="db_error")

    def get_favorites(self, item_type: str = "song") -> list[dict[str, Any]]:
        """Get all saved favorites."""
        try:
            with self._connect() as conn:
                if item_type:
                    rows = conn.execute("SELECT id, item_type, title, artist_or_author, url FROM user_favorites WHERE item_type = ? ORDER BY id DESC", (item_type.casefold(),)).fetchall()
                else:
                    rows = conn.execute("SELECT id, item_type, title, artist_or_author, url FROM user_favorites ORDER BY id DESC").fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def save_lesson(self, topic: str, lesson: str) -> MemoryResult:
        """Save an operational lesson or user correction."""
        top = str(topic).strip()
        les = str(lesson).strip()
        if not top or not les:
            return MemoryResult(False, "save_lesson", "Topic aur lesson required hain.", error="empty_lesson")
        now_str = _aware_utc(self._now_fn()).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO learned_lessons (topic, lesson, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (top, les, now_str),
                )
            return MemoryResult(True, "save_lesson", f"Captain, naya lesson seekh liya hai: [{top}] {les}", {"topic": top, "lesson": les})
        except Exception as exc:
            return MemoryResult(False, "save_lesson", f"Lesson save nahi ho saka: {exc}", error="db_error")

    def get_lessons(self) -> list[dict[str, str]]:
        """Get all learned lessons from past sessions."""
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT topic, lesson, created_at FROM learned_lessons ORDER BY id DESC LIMIT 15").fetchall()
                return [{"topic": str(r["topic"]), "lesson": str(r["lesson"])} for r in rows]
        except Exception:
            return []

    def store_autonomous_fact(
        self,
        category: str,
        subject: str,
        fact: str,
        confidence: float = 1.0,
    ) -> MemoryResult:
        """Store an organically learned fact extracted from conversation with vector embedding."""
        cat = str(category).strip().casefold() or "general"
        subj = str(subject).strip().casefold()
        f_text = str(fact).strip()
        if not subj or not f_text:
            return MemoryResult(False, "store_autonomous_fact", "Subject aur fact required hain.", error="empty_fact")
        if contains_sensitive_data(f_text):
            return MemoryResult(False, "store_autonomous_fact", "Sensitive data rejected.", error="sensitive_data")
        now_str = _aware_utc(self._now_fn()).isoformat()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO autonomous_facts (category, subject, fact, confidence, status, last_accessed_at, created_at)
                    VALUES (?, ?, ?, ?, 'active', ?, ?)
                    ON CONFLICT(category, subject, fact) DO UPDATE SET
                        confidence = excluded.confidence,
                        status = 'active',
                        last_accessed_at = excluded.last_accessed_at
                    """,
                    (cat, subj, f_text, float(confidence), now_str, now_str),
                )
                fact_id = cursor.lastrowid or 0
                if fact_id == 0:
                    row = conn.execute(
                        "SELECT id FROM autonomous_facts WHERE category = ? AND subject = ? AND fact = ?",
                        (cat, subj, f_text),
                    ).fetchone()
                    if row:
                        fact_id = int(row["id"])

            # Compute and store vector embedding for semantic search
            if fact_id > 0:
                try:
                    from vector_memory import VectorMemoryStore
                    vec_store = VectorMemoryStore(self.database_path)
                    vec_store.upsert_embedding(
                        item_id=fact_id,
                        item_type="fact",
                        text=f"{cat} {subj}: {f_text}",
                    )
                except Exception as vec_err:
                    LOGGER.debug("Fact vector embedding notice: %s", vec_err)

            return MemoryResult(True, "store_autonomous_fact", f"Organically learned: [{subj}] {f_text}", {"id": fact_id, "subject": subj, "fact": f_text})
        except Exception as exc:
            return MemoryResult(False, "store_autonomous_fact", f"DB Error: {exc}", error="db_error")

    def search_autonomous_facts(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search autonomous facts: Vector semantic search first, token matching fallback."""
        # 1. Hybrid semantic & FTS5 search
        try:
            from vector_memory import VectorMemoryStore
            vec_store = VectorMemoryStore(self.database_path)
            # Hybrid search: combines dense vector similarity + SQLite FTS5 for exact name/keyword recall
            if hasattr(vec_store, "hybrid_search"):
                sim_matches = vec_store.hybrid_search(query, item_type="fact", limit=limit, min_similarity=0.35)
            else:
                sim_matches = vec_store.search_similar(query, item_type="fact", limit=limit, min_similarity=0.45)
            if sim_matches:
                fact_ids = [m[0] for m in sim_matches]
                placeholders = ",".join("?" for _ in fact_ids)
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT id, category, subject, fact, confidence, status, created_at FROM autonomous_facts WHERE id IN ({placeholders}) AND status = 'active'",
                        tuple(fact_ids),
                    ).fetchall()
                    row_map = {int(r["id"]): dict(r) for r in rows}
                    ordered = [row_map[f_id] for f_id in fact_ids if f_id in row_map]
                    if ordered:
                        return ordered
        except Exception as v_exc:
            LOGGER.debug("Vector search fallback notice: %s", v_exc)

        # 2. Token / keyword matching fallback
        q_tokens = _memory_tokens(query)
        if not q_tokens:
            return self.get_recent_autonomous_facts(limit=limit)
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, category, subject, fact, confidence, status, created_at FROM autonomous_facts WHERE status = 'active' ORDER BY id DESC"
                ).fetchall()
                results = []
                for r in rows:
                    content = f"{r['category']} {r['subject']} {r['fact']}".casefold()
                    match_count = sum(1 for tok in q_tokens if tok in content)
                    if match_count > 0:
                        results.append((match_count, dict(r)))
                results.sort(key=lambda x: (x[0], x[1]["confidence"]), reverse=True)
                return [item[1] for item in results[:limit]]
        except Exception as exc:
            LOGGER.debug("search_autonomous_facts error: %s", exc)
            return []

    def get_recent_autonomous_facts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get most recent organically learned active facts."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, category, subject, fact, confidence, status, created_at FROM autonomous_facts WHERE status = 'active' ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_formatted_captain_knowledge_summary(self) -> str:
        """Generate a concise prompt injection block with everything known about Captain."""
        profile = self.get_full_profile()
        favorites = self.get_favorites()
        lessons = self.get_lessons()
        auto_facts = self.get_recent_autonomous_facts(limit=10)

        lines = []
        if profile:
            lines.append("CAPTAIN'S PERSONAL PROFILE & PREFERENCES:")
            for k, v in profile.items():
                lines.append(f" - {k.replace('_', ' ').title()}: {v}")

        # Explicit saved memory items (preferences, notes)
        try:
            with self._connect() as conn:
                m_rows = conn.execute(
                    "SELECT kind, content FROM memory_items ORDER BY id DESC LIMIT 8"
                ).fetchall()
                if m_rows:
                    lines.append("SAVED PERSONAL NOTES & PREFERENCES:")
                    for mr in m_rows:
                        lines.append(f" - ({mr['kind']}) {mr['content']}")
        except Exception:
            pass

        if auto_facts:
            lines.append("ORGANICALLY OBSERVED FACTS ABOUT CAPTAIN:")
            for af in auto_facts:
                lines.append(f" - [{af['subject']}]: {af['fact']}")

        # Recent episodic conversation sessions
        try:
            with self._connect() as conn:
                ep_rows = conn.execute(
                    "SELECT session_date, summary FROM episodic_sessions ORDER BY id DESC LIMIT 5"
                ).fetchall()
                if ep_rows:
                    lines.append("RECENT CONVERSATION SESSIONS & TIMELINE:")
                    for er in ep_rows:
                        lines.append(f" - [{er['session_date']}]: {er['summary']}")
        except Exception:
            pass

        if favorites:
            lines.append("CAPTAIN'S FAVORITE SONGS & ARTISTS:")
            for f in favorites[:8]:
                art = f" (by {f['artist_or_author']})" if f.get("artist_or_author") else ""
                lines.append(f" - {f['title']}{art}")

        if lessons:
            lines.append("LESSONS LEARNED FROM PAST INTERACTIONS:")
            for l in lessons[:5]:
                lines.append(f" - [{l['topic']}]: {l['lesson']}")

        return "\n".join(lines).strip()

    def recall_comprehensive_memory(self, query: str, limit: int = 5) -> str:
        """Search and synthesize memories, profile entries, autonomous facts, and episodic sessions."""
        cleaned_query = str(query).strip().casefold()
        results: list[str] = []

        # 1. Check profile keys and values
        profile = self.get_full_profile()
        matched_profile = []
        query_words = [w for w in cleaned_query.split() if len(w) > 2]
        for k, v in profile.items():
            k_clean = k.replace("_", " ").casefold()
            v_clean = str(v).casefold()
            if not query_words or any(w in k_clean or w in v_clean for w in query_words):
                matched_profile.append(f"{k.replace('_', ' ').title()}: {v}")
        if matched_profile:
            results.append("CAPTAIN PROFILE DETAILS:\n" + "\n".join(f" - {p}" for p in matched_profile[:8]))

        # 2. Search autonomous facts
        auto_facts = self.search_autonomous_facts(query, limit=limit)
        if auto_facts:
            results.append("LEARNED FACTS:\n" + "\n".join(f" - [{af['subject']}]: {af['fact']}" for af in auto_facts))

        # 3. Search explicit memories
        recalled_items = self.search_items(query, limit=limit)
        if recalled_items:
            results.append("SAVED NOTES & PREFERENCES:\n" + "\n".join(f" - ({item.kind}) {item.content}" for item in recalled_items))

        # 4. Search episodic past sessions
        try:
            from episodic_memory import EpisodicMemoryStore
            ep_store = EpisodicMemoryStore(self.database_path)
            episodes = ep_store.search_episodes(query, limit=3)
            if episodes:
                results.append("PAST SESSIONS / TIMELINE:\n" + "\n".join(f" - [{ep.session_date}]: {ep.summary}" for ep in episodes))
        except Exception:
            pass

        # 5. Search favorites
        favs = self.get_favorites()
        matched_favs = [
            f for f in favs
            if any(w in f["title"].casefold() or w in f.get("artist_or_author", "").casefold() for w in query_words)
        ]
        if matched_favs:
            results.append("FAVORITES:\n" + "\n".join(f" - {f['title']}" + (f" by {f['artist_or_author']}" if f.get('artist_or_author') else "") for f in matched_favs[:4]))

        if not results:
            summary = self.get_formatted_captain_knowledge_summary()
            return summary or f"Captain, '{query}' se related koi memory ya record nahi mila."

        return "\n\n".join(results)

    def close(self) -> None:
        """Compatibility hook; connections are short-lived per operation."""

    @staticmethod
    def _validate_content(content: str, maximum: int) -> MemoryResult | None:
        if not content:
            return MemoryResult(
                False,
                "remember",
                "Empty content save nahi kiya.",
                error="empty_content",
            )
        if len(content) > maximum:
            return MemoryResult(
                False,
                "remember",
                f"Content maximum {maximum} characters ka ho sakta hai.",
                error="content_too_long",
            )
        if contains_sensitive_data(content):
            return MemoryResult(
                False,
                "remember",
                (
                    "Sensitive data memory mein save nahi kiya. API keys, "
                    "passwords, OTPs, payment data aur private clipboard blocked hain."
                ),
                error="sensitive_data",
            )
        return None

    @staticmethod
    def _database_error(action: str, exc: Exception) -> MemoryResult:
        return MemoryResult(
            False,
            action,
            "Local memory database operation fail hui; app continue rahegi.",
            {"exception_type": type(exc).__name__},
            "database_error",
        )

    @staticmethod
    def _reminder_from_row(row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=int(row["id"]),
            message=str(row["message"]),
            due_at=datetime.fromisoformat(str(row["due_at_utc"])),
            created_at=str(row["created_at"]),
            delivered_at=(
                str(row["delivered_at"])
                if row["delivered_at"] is not None
                else None
            ),
        )


class ReminderMonitor:
    """Poll due reminders in a lightweight daemon while the CLI is idle."""

    def __init__(
        self,
        store: SQLiteMemoryStore,
        callback: ReminderCallback,
        *,
        poll_seconds: float = 1.0,
    ) -> None:
        self._store = store
        self._callback = callback
        self._poll_seconds = min(max(float(poll_seconds), 0.05), 60.0)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start one daemon polling thread if it is not already active."""

        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="darkshadow-reminder-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop polling and wait briefly for deterministic cleanup."""

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                reminders = self._store.pop_due_reminders()
            except Exception as exc:
                LOGGER.warning(
                    "Reminder polling failed (type=%s)", type(exc).__name__
                )
                reminders = ()
            for reminder in reminders:
                if self._stop_event.is_set():
                    return
                try:
                    self._callback(reminder)
                except Exception as exc:
                    LOGGER.warning(
                        "Reminder callback failed (type=%s)", type(exc).__name__
                    )
                    continue
            self._stop_event.wait(self._poll_seconds)


def parse_memory_command(
    text: str,
    *,
    now: datetime | None = None,
) -> ParsedMemoryCommand | None:
    """Parse explicit memory/note/reminder commands without a model."""

    cleaned = str(text).strip()
    if not cleaned:
        return None
    current = now or datetime.now().astimezone()

    if re.fullmatch(
        r"(?:/memories|what do you remember\??|kya yaad hai\??)",
        cleaned,
        re.IGNORECASE,
    ):
        return ParsedMemoryCommand("list_items")
    if re.fullmatch(r"(?:/notes|show notes|list notes)", cleaned, re.IGNORECASE):
        return ParsedMemoryCommand("list_items", {"kind": "note"})
    if re.fullmatch(
        r"(?:/reminders|show reminders|list reminders)",
        cleaned,
        re.IGNORECASE,
    ):
        return ParsedMemoryCommand("list_reminders")
    if re.fullmatch(r"(?:/remember|remember\s+(?:this|that))", cleaned, re.IGNORECASE):
        return ParsedMemoryCommand(
            "add_item",
            {"kind": "preference", "content": ""},
        )
    if re.fullmatch(r"/note", cleaned, re.IGNORECASE):
        return ParsedMemoryCommand(
            "add_item",
            {"kind": "note", "content": ""},
        )
    if re.fullmatch(r"(?:/remind|remind\s+me)", cleaned, re.IGNORECASE):
        return ParsedMemoryCommand(
            "invalid_reminder",
            {"message": "Format: remind me tomorrow at 09:00 to call Rahul"},
        )

    match = re.fullmatch(
        r"(?:/remember\s+|remember\s+(?:this|that)(?::|\s+)|"
        r"yaad\s+rakho(?:\s+ki)?\s+)(.+)",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        return ParsedMemoryCommand(
            "add_item",
            {"kind": "preference", "content": match.group(1).strip()},
        )

    match = re.fullmatch(r"remember\s+(.+)", cleaned, re.IGNORECASE)
    if match:
        content = re.sub(
            r"(?:,?\s+(?:ok|okay))?[.!]*$",
            "",
            match.group(1).strip(),
            flags=re.IGNORECASE,
        ).strip()
        return ParsedMemoryCommand(
            "add_item",
            {"kind": "preference", "content": content},
        )

    match = re.fullmatch(
        r"(.+?)\s+yaad\s+rakh(?:o|na|ana)(?:\s+(?:hai|na))?"
        r"(?:\s+(?:ok|okay))?[.!?]*",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        content = match.group(1).strip()
        if re.fullmatch(r"(?:ye|yeh|this|woh|wo)\b.*", content, re.IGNORECASE):
            return ParsedMemoryCommand("missing_memory_subject")
        return ParsedMemoryCommand(
            "add_item",
            {"kind": "preference", "content": content},
        )

    match = re.fullmatch(
        r"(?:/note\s+|note\s*:\s*|save\s+(?:a\s+)?note\s+)(.+)",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        return ParsedMemoryCommand(
            "add_item",
            {"kind": "note", "content": match.group(1).strip()},
        )

    match = re.fullmatch(
        r"(?:/forget|forget)(?:\s+(?:memory|note))?\s+#?(\d+)",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        return ParsedMemoryCommand("forget_item", {"item_id": int(match.group(1))})
    match = re.fullmatch(
        r"forget\s+this\s*:\s*(.+)",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        return ParsedMemoryCommand(
            "forget_item", {"content": match.group(1).strip()}
        )
    if re.fullmatch(r"forget\s+this", cleaned, re.IGNORECASE):
        return ParsedMemoryCommand("forget_item")

    match = re.fullmatch(
        r"(?:/delete-reminder|delete\s+reminder)\s+#?(\d+)",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        return ParsedMemoryCommand(
            "delete_reminder", {"reminder_id": int(match.group(1))}
        )

    reminder = _parse_reminder_command(cleaned, current)
    if reminder is not None:
        return reminder
    return None


def _parse_reminder_command(
    text: str,
    now: datetime,
) -> ParsedMemoryCommand | None:
    prefix = re.match(r"^(?:/remind|remind\s+me)\s+(.+)$", text, re.IGNORECASE)
    if prefix is None:
        return None
    body = prefix.group(1).strip()
    patterns = (
        re.fullmatch(
            r"(?:on\s+)?(today|tomorrow|\d{4}-\d{2}-\d{2})\s+"
            r"(?:at\s+)?(\d{1,2}:\d{2})\s+(?:to\s+)?(.+)",
            body,
            re.IGNORECASE,
        ),
        re.fullmatch(
            r"at\s+(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})\s+"
            r"(?:to\s+)?(.+)",
            body,
            re.IGNORECASE,
        ),
    )
    match = next((candidate for candidate in patterns if candidate), None)
    if match is None:
        return ParsedMemoryCommand(
            "invalid_reminder",
            {"message": "Format: remind me tomorrow at 09:00 to call Rahul"},
        )
    date_token, time_token, message = match.groups()
    try:
        hour_text, minute_text = time_token.split(":", maxsplit=1)
        hour, minute = int(hour_text), int(minute_text)
        if hour > 23 or minute > 59:
            raise ValueError
        if date_token.casefold() == "today":
            target_date = now.date()
        elif date_token.casefold() == "tomorrow":
            target_date = (now + timedelta(days=1)).date()
        else:
            target_date = datetime.strptime(date_token, "%Y-%m-%d").date()
        due_at = datetime.combine(target_date, datetime.min.time()).replace(
            hour=hour,
            minute=minute,
            tzinfo=now.tzinfo,
        )
    except (TypeError, ValueError):
        return ParsedMemoryCommand(
            "invalid_reminder",
            {"message": "Reminder date/time invalid hai."},
        )
    return ParsedMemoryCommand(
        "add_reminder",
        {"message": message.strip(), "due_at": due_at},
    )


def handle_memory_command(
    text: str,
    store: SQLiteMemoryStore | None,
    *,
    now: datetime | None = None,
) -> MemoryResult | None:
    """Parse and execute one explicit local memory command."""

    command = parse_memory_command(text, now=now)
    if command is None:
        return None
    if store is None:
        return MemoryResult(
            False,
            "memory",
            (
                "Persistent memory opt-in disabled hai. `.env` mein "
                "DARKSHADOW_MEMORY_ENABLED=true set karke restart kijiye."
            ),
            error="memory_disabled",
        )
    if command.action == "invalid_reminder":
        return MemoryResult(
            False,
            "reminder",
            str(command.arguments["message"]),
            error="invalid_reminder_format",
        )
    if command.action == "missing_memory_subject":
        return MemoryResult(
            False,
            "remember",
            "Memory save karne ke liye naam bhi likhiye, jaise: 'Shumit mera dost hai, yaad rakhana'.",
            error="missing_memory_subject",
        )
    try:
        if command.action == "list_items":
            items = store.list_items(**command.arguments)
            if not items:
                return MemoryResult(
                    True,
                    "list_memory",
                    "Koi matching saved memory nahi hai.",
                    {"count": 0},
                )
            lines = [f"#{item.id} [{item.kind}] {item.content}" for item in items]
            return MemoryResult(
                True,
                "list_memory",
                "Saved memory:\n" + "\n".join(lines),
                {"count": len(items)},
            )
        if command.action == "list_reminders":
            reminders = store.list_reminders()
            if not reminders:
                return MemoryResult(
                    True,
                    "list_reminders",
                    "Koi pending reminder nahi hai.",
                    {"count": 0},
                )
            lines = [
                (
                    f"#{reminder.id} "
                    f"{reminder.due_at.astimezone().strftime('%d %b %Y %I:%M %p')}"
                    f" - {reminder.message}"
                )
                for reminder in reminders
            ]
            return MemoryResult(
                True,
                "list_reminders",
                "Pending reminders:\n" + "\n".join(lines),
                {"count": len(reminders)},
            )
        method = getattr(store, command.action, None)
        if not callable(method):
            return MemoryResult(
                False,
                "memory",
                "Memory action allowlist mein nahi hai.",
                error="action_not_allowed",
            )
        return method(**command.arguments)
    except (sqlite3.Error, OSError) as exc:
        return MemoryResult(
            False,
            command.action,
            "Local memory database unavailable hai; app continue rahegi.",
            {"exception_type": type(exc).__name__},
            "database_error",
        )


def recall_memory(
    text: str,
    store: SQLiteMemoryStore | None,
) -> MemoryResult | None:
    """Answer an explicit personal-fact question from opt-in local memory."""

    if store is None:
        return None
    cleaned = " ".join(str(text).strip().split())
    patterns = (
        r"^(?:who\s+is|who's)\s+(.+?)[?.!]*$",
        r"^(.+?)\s+(?:kaun|kon|koun|kau)\s+(?:hai|h)"
        r"(?:\s+(?:ye\s+)?batao)?[?.!]*$",
        r"^(?:what\s+do\s+you\s+know\s+about|tell\s+me\s+about)\s+(.+?)[?.!]*$",
        r"^(?:mera|meri|my)\s+(.+?)\s+(?:kya|kab|kaun|kon)\s+(?:hai|h)[?.!]*$",
        r"^(?:what\s+is|what's|tell\s+me)\s+(?:my|captain's)\s+(.+?)[?.!]*$",
        r"^(?:do\s+you\s+remember|kya\s+tumhe\s+yaad\s+hai|kya\s+yaad\s+hai)\s+(.+?)[?.!]*$",
    )
    target = ""
    for pattern in patterns:
        match = re.fullmatch(pattern, cleaned, re.IGNORECASE)
        if match:
            target = match.group(1).strip(" .?!")
            break
    if not target and re.search(
        r"\b(?:friend|friends|dost|doston)\b", cleaned, re.IGNORECASE
    ):
        target = "friend"
    if not target and re.search(
        r"\b(?:mujhe\s+kya\s+pasand|my\s+preferences|what\s+do\s+i\s+like|mene\s+kya\s+bataya|what\s+did\s+i\s+tell)\b",
        cleaned,
        re.IGNORECASE,
    ):
        target = "preference"

    if not target:
        return None
    try:
        matches = store.search_items(target, limit=3)
        if not matches and target == "preference":
            matches = store.list_items(limit=3)
    except (sqlite3.Error, OSError):
        return None
    if not matches:
        return None
    item = matches[0]
    normalized = _normalize_content(item.content)
    target_name = target.strip().title()
    if "best friend" in normalized or "best dost" in normalized:
        message = (
            f"Captain, {target_name} aapke best friend hain—ye meri saved "
            "memory mein hai."
        )
    elif "friend" in normalized or "dost" in normalized:
        message = (
            f"Captain, {target_name} aapke dost hain—ye meri saved memory "
            "mein hai."
        )
    else:
        message = f"Captain, meri saved memory ke mutabik: {item.content}"
    return MemoryResult(
        True,
        "recall_memory",
        message,
        {"id": item.id, "kind": item.kind},
    )


__all__ = [
    "MemoryItem",
    "MemoryResult",
    "ParsedMemoryCommand",
    "Reminder",
    "ReminderMonitor",
    "SQLiteMemoryStore",
    "contains_sensitive_data",
    "handle_memory_command",
    "parse_memory_command",
    "recall_memory",
]
