import uuid
from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.domain.task_models import Task
from src.assistant_personal.infrastructure.mongo_client import get_db


class TaskService:
    """Servicio que gestiona las tareas del asistente personal.

    Esta clase actúa como una capa de negocio: recibe peticiones de crear,
    listar o completar tareas y se encarga de comunicarse con MongoDB.
    """

    def __init__(self, db_name: str = "personal_management") -> None:
        # Guardamos el nombre de la base de datos que usaremos.
        self.db_name = db_name

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

    def list_tasks(self) -> list[dict[str, Any]]:
        """Devuelve las tareas más recientes de la colección personal_tasks."""
        db = get_db(self.db_name)
        raw_tasks = list(db.personal_tasks.find({}, {"_id": 0}).limit(10))
        return [self._serialize_value(task) for task in raw_tasks]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Devuelve una tarea concreta por su task_id."""
        db = get_db(self.db_name)
        task = db.personal_tasks.find_one({"task_id": task_id}, {"_id": 0})
        if task is None:
            return None
        return self._serialize_value(task)

    def create_task(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Crea una nueva tarea en MongoDB.

        Primero convierte la entrada a un diccionario, valida que tenga título
        y luego la guarda en la colección correspondiente.
        """
        payload = self._to_dict(task)
        if not payload.get("title"):
            raise ValueError("El título de la tarea es obligatorio")

        payload["task_id"] = payload.get("task_id") or str(uuid.uuid4())

        db = get_db(self.db_name)
        result = db.personal_tasks.insert_one(payload)
        return {"inserted_id": str(result.inserted_id), "task_id": payload["task_id"]}

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Actualiza campos de una tarea existente identificada por task_id."""
        if not updates:
            raise ValueError("No se proporcionaron campos para actualizar")

        db = get_db(self.db_name)
        result = db.personal_tasks.update_one(
            {"task_id": task_id},
            {"$set": updates},
        )
        if result.matched_count == 0:
            return None

        updated_task = db.personal_tasks.find_one({"task_id": task_id}, {"_id": 0})
        return self._serialize_value(updated_task) if updated_task is not None else None

    def complete_task(self, task_id: str) -> dict[str, Any]:
        """Marca una tarea como completada en base a su task_id."""
        db = get_db(self.db_name)
        result = db.personal_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "Completed"}},
        )
        return {"matched": result.matched_count, "modified": result.modified_count}
