"""Headless background WhatsApp messaging engine for DarkShadow.

Supports:
1. Official Meta WhatsApp Cloud API (Graph API)
2. Twilio WhatsApp REST API
3. Clean phone number normalization and fallback detection
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

LOGGER = logging.getLogger(__name__)


def normalize_whatsapp_phone(recipient: str) -> str | None:
    """Normalize user-provided recipient into clean international E.164 phone digits.

    Returns digits with leading + (e.g. '+919876543210') or None if not a valid phone number.
    """
    cleaned = str(recipient).strip()
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        return None

    # Already includes leading + or standard international length
    if cleaned.startswith("+"):
        if 7 <= len(digits) <= 15:
            return f"+{digits}"
        return None

    # Indian 10-digit mobile number auto-prefix +91
    if len(digits) == 10:
        return f"+91{digits}"

    # 11 or 12 digit numbers starting with 91 or 0
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    if len(digits) >= 11 and 11 <= len(digits) <= 15:
        return f"+{digits}"

    return None


def send_whatsapp_cloud_api(
    phone_number_id: str,
    access_token: str,
    recipient_phone: str,
    message: str,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Dispatch a WhatsApp message via Meta's official WhatsApp Cloud API."""
    phone_digits = re.sub(r"[^\d]", "", recipient_phone)
    if not phone_digits:
        return {"success": False, "error": "invalid_recipient_phone", "provider": "cloud_api"}

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_digits,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message,
        },
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Authorization": f"Bearer {access_token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "DarkShadow-AI/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            status_code = response.status
            res_data = json.loads(response.read().decode("utf-8"))
            msg_id = ""
            if "messages" in res_data and res_data["messages"]:
                msg_id = res_data["messages"][0].get("id", "")
            return {
                "success": True,
                "provider": "cloud_api",
                "status_code": status_code,
                "message_id": msg_id,
                "data": res_data,
            }
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="ignore")
        LOGGER.warning("WhatsApp Cloud API HTTP error %d: %s", err.code, err_body)
        return {
            "success": False,
            "provider": "cloud_api",
            "status_code": err.code,
            "error": f"HTTP {err.code}: {err_body}",
        }
    except Exception as exc:
        LOGGER.warning("WhatsApp Cloud API dispatch error: %s", exc)
        return {
            "success": False,
            "provider": "cloud_api",
            "error": str(exc),
        }


def send_twilio_whatsapp(
    account_sid: str,
    auth_token: str,
    from_number: str,
    recipient_phone: str,
    message: str,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Dispatch a WhatsApp message via Twilio REST API."""
    import base64

    clean_to = recipient_phone if recipient_phone.startswith("+") else f"+{recipient_phone}"
    to_field = f"whatsapp:{clean_to}"
    from_field = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    form_data = urllib.parse.urlencode({
        "To": to_field,
        "From": from_field,
        "Body": message,
    }).encode("utf-8")

    auth_str = f"{account_sid}:{auth_token}"
    auth_header = f"Basic {base64.b64encode(auth_str.encode('ascii')).decode('ascii')}"

    req = urllib.request.Request(
        url,
        data=form_data,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "DarkShadow-AI/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            status_code = response.status
            res_data = json.loads(response.read().decode("utf-8"))
            return {
                "success": True,
                "provider": "twilio",
                "status_code": status_code,
                "message_sid": res_data.get("sid", ""),
                "status": res_data.get("status", ""),
                "data": res_data,
            }
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="ignore")
        LOGGER.warning("Twilio WhatsApp HTTP error %d: %s", err.code, err_body)
        return {
            "success": False,
            "provider": "twilio",
            "status_code": err.code,
            "error": f"HTTP {err.code}: {err_body}",
        }
    except Exception as exc:
        LOGGER.warning("Twilio WhatsApp dispatch error: %s", exc)
        return {
            "success": False,
            "provider": "twilio",
            "error": str(exc),
        }


def dispatch_headless_whatsapp(
    recipient: str,
    message: str,
    settings: Any | None = None,
) -> dict[str, Any] | None:
    """Dispatch WhatsApp message headlessly if API credentials are configured.

    Returns dict with success info, or None if no headless API is configured so
    the system can fall back to desktop/browser automation.
    """
    if settings is None:
        try:
            from config import load_settings
            settings = load_settings()
        except Exception:
            return None

    normalized_phone = normalize_whatsapp_phone(recipient)
    if not normalized_phone:
        # Recipient is a contact name or not a valid phone number; cannot use headless direct API
        return None

    provider = getattr(settings, "whatsapp_provider", "auto").lower()

    # 1. WhatsApp Cloud API
    if provider in {"auto", "cloud_api"} and getattr(settings, "whatsapp_cloud_configured", False):
        phone_id = settings.whatsapp_phone_number_id or ""
        token = settings.whatsapp_access_token or ""
        if phone_id and token:
            res = send_whatsapp_cloud_api(phone_id, token, normalized_phone, message)
            if res.get("success"):
                return res
            # If explicit cloud_api was requested and failed, return error
            if provider == "cloud_api":
                return res

    # 2. Twilio WhatsApp API
    if provider in {"auto", "twilio"} and getattr(settings, "twilio_whatsapp_configured", False):
        sid = settings.twilio_account_sid or ""
        auth = settings.twilio_auth_token or ""
        from_num = getattr(settings, "twilio_whatsapp_from", None) or "+14155238886"  # Twilio sandbox default
        if sid and auth:
            res = send_twilio_whatsapp(sid, auth, from_num, normalized_phone, message)
            if res.get("success"):
                return res
            if provider == "twilio":
                return res

    return None
