from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.infrastructure.observabilidad import get_logger

logger = get_logger(__name__)

# Scopes que cada tool exigirá cuando exista autenticación real (§A.11, Fase 6-7). Hoy es solo
# metadata sin enforcement — deja el terreno preparado para no tener que decidir esto bajo presión.
TOOL_SCOPES: dict[str, str] = {
    "health_check": "read",
    "listar_tareas": "read",
    "buscar_tarea": "read",
    "crear_tarea": "write",
    "actualizar_tarea": "write",
    "completar_tarea": "write",
}


def _provided_keys(**kwargs: Any) -> set[str]:
    """Nombres de los argumentos que el llamador pasó con valor (no `None`) — para auditoría."""
    return {key for key, value in kwargs.items() if value is not None}


async def _audited(tool_name: str, provided_params: set[str], call: Awaitable[Any]) -> Any:
    """Registra invocación y resultado de una tool MCP para auditoría (ítem 3.3).

    `provided_params` son solo las claves de los argumentos recibidos, nunca sus valores: pueden
    ser texto libre del usuario y no deben quedar en el log.
    """
    logger.info("mcp_tool_invocada", tool=tool_name, scope=TOOL_SCOPES[tool_name], parametros=sorted(provided_params))
    try:
        result = await call
    except Exception as exc:
        logger.warning("mcp_tool_resultado", tool=tool_name, exito=False, error=str(exc))
        raise
    logger.info("mcp_tool_resultado", tool=tool_name, exito=True)
    return result


def _build_task_payload(
    *,
    title: str,
    description: str | None = None,
    status: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    priority: dict[str, Any] | None = None,
    dates: dict[str, Any] | None = None,
    recurrence: dict[str, Any] | None = None,
    context_metadata: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
    agent_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "status": status,
        "category": category,
        "tags": tags or [],
        "priority": priority,
        "dates": dates or {},
        "recurrence": recurrence or {},
        "context_metadata": context_metadata or {},
        "steps": steps or [],
        "agent_notes": agent_notes or [],
    }


def _build_update_payload(
    *,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    priority: dict[str, Any] | None = None,
    dates: dict[str, Any] | None = None,
    recurrence: dict[str, Any] | None = None,
    context_metadata: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
    agent_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if title is not None:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if status is not None:
        updates["status"] = status
    if category is not None:
        updates["category"] = category
    if tags is not None:
        updates["tags"] = tags
    if priority is not None:
        updates["priority"] = priority
    if dates is not None:
        updates["dates"] = dates
    if recurrence is not None:
        updates["recurrence"] = recurrence
    if context_metadata is not None:
        updates["context_metadata"] = context_metadata
    if steps is not None:
        updates["steps"] = steps
    if agent_notes is not None:
        updates["agent_notes"] = agent_notes
    return updates


def register_task_tools(mcp: FastMCP, service: TaskService) -> None:
    """Registra todas las herramientas relacionadas con tareas en el servidor MCP."""

    @mcp.tool()
    async def health_check() -> dict[str, Any]:
        """Verifica el estado del servidor MCP y sus dependencias (base de datos, conexiones)."""

        async def _call() -> dict[str, Any]:
            repository = service.repository
            result = repository.check_connection()
            if hasattr(result, "__await__"):
                result = await result
            mongo_status = bool(result)

            return {
                "status": "ok" if mongo_status else "degraded",
                "service": "assistant-mcp-server",
                "database": "connected" if mongo_status else "disconnected",
            }

        return await _audited("health_check", set(), _call())

    @mcp.tool()
    async def listar_tareas() -> list[dict[str, Any]]:
        """Devuelve las tareas activas del asistente personal."""
        return await _audited("listar_tareas", set(), service.list_tasks_async())

    @mcp.tool()
    async def crear_tarea(
        title: str,
        description: str | None = None,
        status: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        priority: dict[str, Any] | None = None,
        dates: dict[str, Any] | None = None,
        recurrence: dict[str, Any] | None = None,
        context_metadata: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
        agent_notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Crea una nueva tarea con los campos principales del modelo de negocio."""
        provided = _provided_keys(
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            dates=dates,
            recurrence=recurrence,
            context_metadata=context_metadata,
            steps=steps,
            agent_notes=agent_notes,
        )
        call = service.create_task_async(_build_task_payload(
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            dates=dates,
            recurrence=recurrence,
            context_metadata=context_metadata,
            steps=steps,
            agent_notes=agent_notes,
        ))
        return await _audited("crear_tarea", provided, call)

    @mcp.tool()
    async def actualizar_tarea(
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        priority: dict[str, Any] | None = None,
        dates: dict[str, Any] | None = None,
        recurrence: dict[str, Any] | None = None,
        context_metadata: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
        agent_notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Actualiza una tarea existente por task_id usando los campos principales del modelo de negocio."""
        provided = _provided_keys(
            task_id=task_id,
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            dates=dates,
            recurrence=recurrence,
            context_metadata=context_metadata,
            steps=steps,
            agent_notes=agent_notes,
        )
        updates = _build_update_payload(
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            dates=dates,
            recurrence=recurrence,
            context_metadata=context_metadata,
            steps=steps,
            agent_notes=agent_notes,
        )

        return await _audited("actualizar_tarea", provided, service.update_task_async(task_id, updates))

    @mcp.tool()
    async def completar_tarea(task_id: str) -> dict[str, Any]:
        """Marca una tarea como completada."""
        return await _audited("completar_tarea", {"task_id"}, service.complete_task_async(task_id))

    @mcp.tool()
    async def buscar_tarea(task_id: str) -> dict[str, Any] | None:
        """Busca una tarea concreta por su task_id."""
        return await _audited("buscar_tarea", {"task_id"}, service.get_task_async(task_id))
