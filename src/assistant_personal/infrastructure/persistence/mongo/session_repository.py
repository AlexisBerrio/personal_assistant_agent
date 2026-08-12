from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.persistence.mongo.client import get_db


class MongoSessionRepository(SessionMemoryRepository):
    """Repositorio para almacenar memoria de corto plazo por sesión en MongoDB."""

    def __init__(self, db_name: str = "personal_management", get_db_fn: Any | None = None) -> None:
        self.db_name = db_name
        self._get_db_fn = get_db_fn or get_db

    def _get_collection(self) -> Any:
        db = self._get_db_fn(self.db_name)
        return db.conversation_sessions

    def _get_session(self, session_id: str) -> dict[str, Any]:
        collection = self._get_collection()
        session = collection.find_one({"session_id": session_id}) or {}
        return {
            "session_id": session.get("session_id", session_id),
            "turns": session.get("turns", []),
            "items": session.get("items", []),
            "updated_at": session.get("updated_at"),
            "created_at": session.get("created_at"),
        }

    def _upsert_session(self, session_id: str, updates: dict[str, Any]) -> None:
        collection = self._get_collection()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        payload = {
            "$set": {"session_id": session_id, **updates, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        }
        collection.update_one({"session_id": session_id}, payload, upsert=True)

    def append_turn(self, session_id: str, user_message: str, assistant_response: str) -> None:
        session = self._get_session(session_id)
        turns = session.get("turns", [])
        turns.append({
            "user_message": user_message,
            "assistant_response": assistant_response,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._upsert_session(session_id, {"turns": turns[-5:]})

    def add_context_item(self, session_id: str, key: str, value: str) -> None:
        session = self._get_session(session_id)
        items = session.get("items", [])
        existing = False
        for item in items:
            if item.get("key") == key:
                item["value"] = value
                existing = True
                break
        if not existing:
            items.append({"key": key, "value": value})
        self._upsert_session(session_id, {"items": items[-5:]})

    def get_context_summary(self, session_id: str, max_turns: int = 3, max_items: int = 5) -> dict[str, Any]:
        session = self._get_session(session_id)
        turns = list(session.get("turns", []))[-max_turns:]
        items = list(session.get("items", []))[-max_items:]
        return {"turns": turns, "items": items}
