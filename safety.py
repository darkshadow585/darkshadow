"""Small Phase 1 safety helpers shared by user-facing responses."""

from __future__ import annotations

import re


_CAPTAIN_PATTERN = re.compile(r"\b(?:captain|कैप्टन)\b", re.IGNORECASE)


def ensure_captain_address(text: str) -> str:
    """Ensure a non-empty response addresses the user as Captain."""

    cleaned = text.strip()
    if not cleaned:
        return "Captain, mujhe khaali response mila. Please dobara try kijiye."
    if _CAPTAIN_PATTERN.search(cleaned):
        return cleaned
    return f"Captain, {cleaned}"


def speech_friendly_text(display_text: str) -> str:
    """Make common Roman-Hindi words easier for Hindi TTS to pronounce."""

    replacements = {
        "Captain": "कैप्टन",
        "captain": "कैप्टन",
        "namaste": "नमस्ते",
        "Namaste": "नमस्ते",
        "aap": "आप",
        "kijiye": "कीजिए",
        "dobara": "दोबारा",
        "samajh": "समझ",
        "nahi": "नहीं",
        "haan": "हाँ",
        "theek": "ठीक",
    }
    result = display_text
    for source, target in replacements.items():
        result = re.sub(rf"\b{re.escape(source)}\b", target, result)
    return result


_PAYMENT_PATTERNS = re.compile(
    r"(?:\b(?:buy[-_ ]*now|place[-_ ]*order|proceed[-_ ]*to[-_ ]*pay|pay[-_ ]*now|complete[-_ ]*payment|"
    r"payment\s*karo|pay\s*karo|kharido|kharid\s*lo|order\s*place\s*karo|"
    r"checkout|enter\s*cvv|enter\s*otp|upi[-_ ]*pin|atm[-_ ]*pin|"
    r"credit[-_ ]*card|debit[-_ ]*card|card\s*details|bank\s*transfer|net\s*banking|"
    r"भुगतान|खरीदो|पेमेंट|आर्डर\s*प्लेस)\b|pay[-_]now|payment|checkout)",
    re.IGNORECASE,
)

PAYMENT_BLOCKED_MESSAGE = (
    "Security protocol: Automated payment, checkout aur financial credentials "
    "execution strictly blocked hai. Carting aur comparison available hai, par final payment "
    "kripya manually complete kijiye."
)


def is_payment_or_checkout_intent(text: str) -> bool:
    """Return whether user text or tool input attempts payment or financial checkout."""
    if not text:
        return False
    return bool(_PAYMENT_PATTERNS.search(str(text)))


_PHYSICAL_CAMERA_PATTERNS = re.compile(
    r"(?:\b(?:webcam|camera|cam|video[-_ ]*call|face[-_ ]*record(?:ing)?|record[-_ ]*face|"
    r"camera\s*(?:on|kholo|chalao|start|open)|turn\s*on\s*camera|open\s*camera|start\s*camera|"
    r"webcam\s*(?:on|kholo|chalao|start|open)|turn\s*on\s*webcam|open\s*webcam|start\s*webcam|"
    r"chehra\s*(?:dekho|dikhao|record)|face\s*(?:dekho|dikhao|record)|"
    r"capture\s*(?:video|selfie|face)|take\s*selfie|selfie\s*lo|photo\s*(?:khincho|lo)|"
    r"कैमरा|वेबकैम|चेहरा\s*देखो)\b)",
    re.IGNORECASE,
)

CAMERA_BLOCKED_MESSAGE = (
    "Privacy Protocol: Captain ki privacy ke mutabiq physical camera/webcam hardware access "
    "permanently disabled hai. Face ya room recording strictly blocked hai. "
    "Desktop monitor screen vision aur PC automation 100% active hain."
)


def is_physical_camera_intent(text: str) -> bool:
    """Return whether user text attempts physical camera/webcam/face recording."""
    if not text:
        return False
    cleaned = re.sub(r"[-_]+", " ", str(text)).strip()
    return bool(_PHYSICAL_CAMERA_PATTERNS.search(cleaned))


# =============================================================================
# TERMINAL / POWERSHELL COMMAND SECURITY SHIELD
# =============================================================================

_DANGEROUS_TERMINAL_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
        "Disk formatting is strictly blocked to protect your drives.",
    ),
    (
        re.compile(r"\b(?:diskpart|bootrec|bcdedit)\b", re.IGNORECASE),
        "Partition and boot record modification commands are strictly blocked.",
    ),
    (
        re.compile(r"\bcipher\s+/[wW]", re.IGNORECASE),
        "Drive data wiping is blocked.",
    ),
    (
        re.compile(
            r"\b(?:del|erase)\b.*?(?:[a-z]:\\(?:\*|\s*$)|\\windows|\\system32|\bwindows\b|\bsystem32\b)",
            re.IGNORECASE,
        ),
        "System and root directory deletion is strictly blocked.",
    ),
    (
        re.compile(
            r"\b(?:rmdir|rd)\b.*?(?:[a-z]:\\|\\windows|\\system32|\bwindows\b|\bsystem32\b)",
            re.IGNORECASE,
        ),
        "Recursive deletion of system and root directories is blocked.",
    ),
    (
        re.compile(
            r"\bRemove-Item\b.*?(?:[a-z]:\\|\\windows|\\system32|\bwindows\b|\bsystem32\b)",
            re.IGNORECASE,
        ),
        "PowerShell recursive deletion of system/root directories is blocked.",
    ),
    (
        re.compile(
            r"\brm\s+-[rf]{1,}\s+.*?(?:/|[a-z]:\\|\\windows|\\system32|\bwindows\b|\bsystem32\b)",
            re.IGNORECASE,
        ),
        "Recursive force removal of system/root paths is blocked.",
    ),
    (
        re.compile(r"\breg\s+delete\s+.*(?:hklm|hkcr|hku)\b", re.IGNORECASE),
        "Deleting critical system registry hives is strictly blocked.",
    ),
    (
        re.compile(r"\bshutdown\s+/[sSrR]", re.IGNORECASE),
        "Unconfirmed system shutdown/restart commands are blocked.",
    ),
    (
        re.compile(
            r"\b(?:iex|invoke-expression)\s*[\(\{]|(?:downloadstring|downloadfile)\b",
            re.IGNORECASE,
        ),
        "Executing untrusted remote download scripts is blocked.",
    ),
    (
        re.compile(
            r"\bpowershell(?:\.exe)?\s+.*-(?:enc|encodedcommand)\b",
            re.IGNORECASE,
        ),
        "Obfuscated encoded PowerShell execution is blocked.",
    ),
    (
        re.compile(r"\|\s*(?:bash|powershell|cmd|iex)\b", re.IGNORECASE),
        "Piping untrusted network output into shell interpreters is blocked.",
    ),
    (
        re.compile(r"\bdrop\s+(?:database|schema)\b", re.IGNORECASE),
        "Database drop operations are blocked.",
    ),
]

_READ_ONLY_TERMINAL_PATTERN = re.compile(
    r"^\s*(?:get-process|get-service|get-childitem|get-content|get-command|"
    r"get-history|get-date|get-item|get-location|get-volume|dir|ls|ipconfig|systeminfo|"
    r"ping|tracert|nslookup|netstat|whoami|hostname|tasklist|wmic|where|type|cat|"
    r"head|tail|findstr|echo|git\s+(?:status|log|branch|diff|remote|show)|"
    r"python(?:\.exe)?\s+(?:--version|-V)|pip\s+(?:list|show)|winget\s+(?:search|list))\b",
    re.IGNORECASE,
)


def is_dangerous_terminal_command(command: str) -> tuple[bool, str]:
    """Inspect a shell/PowerShell command against the 4-Layer Zero-Tolerance blocklist."""
    if not command:
        return False, ""
    cleaned = str(command).strip()

    # 1. Financial / checkout patterns
    if is_payment_or_checkout_intent(cleaned):
        return True, PAYMENT_BLOCKED_MESSAGE

    # 2. Camera hardware intent
    if is_physical_camera_intent(cleaned):
        return True, CAMERA_BLOCKED_MESSAGE

    # 3. Dangerous OS modification / wiping rules
    for pattern, reason in _DANGEROUS_TERMINAL_RULES:
        if pattern.search(cleaned):
            return True, f"Security Shield Blocked: {reason}"

    return False, ""


def is_read_only_terminal_command(command: str) -> bool:
    """Return True if command is purely diagnostic, informational, or read-only (Green Tier)."""
    if not command:
        return False
    return bool(_READ_ONLY_TERMINAL_PATTERN.search(str(command).strip()))

