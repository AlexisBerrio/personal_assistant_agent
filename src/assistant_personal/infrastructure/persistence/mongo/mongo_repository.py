from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.infrastructure.mongo_client import get_db


class MongoTaskRepository:
    """Repositorio concreto para persistir tareas en MongoDB."""

    def __init__(self, db_name: str = "personal_management", get_db_fn: Any | None = None) -> None:
        self.db_name = db_name
        self._get_db_fn = get_db_fn or get_db

    def _get_db(self) -> Any:
        return self._get_db_fn(self.db_name)

    def _active_task_filter(self, task_id: str | None = None) -> dict[str, Any]:
        filter_query: dict[str, Any] = {"is_deleted": {"$ne": True}}
        if task_id is not None:
            filter_query["task_id"] = task_id
        return filter_query

    def _record_history(self, db: Any, task_id: str, updates: dict[str, Any], previous_task: dict[str, Any] | None) -> None:
        if not updates:
            return

        history_entry = {
            "task_id": task_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
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

    def list_active_tasks(self) -> list[dict[str, Any]]:
        db = self._get_db()
        return list(db.personal_tasks.find(self._active_task_filter(), {"_id": 0}).limit(10))

    def get_task_by_id(self, task_id: str) -> dict[str, Any] | None:
        db = self._get_db()
        return db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        )

    def get_task_history(self, task_id: str) -> list[dict[str, Any]]:
        db = self._get_db()
        return list(db.task_history.find({"task_id": task_id}, {"_id": 0}).sort("timestamp", 1))

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        db = self._get_db()
        result = db.personal_tasks.insert_one(payload)
        return {"inserted_id": str(result.inserted_id), "task_id": payload["task_id"]}

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        db = self._get_db()
        previous_task = db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        )
        if previous_task is None:
            return None

        result = db.personal_tasks.update_one(
            self._active_task_filter(task_id),
            {"$set": updates},
        )
        if result.matched_count == 0:
            return None

        self._record_history(db, task_id, updates, previous_task)
        updated_task = db.personal_tasks.find_one(self._active_task_filter(task_id), {"_id": 0})
        return updated_task

    def complete_task(self, task_id: str) -> dict[str, Any]:
        db = self._get_db()
        previous_task = db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        )
        if previous_task is None:
            return {"matched": 0, "modified": 0}

        result = db.personal_tasks.update_one(
            self._active_task_filter(task_id),
            {"$set": {"status": "Completed"}},
        )
        self._record_history(db, task_id, {"status": "Completed"}, previous_task)
        return {"matched": result.matched_count, "modified": result.modified_count}

    def delete_task(self, task_id: str) -> dict[str, Any] | None:
        db = self._get_db()
        previous_task = db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        )
        if previous_task is None:
            return None

        deleted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        result = db.personal_tasks.update_one(
            self._active_task_filter(task_id),
            {"$set": {"is_deleted": True, "deleted_at": deleted_at, "status": "Deleted"}},
        )
        if result.matched_count == 0:
            return None

        self._record_history(db, task_id, {"status": "Deleted", "is_deleted": True}, previous_task)
        return {"task_id": task_id, "deleted": True, "deleted_at": deleted_at}
