"""An MCP server so LLMs such as Claude can read and edit Keynote decks.

Run it with ``pykeynote mcp``. It speaks the Model Context Protocol over
stdio (one JSON-RPC message per line) and offers the tools in
:mod:`pykeynote.tools`. It needs nothing beyond pykeynote itself.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional, TextIO

from . import __version__, tools

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Tools for Apple Keynote .key files. They read and write the files "
    "directly, so Keynote doesn't need to be running. Start with deck_info to "
    "see a deck's slides and layouts, read_slide for one slide's text, and "
    "export_markdown for the whole deck. Every editing tool saves the deck "
    "when it is done; pass output to save a copy instead. Slide indexes start "
    "at 0. Use absolute paths, since the server's working directory is unknown."
)

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


def _tool_listing(tool: Dict[str, Any]) -> Dict[str, Any]:
    listing = {"name": tool["name"], "description": tool["description"], "inputSchema": tool["inputSchema"]}
    annotations = {"readOnlyHint": bool(tool.get("readOnly"))}
    if not tool.get("readOnly"):
        annotations["destructiveHint"] = bool(tool.get("destructive"))
    listing["annotations"] = annotations
    return listing


class Server:
    """Handles one MCP session. :meth:`handle` takes a message and returns the reply, if any."""

    def __init__(self) -> None:
        self.protocol_version = PROTOCOL_VERSIONS[0]

    def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "invalid request")
        method = message["method"]
        params = message.get("params") or {}
        if "id" not in message:
            return None  # a notification, such as notifications/initialized
        request_id = message["id"]
        handler = getattr(self, "_" + method.replace("/", "_"), None)
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"method not found: {method}")
        try:
            result = handler(params)
        except _InvalidParams as e:
            return _error(request_id, INVALID_PARAMS, str(e))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion")
        self.protocol_version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "pykeynote", "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    def _ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def _tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"tools": [_tool_listing(t) for t in tools.TOOLS]}

    def _tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        if name not in tools.TOOLS_BY_NAME:
            raise _InvalidParams(f"unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise _InvalidParams("arguments must be an object")
        allowed = tools.TOOLS_BY_NAME[name]["inputSchema"]["properties"]
        unknown = sorted(set(arguments) - set(allowed))
        if unknown:
            return _tool_error(f"unknown argument(s) for {name}: {', '.join(unknown)}")
        try:
            result = tools.call(name, arguments)
        except Exception as e:  # report it to the model rather than end the session
            return _tool_error(f"{type(e).__name__}: {e}")
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
                "structuredContent": result, "isError": False}


class _InvalidParams(Exception):
    pass


def _tool_error(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    """Answer MCP messages on ``stdin`` until it closes."""
    server = Server()
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply: Optional[Dict[str, Any]] = _error(None, PARSE_ERROR, "parse error")
        else:
            reply = server.handle(message)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
