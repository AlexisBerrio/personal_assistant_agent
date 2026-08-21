from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.task_models import Task
from src.assistant_personal.infrastructure.observabilidad import get_logger

logger = get_logger(__name__)


class HealthCheckResponse(BaseModel):
    status: str
    service: str
    database: str


class ListarTareasResponse(BaseModel):
    tasks: list[Task]


class TareaResponse(BaseModel):
    task: Task | None


class CompletarTareaResponse(BaseModel):
    matched: int
    modified: int


class DeletedTaskInfo(BaseModel):
    """`delete_task_async` no devuelve una `Task` completa, solo un recibo de la eliminación."""

    task_id: str
    deleted: bool
    deleted_at: str | None = None


class EliminarTareaResponse(BaseModel):
    task: DeletedTaskInfo | None


# Scopes que cada tool exigirá cuando exista autenticación real, sin enforcement todavía — deja
# el terreno preparado para no tener que decidir esto bajo presión más adelante.
TOOL_SCOPES: dict[str, str] = {
    "health_check": "read",
    "listar_tareas": "read",
    "buscar_tarea": "read",
    "crear_tarea": "write",
    "actualizar_tarea": "write",
    "completar_tarea": "write",
    "eliminar_tarea": "write",
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
    due_date: str | None = None,
    recurrence: dict[str, Any] | None = None,
    agent_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "status": status,
        "category": category,
        "tags": tags or [],
        "priority": priority,
        "due_date": due_date,
        "recurrence": recurrence or {},
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
    due_date: str | None = None,
    recurrence: dict[str, Any] | None = None,
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
    if due_date is not None:
        updates["due_date"] = due_date
    if priority is not None:
        updates["priority"] = priority
    if recurrence is not None:
        updates["recurrence"] = recurrence
    if agent_notes is not None:
        updates["agent_notes"] = agent_notes
    return updates


def register_task_tools(mcp: FastMCP, service: TaskService) -> None:
    """Registra todas las herramientas relacionadas con tareas en el servidor MCP."""

    @mcp.tool()
    async def health_check() -> HealthCheckResponse:
        """Verifica el estado del servidor MCP y su conexión a Mongo.

        Devuelve: {"status": "ok"|"degraded", "service": str, "database": "connected"|"disconnected"}.
        Nunca falla — un problema de conexión se refleja en el contenido, no en un error de la tool.
        """

        async def _call() -> HealthCheckResponse:
            repository = service.repository
            result = repository.check_connection()
            if hasattr(result, "__await__"):
                result = await result
            mongo_status = bool(result)

            return HealthCheckResponse(
                status="ok" if mongo_status else "degraded",
                service="assistant-mcp-server",
                database="connected" if mongo_status else "disconnected",
            )

        return await _audited("health_check", set(), _call())

    @mcp.tool()
    async def listar_tareas(estado: str | None = None, limite: int = 20) -> ListarTareasResponse:
        """Devuelve las tareas activas (status distinto de "Deleted") del usuario.

        `estado` filtra por status exacto ("Pending", "In Progress", "Completed") — omitido trae
        todas las activas. `limite` acota cuántas trae, con techo de 100 en el servidor aunque se
        pida más; el valor por defecto es 20. Todavía no filtra por fecha (fuera de alcance).
        Devuelve: {"tasks": [...]}.
        """
        provided = _provided_keys(estado=estado)
        tasks = await _audited("listar_tareas", provided, service.list_tasks_async(estado, limite))
        return ListarTareasResponse(tasks=[Task.model_validate(task) for task in tasks])

    @mcp.tool()
    async def crear_tarea(
        title: str,
        description: str | None = None,
        status: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        priority: dict[str, Any] | None = None,
        due_date: str | None = None,
        recurrence: dict[str, Any] | None = None,
        agent_notes: list[dict[str, Any]] | None = None,
    ) -> Task:
        """Crea una nueva tarea. Solo `title` es obligatorio.

        `status` acepta: "Pending" (default si se omite), "In Progress", "Completed", "Deleted" —
        cualquier otro valor no está soportado por el resto del sistema. `priority`/`recurrence`
        son objetos libres sin un esquema fijo todavía; úsalos solo si el usuario dio esa
        información explícitamente, no inventes su contenido.

        `due_date` (fecha de vencimiento) exige formato ISO 8601 ("2026-08-28" o
        "2026-08-28T00:00:00") — un valor en otro formato se rechaza con error. Esta tool NO
        interpreta lenguaje natural ("el viernes", "en dos semanas"): traducir lo que dijo el
        usuario a una fecha ISO concreta es responsabilidad de quien llama a esta tool, no de la
        tool misma. `created_at` lo fija el sistema automáticamente, no es un parámetro aquí.

        Devuelve la tarea creada completa, incluyendo el `task_id` generado.
        """
        provided = _provided_keys(
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            due_date=due_date,
            recurrence=recurrence,
            agent_notes=agent_notes,
        )
        call = service.create_task_async(_build_task_payload(
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            due_date=due_date,
            recurrence=recurrence,
            agent_notes=agent_notes,
        ))
        created = await _audited("crear_tarea", provided, call)
        return Task.model_validate(created)

    @mcp.tool()
    async def actualizar_tarea(
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        priority: dict[str, Any] | None = None,
        due_date: str | None = None,
        recurrence: dict[str, Any] | None = None,
        agent_notes: list[dict[str, Any]] | None = None,
    ) -> TareaResponse:
        """Actualiza una tarea existente por `task_id`. Actualización parcial: solo se tocan los
        campos que se pasen con valor, el resto de la tarea queda igual — no hace falta reenviar
        el objeto completo. Valores válidos de `status`: "Pending", "In Progress", "Completed",
        "Deleted".

        `due_date` exige formato ISO 8601 ("2026-08-28" o "2026-08-28T00:00:00"), se rechaza
        cualquier otro formato. Traducir lenguaje natural ("el viernes") a esa fecha es
        responsabilidad de quien llama a esta tool, no de la tool misma. `completed_at` no se
        actualiza aquí — lo fija `completar_tarea` automáticamente.

        Devuelve: {"task": {...} | None}. Si `task_id` no existe, `task` es `None` — no lanza error.
        """
        provided = _provided_keys(
            task_id=task_id,
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            due_date=due_date,
            recurrence=recurrence,
            agent_notes=agent_notes,
        )
        updates = _build_update_payload(
            title=title,
            description=description,
            status=status,
            category=category,
            tags=tags,
            priority=priority,
            due_date=due_date,
            recurrence=recurrence,
            agent_notes=agent_notes,
        )

        task = await _audited("actualizar_tarea", provided, service.update_task_async(task_id, updates))
        return TareaResponse(task=Task.model_validate(task) if task is not None else None)

    @mcp.tool()
    async def completar_tarea(task_id: str) -> CompletarTareaResponse:
        """Marca una tarea como completada (status "Completed") por su `task_id`.

        Devuelve: {"matched": int, "modified": int}. Si `task_id` no existe, devuelve
        {"matched": 0, "modified": 0} sin lanzar error. Idempotente: repetir la llamada sobre una
        tarea ya completada devuelve {"matched": 1, "modified": 0}.
        """
        result = await _audited("completar_tarea", {"task_id"}, service.complete_task_async(task_id))
        return CompletarTareaResponse.model_validate(result)

    @mcp.tool()
    async def buscar_tarea(task_id: str) -> TareaResponse:
        """Busca una tarea concreta por su `task_id` exacto (no acepta título ni descripción).

        Devuelve: {"task": {...} | None}. Si no existe, `task` es `None` — no lanza error.
        """
        task = await _audited("buscar_tarea", {"task_id"}, service.get_task_async(task_id))
        return TareaResponse(task=Task.model_validate(task) if task is not None else None)

    @mcp.tool()
    async def eliminar_tarea(task_id: str) -> EliminarTareaResponse:
        """Elimina una tarea por su `task_id` exacto — soft delete: queda marcada como "Deleted",
        no desaparece de Mongo, y ya no aparece en `listar_tareas`.

        Devuelve: {"task": {"task_id", "deleted", "deleted_at"} | None} — no la tarea completa,
        solo un recibo de la eliminación. Si `task_id` no existe, `task` es `None`, sin error.
        """
        task = await _audited("eliminar_tarea", {"task_id"}, service.delete_task_async(task_id))
        return EliminarTareaResponse(task=DeletedTaskInfo.model_validate(task) if task is not None else None)
