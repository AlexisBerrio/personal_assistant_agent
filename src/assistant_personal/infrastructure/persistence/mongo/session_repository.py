from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db


class MongoSessionRepository(SessionMemoryRepository):
    """Repositorio async para almacenar memoria de corto plazo por sesión en MongoDB.

    Async de extremo a extremo: ningún método hace bridging con `asyncio.run`.
    Consumirlo desde código síncrono requiere un event loop propio (ej. `asyncio.run`
    en el punto de entrada), nunca dentro de este repositorio.
    """

    def __init__(self, db_name: str | None = None, get_db_fn: Any | None = None) -> None:
        self.db_name = db_name or get_settings().mongo_db_name
        self._get_db_fn = get_db_fn or get_db

    def _build_timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    async def _get_collection(self) -> Any:
        db = await self._get_db_fn(self.db_name)
        return db.conversation_sessions

    async def _get_session(self, session_id: str) -> dict[str, Any]:
        collection = await self._get_collection()
        session = await collection.find_one({"session_id": session_id}) or {}
        return {
            "session_id": session.get("session_id", session_id),
            "turns": session.get("turns", []),
            "items": session.get("items", []),
            "updated_at": session.get("updated_at"),
            "created_at": session.get("created_at"),
        }

    async def _upsert_session(self, session_id: str, updates: dict[str, Any]) -> None:
        collection = await self._get_collection()
        now = self._build_timestamp()
        payload = {
            "$set": {"session_id": session_id, **updates, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        }
        await collection.update_one({"session_id": session_id}, payload, upsert=True)

    async def append_turn_async(self, session_id: str, user_message: str, assistant_response: str) -> None:
        session = await self._get_session(session_id)
        turns = session.get("turns", [])
        turns.append({
            "user_message": user_message,
            "assistant_response": assistant_response,
            "timestamp": self._build_timestamp(),
        })
        await self._upsert_session(session_id, {"turns": turns[-5:]})

    async def add_context_item_async(self, session_id: str, key: str, value: str) -> None:
        session = await self._get_session(session_id)
        items = session.get("items", [])
        existing = False
        for item in items:
            if item.get("key") == key:
                item["value"] = value
                existing = True
                break
        if not existing:
            items.append({"key": key, "value": value})
        await self._upsert_session(session_id, {"items": items[-5:]})

    async def get_context_summary_async(self, session_id: str, max_turns: int = 3, max_items: int = 5) -> dict[str, Any]:
        session = await self._get_session(session_id)
        turns = list(session.get("turns", []))[-max_turns:]
        items = list(session.get("items", []))[-max_items:]
        return {"turns": turns, "items": items}
