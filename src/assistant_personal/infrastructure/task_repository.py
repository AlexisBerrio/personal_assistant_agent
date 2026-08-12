from __future__ import annotations

from typing import Any

from src.assistant_personal.domain.repositories.task_repository import TaskRepository
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db
from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import MongoTaskRepository


def build_default_task_repository(db_name: str = "personal_management", get_db_fn: Any | None = None) -> TaskRepository:
    """Construye el adaptador MongoDB por defecto para el puerto del dominio."""
    return MongoTaskRepository(db_name=db_name, get_db_fn=get_db_fn or get_db)


__all__ = ["MongoTaskRepository", "build_default_task_repository"]
