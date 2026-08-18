from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.config import get_settings
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db


class MongoTaskRepository:
    """Repositorio concreto para persistir tareas en MongoDB con Motor."""

    def __init__(self, db_name: str | None = None, get_db_fn: Any | None = None) -> None:
        self.db_name = db_name or get_settings().mongo_db_name
        self._get_db_fn = get_db_fn or get_db

    async def _get_db(self) -> Any:
        return await self._get_db_fn(self.db_name)

    def _active_task_filter(self, task_id: str | None = None) -> dict[str, Any]:
        filter_query: dict[str, Any] = {"is_deleted": {"$ne": True}}
        if task_id is not None:
            filter_query["task_id"] = task_id
        return filter_query

    async def check_connection(self) -> bool:
        """Devuelve True si la base de datos responde a un ping."""
        try:
            db = await self._get_db()
            await db.command("ping")
            return True
        except Exception:
            return False

    async def _maybe_await(self, value: Any) -> Any:
        """Devuelve el resultado, esperando la coroutine solo si hace falta."""
        if inspect.isawaitable(value):
            return await value
        return value

    async def _collect_documents(self, cursor: Any) -> list[dict[str, Any]]:
        """Recoge documentos desde un cursor síncrono o asíncrono."""
        if hasattr(cursor, "__aiter__"):
            return [doc async for doc in cursor]
        return [doc for doc in cursor]

    async def _record_history(
        self, db: Any, task_id: str, updates: dict[str, Any], previous_task: dict[str, Any] | None
    ) -> None:
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

        await self._maybe_await(db.task_history.insert_one(history_entry))

    async def list_active_tasks_async(self) -> list[dict[str, Any]]:
        db = await self._get_db()
        cursor = db.personal_tasks.find(self._active_task_filter(), {"_id": 0}).limit(10)
        return await self._collect_documents(cursor)

    async def get_task_by_id_async(self, task_id: str) -> dict[str, Any] | None:
        db = await self._get_db()
        return await self._maybe_await(db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        ))

    async def get_task_history_async(self, task_id: str) -> list[dict[str, Any]]:
        db = await self._get_db()
        cursor = db.task_history.find({"task_id": task_id}, {"_id": 0}).sort("timestamp", 1)
        return await self._collect_documents(cursor)

    async def create_task_async(self, payload: dict[str, Any]) -> dict[str, Any]:
        db = await self._get_db()
        result = await self._maybe_await(db.personal_tasks.insert_one(payload))
        return {**payload, "inserted_id": str(result.inserted_id)}

    async def update_task_async(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        db = await self._get_db()
        previous_task = await self._maybe_await(db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        ))
        if previous_task is None:
            return None

        result = await self._maybe_await(db.personal_tasks.update_one(
            self._active_task_filter(task_id),
            {"$set": updates},
        ))
        if result.matched_count == 0:
            return None

        await self._record_history(db, task_id, updates, previous_task)
        updated_task = await self._maybe_await(db.personal_tasks.find_one(
            self._active_task_filter(task_id), {"_id": 0}))
        return updated_task

    async def complete_task_async(self, task_id: str) -> dict[str, Any]:
        db = await self._get_db()
        previous_task = await self._maybe_await(db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        ))
        if previous_task is None:
            return {"matched": 0, "modified": 0}

        result = await self._maybe_await(db.personal_tasks.update_one(
            self._active_task_filter(task_id),
            {"$set": {"status": "Completed"}},
        ))
        await self._record_history(db, task_id, {"status": "Completed"}, previous_task)
        return {"matched": result.matched_count, "modified": result.modified_count}

    async def delete_task_async(self, task_id: str) -> dict[str, Any] | None:
        db = await self._get_db()
        previous_task = await self._maybe_await(db.personal_tasks.find_one(
            self._active_task_filter(task_id),
            {"_id": 0},
        ))
        if previous_task is None:
            return None

        deleted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        result = await self._maybe_await(db.personal_tasks.update_one(
            self._active_task_filter(task_id),
            {"$set": {"is_deleted": True, "deleted_at": deleted_at, "status": "Deleted"}},
        ))
        if result.matched_count == 0:
            return None

        await self._record_history(db, task_id, {"status": "Deleted", "is_deleted": True}, previous_task)
        return {"task_id": task_id, "deleted": True, "deleted_at": deleted_at}

