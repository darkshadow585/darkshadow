"""Comprehensive tests for Search Grounding, Map Grounding, Gemini Embedding 2 RAG, and Computer Use."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from config import Settings, load_settings
from realtimeinfo import (
    RealtimeInfoService,
    RealtimeResponse,
    SourceCitation,
    is_maps_or_location_query,
    requires_fresh_information,
)
from vector_memory import VectorEmbedder, VectorMemoryStore
from computer_use_agent import ComputerUseAgent, ComputerUseStepResult
from automation import (
    AUTOMATION_FUNCTION_SCHEMAS,
    ParsedAutomationCommand,
    execute_computer_task,
    search_location_or_places,
    index_document_or_folder,
    search_knowledge_base,
)


class TestNewCapabilities(unittest.TestCase):
    """Test suite verifying all four next-gen capabilities integrated into DarkShadow."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_rag.db"
        self.settings = Settings(
            api_key="fake-test-key",
            model="gemini-3.8-flash",
            casual_model="gemini-3.5-flash-lite",
            search_grounding_provider="google",
            map_grounding_enabled=True,
            embedding_model="gemini-embedding-2",
            computer_use_enabled=True,
            computer_use_max_steps=5,
            memory_database_path=self.db_path,
        )

    # =========================================================================
    # 1. SEARCH & MAP GROUNDING TESTS
    # =========================================================================

    def test_maps_query_detection(self) -> None:
        """Verify queries asking for places, directions, or nearby locations are recognized."""
        self.assertTrue(is_maps_or_location_query("Kanpur me best cafe kahan hai"))
        self.assertTrue(is_maps_or_location_query("nearest petrol pump near me"))
        self.assertTrue(is_maps_or_location_query("Delhi railway station ka rasta"))
        self.assertTrue(is_maps_or_location_query("hospital kidhar hai"))
        self.assertFalse(is_maps_or_location_query("Python me loop kaise likhein"))
        self.assertFalse(is_maps_or_location_query("aaj ka weather kaisa hai"))

    def test_requires_fresh_information_routes_maps(self) -> None:
        """Verify requires_fresh_information triggers for maps and place recommendations."""
        self.assertTrue(requires_fresh_information("hotel near me"))
        self.assertTrue(requires_fresh_information("aaj ka ipl match score"))
        self.assertFalse(requires_fresh_information("tum kaun ho"))

    def test_google_maps_grounding_parsing(self) -> None:
        """Verify Google Maps Grounding metadata extracts map titles and URIs."""
        service = RealtimeInfoService(self.settings)

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Z Square Mall ke paas CCD aur Starbucks acche cafes hain."

        # Mock GroundingChunkMaps
        mock_chunk_maps = MagicMock()
        mock_chunk_maps.maps.title = "Cafe Coffee Day Z Square"
        mock_chunk_maps.maps.uri = "https://maps.google.com/?cid=123"
        mock_chunk_maps.web = None

        mock_candidate = MagicMock()
        mock_candidate.grounding_metadata.grounding_chunks = [mock_chunk_maps]
        mock_resp.candidates = [mock_candidate]
        mock_client.models.generate_content.return_value = mock_resp

        with patch("automation._get_cached_genai_client", return_value=mock_client):
            resp = service._answer_with_google_maps("Kanpur Z Square ke paas best cafe")
            self.assertIsNotNone(resp)
            self.assertIn("CCD", resp.display_text)
            self.assertEqual(resp.intent, "maps_grounding")
            self.assertTrue(any("Cafe Coffee Day" in s.title for s in resp.sources))
            self.assertTrue(any("maps.google.com" in s.url for s in resp.sources))

    def test_google_search_grounding_fallback(self) -> None:
        """Verify Google Search Grounding extracts web source citations."""
        service = RealtimeInfoService(self.settings)

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "India ne aaj cricket match jeet liya."

        mock_chunk_web = MagicMock()
        mock_chunk_web.maps = None
        mock_chunk_web.web.title = "ESPN Cricinfo Match Summary"
        mock_chunk_web.web.uri = "https://www.espncricinfo.com/match-123"

        mock_candidate = MagicMock()
        mock_candidate.grounding_metadata.grounding_chunks = [mock_chunk_web]
        mock_resp.candidates = [mock_candidate]
        mock_client.models.generate_content.return_value = mock_resp

        with patch("automation._get_cached_genai_client", return_value=mock_client):
            resp = service._answer_with_google_search("aaj ka match score")
            self.assertIsNotNone(resp)
            self.assertEqual(resp.intent, "realtime")
            self.assertTrue(any("ESPN Cricinfo" in s.title for s in resp.sources))

    # =========================================================================
    # 2. GEMINI EMBEDDING 2 & PERSONAL DOCUMENT RAG TESTS
    # =========================================================================

    def test_vector_embedder_gemini_embedding_2(self) -> None:
        """Verify VectorEmbedder requests gemini-embedding-2 and produces normalized vector."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        # Mock 3072-dimensional vector as returned by gemini-embedding-2
        mock_vec = [0.1] * 3072
        mock_embedding_obj = MagicMock()
        mock_embedding_obj.values = mock_vec
        mock_resp.embeddings = [mock_embedding_obj]
        mock_client.models.embed_content.return_value = mock_resp

        embedder = VectorEmbedder(gemini_client=mock_client, model_name="gemini-embedding-2")
        vec = embedder.get_embedding("Deep learning and artificial intelligence")

        self.assertEqual(embedder.model_name, "gemini-embedding-2")
        self.assertIsInstance(vec, np.ndarray)
        self.assertEqual(len(vec), 3072)
        norm = float(np.linalg.norm(vec))
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_personal_rag_file_indexing_and_search(self) -> None:
        """Verify indexing a local file into SQLite and retrieving it via cosine similarity."""
        sample_file = Path(self.temp_dir) / "notes.txt"
        sample_file.write_text(
            "Kuldeep is working on project DarkShadow featuring autonomous Computer Use, "
            "Google Maps Grounding, and voice interaction in Hindi.",
            encoding="utf-8",
        )

        store = VectorMemoryStore(self.db_path)
        idx_res = store.index_file(sample_file)
        self.assertTrue(idx_res["success"])
        self.assertGreaterEqual(idx_res["chunks_indexed"], 1)

        # Query semantic knowledge base
        results = store.search_knowledge_base("autonomous Computer Use and Google Maps", limit=2)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["file_name"], "notes.txt")
        self.assertIn("DarkShadow", results[0]["content"])
        self.assertGreater(results[0]["similarity"], 0.20)

    # =========================================================================
    # 3. COMPUTER USE AGENT TESTS
    # =========================================================================

    def test_computer_use_safety_blocks(self) -> None:
        """Verify ComputerUseAgent strictly rejects checkout and camera attempts."""
        agent = ComputerUseAgent(gemini_client=MagicMock(), max_steps=3)

        # 1. Checkout attempt
        res_pay = agent.run_goal("Amazon par order place karo aur credit card se buy now karo")
        self.assertFalse(res_pay["success"])
        self.assertEqual(res_pay["error"], "payment_blocked")

        # 2. Camera attempt
        res_cam = agent.run_goal("Open webcam and record Captain's face")
        self.assertFalse(res_cam["success"])
        self.assertEqual(res_cam["error"], "camera_blocked")

    def test_computer_use_coordinate_normalization(self) -> None:
        """Verify execute_action properly scales normalized 0-1 and 0-1000 coordinates."""
        with patch("pyautogui.click") as mock_click:
            # 0.5 normalized on 1920x1080 -> 960, 540
            success, msg = ComputerUseAgent.execute_action("click", x=0.5, y=0.5, screen_w=1920, screen_h=1080)
            self.assertTrue(success)
            mock_click.assert_called_with(960, 540)

            # 500 on 0-1000 scale with is_normalized=True -> 960, 540
            success_1000, _ = ComputerUseAgent.execute_action("click", x=500.0, y=500.0, screen_w=1920, screen_h=1080, is_normalized=True)
            self.assertTrue(success_1000)
            mock_click.assert_called_with(960, 540)

    def test_computer_use_action_types(self) -> None:
        """Verify various Computer Use actions dispatch correctly."""
        with patch("pyautogui.doubleClick") as mock_dbl, \
             patch("pyautogui.hotkey") as mock_key, \
             patch("pyperclip.copy") as mock_copy:

            s_dbl, _ = ComputerUseAgent.execute_action("double_click", x=100, y=200, screen_w=1920, screen_h=1080)
            self.assertTrue(s_dbl)
            mock_dbl.assert_called_with(100, 200)

            s_type, _ = ComputerUseAgent.execute_action("type", text="DarkShadow Ready")
            self.assertTrue(s_type)
            mock_copy.assert_called_with("DarkShadow Ready")
            mock_key.assert_called_with("ctrl", "v")

            s_key, _ = ComputerUseAgent.execute_action("key", key="ctrl+s")
            self.assertTrue(s_key)
            mock_key.assert_called_with("ctrl", "s")

    # =========================================================================
    # 4. TOOL REGISTRY SCHEMAS & AUTOMATION DISPATCH
    # =========================================================================

    def test_new_tool_schemas_registered(self) -> None:
        """Verify all four new tools are in AUTOMATION_FUNCTION_SCHEMAS."""
        names = {s["name"] for s in AUTOMATION_FUNCTION_SCHEMAS}
        self.assertIn("execute_computer_task", names)
        self.assertIn("search_location_or_places", names)
        self.assertIn("index_document_or_folder", names)
        self.assertIn("search_knowledge_base", names)

    def test_automation_functions_callable(self) -> None:
        """Verify wrapper functions execute safely with valid input."""
        # search_location_or_places with empty query
        res = search_location_or_places("")
        self.assertFalse(res.success)
        self.assertEqual(res.error, "empty_query")

        # index_document_or_folder with nonexistent path
        res_idx = index_document_or_folder("Z:\\nonexistent_dir_12345\\file.txt")
        self.assertFalse(res_idx.success)
        self.assertEqual(res_idx.error, "path_not_found")

    def test_computer_use_model_fallback_on_503(self) -> None:
        """Verify ComputerUseAgent automatically falls back to flash-lite if primary model returns 503."""
        mock_client = MagicMock()

        # Primary model raises 503 ServerError
        def mock_gen_content(model, contents, config):
            if model == "gemini-3.8-flash":
                from google.genai.errors import ServerError
                raise ServerError(503, {}, "Model high demand 503")
            # Fallback model returns step plan
            resp = MagicMock()
            resp.text = '{"thought": "WhatsApp is open. Clicking photo.", "action": "click", "x": 500, "y": 400, "status": "in_progress"}'
            return resp

        mock_client.models.generate_content.side_effect = mock_gen_content
        agent = ComputerUseAgent(gemini_client=mock_client, model="gemini-3.8-flash")
        plan = agent._plan_next_step("Open WhatsApp and click photo", b"fake_img", [], 1920, 1080)

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "click")
        self.assertEqual(plan["x"], 500)
        self.assertEqual(plan["y"], 400)


if __name__ == "__main__":
    unittest.main()
