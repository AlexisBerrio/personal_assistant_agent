from __future__ import annotations

import asyncio
import sys
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.config import get_settings


settings = get_settings()


class MongoConnection:
    """Encapsula la conexión con MongoDB para mantener la infraestructura ordenada."""

    def __init__(self) -> None:
        self.client: Any = None
        self.connection_error: str | None = None
        self._connect()

    def _connect(self) -> None:
        """Intenta conectar a MongoDB y validar la conexión."""
        try:
            self.client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._ensure_task_indexes())
            else:
                asyncio.get_running_loop().create_task(self._ensure_task_indexes())
        except Exception as exc:  # pragma: no cover - fallback de conexión
            self.connection_error = str(exc)
            self.client = None
            print(f"[Mongo] No se pudo conectar: {exc}", file=sys.stderr)

    async def _ensure_task_indexes(self) -> None:
        """Crea índices de negocio necesarios para la colección de tareas."""
        if self.client is None:
            return

        db = self.client[settings.mongo_db_name]
        await db.personal_tasks.create_index([("task_id", 1)], unique=True)

    async def get_db(self, db_name: str = settings.mongo_db_name):
        """Devuelve una base de datos si la conexión está disponible."""
        if self.connection_error or self.client is None:
            raise RuntimeError(
                "MongoDB no está disponible. Revisa la URI y la conectividad."
            )
        return self.client[db_name]


mongo_connection = MongoConnection()


async def get_db(db_name: str = settings.mongo_db_name):
    """Función de conveniencia para obtener la base de datos desde otros módulos."""
    return await mongo_connection.get_db(db_name)
