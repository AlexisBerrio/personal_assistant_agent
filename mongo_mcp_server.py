from __future__ import annotations

from typing import Any

from app import service as app_service
from src.assistant_personal.infrastructure.mcp.server import mcp
from src.assistant_personal.infrastructure.mcp.tools.task_tools import register_task_tools

service = app_service


def listar_tareas() -> list[dict[str, Any]]:
    """Devuelve las tareas activas del asistente personal."""
    return service.list_tasks()


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


def completar_tarea(task_id: str) -> dict[str, Any]:
    """Marca una tarea como completada."""
    return service.complete_task(task_id)


def buscar_tarea(task_id: str) -> dict[str, Any] | None:
    """Busca una tarea concreta por su task_id."""
    return service.get_task(task_id)


def register_tools() -> None:
    """Registra las herramientas MCP en el servidor activo."""
    register_task_tools(mcp, service)


def run_server() -> None:
    """Arranca el servidor MCP."""
    register_tools()
    mcp.run()


def main() -> None:
    """Punto de entrada para ejecutar el servidor MCP como script."""
    run_server()


if __name__ == "__main__":
    main()
