from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.entities import UserProfileFact
from src.assistant_personal.domain.repositories.long_term_memory_repository import LongTermMemoryRepository
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db


class MongoLongTermMemoryRepository(LongTermMemoryRepository):
    """Repositorio async para hechos de perfil de usuario en MongoDB (§A.9, ítem 2.5).

    Async de extremo a extremo, mismo patrón que `MongoSessionRepository`.
    """

    def __init__(self, db_name: str | None = None, get_db_fn: Any | None = None, tenant_id: str | None = None) -> None:
        self.db_name = db_name or get_settings().mongo_db_name
        self._get_db_fn = get_db_fn or get_db
        # Fijo en "default" hasta que exista multi-tenant real (Fase 8) — ver §A.13, ítem 1.7.
        self.tenant_id = tenant_id or "default"

    def _build_timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def _fact_filter(self, user_id: str, key: str | None = None) -> dict[str, Any]:
        filter_query: dict[str, Any] = {"tenant_id": self.tenant_id, "user_id": user_id}
        if key is not None:
            filter_query["key"] = key
        return filter_query

    async def _get_collection(self) -> Any:
        db = await self._get_db_fn(self.db_name)
        return db.user_profile_facts

    async def upsert_fact_async(self, user_id: str, fact: UserProfileFact, source: str = "manual") -> None:
        collection = await self._get_collection()
        now = self._build_timestamp()
        payload = {
            "$set": {
                "value": fact.value,
                "confidence": fact.confidence,
                "source": source,
                "updated_at": now,
            },
            "$setOnInsert": {
                "tenant_id": self.tenant_id,
                "user_id": user_id,
                "key": fact.key,
                "created_at": now,
            },
        }
        await collection.update_one(self._fact_filter(user_id, fact.key), payload, upsert=True)

    async def get_facts_async(self, user_id: str, limit: int = 10) -> list[UserProfileFact]:
        collection = await self._get_collection()
        cursor = collection.find(self._fact_filter(user_id), {"_id": 0}).sort("updated_at", -1).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [
            UserProfileFact(key=doc["key"], value=doc["value"], confidence=doc.get("confidence", 0.8))
            for doc in documents
        ]

    async def delete_facts_async(self, user_id: str) -> int:
        collection = await self._get_collection()
        result = await collection.delete_many(self._fact_filter(user_id))
        return int(result.deleted_count)
