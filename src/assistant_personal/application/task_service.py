import uuid
from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.domain.task_models import Task
from src.assistant_personal.domain.repositories.task_repository import TaskRepository
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db
from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import MongoTaskRepository


class TaskService:
    """Servicio que gestiona las tareas del asistente personal.

    Esta clase actúa como una capa de negocio: recibe peticiones de crear,
    listar o completar tareas y se encarga de comunicarse con MongoDB.
    """

    DEFAULT_STATUS = "Pending"
    IN_PROGRESS_STATUS = "In Progress"
    COMPLETED_STATUS = "Completed"
    DELETED_STATUS = "Deleted"
    ALLOWED_STATUS_VALUES = {
        DEFAULT_STATUS,
        IN_PROGRESS_STATUS,
        COMPLETED_STATUS,
        DELETED_STATUS,
    }
    ALLOWED_PRIORITY_VALUES = {
        "Low",
        "Medium",
        "High",
    }
    ALLOWED_CATEGORY_VALUES = {
        "Personal",
        "Work",
        "Study",
        "Health",
        "Home",
    }

    def __init__(self, db_name: str = "personal_management", repository: TaskRepository | None = None) -> None:
        # Guardamos el nombre de la base de datos que usaremos.
        self.db_name = db_name
        self.repository = repository or MongoTaskRepository(db_name=db_name, get_db_fn=get_db)

    def _to_dict(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Convierte un objeto Task o un diccionario en un diccionario simple.

        La estructura oficial de la colección debe conservarse completa en el
        payload para que el servicio sea consistente con los documentos reales.
        """
        if isinstance(task, Task):
            payload: dict[str, Any] = {
                "title": task.title,
                "task_id": task.task_id,
                "description": task.description,
                "status": task.status,
                "category": task.category,
                "tags": task.tags,
                "priority": task.priority,
                "dates": task.dates,
                "recurrence": task.recurrence,
                "context_metadata": task.context_metadata,
                "steps": task.steps,
                "agent_notes": task.agent_notes,
            }
            return payload
        if isinstance(task, dict):
            return task
        raise TypeError("task debe ser un Task o un dict")

    def _serialize_value(self, value: Any) -> Any:
        """Convierte valores no JSON-serializables a tipos compatibles con FastAPI."""
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return value.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        return value

    def _validate_status(self, status: Any) -> str:
        """Valida y normaliza el estado de una tarea."""
        if status is None:
            return self.DEFAULT_STATUS
        if not isinstance(status, str) or not status.strip():
            raise ValueError("El estado de la tarea no puede estar vacío")

        normalized_status = status.strip()
        if normalized_status not in self.ALLOWED_STATUS_VALUES:
            allowed_values = ", ".join(sorted(self.ALLOWED_STATUS_VALUES))
            raise ValueError(f"Estado no válido. Valores permitidos: {allowed_values}")
        return normalized_status

    def _validate_priority(self, priority: Any) -> dict[str, Any] | None:
        """Valida y normaliza la prioridad de una tarea."""
        if priority is None:
            return None
        if not isinstance(priority, dict):
            raise ValueError("La prioridad debe ser un objeto con un campo level")

        priority_level = priority.get("level")
        if not isinstance(priority_level, str) or not priority_level.strip():
            raise ValueError("La prioridad debe incluir un nivel válido")

        normalized_priority = priority_level.strip()
        if normalized_priority not in self.ALLOWED_PRIORITY_VALUES:
            allowed_values = ", ".join(sorted(self.ALLOWED_PRIORITY_VALUES))
            raise ValueError(f"Prioridad no válida. Valores permitidos: {allowed_values}")
        return {**priority, "level": normalized_priority}

    def _validate_category(self, category: Any) -> str | None:
        """Valida y normaliza la categoría de una tarea."""
        if category is None:
            return None
        if not isinstance(category, str) or not category.strip():
            raise ValueError("La categoría de la tarea no puede estar vacía")

        normalized_category = category.strip()
        if normalized_category not in self.ALLOWED_CATEGORY_VALUES:
            allowed_values = ", ".join(sorted(self.ALLOWED_CATEGORY_VALUES))
            raise ValueError(f"Categoría no válida. Valores permitidos: {allowed_values}")
        return normalized_category

    def _validate_create_payload(self, payload: dict[str, Any]) -> None:
        """Valida los datos básicos de una tarea antes de persistirla."""
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("El título de la tarea es obligatorio")

        self._validate_status(payload.get("status"))
        self._validate_priority(payload.get("priority"))
        self._validate_category(payload.get("category"))

    def _require_task_id(self, task_id: str) -> str:
        """Valida que el task_id sea un identificador útil para el negocio."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("El task_id de la tarea es obligatorio")
        return task_id.strip()

    def _validate_update_payload(self, updates: dict[str, Any]) -> None:
        """Valida los campos que se van a actualizar."""
        if "title" in updates:
            title = updates["title"]
            if not isinstance(title, str) or not title.strip():
                raise ValueError("El título de la tarea no puede estar vacío")
            updates["title"] = title.strip()

        if "status" in updates:
            updates["status"] = self._validate_status(updates["status"])

        if "priority" in updates:
            updates["priority"] = self._validate_priority(updates["priority"])

        if "category" in updates:
            updates["category"] = self._validate_category(updates["category"])

    def list_tasks(self) -> list[dict[str, Any]]:
        """Devuelve las tareas más recientes de la colección personal_tasks."""
        raw_tasks = self.repository.list_active_tasks()
        return [self._serialize_value(task) for task in raw_tasks]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Devuelve una tarea concreta por su task_id."""
        normalized_task_id = self._require_task_id(task_id)
        task = self.repository.get_task_by_id(normalized_task_id)
        if task is None:
            return None
        return self._serialize_value(task)

    def get_task_history(self, task_id: str) -> list[dict[str, Any]]:
        """Devuelve el historial de cambios de una tarea."""
        normalized_task_id = self._require_task_id(task_id)
        history = self.repository.get_task_history(normalized_task_id)
        return [self._serialize_value(entry) for entry in history]

    def create_task(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Crea una nueva tarea en MongoDB.

        Primero convierte la entrada a un diccionario, valida que tenga título
        y luego la guarda en la colección correspondiente.
        """
        payload = self._to_dict(task)
        self._validate_create_payload(payload)

        payload["title"] = payload["title"].strip()
        payload["status"] = self._validate_status(payload.get("status"))
        payload["priority"] = self._validate_priority(payload.get("priority"))
        payload["category"] = self._validate_category(payload.get("category"))
        payload["task_id"] = payload.get("task_id") or str(uuid.uuid4())
        payload.setdefault("is_deleted", False)
        payload.setdefault("deleted_at", None)

        return self.repository.create_task(payload)

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Actualiza campos de una tarea existente identificada por task_id."""
        if not isinstance(updates, dict):
            raise ValueError("El cuerpo de la actualización debe ser un objeto")
        if not updates:
            raise ValueError("No se proporcionaron campos para actualizar")

        normalized_task_id = self._require_task_id(task_id)
        self._validate_update_payload(updates)

        task = Task(title="", status=self.DEFAULT_STATUS)
        task.apply_updates(updates)
        updates = {key: value for key, value in task.__dict__.items() if key in updates or key == "status"}
        updated_task = self.repository.update_task(normalized_task_id, updates)
        return self._serialize_value(updated_task) if updated_task is not None else None

    def complete_task(self, task_id: str) -> dict[str, Any]:
        """Marca una tarea como completada en base a su task_id."""
        normalized_task_id = self._require_task_id(task_id)
        return self.repository.complete_task(normalized_task_id)

    def delete_task(self, task_id: str) -> dict[str, Any] | None:
        """Marca una tarea como eliminada sin borrarla de la base de datos."""
        normalized_task_id = self._require_task_id(task_id)
        return self.repository.delete_task(normalized_task_id)
