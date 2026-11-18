"""Unified Tool Registry & Dispatcher for DarkShadow.

Serves as the single source of truth across all interaction modes
(Live Voice WebSocket, Typed CLI, Desktop GUI, and ReAct loops) for:
1. Tool argument normalization (forgiving model input variations)
2. Safety gating (blocking payment, checkout, and camera intents)
3. Schema export for Gemini & OpenAI function declarations
4. Unified dispatch to native automation and external MCP tools
"""

from __future__ import annotations

import logging
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


def normalize_tool_arguments(name: str, args: dict[str, Any], user_context: str = "") -> tuple[str, dict[str, Any]]:
    """Normalize model-provided tool arguments to match strict local schemas."""
    name = str(name).strip().lower()
    args = dict(args) if isinstance(args, dict) else {}

    if name == "set_brightness":
        level = (
            args.get("level")
            or args.get("brightness")
            or args.get("value")
            or args.get("percent")
            or args.get("amount")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if level is not None:
            try:
                return "set_brightness", {"level": max(0, min(100, int(level)))}
            except (ValueError, TypeError):
                pass

    elif name == "set_volume":
        level = (
            args.get("level")
            or args.get("volume")
            or args.get("value")
            or args.get("percent")
            or args.get("amount")
            or (list(args.values())[0] if len(args) == 1 else None)
        )
        if level is not None:
            try:
                return "set_volume", {"level": max(0, min(100, int(level)))}
            except (ValueError, TypeError):
                pass

    elif name == "change_volume":
        if "magnitude" in args:
            try:
                mag = int(args["magnitude"])
                direction = "down" if mag < 0 else "up"
                return "change_volume", {
                    "direction": direction,
                    "amount": max(1, min(100, abs(mag))),
                }
            except (ValueError, TypeError):
                pass
        if "direction" in args and (
            "amount" in args or "value" in args or "step" in args
        ):
            d = str(args.get("direction", "up")).lower()
            amt = args.get("amount") or args.get("value") or args.get("step") or 10
            try:
                return "change_volume", {
                    "direction": "down" if ("down" in d or "dec" in d or "-" in d) else "up",
                    "amount": max(1, min(100, abs(int(amt)))),
                }
            except (ValueError, TypeError):
                pass
        if "amount" in args:
            try:
                amt = int(args["amount"])
                direction = "down" if amt < 0 else "up"
                return "change_volume", {
                    "direction": direction,
                    "amount": max(1, min(100, abs(amt))),
                }
            except (ValueError, TypeError):
                pass

    elif name in {"search_youtube", "play_youtube", "play_mood_music"}:
        q = (
            args.get("query")
            or args.get("song_name")
            or args.get("song")
            or args.get("track")
            or args.get("search_query")
            or args.get("title")
            or args.get("video_name")
            or args.get("mood")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return name, {"query": str(q).strip()}

    elif name in {"search_spotify", "play_spotify"}:
        q = (
            args.get("query")
            or args.get("track")
            or args.get("song")
            or args.get("artist")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return name, {"query": str(q).strip()}

    elif name == "search_google":
        q = (
            args.get("query")
            or args.get("search_query")
            or args.get("term")
            or args.get("keywords")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "search_google", {"query": str(q).strip()}

    elif name == "open_application":
        app = (
            args.get("app_name")
            or args.get("application")
            or args.get("name")
            or args.get("target")
            or (list(args.values())[0] if len(args) == 1 else "Edge")
        )
        return "open_application", {"app_name": str(app).strip()}

    elif name == "open_website":
        url = (
            args.get("url_or_name")
            or args.get("url")
            or args.get("website")
            or args.get("site")
            or (list(args.values())[0] if len(args) == 1 else "google.com")
        )
        return "open_website", {"url_or_name": str(url).strip()}

    elif name in {"send_whatsapp_message", "whatsapp_send"}:
        contact = (
            args.get("recipient")
            or args.get("contact_name")
            or args.get("contact")
            or args.get("phone_number")
            or args.get("phone")
            or args.get("to")
            or args.get("name")
            or ""
        )
        msg = (
            args.get("message")
            or args.get("text")
            or args.get("body")
            or args.get("msg")
            or args.get("content")
            or ""
        )
        return "send_whatsapp_message", {
            "recipient": str(contact).strip(),
            "message": str(msg).strip(),
        }

    elif name in {"search_whatsapp_contact", "search_whatsapp", "whatsapp_search"}:
        contact = (
            args.get("contact_name")
            or args.get("contact")
            or args.get("query")
            or args.get("name")
            or args.get("recipient")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "search_whatsapp_contact", {"contact_name": str(contact).strip()}

    elif name in {"prepare_whatsapp_message", "whatsapp_draft", "draft_whatsapp"}:
        contact = (
            args.get("recipient")
            or args.get("contact_name")
            or args.get("contact")
            or args.get("phone")
            or args.get("to")
            or ""
        )
        msg = (
            args.get("message")
            or args.get("text")
            or args.get("body")
            or ""
        )
        return "prepare_whatsapp_message", {
            "recipient": str(contact).strip(),
            "message": str(msg).strip(),
        }

    elif name in {"make_phone_call", "phone_call", "call_contact", "call_phone", "dial_call", "call"}:
        recip = (
            args.get("recipient")
            or args.get("contact_name")
            or args.get("contact")
            or args.get("phone")
            or args.get("number")
            or args.get("name")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        kwargs = {"recipient": str(recip).strip()}
        if "method" in args and args["method"]:
            kwargs["method"] = str(args["method"]).strip()
        return "make_phone_call", kwargs

    elif name == "scroll_screen":
        d = (
            args.get("direction")
            or ("down" if "down" in str(args).lower() else "up")
        )
        clicks = args.get("clicks") or args.get("amount") or 5
        try:
            clicks = int(clicks)
        except (ValueError, TypeError):
            clicks = 5
        return "scroll_screen", {"direction": str(d).lower(), "clicks": clicks}

    elif name == "click_screen_element":
        desc = (
            args.get("description")
            or args.get("element")
            or args.get("target")
            or args.get("name")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "click_screen_element", {"description": str(desc).strip()}

    elif name in {"execute_terminal_command", "terminal_command", "run_terminal_command", "powershell_command"}:
        cmd = (
            args.get("command")
            or args.get("cmd")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        return "execute_terminal_command", {"command": str(cmd).strip()}

    elif name == "search_local_files":
        q = (
            args.get("query")
            or args.get("filename")
            or args.get("pattern")
            or (list(args.values())[0] if len(args) == 1 else "")
        )
        ext = args.get("extension") or ""
        return "search_local_files", {"query": str(q).strip(), "extension": str(ext).strip()}

    elif name in {"inspect_desktop_window", "inspect_window", "inspect_active_window", "get_active_window_context", "active_window_context"}:
        return "inspect_desktop_window", {}

    elif name in {"get_system_telemetry", "system_telemetry", "hardware_telemetry", "get_system_health", "system_health", "system_diagnostics"}:
        return "get_system_telemetry", {}

    elif name in {"get_top_processes", "top_processes", "list_processes", "heavy_processes"}:
        limit = args.get("limit") or 5
        return "get_top_processes", {"limit": int(limit)}

    return name, args


def dispatch_tool(raw_name: str, raw_args: dict[str, Any], user_context: str = "") -> dict[str, Any]:
    """Execute any local automation tool or MCP tool with safety checks and normalization."""
    from safety import is_payment_or_checkout_intent, PAYMENT_BLOCKED_MESSAGE

    # 1. Payment / Financial Safety Barrier
    if is_payment_or_checkout_intent(raw_name) or any(
        is_payment_or_checkout_intent(str(v)) for v in raw_args.values()
    ):
        LOGGER.warning("Blocked payment/checkout tool call: %s(%s)", raw_name, raw_args)
        return {"status": "blocked", "message": PAYMENT_BLOCKED_MESSAGE}

    # 2. Check Model Context Protocol (MCP) server tools first
    try:
        from mcp_client import MCPManager
        mcp = MCPManager.get_instance()
        if mcp.is_mcp_tool(raw_name):
            LOGGER.info("Dispatching to MCP server: %s", raw_name)
            res = mcp.execute_tool(raw_name, raw_args)
            return {
                "status": "ok" if res.get("success") else "error",
                "message": res.get("output") or res.get("error", "MCP tool finished"),
                "data": res.get("raw"),
            }
    except Exception as mcp_exc:
        LOGGER.debug("MCP check notice: %s", mcp_exc)

    # 3. Argument normalization
    name, args = normalize_tool_arguments(raw_name, raw_args, user_context=user_context)

    # 4. Automation command parser & executor
    try:
        from automation import (
            parsed_command_from_tool_call,
            execute_automation_command,
            open_application,
            open_website,
            set_brightness,
            set_volume,
            change_volume,
            search_google,
            search_youtube,
            search_in_active_app,
            play_youtube,
            get_current_time,
            get_current_date,
            get_system_status,
            analyze_screen_content,
            search_product_prices,
            scroll_screen,
            click_screen_element,
            control_browser_action,
            press_keyboard_key,
            send_whatsapp_message,
            search_whatsapp_contact,
            prepare_whatsapp_message,
            make_phone_call,
        )

        command = parsed_command_from_tool_call(name, args)
        if command is not None:
            result = execute_automation_command(command)
            if result is not None:
                payload: dict[str, Any] = {
                    "status": "ok" if result.success else "error",
                    "message": result.message,
                }
                if result.data:
                    payload["data"] = result.data
                return payload

        # Direct functional fallback
        if name == "make_phone_call":
            recip = args.get("recipient") or args.get("contact_name", "")
            method = args.get("method")
            if method:
                res = make_phone_call(recipient=str(recip), method=str(method))
            else:
                res = make_phone_call(recipient=str(recip))
            return {"status": "ok" if res.success else "error", "message": res.message, "data": getattr(res, "data", {})}
        elif name == "send_whatsapp_message":
            recip = args.get("recipient") or args.get("contact_name", "")
            msg = args.get("message", "")
            res = send_whatsapp_message(recipient=str(recip), message=str(msg))
            return {"status": "ok" if res.success else "error", "message": res.message, "data": getattr(res, "data", {})}
        elif name == "search_whatsapp_contact":
            c_name = args.get("contact_name") or args.get("contact", "")
            res = search_whatsapp_contact(contact_name=str(c_name))
            return {"status": "ok" if res.success else "error", "message": res.message, "data": getattr(res, "data", {})}
        elif name == "prepare_whatsapp_message":
            recip = args.get("recipient") or args.get("contact_name", "")
            msg = args.get("message", "")
            res = prepare_whatsapp_message(recipient=str(recip), message=str(msg))
            return {"status": "ok" if res.success else "error", "message": res.message, "data": getattr(res, "data", {})}
        elif name in {"inspect_desktop_window", "get_active_window_context"}:
            from automation import inspect_desktop_window
            res = inspect_desktop_window()
            return {"status": "ok" if res.success else "error", "message": res.message, "data": getattr(res, "data", {})}
        elif name == "search_in_active_app":
            q = args.get("query", "")
            app_hint = args.get("app_name") or "youtube"
            res = search_in_active_app(query=str(q), app_name=app_hint)
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "open_application":
            target = args.get("app_name") or "Edge"
            res = open_application(str(target))
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "open_website":
            target = args.get("url_or_name") or "google.com"
            res = open_website(str(target))
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "search_google":
            q = args.get("query", "")
            res = search_google(str(q))
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "play_youtube":
            q = args.get("query", "")
            res = play_youtube(str(q))
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "set_volume":
            lvl = int(args.get("level", 50))
            res = set_volume(lvl)
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "set_brightness":
            lvl = int(args.get("level", 70))
            res = set_brightness(lvl)
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "get_current_time":
            res = get_current_time()
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "get_current_date":
            res = get_current_date()
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "get_system_status":
            res = get_system_status()
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "get_system_telemetry":
            from system_sentinel import SystemSentinel
            sentinel = SystemSentinel.get_instance()
            report = sentinel.format_telemetry_report()
            return {"status": "ok", "message": report, "data": {"report": report}}
        elif name == "get_top_processes":
            from system_sentinel import SystemSentinel
            sentinel = SystemSentinel.get_instance()
            limit = int(args.get("limit", 5))
            procs = sentinel.get_top_processes(limit=limit)
            report_lines = [f"Captain, top {len(procs)} resource-consuming apps:"]
            for p in procs:
                report_lines.append(f"  - `{p['name']}` (PID {p['pid']}): {p['memory_mb']} MB RAM | {p['cpu_percent']}% CPU")
            msg = "\n".join(report_lines)
            return {"status": "ok", "message": msg, "data": {"processes": procs}}
        elif name == "scroll_screen":
            d = args.get("direction", "down")
            c = int(args.get("clicks", 5))
            res = scroll_screen(direction=d, clicks=c)
            return {"status": "ok" if res.success else "error", "message": res.message}
        elif name == "click_screen_element":
            desc = args.get("description", "")
            res = click_screen_element(target=desc)
            return {"status": "ok" if res.success else "error", "message": res.message}

    except Exception as exc:
        LOGGER.warning("Tool dispatch failed for '%s': %s", raw_name, exc)
        return {"status": "error", "message": f"Tool '{raw_name}' execution me error aaya: {exc}"}

    return {"status": "error", "message": f"Unknown tool: '{raw_name}'"}


def get_unified_tool_schemas(
    include_browser_dom: bool = False,
    include_mcp: bool = True,
) -> list[dict[str, Any]]:
    """Return unified tool schemas compatible with Gemini Function Declarations."""
    try:
        from automation import AUTOMATION_FUNCTION_SCHEMAS
        schemas: list[dict[str, Any]] = []

        excluded_browser_tools = {
            "browser_navigate",
            "browser_click_selector",
            "browser_fill_input",
            "browser_extract_text",
            "vision_browser_goal",
            "control_browser_action",
        }

        for schema in AUTOMATION_FUNCTION_SCHEMAS:
            s_dict = dict(schema)
            if not include_browser_dom and s_dict.get("name") in excluded_browser_tools:
                continue
            schemas.append(s_dict)

        if include_mcp:
            try:
                from mcp_client import MCPManager
                mcp = MCPManager.get_instance()
                mcp_schemas = mcp.get_all_tool_schemas()
                schemas.extend(mcp_schemas)
            except Exception as mcp_err:
                LOGGER.debug("MCP schema merge notice: %s", mcp_err)

        return schemas
    except Exception as exc:
        LOGGER.warning("Failed to build unified tool schemas: %s", exc)
        return []


__all__ = [
    "normalize_tool_arguments",
    "dispatch_tool",
    "get_unified_tool_schemas",
]
