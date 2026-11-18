"""Tests for Live Voice Memory Integration, Persistent Recall, and Multilingual Distillation."""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import load_settings
from memory import SQLiteMemoryStore
from episodic_memory import EpisodicMemoryStore, EpisodicMemoryRetriever, EpisodicMemorySummarizer
from auto_memory import AutonomousMemoryDistiller
from automation import recall_captain_memory, AUTOMATION_FUNCTION_SCHEMAS


class TestLiveVoiceMemory(unittest.TestCase):
    """Verify Live Voice memory recall, multilingual distillation, and session archival."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_live_mem.db"
        self.memory_store = SQLiteMemoryStore(self.db_path)
        base_settings = load_settings()
        self.settings = dataclasses.replace(base_settings, memory_database_path=self.db_path)

    def tearDown(self) -> None:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def test_knowledge_summary_comprehensive_inclusion(self) -> None:
        """Verify get_formatted_captain_knowledge_summary includes profile, memories, facts, and episodes."""
        # 1. Profile
        self.memory_store.save_profile("college", "SHUATS University", "education")
        self.memory_store.save_profile("favorite_subjects", "Physics, Mathematics, Computer Science", "education")

        # 2. Memory items (explicit preference/notes)
        self.memory_store.remember("preference", "Mujhe black color pasand hai aur chai nahi pasand")

        # 3. Autonomous facts
        self.memory_store.store_autonomous_fact("personal", "coding_flow", "Captain loves listening to lofi while coding")

        # 4. Episodic session
        ep_store = EpisodicMemoryStore(self.db_path)
        ep_store.store_episode("Captain and DarkShadow discussed integrating Gemini Live Voice.", "voice, gemini")

        summary = self.memory_store.get_formatted_captain_knowledge_summary()

        self.assertIn("SHUATS University", summary)
        self.assertIn("Physics, Mathematics, Computer Science", summary)
        self.assertIn("black color pasand hai", summary)
        self.assertIn("lofi while coding", summary)
        self.assertIn("integrating Gemini Live Voice", summary)

    def test_recall_captain_memory_tool(self) -> None:
        """Verify recall_captain_memory returns targeted details for subject queries."""
        self.memory_store.save_profile("favorite_subjects", "Computer Science, Mathematics, Physics", "education")
        self.memory_store.save_profile("college", "SHUATS University", "education")

        with patch("config.load_settings", return_value=self.settings):
            res = recall_captain_memory("favorite subjects")
            self.assertTrue(res.success)
            self.assertIn("Computer Science", res.message)
            self.assertIn("Favorite Subjects", res.data.get("memory", ""))

    def test_multilingual_distillation_hinglish(self) -> None:
        """Verify auto_memory extracts favorite subjects in Hinglish and pins to profile."""
        distiller = AutonomousMemoryDistiller(self.memory_store)
        distiller._extract_and_store("mera favourite subject Mathematics aur Computer Science hai", "")

        facts = self.memory_store.get_recent_autonomous_facts(limit=5)
        self.assertTrue(any("favorite_subjects" in f["subject"] for f in facts))

        # Check pinned profile
        profile = self.memory_store.get_full_profile()
        self.assertIn("favorite_subjects", profile)
        self.assertIn("Mathematics", profile["favorite_subjects"])

    def test_multilingual_distillation_devanagari(self) -> None:
        """Verify auto_memory extracts favorite subjects in Devanagari script."""
        distiller = AutonomousMemoryDistiller(self.memory_store)
        distiller._extract_and_store("मेरे फेवरेट सब्जेक्ट Physics और Maths हैं", "")

        facts = self.memory_store.get_recent_autonomous_facts(limit=5)
        self.assertTrue(any("favorite_subjects" in f["subject"] for f in facts))

        profile = self.memory_store.get_full_profile()
        self.assertIn("favorite_subjects", profile)
        self.assertIn("Physics", profile["favorite_subjects"])

    def test_devanagari_temporal_detection(self) -> None:
        """Verify EpisodicMemoryRetriever detects Hindi/Devanagari past session queries."""
        ep_store = EpisodicMemoryStore(self.db_path)
        retriever = EpisodicMemoryRetriever(ep_store)

        # The exact query Captain asked:
        self.assertTrue(retriever.is_temporal_query("लेकिन मैंने पिछले ही चैट में तुमको बताया था।"))
        self.assertTrue(retriever.is_temporal_query("पिछली चैट में क्या बात हुई थी"))
        self.assertTrue(retriever.is_temporal_query("pichle chat me kya discuss kiya tha"))

    def test_live_voice_session_instruction_and_recall_tool(self) -> None:
        """Verify LiveVoiceSession builds config with knowledge summary and registers recall tool."""
        self.memory_store.save_profile("favorite_subjects", "Physics and CS", "education")

        from live_voice import LiveVoiceSession, _execute_tool_call

        session = LiveVoiceSession(self.settings)
        cfg = session._build_config()
        self.assertIsNotNone(cfg)

        # Check system instruction text contains Captain facts
        parts = cfg.system_instruction.parts
        combined_prompt = " ".join(p.text for p in parts if getattr(p, "text", None))
        self.assertIn("Physics and CS", combined_prompt)
        self.assertIn("CAPTAIN PERSISTENT MEMORY & RECALL DIRECTIVE", combined_prompt)

        # Check _execute_tool_call for recall_captain_memory
        with patch("config.load_settings", return_value=self.settings):
            tool_res = _execute_tool_call("recall_captain_memory", {"query": "favorite subjects"})
            self.assertEqual(tool_res.get("status"), "ok")
            self.assertIn("Physics and CS", tool_res.get("message", ""))

    def test_automation_schema_includes_recall_tool(self) -> None:
        """Verify recall_captain_memory is exported in AUTOMATION_FUNCTION_SCHEMAS."""
        schema_names = [s["name"] for s in AUTOMATION_FUNCTION_SCHEMAS]
        self.assertIn("recall_captain_memory", schema_names)


if __name__ == "__main__":
    unittest.main()
