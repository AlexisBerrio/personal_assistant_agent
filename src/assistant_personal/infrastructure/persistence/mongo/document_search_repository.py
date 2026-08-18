from __future__ import annotations

from typing import Any

from src.assistant_personal.config import get_settings
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db


class MongoTextSearchRepository:
    """Adaptador del port `DocumentSearchRepository` (domain/repositories/) usando el índice
    de texto (`$text`) de MongoDB sobre `title`/`description` de `personal_tasks`.

    Primer adaptador no vectorial exigido por §A.10 antes de considerar RAG. El índice de
    texto se crea en `client.py._ensure_task_indexes`, igual que los demás índices de negocio.
    """

    def __init__(self, db_name: str | None = None, get_db_fn: Any | None = None, tenant_id: str | None = None) -> None:
        self.db_name = db_name or get_settings().mongo_db_name
        self._get_db_fn = get_db_fn or get_db
        self.tenant_id = tenant_id or "default"

    async def _get_db(self) -> Any:
        return await self._get_db_fn(self.db_name)

    async def buscar(
        self, consulta: str, filtros: dict[str, Any] | None = None, limite: int = 10
    ) -> list[dict[str, Any]]:
        db = await self._get_db()
        query: dict[str, Any] = {
            "$text": {"$search": consulta},
            "tenant_id": self.tenant_id,
            "is_deleted": {"$ne": True},
            **(filtros or {}),
        }
        cursor = (
            db.personal_tasks.find(query, {"_id": 0, "score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"})])
            .limit(limite)
        )
        return [doc async for doc in cursor]
