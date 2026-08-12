from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.task_models import Task

# Creamos la aplicación FastAPI. Es el punto de entrada para recibir peticiones.
app = FastAPI(title="Asistente Personal", version="0.1.0")
service = TaskService()


class TaskCreateRequest(BaseModel):
    """Modelo que define qué datos recibe la API para crear una tarea."""
    title: str = Field(min_length=1, description="Título principal de la tarea.", json_schema_extra={"example": "Revisar propuesta"})
    description: str | None = Field(default=None, description="Descripción opcional de la tarea.", json_schema_extra={"example": "Confirmar los últimos cambios antes de enviar"})
    status: str = Field(default="Pending", min_length=1, description="Estado de la tarea. Valores permitidos: Pending, In Progress, Completed, Deleted.", json_schema_extra={"example": "Pending"})
    category: str | None = Field(default=None, description="Categoría de la tarea. Valores permitidos: Personal, Work, Study, Health, Home.", json_schema_extra={"example": "Work"})
    tags: list[str] = Field(default_factory=list, description="Etiquetas de clasificación.", json_schema_extra={"example": ["oficina", "urgente"]})
    priority: dict[str, Any] | None = Field(default=None, description="Prioridad de la tarea. Debe incluir un campo level con uno de: Low, Medium, High.", json_schema_extra={"example": {"level": "High", "score": 90}})
    dates: dict[str, Any] | None = Field(default=None, description="Fechas asociadas a la tarea.", json_schema_extra={"example": {"created_at": "2026-08-02T10:00:00", "due_date": "2026-08-05T12:00:00"}})
    recurrence: dict[str, Any] | None = Field(default=None, description="Reglas de recurrencia si aplica.", json_schema_extra={"example": {"is_recurring": False, "frequency": None}})
    context_metadata: dict[str, Any] | None = Field(default=None, description="Metadatos de contexto adicionales.", json_schema_extra={"example": {"source": "manual", "location": "home"}})
    steps: list[dict[str, Any]] = Field(default_factory=list, description="Pasos de ejecución de la tarea.", json_schema_extra={"example": [{"step_id": 1, "text": "Revisar contenido", "is_completed": False}]})
    agent_notes: list[dict[str, Any]] = Field(default_factory=list, description="Notas del agente asociadas a la tarea.", json_schema_extra={"example": [{"timestamp": "2026-08-02T10:05:00", "note": "Tarea creada desde la API"}]})


class TaskUpdateRequest(BaseModel):
    """Modelo que define qué datos admite la API para actualizar una tarea."""
    title: str | None = Field(default=None, description="Nuevo título para la tarea.", json_schema_extra={"example": "Revisar propuesta actualizada"})
    description: str | None = Field(default=None, description="Nueva descripción de la tarea.", json_schema_extra={"example": "Confirmar los últimos cambios antes de enviar"})
    status: str | None = Field(default=None, description="Estado de la tarea. Valores permitidos: Pending, In Progress, Completed, Deleted.", json_schema_extra={"example": "In Progress"})
    category: str | None = Field(default=None, description="Categoría de la tarea. Valores permitidos: Personal, Work, Study, Health, Home.", json_schema_extra={"example": "Work"})
    tags: list[str] | None = Field(default=None, description="Etiquetas de clasificación actualizadas.", json_schema_extra={"example": ["oficina", "urgente"]})
    priority: dict[str, Any] | None = Field(default=None, description="Prioridad de la tarea. Debe incluir un campo level con uno de: Low, Medium, High.", json_schema_extra={"example": {"level": "High", "score": 90}})
    dates: dict[str, Any] | None = Field(default=None, description="Fechas actualizadas de la tarea, como la fecha límite.", json_schema_extra={"example": {"due_date": "2026-08-05T12:00:00"}})
    recurrence: dict[str, Any] | None = Field(default=None, description="Reglas de recurrencia actualizadas.", json_schema_extra={"example": {"is_recurring": False, "frequency": None}})
    context_metadata: dict[str, Any] | None = Field(default=None, description="Metadatos de contexto actualizados.", json_schema_extra={"example": {"source": "manual", "location": "home"}})
    steps: list[dict[str, Any]] | None = Field(default=None, description="Pasos de ejecución actualizados de la tarea.", json_schema_extra={"example": [{"step_id": 1, "text": "Revisar contenido", "is_completed": False}]})


async def _invoke_service_method(method_name: str, *args: Any, **kwargs: Any) -> Any:
    async_method = getattr(service, f"{method_name}_async", None)
    if callable(async_method):
        return await async_method(*args, **kwargs)

    sync_method = getattr(service, method_name, None)
    if callable(sync_method):
        return sync_method(*args, **kwargs)

    raise AttributeError(f"El servicio no implementa '{method_name}'")


@app.get("/health")
def health_check() -> dict[str, str]:
    """Endpoint simple para comprobar que la API responde."""
    return {"status": "ok"}


@app.post("/tasks", status_code=201)
async def create_task(payload: TaskCreateRequest) -> dict[str, str]:
    """Recibe una tarea desde el cliente y la guarda usando el servicio."""
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="El título de la tarea es obligatorio")

    if not payload.status.strip():
        raise HTTPException(status_code=400, detail="El estado de la tarea no puede estar vacío")

    task = Task(
        title=payload.title.strip(),
        description=payload.description,
        status=payload.status.strip(),
        category=payload.category,
        tags=payload.tags,
        priority=payload.priority,
        dates=payload.dates or {},
        recurrence=payload.recurrence or {},
        context_metadata=payload.context_metadata or {},
        steps=payload.steps,
        agent_notes=payload.agent_notes,
    )
    try:
        return await _invoke_service_method("create_task", task)
    except ValueError as exc:
        # Si falta información, devolvemos un error claro al cliente.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/tasks")
async def list_tasks() -> list[dict[str, object]]:
    """Devuelve una lista de tareas almacenadas en MongoDB."""
    return await _invoke_service_method("list_tasks")


@app.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, object] | None:
    """Devuelve una tarea concreta a partir de su task_id."""
    task = await _invoke_service_method("get_task", task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


@app.get("/tasks/{task_id}/history")
async def get_task_history(task_id: str) -> list[dict[str, object]]:
    """Devuelve el historial de cambios de una tarea."""
    history = await _invoke_service_method("get_task_history", task_id)
    if not history:
        raise HTTPException(status_code=404, detail="No se encontró historial para la tarea")
    return history


@app.patch("/tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdateRequest) -> dict[str, object]:
    """Actualiza una tarea existente identificada por task_id.

    Si el payload incluye un estado "Completed", la tarea se marca como
    completada usando la misma ruta de actualización.
    """
    payload_data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    if not payload_data:
        raise HTTPException(status_code=400, detail="Se debe proporcionar al menos un campo para actualizar")

    if str(payload_data.get("status", "")).strip().lower() == "completed":
        return await _invoke_service_method("complete_task", task_id)

    try:
        updated_task = await _invoke_service_method("update_task", task_id, payload_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if updated_task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return updated_task


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, object]:
    """Marca una tarea como eliminada sin borrarla de la base de datos."""
    deleted_task = await _invoke_service_method("delete_task", task_id)
    if deleted_task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return deleted_task
