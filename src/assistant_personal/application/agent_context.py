from __future__ import annotations

from typing import Any

from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository


class InMemorySessionRepository:
    """Repositorio en memoria para pruebas y uso local sin infraestructura externa."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, list[dict[str, str]]]] = {}

    def _get_session(self, session_id: str) -> dict[str, list[dict[str, str]]]:
        return self._sessions.setdefault(session_id, {"turns": [], "items": []})

    def add_context_item(self, session_id: str, key: str, value: str) -> None:
        session = self._get_session(session_id)
        items = session["items"]
        for item in items:
            if item["key"] == key:
                item["value"] = value
                return
        items.append({"key": key, "value": value})

    def append_turn(self, session_id: str, user_message: str, assistant_response: str) -> None:
        session = self._get_session(session_id)
        session["turns"].append({"user_message": user_message, "assistant_response": assistant_response})

    def get_context_summary(self, session_id: str, max_turns: int = 3, max_items: int = 5) -> dict[str, Any]:
        session = self._get_session(session_id)
        return {
            "turns": session["turns"][-max_turns:],
            "items": session["items"][-max_items:],
        }


class ShortTermMemory:
    """Memoria temporal para la conversación actual con límites controlados."""

    def __init__(self, repository: SessionMemoryRepository, max_turns: int = 3, max_items: int = 5) -> None:
        self.repository = repository
        self.max_turns = max_turns
        self.max_items = max_items

    def add(self, key: str, value: str, session_id: str = "default") -> None:
        self.repository.add_context_item(session_id, key, value)

    def add_turn(self, user_message: str, assistant_response: str, session_id: str = "default") -> None:
        self.repository.append_turn(session_id, user_message, assistant_response)

    def get_items(self, session_id: str = "default") -> list[tuple[str, str]]:
        summary = self.repository.get_context_summary(session_id, max_turns=self.max_turns, max_items=self.max_items)
        return [(item["key"], item["value"]) for item in summary.get("items", [])]

    def get_turns(self, session_id: str = "default") -> list[tuple[str, str]]:
        summary = self.repository.get_context_summary(session_id, max_turns=self.max_turns, max_items=self.max_items)
        return [(turn["user_message"], turn["assistant_response"]) for turn in summary.get("turns", [])]


class LongTermMemory:
    """Memoria persistente con hechos clave del usuario."""

    def __init__(self) -> None:
        self._facts: dict[str, str] = {}

    def add_fact(self, key: str, value: str) -> None:
        self._facts[key] = value

    def get_facts(self) -> dict[str, str]:
        return dict(self._facts)


class AgentContext:
    """Agrega contexto de corto y largo plazo para un agente simple."""

    def __init__(self, short_term_repository: SessionMemoryRepository | None = None) -> None:
        self.short_term_memory = ShortTermMemory(repository=short_term_repository or InMemorySessionRepository())
        self.long_term_memory = LongTermMemory()

    def build_context_summary(self, session_id: str = "default") -> str:
        recent_items = self.short_term_memory.get_items(session_id=session_id)[-3:]
        recent_turns = self.short_term_memory.get_turns(session_id=session_id)[-3:]
        recent_facts = list(self.long_term_memory.get_facts().items())[-3:]

        items = "; ".join(f"{key}={value}" for key, value in recent_items)
        turns = "; ".join(f"user:{user_msg} | assistant:{assistant_msg}" for user_msg, assistant_msg in recent_turns)
        facts = "; ".join(f"{key}={value}" for key, value in recent_facts)
        context_parts = [part for part in [items, turns, facts] if part]
        return f"Contexto reciente: {' | '.join(context_parts)}".strip()
