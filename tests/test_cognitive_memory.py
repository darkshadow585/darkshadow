"""Tests for Cognitive Memory 2.0: Vector Semantic Search, Episodic Memory, and Conflict Resolution."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from config import load_settings
from memory import SQLiteMemoryStore
from vector_memory import VectorEmbedder, VectorMemoryStore
from episodic_memory import (
    EpisodicMemoryStore,
    EpisodicMemorySummarizer,
    EpisodicMemoryRetriever,
)
from auto_memory import AutonomousMemoryDistiller, AutonomousMemoryRetriever
from chatbot import DarkShadowChatbot, ConversationTurn


class TestCognitiveMemory(unittest.TestCase):
    """Verify all Cognitive Memory 2.0 components."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_cognitive_mem.db"
        self.memory_store = SQLiteMemoryStore(self.db_path)
        self.settings = load_settings()

    def tearDown(self) -> None:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    # =========================================================================
    # 1. VECTOR EMBEDDINGS & SEMANTIC SEARCH
    # =========================================================================
    def test_vector_embedder_normalization(self) -> None:
        """Verify vector embedder returns normalized float32 vectors with norm approx 1.0."""
        embedder = VectorEmbedder()
        vec = embedder.get_embedding("Captain loves programming in Python")
        self.assertIsInstance(vec, np.ndarray)
        self.assertEqual(vec.dtype, np.float32)
        norm = float(np.linalg.norm(vec))
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_vector_semantic_search_retrieval(self) -> None:
        """Verify vector memory store performs cosine similarity search on BLOBs."""
        vec_store = VectorMemoryStore(self.db_path)
        vec_store.upsert_embedding(item_id=1, item_type="fact", text="Captain loves software development and Python coding")
        vec_store.upsert_embedding(item_id=2, item_type="fact", text="Captain enjoys playing acoustic guitar and music")

        # Query about programming using words not in the text
        results = vec_store.search_similar(query="software engineering programming", item_type="fact", limit=1, min_similarity=0.20)
        self.assertGreaterEqual(len(results), 1)
        # First match should be item_id 1
        self.assertEqual(results[0][0], 1)
        self.assertGreater(results[0][2], 0.3)

    def test_autonomous_fact_vector_search_integration(self) -> None:
        """Verify memory_store.search_autonomous_facts uses vector similarity search."""
        self.memory_store.store_autonomous_fact(
            category="preference",
            subject="music",
            fact="Captain loves listening to relaxing lofi beats while working",
        )
        # Search using conceptual phrase
        matches = self.memory_store.search_autonomous_facts("relaxing background songs", limit=3)
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0]["subject"], "music")
        self.assertIn("lofi beats", matches[0]["fact"])

    # =========================================================================
    # 2. ROLLING EPISODIC MEMORY TESTS
    # =========================================================================
    def test_episodic_memory_store_and_search(self) -> None:
        """Verify episodic sessions can be stored and recalled."""
        ep_store = EpisodicMemoryStore(self.db_path)
        ep_id = ep_store.store_episode(
            summary="Captain and DarkShadow discussed integrating vector embeddings into SQLite memory.",
            topics="memory, vector, sqlite",
        )
        self.assertGreater(ep_id, 0)

        episodes = ep_store.get_recent_episodes(limit=5)
        self.assertEqual(len(episodes), 1)
        self.assertIn("vector embeddings", episodes[0].summary)

    def test_episodic_retriever_temporal_detection(self) -> None:
        """Verify EpisodicMemoryRetriever identifies temporal / history questions."""
        ep_store = EpisodicMemoryStore(self.db_path)
        retriever = EpisodicMemoryRetriever(ep_store)

        self.assertTrue(retriever.is_temporal_query("pichhle session me humne kya baat ki thi"))
        self.assertTrue(retriever.is_temporal_query("what did we discuss yesterday"))
        self.assertTrue(retriever.is_temporal_query("kal humne kya decide kiya tha"))
        self.assertFalse(retriever.is_temporal_query("Delhi weather today"))
        self.assertFalse(retriever.is_temporal_query("open Chrome"))

    def test_chatbot_history_eviction_triggers_episodic_summary(self) -> None:
        """Verify when history deque is full, the evicted oldest turn is archived to episodic memory."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock(text="Captain aur DarkShadow ne test kiya.")

        bot = DarkShadowChatbot(settings=self.settings, client=mock_client)
        # Fill deque to capacity
        capacity = bot._history.maxlen or 8
        for i in range(capacity):
            bot._history.append(ConversationTurn(user_text=f"User turn {i}", assistant_text=f"Assistant turn {i}"))

        self.assertEqual(len(bot._history), capacity)
        oldest_user_turn = bot._history[0].user_text

        # Now respond, which should trigger eviction of the oldest turn
        with patch.object(bot, "_request_gemini", return_value="Captain, agla turn ready hai."):
            with patch("episodic_memory.EpisodicMemorySummarizer.summarize_evicted_turn_async") as mock_summarize:
                bot.respond("Naya turn", memory_store=self.memory_store)
                mock_summarize.assert_called_once()
                args, _ = mock_summarize.call_args
                self.assertEqual(args[0], oldest_user_turn)

    # =========================================================================
    # 3. MEMORY CONFLICT RESOLUTION & CONSOLIDATION
    # =========================================================================
    def test_memory_conflict_resolution_supersedes_old_fact(self) -> None:
        """Verify contradictory or updating statements supersede older facts."""
        distiller = AutonomousMemoryDistiller(self.memory_store)

        # 1. First statement: Likes coffee
        res1 = self.memory_store.store_autonomous_fact(
            category="preference",
            subject="beverage",
            fact="Captain loves drinking strong coffee in morning",
        )
        fact1_id = res1.data.get("id")

        # 2. Second statement: Stopped coffee, now drinks green tea
        res2 = self.memory_store.store_autonomous_fact(
            category="preference",
            subject="beverage",
            fact="Captain ne coffee chhod di ab green tea peete hain",
        )
        fact2_id = res2.data.get("id")

        # Run conflict resolution
        distiller._resolve_conflicts(
            category="preference",
            subject="beverage",
            new_fact="Captain ne coffee chhod di ab green tea peete hain",
            new_fact_id=fact2_id,
        )

        # Check in DB
        with self.memory_store._connect() as conn:
            old_row = conn.execute("SELECT status, superseded_by FROM autonomous_facts WHERE id = ?", (fact1_id,)).fetchone()
            new_row = conn.execute("SELECT status, superseded_by FROM autonomous_facts WHERE id = ?", (fact2_id,)).fetchone()

            self.assertEqual(old_row["status"], "superseded")
            self.assertEqual(old_row["superseded_by"], fact2_id)
            self.assertEqual(new_row["status"], "active")

        # Verify get_recent_autonomous_facts only returns the active fact
        recent = self.memory_store.get_recent_autonomous_facts(limit=10)
        facts_list = [r["fact"] for r in recent]
        self.assertIn("Captain ne coffee chhod di ab green tea peete hain", facts_list)
        self.assertNotIn("Captain loves drinking strong coffee in morning", facts_list)


if __name__ == "__main__":
    unittest.main()
