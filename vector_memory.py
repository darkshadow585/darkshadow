"""Vector Semantic Memory & Dense Embedding Engine for DarkShadow.

Provides:
1. VectorEmbedder: Generates dense normalized embeddings via Gemini (gemini-embedding-2)
   with an automatic local n-gram vectorizer fallback for offline operation.
2. VectorMemoryStore: Stores packed float32 BLOB vectors in SQLite and executes
   vectorized cosine similarity searches in numpy with <2ms latency.
3. Hybrid Search: FTS5 full-text keyword search fused with dense vector cosine
   similarity via Reciprocal Rank Fusion (RRF) for exact name/keyword recall
   alongside semantic understanding.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

LOGGER = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIM = 768
LOCAL_FALLBACK_DIM = 256


class VectorEmbedder:
    """Generates normalized vector embeddings for text using Gemini Embedding 2 or local fallback."""

    def __init__(
        self,
        gemini_client: Any = None,
        model_name: str = "gemini-embedding-2",
        api_key: str | None = None,
    ) -> None:
        if gemini_client is None and api_key:
            try:
                from automation import _get_cached_genai_client
                gemini_client = _get_cached_genai_client(api_key)
            except Exception:
                try:
                    from google import genai
                    gemini_client = genai.Client(api_key=api_key)
                except Exception:
                    pass
        self.gemini_client = gemini_client
        self.model_name = model_name or "gemini-embedding-2"
        self._cache: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    def get_embedding(self, text: str) -> np.ndarray:
        """Return a normalized 1D float32 numpy array for text."""
        cleaned = " ".join(str(text).strip().casefold().split())
        if not cleaned:
            return np.zeros(DEFAULT_EMBEDDING_DIM, dtype=np.float32)

        cache_key = hashlib.md5(f"{self.model_name}:{cleaned}".encode("utf-8")).hexdigest()
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        vec: np.ndarray | None = None

        # 1. Try Gemini Embedding Models API with progressive fallback
        if self.gemini_client is not None:
            models_to_try = [self.model_name]
            for fallback in ("gemini-embedding-2", "gemini-embedding-001", "text-embedding-004"):
                if fallback not in models_to_try:
                    models_to_try.append(fallback)

            for candidate_model in models_to_try:
                try:
                    resp = self.gemini_client.models.embed_content(
                        model=candidate_model,
                        contents=cleaned,
                    )
                    raw_vec = None
                    if hasattr(resp, "embeddings") and resp.embeddings:
                        raw_vec = getattr(resp.embeddings[0], "values", resp.embeddings[0])
                    elif hasattr(resp, "embedding") and resp.embedding:
                        raw_vec = getattr(resp.embedding, "values", resp.embedding)

                    if raw_vec:
                        vec = np.array(raw_vec, dtype=np.float32)
                        break
                except Exception as exc:
                    LOGGER.debug("Gemini embed_content (%s) notice: %s", candidate_model, exc)

        # 2. Local deterministic fallback (fast n-gram hashing)
        if vec is None:
            vec = self._local_fallback_embedding(cleaned, dim=DEFAULT_EMBEDDING_DIM)

        # Normalize vector for cosine similarity
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        with self._lock:
            # Maintain small LRU-style cache
            if len(self._cache) > 2000:
                self._cache.clear()
            self._cache[cache_key] = vec

        return vec

    @staticmethod
    def _local_fallback_embedding(text: str, dim: int = DEFAULT_EMBEDDING_DIM) -> np.ndarray:
        """Deterministic, lightweight local n-gram frequency hash vector."""
        vec = np.zeros(dim, dtype=np.float32)
        words = text.split()
        for word in words:
            # Word hash
            h_word = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            vec[h_word % dim] += 1.5
            # Character bigrams
            for i in range(len(word) - 1):
                bi = word[i : i + 2]
                h_bi = int(hashlib.md5(bi.encode("utf-8")).hexdigest(), 16)
                vec[h_bi % dim] += 0.5

        # Normalization
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


@dataclass(frozen=True, slots=True)
class SemanticSearchResult:
    """Result from a vector semantic search."""

    item_id: int
    item_type: str
    similarity: float
    content: str
    metadata: dict[str, Any]


class VectorMemoryStore:
    """Manages SQLite vector embeddings and performs cosine similarity queries."""

    def __init__(self, db_path: Path | str, embedder: VectorEmbedder | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.embedder = embedder or VectorEmbedder()
        self.ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self) -> None:
        """Ensure schema exists for memory embeddings, FTS5 indexes, and personal RAG documents."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    item_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (item_id, item_type)
                )
                """
            )
            # FTS5 full-text index for exact keyword/name recall on memories.
            # unicode61 with remove_diacritics handles Hindi/Hinglish/English naturally.
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    item_id UNINDEXED,
                    item_type UNINDEXED,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_rag_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_file_path ON personal_rag_documents(file_path)"
            )
            # FTS5 full-text index for exact keyword recall on RAG documents.
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts
                USING fts5(
                    doc_id UNINDEXED,
                    file_name,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )

    def upsert_embedding(self, item_id: int, item_type: str, text: str) -> None:
        """Compute and store binary float32 vector embedding and FTS5 text for an item."""
        vec = self.embedder.get_embedding(text)
        blob = vec.tobytes()
        dim = len(vec)
        now_str = ""
        try:
            from datetime import datetime, timezone
            now_str = datetime.now(timezone.utc).isoformat()
        except Exception:
            pass

        with self._connect() as conn:
            # 1. Dense vector embedding table
            conn.execute(
                """
                INSERT INTO memory_embeddings (item_id, item_type, embedding, dimension, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id, item_type) DO UPDATE SET
                    embedding = excluded.embedding,
                    dimension = excluded.dimension,
                    created_at = excluded.created_at
                """,
                (item_id, item_type, blob, dim, now_str),
            )
            # 2. FTS5 full-text index (delete-then-insert for idempotent upsert)
            try:
                conn.execute(
                    "DELETE FROM memory_fts WHERE item_id = ? AND item_type = ?",
                    (str(item_id), item_type),
                )
                conn.execute(
                    "INSERT INTO memory_fts (item_id, item_type, content) VALUES (?, ?, ?)",
                    (str(item_id), item_type, text),
                )
            except Exception as fts_exc:
                LOGGER.debug("FTS5 upsert notice: %s", fts_exc)

    def search_similar(
        self,
        query: str,
        item_type: str | None = None,
        limit: int = 5,
        min_similarity: float = 0.50,
    ) -> list[tuple[int, str, float]]:
        """Find stored items with highest cosine similarity to query.

        Returns list of (item_id, item_type, similarity_score).
        """
        query_vec = self.embedder.get_embedding(query)
        if len(query_vec) == 0:
            return []

        try:
            with self._connect() as conn:
                if item_type:
                    rows = conn.execute(
                        "SELECT item_id, item_type, embedding, dimension FROM memory_embeddings WHERE item_type = ?",
                        (item_type,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT item_id, item_type, embedding, dimension FROM memory_embeddings"
                    ).fetchall()

                if not rows:
                    return []

                item_ids = []
                item_types = []
                vectors = []

                for r in rows:
                    blob = r["embedding"]
                    dim = int(r["dimension"])
                    if len(blob) == dim * 4:  # float32 = 4 bytes
                        v = np.frombuffer(blob, dtype=np.float32)
                        # Handle dimension mismatch if any
                        if len(v) == len(query_vec):
                            item_ids.append(int(r["item_id"]))
                            item_types.append(str(r["item_type"]))
                            vectors.append(v)

                if not vectors:
                    return []

                matrix = np.vstack(vectors)  # Shape: (N, D)
                # Cosine similarity: dot product of normalized vectors
                sims = np.dot(matrix, query_vec)  # Shape: (N,)

                results = []
                for idx in range(len(sims)):
                    score = float(sims[idx])
                    if score >= min_similarity:
                        results.append((item_ids[idx], item_types[idx], round(score, 4)))

                results.sort(key=lambda x: x[2], reverse=True)
                return results[:limit]

        except Exception as exc:
            LOGGER.warning("Vector search error: %s", exc)
            return []

    def _fts5_search_memory(
        self,
        query: str,
        item_type: str | None = None,
        limit: int = 15,
    ) -> list[tuple[int, str, float]]:
        """Run FTS5 MATCH query on memory_fts and return (item_id, item_type, bm25_score).

        Uses OR-joined tokens for broad recall (matching any word in the query).
        BM25 scores are negative in SQLite FTS5 (lower = better match), so they
        are negated for consistent ascending ranking.
        """
        cleaned = " ".join(query.strip().split())
        if not cleaned:
            return []
        # OR-join all words for broad keyword recall
        fts_query = " OR ".join(
            word for word in cleaned.split() if len(word) >= 2
        )
        if not fts_query:
            fts_query = cleaned
        try:
            with self._connect() as conn:
                if item_type:
                    rows = conn.execute(
                        "SELECT item_id, item_type, bm25(memory_fts) AS score "
                        "FROM memory_fts WHERE item_type = ? AND memory_fts MATCH ? "
                        "ORDER BY score LIMIT ?",
                        (item_type, fts_query, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT item_id, item_type, bm25(memory_fts) AS score "
                        "FROM memory_fts WHERE memory_fts MATCH ? "
                        "ORDER BY score LIMIT ?",
                        (fts_query, limit),
                    ).fetchall()
                return [(int(r[0]), str(r[1]), float(r[2])) for r in rows]
        except Exception as exc:
            LOGGER.debug("FTS5 memory search notice: %s", exc)
            return []

    def hybrid_search(
        self,
        query: str,
        item_type: str | None = None,
        limit: int = 5,
        min_similarity: float = 0.35,
        rrf_k: int = 60,
        vector_weight: float = 0.6,
        fts_weight: float = 0.4,
    ) -> list[tuple[int, str, float]]:
        """Hybrid search: dense vector cosine + FTS5 keyword, fused with Reciprocal Rank Fusion.

        RRF formula: Score(d) = Σ(w_r / (k + rank_r(d)))
        where k=60, w_vec=0.6, w_fts=0.4.

        This ensures exact names like 'Rahul', phone numbers, and code error strings
        are found via FTS5 keyword match even when semantic embedding similarity is low,
        while conceptual/semantic queries still rank correctly via dense vectors.
        """
        # 1. Dense vector search (existing, with relaxed limit for fusion pool)
        vec_results = self.search_similar(
            query, item_type=item_type, limit=limit * 3, min_similarity=min_similarity,
        )

        # 2. FTS5 keyword search
        fts_results = self._fts5_search_memory(query, item_type=item_type, limit=limit * 3)

        # 3. Reciprocal Rank Fusion
        scores: dict[tuple[int, str], float] = {}
        for rank, (item_id, itype, _sim) in enumerate(vec_results):
            key = (item_id, itype)
            scores[key] = scores.get(key, 0.0) + vector_weight / (rrf_k + rank + 1)
        for rank, (item_id, itype, _bm25) in enumerate(fts_results):
            key = (item_id, itype)
            scores[key] = scores.get(key, 0.0) + fts_weight / (rrf_k + rank + 1)

        if not scores:
            return []

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(k[0], k[1], round(s, 6)) for k, s in ranked[:limit]]

    # =========================================================================
    # PERSONAL DOCUMENT RAG & KNOWLEDGE BASE
    # =========================================================================

    def index_file(
        self,
        file_path: str | Path,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> dict[str, Any]:
        """Index a local text/markdown/code file into the personal RAG knowledge base."""
        p = Path(file_path).resolve()
        if not p.is_file():
            return {
                "success": False,
                "error": "file_not_found",
                "message": f"File '{file_path}' nahi mili.",
            }

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {
                "success": False,
                "error": "read_error",
                "message": f"File read nahi ho saki: {exc}",
            }

        words = content.split()
        if not words:
            return {"success": True, "chunks_indexed": 0, "message": "File empty hai."}

        chunks: list[str] = []
        step = max(1, chunk_size - overlap)
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + chunk_size]).strip()
            if chunk:
                chunks.append(chunk)

        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("DELETE FROM personal_rag_documents WHERE file_path = ?", (str(p),))
            # Also clear old FTS5 entries for this file
            try:
                conn.execute(
                    "DELETE FROM rag_fts WHERE doc_id IN "
                    "(SELECT id FROM personal_rag_documents WHERE file_path = ?)",
                    (str(p),),
                )
            except Exception:
                pass
            for idx, chunk in enumerate(chunks):
                vec = self.embedder.get_embedding(chunk)
                blob = vec.tobytes()
                conn.execute(
                    """
                    INSERT INTO personal_rag_documents
                    (file_path, file_name, chunk_index, content, embedding, dimension, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(p), p.name, idx, chunk, blob, len(vec), now_str, json.dumps({"word_count": len(chunk.split())})),
                )
                # Dual-index: also write chunk text to FTS5 for keyword recall
                try:
                    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        "INSERT INTO rag_fts (doc_id, file_name, content) VALUES (?, ?, ?)",
                        (str(doc_id), p.name, chunk),
                    )
                except Exception as fts_exc:
                    LOGGER.debug("RAG FTS5 index notice: %s", fts_exc)

        return {
            "success": True,
            "file_name": p.name,
            "file_path": str(p),
            "chunks_indexed": len(chunks),
            "message": f"File '{p.name}' successfully index ho gayi ({len(chunks)} chunks stored).",
        }

    def index_directory(
        self,
        dir_path: str | Path,
        extensions: tuple[str, ...] = (".txt", ".md", ".py", ".json", ".csv", ".log"),
        max_files: int = 100,
    ) -> dict[str, Any]:
        """Recursively index supported text files from a directory."""
        p = Path(dir_path).resolve()
        if not p.is_dir():
            return {
                "success": False,
                "error": "dir_not_found",
                "message": f"Directory '{dir_path}' nahi mili.",
            }

        indexed = 0
        total_chunks = 0
        for f in p.rglob("*"):
            if f.is_file() and f.suffix.lower() in extensions:
                res = self.index_file(f)
                if res.get("success"):
                    indexed += 1
                    total_chunks += int(res.get("chunks_indexed", 0))
                if indexed >= max_files:
                    break

        return {
            "success": True,
            "files_indexed": indexed,
            "total_chunks": total_chunks,
            "message": f"Total {indexed} files index ho gayi hain ({total_chunks} chunks stored).",
        }

    def search_knowledge_base(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.25,
    ) -> list[dict[str, Any]]:
        """Semantic dense vector search over indexed personal files and notes."""
        query_vec = self.embedder.get_embedding(query)
        if len(query_vec) == 0:
            return []

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, file_path, file_name, chunk_index, content, embedding, dimension FROM personal_rag_documents"
                ).fetchall()
                if not rows:
                    return []

                records = []
                vectors = []
                for r in rows:
                    blob = r["embedding"]
                    dim = int(r["dimension"])
                    if len(blob) == dim * 4:
                        v = np.frombuffer(blob, dtype=np.float32)
                        if len(v) == len(query_vec):
                            records.append(r)
                            vectors.append(v)

                if not vectors:
                    return []

                matrix = np.vstack(vectors)
                sims = np.dot(matrix, query_vec)

                results = []
                for idx in range(len(sims)):
                    score = float(sims[idx])
                    if score >= min_similarity:
                        rec = records[idx]
                        results.append({
                            "id": int(rec["id"]),
                            "file_name": str(rec["file_name"]),
                            "file_path": str(rec["file_path"]),
                            "chunk_index": int(rec["chunk_index"]),
                            "content": str(rec["content"]),
                            "similarity": round(score, 4),
                        })

                results.sort(key=lambda x: x["similarity"], reverse=True)
                return results[:limit]
        except Exception as exc:
            LOGGER.warning("Knowledge base search error: %s", exc)
            return []

    def _fts5_search_rag(
        self,
        query: str,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        """Run FTS5 MATCH query on rag_fts and return matching RAG document chunks."""
        cleaned = " ".join(query.strip().split())
        if not cleaned:
            return []
        fts_query = " OR ".join(
            word for word in cleaned.split() if len(word) >= 2
        )
        if not fts_query:
            fts_query = cleaned
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT rf.doc_id, rf.file_name, rf.content, bm25(rag_fts) AS score "
                    "FROM rag_fts rf WHERE rag_fts MATCH ? "
                    "ORDER BY score LIMIT ?",
                    (fts_query, limit),
                ).fetchall()
                results = []
                for r in rows:
                    doc_id = int(r[0])
                    # Fetch full metadata from the main RAG table
                    meta_row = conn.execute(
                        "SELECT id, file_path, file_name, chunk_index, content "
                        "FROM personal_rag_documents WHERE id = ?",
                        (doc_id,),
                    ).fetchone()
                    if meta_row:
                        results.append({
                            "id": int(meta_row["id"]),
                            "file_name": str(meta_row["file_name"]),
                            "file_path": str(meta_row["file_path"]),
                            "chunk_index": int(meta_row["chunk_index"]),
                            "content": str(meta_row["content"]),
                            "similarity": float(r[3]),  # BM25 score
                        })
                    else:
                        results.append({
                            "id": doc_id,
                            "file_name": str(r[1]),
                            "file_path": "",
                            "chunk_index": 0,
                            "content": str(r[2]),
                            "similarity": float(r[3]),
                        })
                return results
        except Exception as exc:
            LOGGER.debug("FTS5 RAG search notice: %s", exc)
            return []

    def hybrid_search_knowledge_base(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.25,
        rrf_k: int = 60,
        vector_weight: float = 0.6,
        fts_weight: float = 0.4,
    ) -> list[dict[str, Any]]:
        """Hybrid dense vector + FTS5 keyword search over indexed personal files.

        Uses Reciprocal Rank Fusion (RRF) to merge dense semantic results with
        FTS5 exact keyword matches. Ensures file names, function names, and exact
        code strings are recalled alongside conceptual semantic queries.
        """
        # 1. Dense vector search
        vec_results = self.search_knowledge_base(
            query, limit=limit * 3, min_similarity=min_similarity,
        )

        # 2. FTS5 keyword search
        fts_results = self._fts5_search_rag(query, limit=limit * 3)

        # 3. Reciprocal Rank Fusion by doc ID
        scores: dict[int, float] = {}
        meta: dict[int, dict[str, Any]] = {}

        for rank, item in enumerate(vec_results):
            doc_id = item["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + vector_weight / (rrf_k + rank + 1)
            meta[doc_id] = item

        for rank, item in enumerate(fts_results):
            doc_id = item["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + fts_weight / (rrf_k + rank + 1)
            if doc_id not in meta:
                meta[doc_id] = item

        if not scores:
            return []

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [meta[doc_id] for doc_id, _ in ranked[:limit] if doc_id in meta]



__all__ = [
    "VectorEmbedder",
    "VectorMemoryStore",
    "SemanticSearchResult",
    "DEFAULT_EMBEDDING_DIM",
]
