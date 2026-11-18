"""Deterministic Hindi/Hinglish versus English speech voice selection."""

from __future__ import annotations

import re


_DEVANAGARI = re.compile(r"[\u0900-\u097f]")
_WORDS = re.compile(r"[a-zA-Z']+")

# Comprehensive list of everyday Hindi/Hinglish words (170+ entries)
_HINGLISH_WORDS = {
    # Question words
    "kya", "kyu", "kyun", "kaun", "kisko", "kisse", "kahan", "kaha", "kab",
    "kaise", "kaisa", "kaisi", "kitna", "kitne", "kitni",
    # Pronouns & determiners
    "main", "mujhe", "mera", "meri", "mere", "mujhhse",
    "hum", "humein", "humara", "humari", "humare",
    "tum", "tumhe", "tumhara", "tumhari", "tumhare",
    "aap", "aapko", "aapka", "aapki", "aapke",
    "ye", "yeh", "isse", "iska", "iski", "iske",
    "wo", "woh", "usse", "uska", "uski", "uske",
    "inhe", "unhe", "inka", "unka", "inki", "unki",
    "apna", "apni", "apne", "khud",
    # Common verbs & action words
    "kar", "karo", "karna", "karein", "karta", "karti", "karte", "kiya",
    "ho", "hai", "hain", "hoga", "hogi", "honge", "hona", "hota", "hoti",
    "tha", "the", "thi",
    "bol", "bolo", "bolna", "bata", "batao", "batana",
    "dekh", "dekho", "dekhna", "dikha", "dikhao", "dikhana",
    "sun", "suno", "sunao", "sunna",
    "khol", "kholo", "kholna", "chal", "chala", "chalao", "chalana",
    "baja", "bajao", "bajana", "band", "ruk", "ruko", "rok", "roko",
    "bhej", "bhejo", "bhejna", "likh", "likho", "likhna",
    "padh", "padho", "padhna", "le", "lo", "lelo", "lena",
    "de", "do", "dedo", "dena", "aao", "aana", "jao", "jaana",
    "samajh", "samjho", "samjha", "rakh", "rakho", "chahiye",
    # Connectives, adverbs & prepositions
    "ka", "ki", "ke", "ko", "se", "me", "mein", "pe", "par",
    "aur", "ya", "lekin", "magar", "bhi", "to", "toh",
    "yahan", "yaha", "wahan", "waha", "jahan", "jaha",
    "upar", "neeche", "andar", "bahar", "aage", "peeche",
    "paas", "door", "saath", "pehle", "baad",
    "abhi", "aaj", "kal", "parson", "phir", "dobara",
    "jaldi", "dheere", "thoda", "thodi", "zyada", "jyada",
    "bahut", "bohot", "kuch", "kuchh", "koi", "sab", "sabse", "sirf",
    # Modifiers & conversational slang
    "acha", "accha", "achha", "achi", "theek", "thik", "sahi", "galat",
    "wala", "wali", "wale", "waala", "waali",
    "nahi", "naam", "kaam", "baat", "waqt", "samay",
    "gaana", "gana", "geet", "awaaz", "awaz", "video",
    "bhai", "dost", "yaar", "beedu", "bindass", "dhanso", "badhiya",
    "shukriya", "dhanyawad", "namaste", "namaskar", "alvida",
}


def detect_speech_language(text: str) -> str:
    """Return ``hi`` for Devanagari/Hinglish, otherwise ``en``."""
    if _DEVANAGARI.search(text):
        return "hi"

    words = [word.casefold() for word in _WORDS.findall(text)]
    if not words:
        return "en"

    hindi_hits = sum(word in _HINGLISH_WORDS for word in words)

    # For short phrases (<=3 words, e.g. "YouTube kholo", "gaana bajao"), 1 hit is decisive
    if len(words) <= 3:
        return "hi" if hindi_hits >= 1 else "en"

    # For longer sentences, require at least 2 hits or at least 20% of words to be Hindi
    return "hi" if (hindi_hits >= 2 or (hindi_hits / len(words)) >= 0.20) else "en"


def select_edge_voice(text: str, hindi_voice: str, english_voice: str) -> str:
    """Select the configured Edge voice without making an API call."""
    return hindi_voice if detect_speech_language(text) == "hi" else english_voice


__all__ = ["detect_speech_language", "select_edge_voice"]
