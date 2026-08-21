from __future__ import annotations

import inspect
from typing import Any

from src.assistant_personal.application.memory.context_builder import ContextBuilder
from src.assistant_personal.domain.entities import UserProfileFact
from src.assistant_personal.domain.repositories.long_term_memory_repository import LongTermMemoryRepository
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.observabilidad import get_tracer

_MAX_STORED_TURNS = 20
tracer = get_tracer(__name__)


class InMemorySessionRepository:
    """Repositorio en memoria para pruebas y uso local sin infraestructura externa."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def _get_session(self, session_id: str) -> dict[str, Any]:
        return self._sessions.setdefault(session_id, {"turns": [], "items": [], "summary": ""})

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
        # Mismo tope de seguridad que MongoSessionRepository — no el presupuesto real,
        # ver ContextBuilder.
        session["turns"] = session["turns"][-_MAX_STORED_TURNS:]

    def get_context_summary(self, session_id: str, max_turns: int = 3, max_items: int = 5) -> dict[str, Any]:
        session = self._get_session(session_id)
        return {
            "turns": session["turns"][-max_turns:],
            "items": session["items"][-max_items:],
            "summary": session.get("summary", ""),
        }

    def compact_session(self, session_id: str, summary: str, keep_last_turns: int = 1) -> None:
        session = self._get_session(session_id)
        session["summary"] = summary
        session["turns"] = session["turns"][-keep_last_turns:] if keep_last_turns else []

    async def add_context_item_async(self, session_id: str, key: str, value: str) -> None:
        self.add_context_item(session_id, key, value)

    async def append_turn_async(self, session_id: str, user_message: str, assistant_response: str) -> None:
        self.append_turn(session_id, user_message, assistant_response)

    async def get_context_summary_async(
        self, session_id: str, max_turns: int = 3, max_items: int = 5
    ) -> dict[str, Any]:
        return self.get_context_summary(session_id, max_turns=max_turns, max_items=max_items)

    async def compact_session_async(self, session_id: str, summary: str, keep_last_turns: int = 1) -> None:
        self.compact_session(session_id, summary, keep_last_turns)


class ShortTermMemory:
    """Memoria temporal para la conversación actual con límites controlados.

    Consume el repositorio de forma async: usa la variante `_async` del puerto
    cuando existe (obligatoria para adaptadores con I/O real, ej. Mongo) y solo
    recurre al método síncrono cuando el adaptador es puramente en memoria.
    """

    def __init__(self, repository: SessionMemoryRepository, max_turns: int = 3, max_items: int = 5) -> None:
        self.repository = repository
        self.max_turns = max_turns
        self.max_items = max_items

    def add(self, key: str, value: str, session_id: str = "default") -> None:
        """Solo válido con repositorios sin I/O real (ej. InMemorySessionRepository)."""
        self.repository.add_context_item(session_id, key, value)

    def add_turn(self, user_message: str, assistant_response: str, session_id: str = "default") -> None:
        """Solo válido con repositorios sin I/O real (ej. InMemorySessionRepository)."""
        self.repository.append_turn(session_id, user_message, assistant_response)

    def get_items(self, session_id: str = "default") -> list[tuple[str, str]]:
        """Solo válido con repositorios sin I/O real (ej. InMemorySessionRepository)."""
        summary = self.repository.get_context_summary(session_id, max_turns=self.max_turns, max_items=self.max_items)
        return [(item["key"], item["value"]) for item in summary.get("items", [])]

    def get_turns(self, session_id: str = "default") -> list[tuple[str, str]]:
        """Solo válido con repositorios sin I/O real (ej. InMemorySessionRepository)."""
        summary = self.repository.get_context_summary(session_id, max_turns=self.max_turns, max_items=self.max_items)
        return [(turn["user_message"], turn["assistant_response"]) for turn in summary.get("turns", [])]

    async def _invoke_repository_async(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        for candidate_name in (f"{method_name}_async", method_name):
            method = getattr(self.repository, candidate_name, None)
            if callable(method):
                result = method(*args, **kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result

        raise AttributeError(f"El repositorio de sesión no implementa '{method_name}'")

    async def add_async(self, key: str, value: str, session_id: str = "default") -> None:
        await self._invoke_repository_async("add_context_item", session_id, key, value)

    async def add_turn_async(self, user_message: str, assistant_response: str, session_id: str = "default") -> None:
        await self._invoke_repository_async("append_turn", session_id, user_message, assistant_response)

    async def get_items_async(self, session_id: str = "default") -> list[tuple[str, str]]:
        summary = await self._invoke_repository_async(
            "get_context_summary", session_id, max_turns=self.max_turns, max_items=self.max_items
        )
        return [(item["key"], item["value"]) for item in summary.get("items", [])]

    async def get_turns_async(self, session_id: str = "default") -> list[tuple[str, str]]:
        summary = await self._invoke_repository_async(
            "get_context_summary", session_id, max_turns=self.max_turns, max_items=self.max_items
        )
        return [(turn["user_message"], turn["assistant_response"]) for turn in summary.get("turns", [])]

    async def get_raw_session_async(self, session_id: str = "default", max_turns: int = 10) -> dict[str, Any]:
        """Sesión sin recortar a `max_turns`/`max_items` de instancia — usado por `ContextBuilder`, que
            decide cuánto entra según presupuesto de tokens, no un conteo fijo."""
        result: dict[str, Any] = await self._invoke_repository_async(
            "get_context_summary", session_id, max_turns=max_turns, max_items=self.max_items
        )
        return result

    async def compact_async(self, session_id: str, summary: str, keep_last_turns: int = 1) -> None:
        await self._invoke_repository_async("compact_session", session_id, summary, keep_last_turns)


class InMemoryLongTermMemoryRepository:
    """Repositorio en memoria para pruebas y uso local sin infraestructura externa."""

    def __init__(self) -> None:
        self._facts: dict[str, dict[str, UserProfileFact]] = {}

    def upsert_fact(self, user_id: str, fact: UserProfileFact, source: str = "manual") -> None:
        self._facts.setdefault(user_id, {})[fact.key] = fact

    def get_facts(self, user_id: str, limit: int = 10) -> list[UserProfileFact]:
        return list(self._facts.get(user_id, {}).values())[-limit:]

    def delete_facts(self, user_id: str) -> int:
        return len(self._facts.pop(user_id, {}))

    async def upsert_fact_async(self, user_id: str, fact: UserProfileFact, source: str = "manual") -> None:
        self.upsert_fact(user_id, fact, source)

    async def get_facts_async(self, user_id: str, limit: int = 10) -> list[UserProfileFact]:
        return self.get_facts(user_id, limit=limit)

    async def delete_facts_async(self, user_id: str) -> int:
        return self.delete_facts(user_id)


class LongTermMemory:
    """Memoria persistente con hechos de perfil del usuario, con presupuesto acotado —
    sobrevive a un reinicio cuando el repositorio es `MongoLongTermMemoryRepository`.

    Mismo patrón de despacho que `ShortTermMemory`: métodos síncronos válidos solo con
    repositorios sin I/O real; `_async` para adaptadores con I/O real (ej. Mongo).
    """

    def __init__(self, repository: LongTermMemoryRepository, user_id: str = "default") -> None:
        self.repository = repository
        self.user_id = user_id

    def add_fact(self, key: str, value: str, confidence: float = 1.0, source: str = "manual") -> None:
        """Solo válido con repositorios sin I/O real (ej. InMemoryLongTermMemoryRepository)."""
        self.repository.upsert_fact(self.user_id, UserProfileFact(key=key, value=value, confidence=confidence), source)

    def get_facts(self) -> dict[str, str]:
        """Solo válido con repositorios sin I/O real (ej. InMemoryLongTermMemoryRepository)."""
        return {fact.key: fact.value for fact in self.repository.get_facts(self.user_id)}

    async def _invoke_repository_async(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        for candidate_name in (f"{method_name}_async", method_name):
            method = getattr(self.repository, candidate_name, None)
            if callable(method):
                result = method(*args, **kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result

        raise AttributeError(f"El repositorio de memoria de largo plazo no implementa '{method_name}'")

    async def add_fact_async(self, key: str, value: str, confidence: float = 1.0, source: str = "manual") -> None:
        fact = UserProfileFact(key=key, value=value, confidence=confidence)
        await self._invoke_repository_async("upsert_fact", self.user_id, fact, source)

    async def get_facts_async(self) -> dict[str, str]:
        facts = await self._invoke_repository_async("get_facts", self.user_id)
        return {fact.key: fact.value for fact in facts}

    async def delete_facts_async(self) -> int:
        return int(await self._invoke_repository_async("delete_facts", self.user_id))


_RecentContext = tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]


class AgentContext:
    """Agrega contexto de corto y largo plazo para un agente simple."""

    def __init__(
        self,
        short_term_repository: SessionMemoryRepository | None = None,
        long_term_repository: LongTermMemoryRepository | None = None,
        user_id: str = "default",
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self.short_term_memory = ShortTermMemory(repository=short_term_repository or InMemorySessionRepository())
        self.long_term_memory = LongTermMemory(
            repository=long_term_repository or InMemoryLongTermMemoryRepository(), user_id=user_id
        )
        # Sin `summarizer` por defecto: el resumen incremental requiere un LLM real, que
        # `AgentContext` (capa de aplicación) no debe depender directamente — lo inyecta
        # `TaskOrchestrator`, que ya construye el resto de la infraestructura por defecto.
        self.context_builder = context_builder or ContextBuilder()
        self.last_context_tokens: int | None = None

    def _collect_recent_context(self, session_id: str) -> _RecentContext:
        recent_items = self.short_term_memory.get_items(session_id=session_id)[-3:]
        recent_turns = self.short_term_memory.get_turns(session_id=session_id)[-3:]
        recent_facts = list(self.long_term_memory.get_facts().items())[-3:]
        return recent_items, recent_turns, recent_facts

    def _format_context_summary(
        self,
        recent_items: list[tuple[str, str]],
        recent_turns: list[tuple[str, str]],
        recent_facts: list[tuple[str, str]],
    ) -> str:
        items = "; ".join(f"{key}={value}" for key, value in recent_items)
        turns = "; ".join(f"user:{user_msg} | assistant:{assistant_msg}" for user_msg, assistant_msg in recent_turns)
        facts = "; ".join(f"{key}={value}" for key, value in recent_facts)
        context_parts = [part for part in [items, turns, facts] if part]
        return f"Contexto reciente: {' | '.join(context_parts)}".strip()

    def build_context_summary(self, session_id: str = "default") -> str:
        recent_items, recent_turns, recent_facts = self._collect_recent_context(session_id)
        return self._format_context_summary(recent_items, recent_turns, recent_facts)

    async def build_context_summary_async(self, session_id: str = "default") -> str:
        """Delega en `ContextBuilder`: presupuesto de tokens medible en vez de conteos fijos
        arbitrarios. `last_context_tokens` queda disponible para observabilidad (mismo patrón
        que `last_llm_metadata` del router)."""
        with tracer.start_as_current_span("memoria.cargar") as span:
            span.set_attribute("session_id", session_id)
            context_text, tokens = await self.context_builder.build_context_async(
                self.short_term_memory, self.long_term_memory, session_id
            )
            self.last_context_tokens = tokens
            span.set_attribute("contexto_tokens", tokens)
            return context_text

    async def maybe_summarize_session_async(self, session_id: str = "default") -> None:
        await self.context_builder.maybe_summarize_async(self.short_term_memory, session_id)
