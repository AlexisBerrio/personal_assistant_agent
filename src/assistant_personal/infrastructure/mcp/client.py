from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_SCRIPT = _REPO_ROOT / "mongo_mcp_server.py"


class McpTaskServiceClient:
    """Cliente MCP real (stdio) con la misma interfaz async que `TaskService`
    (`list_tasks_async`/`create_task_async`/`complete_task_async`), para que
    `TaskOrchestrator` lo use como `service` sin cambios en `_dispatch`.

    Sustituye el import directo de `TaskService` en el camino del orquestador: la única forma
    de tocar Mongo pasa por las tools declaradas en `mongo_mcp_server.py` (`crear_tarea`,
    `listar_tareas`, `completar_tarea`), no por saltarse el protocolo.
    """

    def __init__(
        self,
        python_command: str | None = None,
        session: ClientSession | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._python_command = python_command or sys.executable
        # El SDK de MCP NO hereda el entorno del proceso padre por defecto (solo una allowlist
        # de seguridad — PATH, APPDATA, etc. — que excluye MONGO_URI/OPENAI_API_KEY). Sin pasar
        # el entorno completo explícitamente, el subproceso no encontraría `.env`.
        self._env = env if env is not None else dict(os.environ)
        self._exit_stack: AsyncExitStack | None = None
        self._session = session
        self._owns_session = session is None

    async def _ensure_session(self) -> ClientSession:
        if self._session is not None:
            return self._session

        params = StdioServerParameters(command=self._python_command, args=[str(_SERVER_SCRIPT)], env=self._env)
        self._exit_stack = AsyncExitStack()
        read_stream, write_stream = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        self._session = session
        return session

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        session = await self._ensure_session()
        result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(_extract_text(result) or f"La tool MCP '{name}' devolvió un error.")
        return result.structuredContent if result.structuredContent is not None else _extract_text(result)

    async def list_tools(self) -> list[Any]:
        """Catálogo de tools del servidor (nombre, descripción, JSON schema de parámetros)."""
        session = await self._ensure_session()
        result = await session.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invocación genérica de cualquier tool por nombre."""
        return await self._call_tool(name, arguments)

    async def list_tasks_async(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        arguments: dict[str, Any] = {"limite": limit}
        if status is not None:
            arguments["estado"] = status
        result = await self._call_tool("listar_tareas", arguments)
        return (result or {}).get("tasks", [])

    async def create_task_async(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call_tool("crear_tarea", payload)

    async def complete_task_async(self, task_id: str) -> dict[str, Any]:
        return await self._call_tool("completar_tarea", {"task_id": task_id})

    async def delete_task_async(self, task_id: str) -> dict[str, Any] | None:
        result = await self._call_tool("eliminar_tarea", {"task_id": task_id})
        return (result or {}).get("task")

    async def aclose(self) -> None:
        if self._owns_session and self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None


def _extract_text(result: CallToolResult) -> str | None:
    for block in result.content:
        if isinstance(block, TextContent):
            return block.text
    return None
