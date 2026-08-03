from __future__ import annotations

from src.assistant_personal.infrastructure.mcp.server import mcp, register_tools, run_server


def main() -> None:
    """Punto de entrada para ejecutar el servidor MCP como script."""
    run_server()


if __name__ == "__main__":
    main()
