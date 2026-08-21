from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

mcp = FastMCP("personal_assistant")
_tools_registered = False


async def health_handler(_: Any) -> JSONResponse:
    """Endpoint HTTP simple para comprobar que el servidor MCP responde."""
    return JSONResponse({"status": "ok", "service": "assistant-mcp-server"})


def register_tools() -> None:
    """Registra las herramientas MCP en el servidor con su propia instancia de `TaskService`.

    Antes importaba `service` desde `app.py` (el entrypoint de FastAPI), que nunca lo expone a
    nivel de módulo — además de ser un bug, era una violación de capas: infraestructura no debe
    depender del script de arranque de otra interfaz. El servidor MCP construye su propio
    `TaskService` con los adaptadores por defecto, igual que hace `app.py` en su `lifespan`.
    """
    global _tools_registered
    if _tools_registered:
        return

    from src.assistant_personal.application.tasks.task_service import TaskService
    from src.assistant_personal.infrastructure.mcp.tools.task_tools import register_task_tools

    register_task_tools(mcp, TaskService())
    _tools_registered = True


def create_mcp_app() -> Any:
    """Crea una app ASGI para exponer el servidor MCP sobre HTTP."""
    register_tools()
    app = mcp.streamable_http_app()
    app.add_route("/health", health_handler, methods=["GET"])
    return app


mcp_http_app = create_mcp_app()


def run_server() -> None:
    """Arranca el servidor MCP en modo stdio."""
    register_tools()
    mcp.run()


def run_http_server(host: str = "127.0.0.1", port: int = 8001) -> None:
    """Arranca el servidor MCP sobre HTTP para pruebas desde Thunder Client."""
    import uvicorn

    uvicorn.run(mcp_http_app, host=host, port=port)


if __name__ == "__main__":
    run_server()
