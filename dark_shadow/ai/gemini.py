"""
DARK SHADOW® - Modular Gemini AI Integration
Handles LLM queries with automated model fallback, conversation memory,
and smart offline desktop assistance when network is absent.
"""

import os
import time
import psutil
import datetime
import logging
from typing import Optional, List, Dict
from PySide6.QtCore import QThread, Signal

from ..config import AIConfig

logger = logging.getLogger("dark_shadow.ai.gemini")

# Attempt importing official Google GenAI SDK
GENAI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    logger.warning("google-genai SDK not available; operating in offline fallback mode.")


class GeminiAssistant:
    """
    Core AI client wrapping Google Gemini API.
    Supports multi-model failover and local desktop query answering.
    """

    FALLBACK_MODELS = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]

    def __init__(self, config: AIConfig):
        self.config = config
        self.client = None
        self.conversation_history: List[Dict[str, str]] = []
        self._init_client()

    def _init_client(self):
        """Initialize Google GenAI client if API key is present."""
        api_key = self.config.api_key or os.getenv("GEMINI_API_KEY", "")
        if GENAI_AVAILABLE and api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                logger.info("Gemini Client successfully initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client: {e}")
                self.client = None
        else:
            self.client = None
            logger.info("Running without Gemini Client (offline mode active).")

    def query(self, user_prompt: str) -> str:
        """
        Send user query to Gemini. Tries primary model and cascades
        through fallback models before using local offline intelligence.
        """
        user_prompt = user_prompt.strip()
        if not user_prompt:
            return "I am listening."

        # Check for quick local commands first
        local_resp = self._check_local_commands(user_prompt)
        if local_resp:
            return local_resp

        # Try Gemini API if client is available
        if self.client:
            models_to_try = [self.config.model_name] + [
                m for m in self.FALLBACK_MODELS if m != self.config.model_name
            ]

            for model in models_to_try:
                try:
                    logger.info(f"Querying Gemini model: {model}...")
                    response = self.client.models.generate_content(
                        model=model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=self.config.system_prompt,
                            temperature=0.7,
                            max_output_tokens=180
                        ) if hasattr(types, 'GenerateContentConfig') else None
                    )
                    if response and response.text:
                        text = response.text.strip()
                        # Record history
                        self.conversation_history.append({"user": user_prompt, "assistant": text})
                        if len(self.conversation_history) > 10:
                            self.conversation_history.pop(0)
                        return text

                except Exception as e:
                    logger.warning(f"Model '{model}' query failed: {e}. Trying next fallback...")
                    continue

        # Offline fallback response if API calls fail or offline
        return self._generate_offline_response(user_prompt)

    def _check_local_commands(self, prompt: str) -> Optional[str]:
        """Answer immediate hardware/desktop questions instantly without API latency."""
        p = prompt.lower()

        # Time query
        if "what time" in p or "current time" in p or "what's the time" in p:
            now_str = datetime.datetime.now().strftime("%I:%M %p")
            return f"It is currently {now_str}."

        # Date query
        if "what date" in p or "today's date" in p or "what day is it" in p:
            date_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
            return f"Today is {date_str}."

        # Battery query
        if "battery" in p or "power level" in p:
            try:
                battery = psutil.sensors_battery()
                if battery:
                    pct = int(battery.percent)
                    plugged = "plugged in" if battery.power_plugged else "on battery power"
                    return f"Battery is at {pct} percent, currently {plugged}."
            except Exception:
                pass

        # System health / resources
        if "system status" in p or "cpu usage" in p or "ram usage" in p or "memory" in p:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
            return f"System load is nominal. CPU utilization is at {cpu} percent, and memory is at {mem} percent."

        return None

    def _generate_offline_response(self, prompt: str) -> str:
        """Intelligent, poised offline response when Gemini is unreachable."""
        p = prompt.lower()
        if "who are you" in p or "what are you" in p:
            return "I am DARK SHADOW, your living desktop AI entity for Windows 11."
        elif "hello" in p or "hi" in p or "hey" in p:
            return "Greetings. I am here and at your service."
        elif "thank" in p:
            return "Always a pleasure."
        elif "sleep" in p or "dismiss" in p or "hide" in p:
            return "Returning to the shadows."
        else:
            return f"Acknowledged: '{prompt}'. Offline subsystem online."


class GeminiWorker(QThread):
    """
    Background worker thread to query Gemini without stalling the 60 FPS UI.
    """
    response_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, assistant: GeminiAssistant, prompt: str, parent=None):
        super().__init__(parent)
        self.assistant = assistant
        self.prompt = prompt

    def run(self):
        try:
            answer = self.assistant.query(self.prompt)
            self.response_ready.emit(answer)
        except Exception as e:
            logger.error(f"GeminiWorker execution error: {e}")
            self.error_occurred.emit(str(e))
