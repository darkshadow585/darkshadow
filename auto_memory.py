"""Autonomous Organic Memory Layer for DarkShadow.

Distills facts, preferences, relationships, and user habits directly
from organic conversation without requiring Captain to say '/remember'.
Runs extraction asynchronously in the background so user latency is 0ms.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Callable

from memory import SQLiteMemoryStore, contains_sensitive_data

LOGGER = logging.getLogger(__name__)

# Heuristic patterns for fast local distillation (0 API token cost, multilingual Hindi/English)
_SUBJECT_PATTERNS = [
    re.compile(
        r"(?:mera|meri|mere|my|मेरा|मेरी|मेरे)\s+(?:favorite|favourite|fav|pasandida|पसंदीदा|फेवरेट)\s+(?:subject|subjects|topic|topics|विषय|सब्जेक्ट|सब्जेक्ट्स)\s+(?:is|are|hai|hain|है|हैं|hote\s+hain)?\s*([a-zA-Z0-9_\s\u0900-\u097F,\+&]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:subject|subjects|विषय|सब्जेक्ट|सब्जेक्ट्स)\s+(?:me|mein|में)\s+(?:mujhe|मुझे)\s+([a-zA-Z0-9_\s\u0900-\u097F,\+&]+)\s+(?:pasand|achha\s+lagta|पसंद|अच्छा लगता)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:my\s+(?:favorite|favourite)\s+subjects?\s+(?:are|is))\s+([a-zA-Z0-9_\s\u0900-\u097F,\+&]+)",
        re.IGNORECASE,
    ),
]

_PREFERENCE_PATTERNS = [
    re.compile(r"\b(?:mujhe|mera|meri|mere|मेरा|मेरी|मेरे|मुझे)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,30}?)\s+(?:pasand|favorite|favourite|achha\s+lagta|पसंद|फेवरेट|पसंदीदा|अच्छा लगता)\b", re.IGNORECASE),
    re.compile(r"\b(?:i\s+like|i\s+love|i\s+prefer|my\s+favorite\s+is|my\s+favourite\s+is)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,30})\b", re.IGNORECASE),
    re.compile(r"\b(?:i\s+hate|mujhe\s+pasand\s+nahi|bekar\s+lagta|मुझे\s+पसंद\s+नहीं)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,30})\b", re.IGNORECASE),
]

_EDUCATION_PATTERNS = [
    re.compile(r"\b(?:mera\s+college|meri\s+university|mera\s+school|मेरा\s+कॉलेज|मेरी\s+यूनिवर्सिटी)\s+(?:is|hai|है)?\s*([a-zA-Z0-9_\s\u0900-\u097F]{2,40})", re.IGNORECASE),
    re.compile(r"\b(?:i\s+study\s+at|main\s+padhta\s+hoon\s+in|main\s+padhta\s+hoon|मैं\s+पढ़ता\s+हूँ)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,40})", re.IGNORECASE),
]

_CITY_PATTERNS = [
    re.compile(r"\b(?:main\s+rehta\s+hoon|i\s+live\s+in|mera\s+shehar|mera\s+city|मैं\s+रहता\s+हूँ|मेरा\s+शहर)\s+(?:in|mein|में)?\s*([a-zA-Z0-9_\s\u0900-\u097F]{2,30})", re.IGNORECASE),
]

_PROJECT_PATTERNS = [
    re.compile(r"\b(?:i\s+am\s+working\s+on|main\s+kaam\s+kar\s+raha\s+hoon|mera\s+project|मेरा\s+प्रोजेक्ट)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,35})\b", re.IGNORECASE),
    re.compile(r"\b(?:main\s+seekh\s+raha\s+hoon|i\s+am\s+learning|मैं\s+सीख\s+रहा\s+हूँ)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,25})\b", re.IGNORECASE),
]

_RELATION_PATTERNS = [
    re.compile(r"\b(?:mera\s+dost|my\s+friend|mera\s+bhai|my\s+brother|meri\s+behen|मेरा\s+दोस्त|मेरी\s+दोस्त)\s+([a-zA-Z0-9_\s\u0900-\u097F]{2,20})\b", re.IGNORECASE),
]


class AutonomousMemoryDistiller:
    """Extracts facts, preferences, and personal context organically from conversations."""

    def __init__(self, memory_store: SQLiteMemoryStore, gemini_client: Any = None) -> None:
        self.memory_store = memory_store
        self.gemini_client = gemini_client
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="DarkShadow-AutoMemory",
        )

    def process_turn_async(self, user_text: str, assistant_text: str = "") -> None:
        """Submit a completed turn for background asynchronous fact extraction."""
        self._executor.submit(self._extract_and_store, user_text, assistant_text)

    def _extract_and_store(self, user_text: str, assistant_text: str) -> None:
        """Run heuristic and/or LLM extraction on user_text."""
        cleaned = str(user_text).strip()
        if len(cleaned) < 5 or contains_sensitive_data(cleaned):
            return

        # 1. Fast heuristic regex extraction
        facts_found = self._extract_heuristics(cleaned)
        for cat, subj, fact_text in facts_found:
            res = self.memory_store.store_autonomous_fact(
                category=cat,
                subject=subj,
                fact=fact_text,
                confidence=0.85,
            )
            fact_id = res.data.get("id", 0) if res.data else 0
            if fact_id:
                self._resolve_conflicts(cat, subj, fact_text, fact_id)
            LOGGER.info("Organically memorized (heuristic): [%s:%s] %s", cat, subj, fact_text)

            # Also pin to user_profile if it's a key profile attribute
            if subj in {"favorite_subjects", "college", "city"}:
                try:
                    self.memory_store.save_profile(key=subj, value=fact_text, category=cat)
                except Exception as p_exc:
                    LOGGER.debug("Failed to pin %s to user_profile: %s", subj, p_exc)

        # 2. If no heuristic matched and sentence looks informative, try lightweight LLM distillation
        if not facts_found and self.gemini_client and len(cleaned) > 20:
            self._extract_via_llm(cleaned)

    def _resolve_conflicts(self, category: str, subject: str, new_fact: str, new_fact_id: int) -> None:
        """Archive older contradictory or superseded facts for the same subject."""
        try:
            with self.memory_store._connect() as conn:
                existing = conn.execute(
                    "SELECT id, fact FROM autonomous_facts WHERE subject = ? AND id != ? AND status = 'active'",
                    (subject.casefold(), new_fact_id),
                ).fetchall()
                if not existing:
                    return

                inversion_keywords = {"nahi", "chhod", "hate", "no longer", "stopped", "quit", "band", "dislike"}
                new_has_neg = any(w in new_fact.casefold() for w in inversion_keywords)

                for row in existing:
                    old_id = int(row["id"])
                    old_fact = str(row["fact"])
                    old_has_neg = any(w in old_fact.casefold() for w in inversion_keywords)

                    if new_has_neg != old_has_neg or category in {"preference"}:
                        conn.execute(
                            "UPDATE autonomous_facts SET status = 'superseded', superseded_by = ? WHERE id = ?",
                            (new_fact_id, old_id),
                        )
                        LOGGER.info("Memory conflict resolved: Archived fact #%d in favor of #%d", old_id, new_fact_id)
        except Exception as exc:
            LOGGER.debug("Memory conflict resolution notice: %s", exc)

    def _extract_heuristics(self, text: str) -> list[tuple[str, str, str]]:
        """Extract facts using regex rules."""
        results = []

        # 1. Favorite Subjects
        for pat in _SUBJECT_PATTERNS:
            m = pat.search(text)
            if m:
                target = m.group(1).strip(" .,;!?")
                target = re.sub(r"\b(?:hai|hain|h|is|are|the|है|हैं)\b", "", target, flags=re.IGNORECASE).strip()
                if target and len(target) > 1 and not contains_sensitive_data(target):
                    results.append(("education", "favorite_subjects", target))
                    break

        # 2. Education / College
        for pat in _EDUCATION_PATTERNS:
            m = pat.search(text)
            if m:
                target = m.group(1).strip(" .,;!?")
                target = re.sub(r"\b(?:hai|hain|h|is|are|है|हैं)\b", "", target, flags=re.IGNORECASE).strip()
                if target and len(target) > 2 and not contains_sensitive_data(target):
                    results.append(("education", "college", target))
                    break

        # 3. City / Residence
        for pat in _CITY_PATTERNS:
            m = pat.search(text)
            if m:
                target = m.group(1).strip(" .,;!?")
                target = re.sub(r"\b(?:hai|hain|h|is|are|है|हैं)\b", "", target, flags=re.IGNORECASE).strip()
                if target and len(target) > 2 and not contains_sensitive_data(target):
                    results.append(("general", "city", target))
                    break

        # 4. General Preferences
        for pat in _PREFERENCE_PATTERNS:
            m = pat.search(text)
            if m:
                target = m.group(1).strip()
                if target and len(target) > 2 and not contains_sensitive_data(target):
                    results.append(("preference", target, f"Captain expressed preference for {target} ('{text}')"))

        # 5. Projects & Learning
        for pat in _PROJECT_PATTERNS:
            m = pat.search(text)
            if m:
                proj = m.group(1).strip()
                if proj and len(proj) > 2:
                    results.append(("project", proj, f"Captain is working on / learning {proj}"))

        # 6. Relationships & Friends
        for pat in _RELATION_PATTERNS:
            m = pat.search(text)
            if m:
                person = m.group(1).strip()
                if person and len(person) > 2:
                    results.append(("relationship", person, f"Captain mentioned acquaintance / relation: {person}"))

        return results

    def _extract_via_llm(self, text: str) -> None:
        """Distill persistent user facts via Gemini if relevant."""
        try:
            prompt = (
                "You are an organic memory extractor for an AI assistant. Analyze what the user said.\n"
                f'User said: "{text}"\n'
                "If the user revealed a personal preference, habit, relationship, project, or fact about themselves, extract it.\n"
                "If it is merely casual small talk, question, or transient command, return NONE.\n"
                "Format as JSON if a fact is present:\n"
                '{"category": "preference"|"project"|"habit"|"personal", "subject": "<1-3 words>", "fact": "<short factual sentence>"}\n'
                "Output JSON ONLY or NONE."
            )
            from config import load_settings
            settings = load_settings()
            model_name = getattr(settings, "casual_model", getattr(settings, "model", "gemini-2.5-flash"))
            resp = self.gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            raw = (resp.text or "").strip()
            if "NONE" in raw or not raw:
                return

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                cat = data.get("category", "personal")
                subj = data.get("subject", "user")
                fact = data.get("fact", "")
                if fact and not contains_sensitive_data(fact):
                    res = self.memory_store.store_autonomous_fact(cat, subj, fact, confidence=0.9)
                    fact_id = res.data.get("id", 0) if (res and hasattr(res, "data") and res.data) else 0
                    if fact_id:
                        self._resolve_conflicts(cat, subj, fact, fact_id)
                    LOGGER.info("Organically memorized (LLM): [%s:%s] %s", cat, subj, fact)
        except Exception as exc:
            LOGGER.debug("LLM memory extraction notice: %s", exc)


class AutonomousMemoryRetriever:
    """Retrieves relevant facts to inject organically into the assistant's context."""

    def __init__(self, memory_store: SQLiteMemoryStore) -> None:
        self.memory_store = memory_store

    def get_context_injection(self, query: str, limit: int = 3) -> str:
        """Find facts relevant to Captain's query and format as prompt context."""
        facts = self.memory_store.search_autonomous_facts(query, limit=limit)
        if not facts:
            return ""

        lines = ["ORGANIC CONTEXTUAL MEMORIES RELEVANT TO THIS TURN:"]
        for f in facts:
            lines.append(f" - [{f['category'].upper()}: {f['subject']}]: {f['fact']}")
        return "\n".join(lines)


__all__ = [
    "AutonomousMemoryDistiller",
    "AutonomousMemoryRetriever",
]
