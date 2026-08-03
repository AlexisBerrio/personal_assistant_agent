from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from src.assistant_personal.application.task_service import TaskService


def register_task_tools(mcp: FastMCP, service: TaskService) -> None:
    """Registra todas las herramientas relacionadas con tareas en el servidor MCP."""

    @mcp.tool()
    def health_check() -> dict[str, Any]:
        """Verifica el estado del servidor MCP y sus dependencias (base de datos, conexiones)."""
        mongo_status = service.repository.check_connection()
        return {
            "status": "ok" if mongo_status else "degraded",
            "service": "assistant-mcp-server",
            "database": "connected" if mongo_status else "disconnected",
        }

    @mcp.tool()
    def listar_tareas() -> list[dict[str, Any]]:
        """Devuelve las tareas activas del asistente personal."""
        return service.list_tasks()

    @mcp.tool()
    def crear_tarea(
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
        return service.create_task({
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
        })

    @mcp.tool()
    def actualizar_tarea(
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

        return service.update_task(task_id, updates)

    @mcp.tool()
    def completar_tarea(task_id: str) -> dict[str, Any]:
        """Marca una tarea como completada."""
        return service.complete_task(task_id)

    @mcp.tool()
    def buscar_tarea(task_id: str) -> dict[str, Any] | None:
        """Busca una tarea concreta por su task_id."""
        return service.get_task(task_id)
