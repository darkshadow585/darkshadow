"""DarkShadow <-> 3D GPU Fur Avatar WebSocket Bridge Server.

Bridges the 3D Fur simulation frontend (Three.js/WebGL in browser)
with DarkShadow's Python OS automation backend:
1. Exposes all DarkShadow OS tools (YouTube, WhatsApp, volume, brightness, terminal, etc.)
2. Executes tools dispatched by Gemini Live in real-time
3. Streams live Windows desktop context, time, and active application state
4. Supports both WebSocket (ws://127.0.0.1:8765/ws) and CORS-enabled HTTP endpoints
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime
from typing import Any

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from aiohttp import web

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [DarkShadow Bridge] %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("darkshadow_bridge")

HOST = "127.0.0.1"
PORT = 8765

CONNECTED_WEBSOCKETS: set[web.WebSocketResponse] = set()


def _convert_schema_types_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert lowercase JSON schema types to uppercase for Gemini Live API."""
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out[k] = v.upper()
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: _convert_schema_types_for_gemini(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _convert_schema_types_for_gemini(v)
        else:
            out[k] = v
    return out


def get_available_tools() -> list[dict[str, Any]]:
    """Return tool declarations for the 3D avatar frontend formatted for Gemini Live."""
    from automation import AUTOMATION_FUNCTION_SCHEMAS

    excluded = {
        "browser_fill_input",
        "browser_click_selector",
        "browser_navigate",
        "browser_extract_text",
    }
    declarations = []
    for s in AUTOMATION_FUNCTION_SCHEMAS:
        name = s.get("name", "")
        if name in excluded:
            continue
        params = s.get("parameters", {})
        cleaned_params = _convert_schema_types_for_gemini(params)
        declarations.append({
            "name": name,
            "description": s.get("description", ""),
            "parameters": cleaned_params,
        })
    return declarations


def get_current_context() -> dict[str, Any]:
    """Return real-time context from DarkShadow."""
    now_local = datetime.now().strftime("%I:%M %p (%d %B %Y, %A)")
    active_title = "Desktop"
    active_proc = "unknown"
    try:
        from desktop_engine import get_desktop_engine
        engine = get_desktop_engine()
        active_title = engine.get_active_window_title() or "Desktop"
        active_proc = getattr(engine, "_get_foreground_process_name", lambda: "unknown")()
    except Exception:
        pass

    return {
        "time": now_local,
        "active_window": active_title,
        "active_process": active_proc,
        "platform": sys.platform,
    }


# =============================================================================
# AIOHTTP MIDDLEWARE & HANDLERS
# =============================================================================

@web.middleware
async def cors_middleware(request: web.Request, handler: Any) -> web.Response:
    """Allow CORS from local Vite dev server (localhost:5173) or any origin."""
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


async def handle_status(request: web.Request) -> web.Response:
    """HTTP GET /status: Health check."""
    return web.json_response({
        "status": "online",
        "service": "DarkShadow 3D Avatar Bridge",
        "clients_connected": len(CONNECTED_WEBSOCKETS),
        "context": get_current_context(),
    })


async def handle_tools(request: web.Request) -> web.Response:
    """HTTP GET /tools: Export DarkShadow tool declarations."""
    tools = get_available_tools()
    return web.json_response({
        "count": len(tools),
        "tools": tools,
    })


async def handle_execute(request: web.Request) -> web.Response:
    """HTTP POST /execute: Execute a DarkShadow tool via HTTP."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)

    name = str(body.get("name", "")).strip()
    args = body.get("args") or {}
    if not name:
        return web.json_response({"error": "missing_tool_name"}, status=400)

    from tool_registry import dispatch_tool
    loop = asyncio.get_running_loop()
    LOGGER.info("Executing tool via HTTP: %s(%s)", name, args)
    res = await loop.run_in_executor(None, dispatch_tool, name, args)
    return web.json_response({
        "name": name,
        "result": res,
        "message": res.get("message", "Done"),
    })


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """WebSocket connection handler for the 3D Avatar frontend."""
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)

    CONNECTED_WEBSOCKETS.add(ws)
    client_ip = request.remote or "127.0.0.1"
    LOGGER.info("3D Fur Avatar connected from %s! (Total clients: %d)", client_ip, len(CONNECTED_WEBSOCKETS))

    # Send initial welcome & context
    welcome_msg = {
        "type": "welcome",
        "service": "DarkShadow OS Brain",
        "version": "2.0",
        "context": get_current_context(),
        "total_tools": len(get_available_tools()),
    }
    await ws.send_str(json.dumps(welcome_msg))

    loop = asyncio.get_running_loop()

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except Exception:
                    await ws.send_str(json.dumps({"type": "error", "message": "Invalid JSON"}))
                    continue

                msg_type = payload.get("type", "")

                if msg_type == "ping":
                    await ws.send_str(json.dumps({"type": "pong", "time": time.time()}))

                elif msg_type == "get_tools":
                    tools = get_available_tools()
                    await ws.send_str(json.dumps({
                        "type": "tools_list",
                        "count": len(tools),
                        "tools": tools,
                    }))

                elif msg_type == "get_context":
                    await ws.send_str(json.dumps({
                        "type": "context",
                        "context": get_current_context(),
                    }))

                elif msg_type == "execute_tool":
                    call_id = payload.get("id") or str(uuid.uuid4())
                    name = str(payload.get("name", "")).strip()
                    args = payload.get("args") or {}
                    user_ctx = str(payload.get("user_context", "")).strip()

                    LOGGER.info("Avatar Tool Call: %s(%s)", name, args)

                    from tool_registry import dispatch_tool
                    try:
                        res = await loop.run_in_executor(
                            None, dispatch_tool, name, args, user_ctx
                        )
                        success = bool(res.get("status") not in {"blocked", "error"})
                        msg_text = str(res.get("message") or res.get("output") or "Done")

                        resp = {
                            "type": "tool_result",
                            "id": call_id,
                            "name": name,
                            "success": success,
                            "message": msg_text,
                            "data": res,
                        }
                    except Exception as exec_err:
                        LOGGER.exception("Tool execution exception: %s", exec_err)
                        resp = {
                            "type": "tool_result",
                            "id": call_id,
                            "name": name,
                            "success": False,
                            "message": f"Tool error: {exec_err}",
                            "data": {"error": str(exec_err)},
                        }

                    await ws.send_str(json.dumps(resp))
                    LOGGER.info("Sent result for %s: %s", name, resp["message"][:80])

            elif msg.type == web.WSMsgType.ERROR:
                LOGGER.warning("WebSocket error: %s", ws.exception())
    finally:
        CONNECTED_WEBSOCKETS.discard(ws)
        LOGGER.info("3D Fur Avatar disconnected. (Remaining clients: %d)", len(CONNECTED_WEBSOCKETS))

    return ws


def create_app() -> web.Application:
    """Build and configure the aiohttp application."""
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_status)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/tools", handle_tools)
    app.router.add_post("/execute", handle_execute)
    app.router.add_get("/ws", handle_websocket)
    return app


def main() -> None:
    """Run the DarkShadow Bridge Server."""
    print("=" * 70)
    print("  [DarkShadow] 3D GPU Fur Simulation Bridge Server")
    print(f"  Listening on: ws://{HOST}:{PORT}/ws and http://{HOST}:{PORT}")
    print("=" * 70)
    app = create_app()
    web.run_app(app, host=HOST, port=PORT, print=LOGGER.info)


if __name__ == "__main__":
    main()
