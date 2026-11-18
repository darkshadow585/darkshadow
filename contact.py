"""DarkShadow Contact Manager & Phone Calling Module.

Provides:
1. Fast local contact lookup and fuzzy matching for WhatsApp & Phone calls.
2. JSON / CSV importing from WhatsApp Web export or Google Contacts.
3. Phone call dispatch via Android ADB (Option 2) with automatic fallback to Windows Phone Link (tel: protocol).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent
_PRIMARY_CONTACTS_FILE = _PROJECT_ROOT / "contacts.json"
_BACKUP_CONTACTS_FILE = _PROJECT_ROOT / ".darkshadow" / "contacts.json"
_CURRENT_CONTACTS_FILE: Path | None = None


def _get_contacts_file() -> Path:
    """Return configured contacts file or default primary contacts.json."""
    if _CURRENT_CONTACTS_FILE is not None:
        return _CURRENT_CONTACTS_FILE
    if _PRIMARY_CONTACTS_FILE.exists():
        return _PRIMARY_CONTACTS_FILE
    if _BACKUP_CONTACTS_FILE.exists():
        return _BACKUP_CONTACTS_FILE
    return _PRIMARY_CONTACTS_FILE


def normalize_phone(phone: str) -> str | None:
    """Clean and normalize phone numbers into international format with leading +."""
    if not phone:
        return None
    cleaned = str(phone).strip()
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        return None

    if cleaned.startswith("+"):
        if 7 <= len(digits) <= 15:
            return f"+{digits}"
        return None

    # Standard 10-digit Indian mobile number
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    if 11 <= len(digits) <= 15:
        return f"+{digits}"
    return None


_DUMMY_PHONE_PATTERNS = {
    "9876543210",
    "9876543211",
    "9876543212",
    "9876543213",
    "9876543214",
    "9876543215",
    "1234567890",
    "0123456789",
    "0000000000",
    "1111111111",
    "9999999999",
}


def is_dummy_phone(phone: str | None) -> bool:
    """Check if a phone number matches known placeholder/mock dummy patterns."""
    if not phone:
        return False
    digits = re.sub(r"[^\d]", "", str(phone))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits in _DUMMY_PHONE_PATTERNS


def load_contacts() -> list[dict[str, Any]]:
    """Load all contacts from contacts.json."""
    file_path = _get_contacts_file()
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("contacts", [])
    except Exception as exc:
        LOGGER.warning("Error reading contacts from %s: %s", file_path, exc)
    return []


def save_contacts(contacts: list[dict[str, Any]]) -> bool:
    """Save contacts list to contacts.json."""
    file_path = _get_contacts_file()
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(contacts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        LOGGER.warning("Error saving contacts to %s: %s", file_path, exc)
        return False


def add_contact(name: str, phone: str, aliases: list[str] | None = None) -> bool:
    """Add or update a single contact."""
    clean_name = str(name).strip()
    norm_phone = normalize_phone(phone)
    if not clean_name or not norm_phone:
        return False

    contacts = load_contacts()
    existing = False
    for c in contacts:
        if c.get("name", "").strip().casefold() == clean_name.casefold():
            c["phone"] = norm_phone
            if aliases:
                current_aliases = set(c.get("aliases", []))
                current_aliases.update([a.strip() for a in aliases if a.strip()])
                c["aliases"] = list(current_aliases)
            existing = True
            break

    if not existing:
        contacts.append({
            "name": clean_name,
            "phone": norm_phone,
            "aliases": [a.strip() for a in aliases if a.strip()] if aliases else [],
        })

    return save_contacts(contacts)


def resolve_contact_phone(query: str) -> str | None:
    """Resolve a name, nickname, or raw number to a normalized phone string."""
    cleaned = str(query).strip()
    if not cleaned:
        return None

    # 1. If it's already a valid phone number, normalize and return
    direct_norm = normalize_phone(cleaned)
    compact_digits = re.sub(r"[^\d]", "", cleaned)
    if direct_norm and (len(compact_digits) >= 10 or cleaned.startswith("+")):
        return direct_norm

    # 2. Search local contacts
    contacts = load_contacts()
    if not contacts:
        return None

    q_lower = cleaned.casefold()

    # Exact name match
    for c in contacts:
        if c.get("name", "").strip().casefold() == q_lower:
            return c.get("phone")

    # Exact alias match
    for c in contacts:
        for alias in c.get("aliases", []):
            if str(alias).strip().casefold() == q_lower:
                return c.get("phone")

    # Word token match (e.g. 'Rohan' in 'Rohan Sharma')
    q_words = set(q_lower.split())
    for c in contacts:
        c_name = c.get("name", "").strip().casefold()
        c_words = set(c_name.split())
        if q_lower in c_words:
            return c.get("phone")
        for alias in c.get("aliases", []):
            a_words = set(str(alias).strip().casefold().split())
            if q_lower in a_words:
                return c.get("phone")

    # Full name in query as whole word/phrase (e.g. 'call Rohit Sharma please')
    for c in contacts:
        c_name = c.get("name", "").strip().casefold()
        if len(c_name) >= 3 and re.search(r"\b" + re.escape(c_name) + r"\b", q_lower):
            return c.get("phone")

    # Substring match if query has at least 3 characters
    if len(q_lower) >= 3:
        for c in contacts:
            c_name = c.get("name", "").strip().casefold()
            if q_lower in c_name:
                return c.get("phone")
            for alias in c.get("aliases", []):
                a_lower = str(alias).strip().casefold()
                if q_lower in a_lower:
                    return c.get("phone")

    return None


def import_contacts_file(file_path: str | Path) -> dict[str, Any]:
    """Import contacts from JSON or CSV file into contacts.json."""
    p = Path(file_path)
    if not p.exists():
        return {"success": False, "error": f"File '{file_path}' not found."}

    existing_contacts = load_contacts()
    existing_map: dict[str, dict[str, Any]] = {
        c.get("name", "").casefold(): c for c in existing_contacts if c.get("name")
    }

    imported_count = 0
    updated_count = 0

    if p.suffix.lower() == ".json":
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else data.get("contacts", [])
            for item in items:
                name = str(item.get("name") or item.get("contact_name") or "").strip()
                phone = str(item.get("number") or item.get("phone") or "").strip()
                norm = normalize_phone(phone)
                if not name or not norm:
                    continue
                key = name.casefold()
                if key in existing_map:
                    existing_map[key]["phone"] = norm
                    updated_count += 1
                else:
                    new_item = {"name": name, "phone": norm, "aliases": item.get("aliases", [])}
                    existing_contacts.append(new_item)
                    existing_map[key] = new_item
                    imported_count += 1
        except Exception as exc:
            return {"success": False, "error": f"JSON import error: {exc}"}

    elif p.suffix.lower() == ".csv":
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Support Google Contacts CSV headers
                    name = (
                        row.get("Name")
                        or f"{row.get('Given Name', '')} {row.get('Family Name', '')}".strip()
                        or row.get("name")
                        or ""
                    ).strip()
                    # Look for phone columns
                    phone = (
                        row.get("Phone 1 - Value")
                        or row.get("Phone")
                        or row.get("Mobile")
                        or row.get("number")
                        or ""
                    ).strip()
                    norm = normalize_phone(phone)
                    if not name or not norm:
                        continue
                    key = name.casefold()
                    if key in existing_map:
                        existing_map[key]["phone"] = norm
                        updated_count += 1
                    else:
                        new_item = {"name": name, "phone": norm, "aliases": []}
                        existing_contacts.append(new_item)
                        existing_map[key] = new_item
                        imported_count += 1
        except Exception as exc:
            return {"success": False, "error": f"CSV import error: {exc}"}
    else:
        return {"success": False, "error": "Unsupported file format. Please use .json or .csv"}

    save_contacts(existing_contacts)
    return {
        "success": True,
        "imported": imported_count,
        "updated": updated_count,
        "total": len(existing_contacts),
        "message": f"{imported_count} naye contacts import hue, {updated_count} update hue. Total: {len(existing_contacts)} contacts.",
    }


def _find_adb_path() -> str | None:
    """Find adb executable path on Windows."""
    which_adb = shutil.which("adb")
    if which_adb:
        return which_adb

    candidates = [
        _PROJECT_ROOT / "platform-tools" / "adb.exe",
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")),
        Path(r"C:\platform-tools\adb.exe"),
        Path(r"C:\adb\adb.exe"),
        Path(os.path.expandvars(r"%USERPROFILE%\platform-tools\adb.exe")),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def make_phone_call(recipient: str, method: str = "auto") -> dict[str, Any]:
    """Dial a phone call via Microsoft Mobile Link (Phone Link) or connected Android ADB.

    Usage:
        make_phone_call("Kuldeep")
        make_phone_call("9876543210", method="phone_link")
    """
    cleaned = str(recipient).strip()
    if not cleaned:
        return {"success": False, "message": "Recipient name ya phone number batayein."}

    resolved_phone = resolve_contact_phone(cleaned)
    if not resolved_phone:
        return {
            "success": False,
            "message": f"Contact '{cleaned}' ka number nahi mila. Kripya contacts.json me number check kijiye.",
            "error": "contact_not_found",
        }

    norm_method = (method or "auto").strip().lower()

    def _dial_phone_link() -> dict[str, Any] | None:
        try:
            # Copy to clipboard as convenient helper for dialer
            try:
                subprocess.run(["clip"], input=resolved_phone.encode("utf-8"), check=False, timeout=1)
            except Exception:
                pass

            startfile = getattr(os, "startfile", None)
            if callable(startfile):
                try:
                    startfile(f"tel:{resolved_phone}")
                except Exception as tel_exc:
                    LOGGER.debug("startfile tel: failed (%s), trying ms-phone:", tel_exc)
                    startfile("ms-phone:")
            else:
                try:
                    subprocess.run(["cmd", "/c", "start", f"tel:{resolved_phone}"], check=True, timeout=3, shell=True)
                except Exception:
                    subprocess.run(["cmd", "/c", "start", "ms-phone:"], check=False, timeout=3, shell=True)

            return {
                "success": True,
                "method": "phone_link",
                "phone": resolved_phone,
                "recipient": cleaned,
                "message": f"Captain, Microsoft Mobile Link ke zariye {cleaned} ({resolved_phone}) ko call laga diya hai.",
            }
        except Exception as tel_err:
            LOGGER.warning("Microsoft Phone Link dialer launch failed: %s", tel_err)
            return None

    def _dial_adb() -> dict[str, Any] | None:
        adb_bin = _find_adb_path()
        if not adb_bin:
            return None
        try:
            devices_out = subprocess.check_output(
                [adb_bin, "devices"],
                stderr=subprocess.STDOUT,
                timeout=3,
            ).decode("utf-8", errors="ignore")

            connected_devices = [
                line.split()[0]
                for line in devices_out.splitlines()[1:]
                if line.strip() and "\tdevice" in line
            ]

            if connected_devices:
                call_cmd = [
                    adb_bin,
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.CALL",
                    "-d",
                    f"tel:{resolved_phone}",
                ]
                subprocess.run(call_cmd, check=True, timeout=5)
                LOGGER.info("Dispatched ADB phone call to %s via %s", resolved_phone, connected_devices[0])
                return {
                    "success": True,
                    "method": "adb",
                    "device": connected_devices[0],
                    "phone": resolved_phone,
                    "recipient": cleaned,
                    "message": f"Captain, Android phone se {cleaned} ({resolved_phone}) ko call laga diya hai.",
                }
        except Exception as adb_err:
            LOGGER.debug("ADB call attempt notice: %s", adb_err)
        return None

    # 1. If method explicitly requests phone_link / mobile_link
    if norm_method in {"phone_link", "phonelink", "mobile_link", "mobilelink", "windows"}:
        res = _dial_phone_link()
        if res:
            return res
        return {
            "success": False,
            "phone": resolved_phone,
            "error": "dialer_failed",
            "message": f"Captain, {cleaned} ({resolved_phone}) ko call lagane ke liye Microsoft Phone Link open nahi ho saka.",
        }

    # 2. If method explicitly requests ADB
    if norm_method == "adb":
        res = _dial_adb()
        if res:
            return res
        return {
            "success": False,
            "phone": resolved_phone,
            "error": "adb_unavailable",
            "message": f"Captain, {cleaned} ({resolved_phone}) ko call lagane ke liye koi connected Android ADB device nahi mila.",
        }

    # 3. Auto mode: try ADB if connected, fallback to Phone Link
    res = _dial_adb()
    if res:
        return res
    res = _dial_phone_link()
    if res:
        return res

    return {
        "success": False,
        "phone": resolved_phone,
        "error": "dialer_failed",
        "message": f"{cleaned} ({resolved_phone}) ko call lagane ke liye Phone Link ya ADB device available nahi hai.",
    }


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args or args[0] in {"--help", "-h", "help"}:
        print("DarkShadow Contact Manager")
        print("Commands:")
        print("  py contact.py list")
        print("  py contact.py add <name> <phone> [<alias1>,...]")
        print("  py contact.py search <name>")
        print("  py contact.py import <file.json|file.csv>")
        print("  py contact.py call <name|number>")
        sys.exit(0)

    cmd = args[0].lower().lstrip("-")
    if cmd == "list":
        contacts = load_contacts()
        print(f"Total contacts: {len(contacts)}")
        for c in contacts:
            aliases = f" ({', '.join(c.get('aliases', []))})" if c.get("aliases") else ""
            print(f"  • {c.get('name')}: {c.get('phone')}{aliases}")

    elif cmd == "add" and len(args) >= 3:
        name = args[1]
        phone = args[2]
        aliases = args[3].split(",") if len(args) > 3 else []
        if add_contact(name, phone, aliases):
            print(f"✅ Contact '{name}' ({phone}) saved successfully!")
        else:
            print("❌ Failed to save contact.")

    elif cmd == "search" and len(args) >= 2:
        q = args[1]
        res = resolve_contact_phone(q)
        if res:
            print(f"Found phone for '{q}': {res}")
        else:
            print(f"No phone found for '{q}'.")

    elif cmd in {"import", "load"} and len(args) >= 2:
        res = import_contacts_file(args[1])
        print(res.get("message") or res.get("error"))

    elif cmd == "call" and len(args) >= 2:
        res = make_phone_call(args[1])
        print(res.get("message"))
