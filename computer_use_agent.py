"""Autonomous Computer Use & Visual Desktop Execution Agent for DarkShadow.

Features:
1. Multi-turn visual execution loop: Screenshot -> Visual Goal Grounding -> Action -> Verify.
2. Safe OS-level mouse/keyboard execution via PyAutoGUI with FAILSAFE = True.
3. Dual-mode action planning: Native types.ComputerUse and Vision ReAct fallback.
4. Strict safety enforcement: Payment checkout shield and physical camera privacy shield.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from safety import (
    CAMERA_BLOCKED_MESSAGE,
    PAYMENT_BLOCKED_MESSAGE,
    ensure_captain_address,
    is_payment_or_checkout_intent,
    is_physical_camera_intent,
    speech_friendly_text,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ComputerUseStepResult:
    """Result of a single Computer Use action step."""

    step: int
    action: str
    thought: str
    success: bool
    status: str
    message: str


class ComputerUseAgent:
    """Executes multi-step desktop & browser goals using visual perception and OS actions."""

    def __init__(
        self,
        gemini_client: Any = None,
        model: str = "gemini-3.8-flash",
        max_steps: int = 10,
    ) -> None:
        self.client = gemini_client
        self.model = model
        self.max_steps = max_steps

    @staticmethod
    def capture_screen_image() -> tuple[bytes | None, int, int]:
        """Capture active desktop monitor display as JPEG bytes with dimensions."""
        try:
            from PIL import ImageGrab
            import pyautogui

            screen = ImageGrab.grab()
            buf = io.BytesIO()
            screen.save(buf, format="JPEG", quality=85)
            w, h = pyautogui.size()
            return buf.getvalue(), int(w), int(h)
        except Exception as exc:
            LOGGER.warning("Screen capture for Computer Use failed: %s", exc)
            return None, 1920, 1080

    @classmethod
    def execute_action(
        cls,
        action: str,
        x: float | None = None,
        y: float | None = None,
        text: str = "",
        key: str = "",
        screen_w: int = 1920,
        screen_h: int = 1080,
        is_normalized: bool = False,
    ) -> tuple[bool, str]:
        """Execute safe desktop action with coordinate scaling and failsafe protection."""
        try:
            import pyautogui
            import pyperclip

            pyautogui.FAILSAFE = True

            act = action.strip().lower()

            # Normalize coordinates if given as unit interval or flagged as normalized
            real_x = None
            real_y = None
            if x is not None and y is not None:
                if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                    real_x = int(x * screen_w)
                    real_y = int(y * screen_h)
                elif is_normalized:
                    real_x = int((x / 1000.0) * screen_w)
                    real_y = int((y / 1000.0) * screen_h)
                else:
                    real_x = int(x)
                    real_y = int(y)
                real_x = max(0, min(screen_w - 1, real_x))
                real_y = max(0, min(screen_h - 1, real_y))

            if act in {"click", "left_click", "mouse_click"}:
                if real_x is not None and real_y is not None:
                    pyautogui.click(real_x, real_y)
                    return True, f"Clicked at ({real_x}, {real_y})"
                pyautogui.click()
                return True, "Clicked active cursor position"

            if act in {"double_click", "double_click_coordinate"}:
                if real_x is not None and real_y is not None:
                    pyautogui.doubleClick(real_x, real_y)
                    return True, f"Double-clicked at ({real_x}, {real_y})"
                pyautogui.doubleClick()
                return True, "Double-clicked active position"

            if act in {"right_click", "context_menu"}:
                if real_x is not None and real_y is not None:
                    pyautogui.rightClick(real_x, real_y)
                    return True, f"Right-clicked at ({real_x}, {real_y})"
                pyautogui.rightClick()
                return True, "Right-clicked active position"

            if act in {"type", "type_text", "write"}:
                if real_x is not None and real_y is not None:
                    pyautogui.click(real_x, real_y)
                    time.sleep(0.2)
                # Use clipboard for reliable Unicode/Hindi typing
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
                return True, f"Typed: '{text}'"

            if act in {"key", "hotkey", "press_key", "shortcut"}:
                keys = [k.strip().lower() for k in key.replace("+", " ").split()]
                if keys:
                    pyautogui.hotkey(*keys)
                    return True, f"Pressed key combination: {key}"
                return False, "No key specified"

            if act in {"scroll", "mouse_scroll"}:
                amount = int(x) if x is not None else -400
                pyautogui.scroll(amount)
                return True, f"Scrolled {amount} units"

            if act in {"wait", "sleep"}:
                wait_sec = min(5.0, max(0.5, float(x or 1.0)))
                time.sleep(wait_sec)
                return True, f"Waited {wait_sec} seconds"

            if act in {"describe", "describe_image", "analyze_image", "describe_photo"}:
                time.sleep(0.5)
                full_screen_bytes, _, _ = cls.capture_screen_image()
                if full_screen_bytes:
                    try:
                        from automation import _get_cached_genai_client
                        from google.genai import types
                        c = _get_cached_genai_client()
                        if c:
                            vis_prompt = (
                                "Carefully describe the photo, image, or picture visible on the screen in natural Hindi/Hinglish for Captain Kuldeep. "
                                "Detail who or what is in the photo, colors, background, and key visual elements."
                            )
                            c_resp = c.models.generate_content(
                                model="gemini-3.5-flash-lite",
                                contents=[types.Part.from_bytes(data=full_screen_bytes, mime_type="image/jpeg"), vis_prompt],
                            )
                            desc_text = (getattr(c_resp, "text", "") or "").strip()
                            if desc_text:
                                return True, desc_text
                    except Exception as e:
                        LOGGER.debug("Photo vision description notice: %s", e)
                return True, text or "Photo screen par open hai."

            if act in {"finish", "done", "completed"}:
                return True, text or "Task marked completed"

            return False, f"Unknown action: {act}"
        except Exception as exc:
            LOGGER.warning("Computer Use action execution error: %s", exc)
            return False, str(exc)

    def run_goal(self, goal: str) -> dict[str, Any]:
        """Run autonomous visual Computer Use loop to accomplish Captain's desktop goal."""
        cleaned_goal = goal.strip()
        if not cleaned_goal:
            return {
                "success": False,
                "error": "empty_goal",
                "message": "Captain, Computer Use ke liye task empty hai.",
            }

        # STRICT PRIVACY & SAFETY INTERCEPTORS
        if is_physical_camera_intent(cleaned_goal):
            return {
                "success": False,
                "error": "camera_blocked",
                "message": CAMERA_BLOCKED_MESSAGE,
            }

        if is_payment_or_checkout_intent(cleaned_goal):
            return {
                "success": False,
                "error": "payment_blocked",
                "message": PAYMENT_BLOCKED_MESSAGE,
            }

        # Pre-flight proactive app launch / foregrounding
        app_targets = {
            "whatsapp": "whatsapp://",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "notepad": "notepad.exe",
            "spotify": "spotify://",
        }
        for app_k, target_uri in app_targets.items():
            if re.search(rf"\b{app_k}\b", cleaned_goal, re.I):
                try:
                    import os
                    startfile = getattr(os, "startfile", None)
                    if callable(startfile):
                        startfile(target_uri)
                        time.sleep(1.2)
                except Exception:
                    pass
                break

        history_steps: list[ComputerUseStepResult] = []
        step_count = 0

        while step_count < self.max_steps:
            step_count += 1
            screen_bytes, screen_w, screen_h = self.capture_screen_image()
            if screen_bytes is None:
                return {
                    "success": False,
                    "error": "screenshot_failed",
                    "message": "Screen capture nahi ho saka.",
                    "steps": [s.__dict__ for s in history_steps],
                }

            # Prompt Gemini to inspect current screen and output next action in structured JSON
            plan = self._plan_next_step(cleaned_goal, screen_bytes, history_steps, screen_w, screen_h)
            if not plan:
                return {
                    "success": False,
                    "error": "planning_failed",
                    "message": "Computer Use model se step plan nahi mil saka.",
                    "steps": [s.__dict__ for s in history_steps],
                }

            thought = plan.get("thought", "")
            action = plan.get("action", "wait")
            x = plan.get("x")
            y = plan.get("y")
            text = plan.get("text", "")
            key = plan.get("key", "")
            status = plan.get("status", "in_progress").lower()

            if action in {"finish", "done"} or status == "completed":
                summary = plan.get("summary") or text or thought or f"Task '{cleaned_goal}' successfully complete ho gaya."
                history_steps.append(
                    ComputerUseStepResult(
                        step=step_count,
                        action=action,
                        thought=thought,
                        success=True,
                        status="completed",
                        message=summary,
                    )
                )
                return {
                    "success": True,
                    "status": "completed",
                    "total_steps": step_count,
                    "message": ensure_captain_address(summary),
                    "steps": [s.__dict__ for s in history_steps],
                }

            success, act_msg = self.execute_action(
                action=action,
                x=x,
                y=y,
                text=text,
                key=key,
                screen_w=screen_w,
                screen_h=screen_h,
            )

            history_steps.append(
                ComputerUseStepResult(
                    step=step_count,
                    action=action,
                    thought=thought,
                    success=success,
                    status=status,
                    message=act_msg,
                )
            )

            time.sleep(0.8)

        # Max steps reached
        final_msg = f"Task '{cleaned_goal}' par {self.max_steps} steps execute kiye gaye."
        return {
            "success": True,
            "status": "max_steps_reached",
            "total_steps": step_count,
            "message": ensure_captain_address(final_msg),
            "steps": [s.__dict__ for s in history_steps],
        }

    def _plan_next_step(
        self,
        goal: str,
        screen_bytes: bytes,
        history_steps: list[ComputerUseStepResult],
        screen_w: int,
        screen_h: int,
    ) -> dict[str, Any] | None:
        """Call Gemini Vision with Computer Use instructions to determine next UI action."""
        if self.client is None:
            return None

        from google.genai import types

        history_summary = "\n".join(
            f"Step {s.step}: action={s.action}, success={s.success}, result={s.message}"
            for s in history_steps[-4:]
        ) or "None (starting step 1)"

        prompt = (
            f"You are DarkShadow Computer Use agent operating Windows 11 for Captain Kuldeep.\n"
            f"Goal: {goal}\n"
            f"Screen Resolution: {screen_w}x{screen_h}\n"
            f"Previous Actions:\n{history_summary}\n\n"
            f"Examine the attached screenshot of the desktop screen. Output ONLY a valid JSON object describing the single next action:\n"
            f"{{\n"
            f'  "thought": "Brief reasoning of what you see on the screen and what to do next",\n'
            f'  "action": "click" | "double_click" | "right_click" | "type" | "key" | "scroll" | "wait" | "finish",\n'
            f'  "x": <integer x coordinate on screen or null>,\n'
            f'  "y": <integer y coordinate on screen or null>,\n'
            f'  "text": "<text to type if action is type, or final summary if action is finish>",\n'
            f'  "key": "<shortcut key e.g. enter, esc, ctrl+s if action is key>",\n'
            f'  "status": "in_progress" | "completed"\n'
            f"}}\n"
            f"Return only raw JSON. No markdown backticks, no explanations."
        )

        parts = [
            types.Part.from_bytes(data=screen_bytes, mime_type="image/jpeg"),
            types.Part.from_text(text=prompt),
        ]

        candidate_models = [self.model, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        seen: set[str] = set()
        models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

        config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=600,
        )

        for candidate_model in models_to_try:
            try:
                resp = self.client.models.generate_content(
                    model=candidate_model,
                    contents=parts,
                    config=config,
                )
                raw = (getattr(resp, "text", "") or "").strip()
                if not raw:
                    continue

                # Clean JSON markdown if model wrapped it in backticks
                cleaned = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE)
                cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
                parsed = json.loads(cleaned)
                if isinstance(parsed, list) and len(parsed) > 0:
                    parsed = parsed[0]
                if isinstance(parsed, dict):
                    return parsed
            except Exception as exc:
                LOGGER.debug("Computer Use planning attempt with model '%s' failed: %s", candidate_model, exc)

        return None


__all__ = ["ComputerUseAgent", "ComputerUseStepResult"]
