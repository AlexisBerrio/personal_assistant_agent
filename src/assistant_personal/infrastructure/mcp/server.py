from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised when the optional dependency is absent
    class FastMCP:  # type: ignore[override]
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            def decorator(func):
                return func
            return decorator

        def run(self) -> None:
            return None

from app import service

mcp = FastMCP("personal_assistant")
