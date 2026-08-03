from __future__ import annotations

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

mcp = FastMCP("personal_assistant")


def register_tools() -> None:
    """Registra las herramientas MCP en el servidor."""
    import src.assistant_personal.infrastructure.mcp.tools.task_tools as task_tools  # noqa: F401
    _ = task_tools


def run_server() -> None:
    """Arranca el servidor MCP."""
    register_tools()
    mcp.run()
