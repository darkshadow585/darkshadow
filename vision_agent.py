"""Vision-Driven GUI Agent & 'Computer Use' Engine for DarkShadow.

Provides visual element localization, coordinate grounding (Set-of-Marks / normalized coords),
and autonomous mouse/keyboard interactions across any Windows desktop application.

Privacy Shield Guarantee:
Physical webcams/cameras are strictly prohibited. Visual capture is 100% restricted
to the user's active monitor display frames.
"""

from __future__ import annotations

import base64
import ctypes
import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisualElementTarget:
    """Predicted visual target on screen."""

    target_name: str
    pixel_x: int
    pixel_y: int
    confidence: float = 1.0
    method: str = "ui_automation"  # "ui_automation" | "vision_llm" | "som_grid"


class ScreenCaptureEngine:
    """Safely captures desktop monitor frames without webcam access."""

    @staticmethod
    def get_screen_resolution() -> tuple[int, int]:
        """Return primary monitor (width, height) using Windows API."""
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            return width, height
        except Exception:
            return 1920, 1080

    @staticmethod
    def capture_screenshot() -> Any:
        """Capture the current monitor display as a PIL Image."""
        try:
            from PIL import ImageGrab
            return ImageGrab.grab(all_screens=False)
        except Exception as exc:
            LOGGER.warning("ImageGrab failed, trying fallback: %s", exc)
            return None


class VisionCoordinateGrounder:
    """Translates natural language UI descriptions to exact screen pixel coordinates."""

    def __init__(self, gemini_client: Any = None) -> None:
        self.gemini_client = gemini_client

    def locate_element(self, target_description: str, image: Any = None) -> VisualElementTarget | None:
        """Locate element coordinates: First via UI Automation, then via Vision LLM."""
        # 1. UI Automation Fast Path (0 API Cost)
        try:
            from desktop_engine import get_desktop_engine
            engine = get_desktop_engine()
            controls = engine.list_window_controls()
            target_lower = target_description.casefold()

            for c in controls:
                if c.name and (target_lower in c.name.casefold() or c.name.casefold() in target_lower):
                    left, top, right, bottom = c.rect
                    cx = (left + right) // 2
                    cy = (top + bottom) // 2
                    if cx > 0 and cy > 0:
                        LOGGER.info("Located '%s' via UI Automation at (%d, %d)", target_description, cx, cy)
                        return VisualElementTarget(
                            target_name=c.name,
                            pixel_x=cx,
                            pixel_y=cy,
                            method="ui_automation",
                        )
        except Exception as exc:
            LOGGER.debug("UI automation element search notice: %s", exc)

        # 2. Vision LLM Grounding Path (Visual Coordinate Prediction)
        if image is None:
            image = ScreenCaptureEngine.capture_screenshot()

        if image is None:
            return None

        return self._locate_via_vision_prompt(target_description, image)

    def _locate_via_vision_prompt(self, target_description: str, image: Any) -> VisualElementTarget | None:
        """Ask Vision LLM to return normalized coordinates [0-1000] for the described element."""
        try:
            # Resize image for fast inference (max 1024 width/height)
            width, height = image.size
            max_dim = 1024
            scale = min(max_dim / width, max_dim / height, 1.0)
            thumb = image.resize((int(width * scale), int(height * scale)))

            buffered = io.BytesIO()
            thumb.save(buffered, format="JPEG", quality=85)
            img_bytes = buffered.getvalue()

            prompt = (
                f"You are a computer use vision agent. Locate the UI element '{target_description}' on this screen.\n"
                "Return JSON ONLY with normalized coordinates from 0 to 1000:\n"
                '{"found": true, "x": <int 0-1000>, "y": <int 0-1000>, "confidence": <float 0-1>}\n'
                'If the element is definitely not present, return {"found": false}.'
            )

            # Check if Gemini client or Ollama is available
            from config import load_settings
            settings = load_settings()

            response_text = ""
            if settings.gemini_api_key:
                from google import genai
                from google.genai import types
                client = self.gemini_client or genai.Client(api_key=settings.gemini_api_key)
                model_name = getattr(settings, "vision_model", getattr(settings, "model", "gemini-2.5-flash"))
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                        prompt,
                    ],
                )
                response_text = response.text or ""

            if not response_text:
                return None

            # Parse JSON from response
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if data.get("found"):
                    norm_x = int(data.get("x", 500))
                    norm_y = int(data.get("y", 500))
                    # Scale normalized coordinates to pyautogui logical screen coordinates (DPI-aware)
                    try:
                        import pyautogui
                        screen_w, screen_h = pyautogui.size()
                    except Exception:
                        screen_w, screen_h = ScreenCaptureEngine.get_screen_resolution()
                    real_x = int((norm_x / 1000.0) * screen_w)
                    real_y = int((norm_y / 1000.0) * screen_h)
                    LOGGER.info("Located '%s' via Vision LLM at (%d, %d)", target_description, real_x, real_y)
                    return VisualElementTarget(
                        target_name=target_description,
                        pixel_x=real_x,
                        pixel_y=real_y,
                        confidence=float(data.get("confidence", 0.9)),
                        method="vision_llm",
                    )
        except Exception as exc:
            LOGGER.debug("Vision LLM coordinate grounding failed: %s", exc)

        return None


class ComputerUseExecutor:
    """Executes validated OS mouse and keyboard actions with visual feedback verification."""

    def __init__(self, grounder: VisionCoordinateGrounder | None = None) -> None:
        self.grounder = grounder or VisionCoordinateGrounder()

    def visual_click(
        self,
        target: str,
        click_type: str = "single",
        verify_delta: bool = True,
    ) -> dict[str, Any]:
        """Locate target element and perform a mouse click."""
        from desktop_engine import ScreenDeltaDetector

        img_before = ScreenCaptureEngine.capture_screenshot() if verify_delta else None
        target_obj = self.grounder.locate_element(target, image=img_before)

        if not target_obj:
            return {
                "success": False,
                "action": "visual_click",
                "target": target,
                "message": f"Screen par element '{target}' locate nahi ho paya.",
            }

        x, y = target_obj.pixel_x, target_obj.pixel_y

        try:
            import pyautogui
            # Smooth human-like cursor move
            pyautogui.moveTo(x, y, duration=0.2)
            time.sleep(0.05)

            if click_type == "double":
                pyautogui.doubleClick(x, y)
            elif click_type == "right":
                pyautogui.rightClick(x, y)
            else:
                pyautogui.click(x, y)

            time.sleep(0.3)

            delta = 0.0
            if verify_delta and img_before:
                detector = ScreenDeltaDetector()
                img_after = ScreenCaptureEngine.capture_screenshot()
                if img_after:
                    delta = detector.compute_delta(img_after)

            return {
                "success": True,
                "action": "visual_click",
                "target": target,
                "method": target_obj.method,
                "coordinates": (x, y),
                "screen_delta": round(delta, 4),
                "message": f"Screen par '{target}' par click kar diya ({target_obj.method}).",
            }
        except Exception as exc:
            LOGGER.warning("pyautogui visual_click failed: %s", exc)
            return {
                "success": False,
                "action": "visual_click",
                "target": target,
                "error": str(exc),
                "message": f"Click execute karte waqt error aaya: {exc}",
            }

    def visual_type(
        self,
        target: str | None,
        text: str,
        press_enter: bool = False,
    ) -> dict[str, Any]:
        """Click the target input field (if specified) and type text."""
        if target:
            click_res = self.visual_click(target, click_type="single", verify_delta=False)
            if not click_res.get("success"):
                LOGGER.debug("Target focus click returned notice: %s", click_res)
            time.sleep(0.15)

        try:
            import pyautogui
            # If text has non-ASCII characters (e.g. Hindi, Unicode), paste via clipboard
            if any(ord(c) > 127 for c in text):
                try:
                    import pyperclip
                    pyperclip.copy(text)
                    pyautogui.hotkey("ctrl", "v")
                    time.sleep(0.05)
                except Exception:
                    pyautogui.write(text, interval=0.02)
            else:
                pyautogui.write(text, interval=0.02)

            if press_enter:
                pyautogui.press("enter")

            return {
                "success": True,
                "action": "visual_type",
                "target": target,
                "typed_text": text,
                "message": f"Text successfully type kar diya: '{text}'",
            }
        except Exception as exc:
            return {
                "success": False,
                "action": "visual_type",
                "error": str(exc),
                "message": f"Type karne me error aaya: {exc}",
            }


_GLOBAL_EXECUTOR: ComputerUseExecutor | None = None


def get_computer_use_executor() -> ComputerUseExecutor:
    """Return the global ComputerUseExecutor instance."""
    global _GLOBAL_EXECUTOR
    if _GLOBAL_EXECUTOR is None:
        _GLOBAL_EXECUTOR = ComputerUseExecutor()
    return _GLOBAL_EXECUTOR


__all__ = [
    "VisualElementTarget",
    "ScreenCaptureEngine",
    "VisionCoordinateGrounder",
    "ComputerUseExecutor",
    "get_computer_use_executor",
]
