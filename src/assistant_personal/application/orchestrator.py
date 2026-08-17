from __future__ import annotations

import asyncio
import uuid
from typing import Any

from src.assistant_personal.application.agent_context import AgentContext
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter


class TaskOrchestrator:
    """Orquesta una interacción simple entre router, guardrails y especialista."""

    def __init__(
        self,
        service: Any,
        router: Any = None,
        max_retries: int = 1,
        session_repository: SessionMemoryRepository | None = None,
        session_id: str | None = None,
    ) -> None:
        self.service = service
        self.router = router or ProductionIntentRouter()
        self.max_retries = max_retries
        self.session_repository = session_repository
        self.context = AgentContext(short_term_repository=self.session_repository)
        self.session_id = session_id or f"session-{uuid.uuid4()}"

    def handle_message(self, message: str) -> dict[str, Any]:
        return asyncio.run(self.handle_message_async(message))

    async def handle_message_async(self, message: str) -> dict[str, Any]:
        if not message or not message.strip():
            return {
                "success": False,
                "action": "clarify",
                "message": "Guardrails: el mensaje está vacío.",
                "reason": "Guardrails: el mensaje está vacío.",
            }

        await self.context.short_term_memory.add_async("user_message", message, session_id=self.session_id)
        context_summary = await self.context.build_context_summary_async(session_id=self.session_id)

        profile_facts = self._extract_profile_facts(message, context_summary)
        await self._persist_profile_facts(profile_facts)
        context_summary = await self.context.build_context_summary_async(session_id=self.session_id)

        intent = self.router.route(message, context=context_summary)
        if intent.action == "clarify":
            response_message = intent.payload.get("message", "No se pudo interpretar")
            await self.context.short_term_memory.add_turn_async(message, response_message, session_id=self.session_id)
            return {"success": False, "action": "clarify", "message": response_message, "reason": response_message}

        if intent.action == "small_talk":
            reply = intent.payload.get("reply") or "¡Hola! ¿En qué te puedo ayudar?"
            await self.context.short_term_memory.add_turn_async(message, reply, session_id=self.session_id)
            return {"success": True, "action": "small_talk", "message": reply, "result": reply}

        if intent.action == "ask_knowledge_base":
            query = intent.payload.get("query") or message
            answer = intent.payload.get("answer") or self._answer_with_general_knowledge(query)
            await self.context.short_term_memory.add_async("last_knowledge_question", query, session_id=self.session_id)
            await self.context.short_term_memory.add_async("last_knowledge_answer", answer, session_id=self.session_id)
            await self.context.short_term_memory.add_turn_async(message, answer, session_id=self.session_id)
            return {"success": True, "action": "ask_knowledge_base", "message": answer, "result": answer}

        try:
            result = await self._execute_with_retries(intent)
            assistant_response = self._format_public_message(intent.action, result)
            await self.context.short_term_memory.add_turn_async(message, assistant_response, session_id=self.session_id)
            return {
                **result,
                "message": assistant_response,
            }
        except ValueError as exc:
            assistant_response = str(exc)
            await self.context.short_term_memory.add_turn_async(message, assistant_response, session_id=self.session_id)
            return {"success": False, "action": intent.action, "message": assistant_response, "reason": str(exc)}

    def _extract_profile_facts(self, message: str, context_summary: str) -> list[dict[str, Any]]:
        if not hasattr(self.router, "extract_profile_facts"):
            return []

        try:
            extracted = self.router.extract_profile_facts(message, context=context_summary)
        except Exception:
            return []

        if not extracted:
            return []

        if hasattr(extracted, "profile_facts"):
            extracted = extracted.profile_facts

        if not isinstance(extracted, list):
            return []

        facts: list[dict[str, Any]] = []
        for item in extracted:
            if isinstance(item, dict):
                key = item.get("key")
                value = item.get("value")
                if key and value is not None:
                    facts.append({"key": str(key), "value": str(value)})
            else:
                key = getattr(item, "key", None)
                value = getattr(item, "value", None)
                if key and value is not None:
                    facts.append({"key": str(key), "value": str(value)})
        return facts

    async def _persist_profile_facts(self, facts: list[dict[str, Any]]) -> None:
        for fact in facts:
            await self.context.short_term_memory.add_async(fact["key"], fact["value"], session_id=self.session_id)

    def _answer_with_general_knowledge(self, query: str) -> str:
        return f"Consulta de conocimiento: {query}"

    def _format_public_message(self, action: str, result: Any) -> str:
        if action == "create_task":
            if isinstance(result, dict):
                payload = result.get("result") or result
                if isinstance(payload, dict):
                    title = payload.get("title") or "tarea"
                    status = payload.get("status") or "creada"
                    return f"Tarea creada: {title} ({status})"
            return "Tarea creada"

        if action == "list_tasks":
            return "Aquí tienes tus tareas."

        if action == "complete_task":
            return "Tarea completada."

        return str(result)

    async def _execute_with_retries(self, intent: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._dispatch(intent)
            except ValueError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
        raise last_error or ValueError("No se pudo completar la acción")

    async def _dispatch(self, intent: Any) -> dict[str, Any]:
        if intent.action == "list_tasks":
            tasks = await self._invoke_service("list_tasks")
            return {"success": True, "action": intent.action, "result": tasks}

        if intent.action == "create_task":
            title = intent.payload.get("title")
            task_payload = {"title": title}
            if not title or not title.strip():
                raise ValueError("Entiendo que quieres crear una tarea, pero me falta el título. ¿Qué tarea deseas crear?")
            result = await self._invoke_service("create_task", task_payload)
            return {"success": True, "action": intent.action, "result": result}

        if intent.action == "complete_task":
            task_id = intent.payload.get("task_id")
            if not task_id:
                raise ValueError("Guardrails: falta el identificador de tarea")
            result = await self._invoke_service("complete_task", task_id)
            return {"success": True, "action": intent.action, "result": result}

        return {"success": False, "action": "clarify", "reason": "No se pudo ejecutar la acción"}

    async def _invoke_service(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        async_method = getattr(self.service, f"{method_name}_async", None)
        if callable(async_method):
            return await async_method(*args, **kwargs)

        sync_method = getattr(self.service, method_name, None)
        if callable(sync_method):
            return sync_method(*args, **kwargs)

        raise AttributeError(f"El servicio no implementa '{method_name}'")
