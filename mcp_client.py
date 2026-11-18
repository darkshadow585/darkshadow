"""Model Context Protocol (MCP) Client & Manager for DarkShadow.

Enables DarkShadow to connect to standard MCP servers over stdio JSON-RPC 2.0,
automatically translating MCP tools into Gemini/OpenAI function schemas
and executing them seamlessly alongside built-in skills.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

DEFAULT_MCP_CONFIG_PATH = Path(".darkshadow/mcp_servers.json")


@dataclass
class MCPToolDefinition:
    """Definition of a single tool exposed by an MCP server."""

    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_gemini_schema(self) -> dict[str, Any]:
        """Convert MCP inputSchema into Gemini function declaration format."""
        schema = dict(self.input_schema)
        # Ensure 'type' is present and schema structure is compatible
        if "type" not in schema:
            schema["type"] = "object"
        return {
            "name": f"mcp_{self.server_name}_{self.name}",
            "description": f"[MCP:{self.server_name}] {self.description}",
            "parameters": schema,
        }


class MCPClient:
    """Manages a single MCP server connection over standard I/O (stdio)."""

    def __init__(self, server_name: str, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        self.server_name = server_name
        self.command = command
        self.args = args
        self.env = env or os.environ.copy()
        self._process: subprocess.Popen[str] | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._tools: dict[str, MCPToolDefinition] = {}
        self.is_connected = False

    def start(self) -> bool:
        """Start the MCP server subprocess and perform the initialize handshake."""
        cmd = [self.command] + self.args
        try:
            LOGGER.info("Starting MCP server '%s': %s", self.server_name, " ".join(cmd))
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self.env,
            )

            # Drain stderr in background to prevent pipe buffer deadlock
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, daemon=True, name=f"MCP-stderr-{self.server_name}"
            )
            self._stderr_thread.start()

            self._request_id = 0

            # 1. Initialize request
            init_response = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "DarkShadow", "version": "2.0.0"},
                },
                timeout=10.0,
            )
            if not init_response or "error" in init_response:
                LOGGER.warning("MCP server '%s' initialization failed: %s", self.server_name, init_response)
                self.stop()
                return False

            # 2. Initialized notification
            self._send_notification("notifications/initialized", {})

            # 3. Discover tools
            self._refresh_tools()
            self.is_connected = True
            LOGGER.info("MCP server '%s' connected with %d tools", self.server_name, len(self._tools))
            return True

        except Exception as exc:
            LOGGER.warning("Failed to launch MCP server '%s': %s", self.server_name, exc)
            self.stop()
            return False

    def _refresh_tools(self) -> None:
        """Fetch tools list from the server."""
        resp = self._send_request("tools/list", {}, timeout=8.0)
        if resp and "result" in resp and "tools" in resp["result"]:
            self._tools.clear()
            for t in resp["result"]["tools"]:
                tool_def = MCPToolDefinition(
                    server_name=self.server_name,
                    name=t.get("name", "unnamed"),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {"type": "object"}),
                )
                self._tools[tool_def.name] = tool_def

    def list_tools(self) -> list[MCPToolDefinition]:
        """Return list of discovered tools."""
        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """Call a specific tool on this MCP server."""
        if not self._process or self._process.poll() is not None:
            return {"success": False, "error": f"MCP server '{self.server_name}' is not running"}

        resp = self._send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=timeout,
        )
        if not resp:
            return {"success": False, "error": f"MCP tool '{tool_name}' timed out"}

        if "error" in resp:
            return {"success": False, "error": resp["error"].get("message", "Unknown error")}

        result = resp.get("result", {})
        content_items = result.get("content", [])
        output_texts = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                output_texts.append(item.get("text", ""))
            elif isinstance(item, str):
                output_texts.append(item)

        output_text = "\n".join(output_texts) if output_texts else str(result)
        is_error = result.get("isError", False)

        return {
            "success": not is_error,
            "output": output_text,
            "raw": result,
        }

    def _send_request(self, method: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any] | None:
        """Send a JSON-RPC 2.0 request and wait for the response."""
        with self._lock:
            if not self._process or not self._process.stdin or not self._process.stdout:
                return None

            self._request_id += 1
            req_id = self._request_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }

            try:
                msg = json.dumps(payload) + "\n"
                self._process.stdin.write(msg)
                self._process.stdin.flush()

                # Read response with timeout to prevent deadlock
                result_container: list[str] = []
                def _read_line() -> None:
                    try:
                        line = self._process.stdout.readline()
                        result_container.append(line)
                    except Exception:
                        pass

                reader = threading.Thread(target=_read_line, daemon=True)
                reader.start()
                reader.join(timeout=timeout)
                if not result_container or not result_container[0]:
                    LOGGER.warning(
                        "MCP server '%s' timed out after %.1fs for '%s'",
                        self.server_name, timeout, method,
                    )
                    return None
                return json.loads(result_container[0].strip())
            except Exception as exc:
                LOGGER.debug("MCP send_request error for '%s' (%s): %s", self.server_name, method, exc)
                return None

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC 2.0 notification (no ID, no response expected)."""
        with self._lock:
            if not self._process or not self._process.stdin:
                return
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
            try:
                msg = json.dumps(payload) + "\n"
                self._process.stdin.write(msg)
                self._process.stdin.flush()
            except Exception as exc:
                LOGGER.debug("MCP send_notification error: %s", exc)

    def _drain_stderr(self) -> None:
        """Continuously drain stderr to prevent pipe buffer deadlock."""
        try:
            while self._process and self._process.stderr:
                line = self._process.stderr.readline()
                if not line:
                    break
                LOGGER.debug("MCP '%s' stderr: %s", self.server_name, line.rstrip())
        except Exception:
            pass

    def stop(self) -> None:
        """Terminate the server process cleanly."""
        with self._lock:
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=2.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None
            self.is_connected = False


class MCPManager:
    """Central manager for loading, starting, and routing across all configured MCP servers."""

    _instance: MCPManager | None = None
    _lock = threading.Lock()

    def __init__(self, config_path: Path | str = DEFAULT_MCP_CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        self._clients: dict[str, MCPClient] = {}
        self._tool_lookup: dict[str, tuple[str, str]] = {}  # qualified_name -> (server_name, original_tool_name)

    @classmethod
    def get_instance(cls, config_path: Path | str = DEFAULT_MCP_CONFIG_PATH) -> MCPManager:
        """Singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config_path)
            return cls._instance

    def load_and_start_servers(self) -> int:
        """Read .darkshadow/mcp_servers.json, initialize clients, and register tools."""
        if not self.config_path.exists():
            LOGGER.debug("MCP config file not found at %s. Skipping MCP auto-start.", self.config_path)
            return 0

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            LOGGER.warning("Failed to parse MCP config %s: %s", self.config_path, exc)
            return 0

        servers = data.get("mcpServers", {})
        started_count = 0

        for server_name, conf in servers.items():
            command = conf.get("command")
            args = conf.get("args", [])
            env = conf.get("env")
            if not command:
                continue

            merged_env = os.environ.copy()
            if env and isinstance(env, dict):
                merged_env.update(env)

            client = MCPClient(server_name, command, args, env=merged_env)
            if client.start():
                self._clients[server_name] = client
                for tool in client.list_tools():
                    qualified_name = f"mcp_{server_name}_{tool.name}"
                    self._tool_lookup[qualified_name] = (server_name, tool.name)
                started_count += 1

        LOGGER.info("MCPManager initialized: %d servers active, %d tools registered", started_count, len(self._tool_lookup))
        return started_count

    def register_server(self, server_name: str, client: MCPClient) -> None:
        """Manually register an active MCPClient (useful for testing or dynamic plugins)."""
        self._clients[server_name] = client
        for tool in client.list_tools():
            qualified_name = f"mcp_{server_name}_{tool.name}"
            self._tool_lookup[qualified_name] = (server_name, tool.name)

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        """Return Gemini-compatible tool schemas for all active MCP tools."""
        schemas = []
        for client in self._clients.values():
            for tool in client.list_tools():
                schemas.append(tool.to_gemini_schema())
        return schemas

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to an MCP server."""
        return tool_name in self._tool_lookup

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by qualified name (e.g. 'mcp_sqlite_query')."""
        if tool_name not in self._tool_lookup:
            return {"success": False, "error": f"Unknown MCP tool '{tool_name}'"}

        server_name, orig_tool_name = self._tool_lookup[tool_name]
        client = self._clients.get(server_name)
        if not client:
            return {"success": False, "error": f"MCP server '{server_name}' is not available"}

        return client.call_tool(orig_tool_name, arguments)

    def shutdown_all(self) -> None:
        """Cleanly stop all running MCP servers."""
        for client in self._clients.values():
            client.stop()
        self._clients.clear()
        self._tool_lookup.clear()


__all__ = [
    "MCPClient",
    "MCPManager",
    "MCPToolDefinition",
    "DEFAULT_MCP_CONFIG_PATH",
]
