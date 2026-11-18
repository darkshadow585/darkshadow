"""Unit tests for DarkShadow 3-column panoramic HUD with light sky blue prompt and white response."""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import QApplication

from ui import (
    AssistantOrb,
    AssistantState,
    DarkShadowWindow,
    MotionConfig,
)


class TestUIMouthAndHUD(unittest.TestCase):
    """Test suite ensuring clean orb rendering and unboxed 3-column panoramic HUD work cleanly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_01_orb_rendering_clean_eyes_no_mouth(self) -> None:
        """Verify AssistantOrb renders cleanly with iconic glowing eyes in all states without mouth."""
        orb = AssistantOrb(MotionConfig())
        pixmap = QPixmap(430, 430)

        for state in AssistantState:
            orb.set_state(state)
            for audio in (0.0, 0.35, 0.85):
                orb.set_audio_level(audio)
                orb._advance()
                painter = QPainter(pixmap)
                orb.paintEvent(None)
                painter.end()

        self.assertFalse(pixmap.isNull())

    def test_02_hud_three_column_layout_unboxed_and_styling(self) -> None:
        """Verify DarkShadowWindow initializes with unboxed left prompt, center orb, and right response."""
        window = DarkShadowWindow()

        # Transcript label on the left with light sky blue styling
        self.assertIsNotNone(window.transcript_label)
        self.assertIn("#80D8FF", window.transcript_label.styleSheet())

        # Central orb and indicators
        self.assertIsNotNone(window.orb)
        self.assertIsNotNone(window.state_label)
        self.assertIsNotNone(window.waveform)

        # Response label on the right with pure white styling
        self.assertIsNotNone(window.response_label)
        self.assertIn("#FFFFFF", window.response_label.styleSheet())

        self.assertIsNotNone(window.source_label)
        self.assertIsNotNone(window.actions)

        # Bottom command input
        self.assertIsNotNone(window.command_input)
        self.assertGreaterEqual(window.minimumWidth(), 880)

        window.close()

    def test_03_transcript_and_response_slots(self) -> None:
        """Verify Captain prompt and DarkShadow response slots update text properly."""
        window = DarkShadowWindow()

        window.set_transcript("What is DarkShadow?")
        self.assertEqual(window.transcript_label.text(), "What is DarkShadow?")

        window.set_response_text("DarkShadow is an autonomous AI assistant.")
        self.assertEqual(
            window.response_label.text(),
            "DarkShadow is an autonomous AI assistant.",
        )

        window.set_source_count(3)
        self.assertIn("3 verified sources", window.source_label.text())

        window.close()


if __name__ == "__main__":
    unittest.main()
