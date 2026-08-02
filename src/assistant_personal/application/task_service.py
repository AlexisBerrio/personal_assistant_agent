import uuid
from datetime import datetime, timezone
from typing import Any

from copy import deepcopy

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

    def _validate_create_payload(self, payload: dict[str, Any]) -> None:
        """Valida los datos básicos de una tarea antes de persistirla."""
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("El título de la tarea es obligatorio")

        status = payload.get("status")
        if status is not None and (not isinstance(status, str) or not status.strip()):
            raise ValueError("El estado de la tarea no puede estar vacío")

    def _active_task_filter(self) -> dict[str, Any]:
        """Devuelve el filtro para encontrar tareas que no han sido borradas lógicamente."""
        return {"is_deleted": {"$ne": True}}

    def _validate_update_payload(self, updates: dict[str, Any]) -> None:
        """Valida los campos que se van a actualizar."""
        if "title" in updates:
            title = updates["title"]
            if not isinstance(title, str) or not title.strip():
                raise ValueError("El título de la tarea no puede estar vacío")
            updates["title"] = title.strip()

        if "status" in updates:
            status = updates["status"]
            if not isinstance(status, str) or not status.strip():
                raise ValueError("El estado de la tarea no puede estar vacío")
            updates["status"] = status.strip()

    def list_tasks(self) -> list[dict[str, Any]]:
        """Devuelve las tareas más recientes de la colección personal_tasks."""
        db = get_db(self.db_name)
        raw_tasks = list(db.personal_tasks.find(self._active_task_filter(), {"_id": 0}).limit(10))
        return [self._serialize_value(task) for task in raw_tasks]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Devuelve una tarea concreta por su task_id."""
        db = get_db(self.db_name)
        task = db.personal_tasks.find_one({"task_id": task_id, **self._active_task_filter()}, {"_id": 0})
        if task is None:
            return None
        return self._serialize_value(task)

    def get_task_history(self, task_id: str) -> list[dict[str, Any]]:
        """Devuelve el historial de cambios de una tarea."""
        db = get_db(self.db_name)
        history = list(db.task_history.find({"task_id": task_id}, {"_id": 0}).sort("timestamp", 1))
        return [self._serialize_value(entry) for entry in history]

    def create_task(self, task: Task | dict[str, Any]) -> dict[str, Any]:
        """Crea una nueva tarea en MongoDB.

        Primero convierte la entrada a un diccionario, valida que tenga título
        y luego la guarda en la colección correspondiente.
        """
        payload = self._to_dict(task)
        self._validate_create_payload(payload)

        payload["title"] = payload["title"].strip()
        payload["status"] = payload.get("status") or "In Progress"
        payload["task_id"] = payload.get("task_id") or str(uuid.uuid4())
        payload.setdefault("is_deleted", False)
        payload.setdefault("deleted_at", None)

        db = get_db(self.db_name)
        result = db.personal_tasks.insert_one(payload)
        return {"inserted_id": str(result.inserted_id), "task_id": payload["task_id"]}

    def _record_history(self, db: Any, task_id: str, updates: dict[str, Any], previous_task: dict[str, Any] | None) -> None:
        """Guarda un registro de cambios en la colección task_history."""
        if not updates:
            return

        history_entry = {
            "task_id": task_id,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "changes": [],
        }

        for field, new_value in updates.items():
            previous_value = previous_task.get(field) if previous_task else None
            history_entry["changes"].append({
                "field": field,
                "previous_value": previous_value,
                "new_value": new_value,
            })

        db.task_history.insert_one(history_entry)

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Actualiza campos de una tarea existente identificada por task_id."""
        if not isinstance(updates, dict):
            raise ValueError("El cuerpo de la actualización debe ser un objeto")
        if not updates:
            raise ValueError("No se proporcionaron campos para actualizar")

        self._validate_update_payload(updates)

        db = get_db(self.db_name)
        previous_task = db.personal_tasks.find_one({"task_id": task_id, "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]}, {"_id": 0})
        if previous_task is None:
            return None

        result = db.personal_tasks.update_one(
            {"task_id": task_id, **self._active_task_filter()},
            {"$set": updates},
        )
        if result.matched_count == 0:
            return None

        self._record_history(db, task_id, updates, previous_task)
        updated_task = db.personal_tasks.find_one({"task_id": task_id, **self._active_task_filter()}, {"_id": 0})
        return self._serialize_value(updated_task) if updated_task is not None else None

    def complete_task(self, task_id: str) -> dict[str, Any]:
        """Marca una tarea como completada en base a su task_id."""
        db = get_db(self.db_name)
        previous_task = db.personal_tasks.find_one({"task_id": task_id, "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]}, {"_id": 0})
        if previous_task is None:
            return {"matched": 0, "modified": 0}

        result = db.personal_tasks.update_one(
            {"task_id": task_id, **self._active_task_filter()},
            {"$set": {"status": "Completed"}},
        )
        self._record_history(db, task_id, {"status": "Completed"}, previous_task)
        return {"matched": result.matched_count, "modified": result.modified_count}

    def delete_task(self, task_id: str) -> dict[str, Any] | None:
        """Marca una tarea como eliminada sin borrarla de la base de datos."""
        db = get_db(self.db_name)
        previous_task = db.personal_tasks.find_one({"task_id": task_id, "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]}, {"_id": 0})
        if previous_task is None:
            return None

        deleted_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        result = db.personal_tasks.update_one(
            {"task_id": task_id, **self._active_task_filter()},
            {"$set": {"is_deleted": True, "deleted_at": deleted_at, "status": "Deleted"}},
        )
        if result.matched_count == 0:
            return None

        self._record_history(db, task_id, {"status": "Deleted", "is_deleted": True}, previous_task)
        return {"task_id": task_id, "deleted": True, "deleted_at": deleted_at}
