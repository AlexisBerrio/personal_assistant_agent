import inspect
import uuid
from datetime import datetime, timezone
from typing import Any, cast

from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.repositories.task_repository import TaskRepository
from src.assistant_personal.domain.task_models import Task
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db
from src.assistant_personal.infrastructure.task_repository import build_default_task_repository


class TaskService:
    """Servicio que gestiona las tareas del asistente personal.

    Esta clase actúa como una capa de negocio: recibe peticiones de crear,
    listar o completar tareas y se encarga de comunicarse con MongoDB.
    """

    DEFAULT_STATUS = "Pending"
    IN_PROGRESS_STATUS = "In Progress"
    COMPLETED_STATUS = "Completed"
    DELETED_STATUS = "Deleted"

    def __init__(self, db_name: str | None = None, repository: TaskRepository | None = None) -> None:
        # Guardamos el nombre de la base de datos que usaremos (única fuente de verdad: Settings).
        self.db_name = db_name or get_settings().mongo_db_name
        self.repository = repository or build_default_task_repository(db_name=self.db_name, get_db_fn=get_db)

    def _to_dict(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Convierte un objeto Task o un diccionario en un diccionario simple."""
        if isinstance(task, Task):
            return task.to_payload()
        if isinstance(task, dict):
            return Task.model_validate(task).to_payload()
        raise TypeError("task debe ser un Task o un dict")

    def _serialize_value(self, value: Any) -> Any:
        """Convierte valores no JSON-serializables a tipos compatibles con FastAPI."""
        return Task._serialize_value(value)

    def _require_task_id(self, task_id: str) -> str:
        """Valida que el task_id sea un identificador útil para el negocio."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("El task_id de la tarea es obligatorio")
        return task_id.strip()

    def _prepare_create_payload(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Normaliza el payload de creación para que el flujo async sea el único punto de transformación."""
        payload = self._to_dict(task)
        payload["task_id"] = payload.get("task_id") or str(uuid.uuid4())
        payload.setdefault("is_deleted", False)
        payload.setdefault("deleted_at", None)
        # Sin importar lo que traiga el payload: la fecha de creación no es algo
        # que el llamador deba poder fijar.
        payload["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    def _prepare_update_payload(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Normaliza el payload de actualización antes de delegar al repositorio."""
        if not isinstance(updates, dict):
            raise ValueError("El cuerpo de la actualización debe ser un objeto")
        if not updates:
            raise ValueError("No se proporcionaron campos para actualizar")

        task = Task.model_construct(title="", status=self.DEFAULT_STATUS)
        changed_values = task.apply_updates(updates)
        return changed_values

    async def _invoke_repository_async(self, method_name: str, *args: Any) -> Any:
        """Invoca un método del repositorio, soportando tanto versiones async como sync."""
        for candidate_name in (f"{method_name}_async", method_name):
            method = getattr(self.repository, candidate_name, None)
            if callable(method):
                result = method(*args)
                if inspect.isawaitable(result):
                    return await result
                return result

        raise AttributeError(f"El repositorio no implementa '{method_name}'")

    async def list_tasks_async(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Devuelve las tareas activas, opcionalmente filtradas por status."""
        raw_tasks = await self._invoke_repository_async("list_active_tasks", status, limit)
        return [self._serialize_value(task) for task in raw_tasks]

    async def get_task_async(self, task_id: str) -> dict[str, Any] | None:
        """Devuelve una tarea concreta por su task_id."""
        normalized_task_id = self._require_task_id(task_id)
        task = await self._invoke_repository_async("get_task_by_id", normalized_task_id)
        if task is None:
            return None
        return cast(dict[str, Any], self._serialize_value(task))

    async def get_task_history_async(self, task_id: str) -> list[dict[str, Any]]:
        """Devuelve el historial de cambios de una tarea."""
        normalized_task_id = self._require_task_id(task_id)
        history = await self._invoke_repository_async("get_task_history", normalized_task_id)
        return [self._serialize_value(entry) for entry in history]

    async def create_task_async(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Crea una nueva tarea en MongoDB."""
        payload = self._prepare_create_payload(task)
        return cast(dict[str, Any], await self._invoke_repository_async("create_task", payload))

    async def update_task_async(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Actualiza campos de una tarea existente identificada por task_id."""
        if not isinstance(updates, dict):
            raise ValueError("El cuerpo de la actualización debe ser un objeto")
        if not updates:
            raise ValueError("No se proporcionaron campos para actualizar")

        normalized_task_id = self._require_task_id(task_id)
        normalized_updates = self._prepare_update_payload(updates)
        updated_task = await self._invoke_repository_async("update_task", normalized_task_id, normalized_updates)
        return self._serialize_value(updated_task) if updated_task is not None else None

    async def complete_task_async(self, task_id: str) -> dict[str, Any]:
        """Marca una tarea como completada en base a su task_id."""
        normalized_task_id = self._require_task_id(task_id)
        return cast(dict[str, Any], await self._invoke_repository_async("complete_task", normalized_task_id))

    async def delete_task_async(self, task_id: str) -> dict[str, Any] | None:
        """Marca una tarea como eliminada sin borrarla de la base de datos."""
        normalized_task_id = self._require_task_id(task_id)
        return cast(
            "dict[str, Any] | None",
            await self._invoke_repository_async("delete_task", normalized_task_id),
        )
