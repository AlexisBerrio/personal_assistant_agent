from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db

_MAX_STORED_TURNS = 20


class MongoSessionRepository(SessionMemoryRepository):
    """Repositorio async para almacenar memoria de corto plazo por sesión en MongoDB.

    Async de extremo a extremo: ningún método hace bridging con `asyncio.run`.
    Consumirlo desde código síncrono requiere un event loop propio (ej. `asyncio.run`
    en el punto de entrada), nunca dentro de este repositorio.
    """

    def __init__(self, db_name: str | None = None, get_db_fn: Any | None = None, tenant_id: str | None = None) -> None:
        self.db_name = db_name or get_settings().mongo_db_name
        self._get_db_fn = get_db_fn or get_db
        # Fijo en "default" hasta que exista multi-tenant real (Fase 8) — ver §A.13, ítem 1.7.
        self.tenant_id = tenant_id or "default"

    def _build_timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def _session_filter(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "tenant_id": self.tenant_id}

    async def _get_collection(self) -> Any:
        db = await self._get_db_fn(self.db_name)
        return db.conversation_sessions

    async def _get_session(self, session_id: str) -> dict[str, Any]:
        collection = await self._get_collection()
        session = await collection.find_one(self._session_filter(session_id)) or {}
        return {
            "session_id": session.get("session_id", session_id),
            "turns": session.get("turns", []),
            "items": session.get("items", []),
            "summary": session.get("summary", ""),
            "updated_at": session.get("updated_at"),
            "created_at": session.get("created_at"),
        }

    async def _upsert_session(self, session_id: str, updates: dict[str, Any]) -> None:
        collection = await self._get_collection()
        now = self._build_timestamp()
        payload = {
            "$set": {"session_id": session_id, "tenant_id": self.tenant_id, **updates, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        }
        await collection.update_one(self._session_filter(session_id), payload, upsert=True)

    async def append_turn_async(self, session_id: str, user_message: str, assistant_response: str) -> None:
        session = await self._get_session(session_id)
        turns = session.get("turns", [])
        turns.append({
            "user_message": user_message,
            "assistant_response": assistant_response,
            "timestamp": self._build_timestamp(),
        })
        # Tope de seguridad, no el presupuesto real: el resumen incremental de `ContextBuilder`
        # recorta a 1 turno + resumen cada `summarize_every_n_turns` (default # 10) vía `compact_session_async`.
        # Este cap más alto (`_MAX_STORED_TURNS`) solo evita crecimiento sin límite si el
        # resumen falla repetidamente (ej. LLM caído varios turnos).
        await self._upsert_session(session_id, {"turns": turns[-_MAX_STORED_TURNS:]})

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

    async def get_context_summary_async(
        self, session_id: str, max_turns: int = 3, max_items: int = 5
    ) -> dict[str, Any]:
        session = await self._get_session(session_id)
        turns = list(session.get("turns", []))[-max_turns:]
        items = list(session.get("items", []))[-max_items:]
        return {"turns": turns, "items": items, "summary": session.get("summary", "")}

    async def compact_session_async(self, session_id: str, summary: str, keep_last_turns: int = 1) -> None:
        """Fija el resumen incremental y recorta `turns` a los últimos `keep_last_turns`
        — los turnos ya incorporados al resumen se descartan de la lista activa."""
        session = await self._get_session(session_id)
        turns = list(session.get("turns", []))
        kept_turns = turns[-keep_last_turns:] if keep_last_turns else []
        await self._upsert_session(session_id, {"summary": summary, "turns": kept_turns})
