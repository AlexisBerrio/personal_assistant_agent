from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any

import structlog

from src.assistant_personal.application.agent_context import AgentContext
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.observabilidad import get_logger
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter

logger = get_logger(__name__)


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
        started_at = time.monotonic()
        # Cada turno es su propia "interacción" a efectos de observabilidad (ver §A.5): un
        # request_id nuevo por turno, no reutilizado entre turnos del mismo CLI interactivo.
        # Si en el futuro esto se invoca dentro de una petición FastAPI ya instrumentada, esto
        # sobreescribe el request_id de la petición para los logs de la interacción — aceptable
        # hoy porque `TaskOrchestrator` no se usa todavía desde `app.py`.
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            return await self._handle_message(message, request_id=request_id, started_at=started_at)
        finally:
            structlog.contextvars.clear_contextvars()

    async def _handle_message(self, message: str, *, request_id: str, started_at: float) -> dict[str, Any]:
        if not message or not message.strip():
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion="clarify", confianza=None, uso_llm=False, llm_metadata=None,
                resultado="guardrails_mensaje_vacio",
            )
            return {
                "success": False,
                "action": "clarify",
                "message": "Guardrails: el mensaje está vacío.",
                "reason": "Guardrails: el mensaje está vacío.",
            }

        await self.context.short_term_memory.add_async("user_message", message, session_id=self.session_id)
        context_summary = await self.context.build_context_summary_async(session_id=self.session_id)

        profile_facts = await self._extract_profile_facts(message, context_summary)
        await self._persist_profile_facts(profile_facts)
        context_summary = await self.context.build_context_summary_async(session_id=self.session_id)

        intent = await self._maybe_await(self.router.route(message, context=context_summary))
        llm_metadata = getattr(self.router, "last_llm_metadata", None)
        uso_llm = intent.source == "llm"

        if intent.action == "clarify":
            response_message = intent.payload.get("message", "No se pudo interpretar")
            await self.context.short_term_memory.add_turn_async(message, response_message, session_id=self.session_id)
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion="clarify", confianza=intent.confidence, uso_llm=uso_llm, llm_metadata=llm_metadata,
                resultado="clarify",
            )
            return {"success": False, "action": "clarify", "message": response_message, "reason": response_message}

        if intent.action == "small_talk":
            reply = intent.payload.get("reply") or "¡Hola! ¿En qué te puedo ayudar?"
            await self.context.short_term_memory.add_turn_async(message, reply, session_id=self.session_id)
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion=intent.action, confianza=intent.confidence, uso_llm=uso_llm, llm_metadata=llm_metadata,
                resultado="success",
            )
            return {"success": True, "action": "small_talk", "message": reply, "result": reply}

        if intent.action == "ask_knowledge_base":
            query = intent.payload.get("query") or message
            answer = intent.payload.get("answer") or self._answer_with_general_knowledge(query)
            await self.context.short_term_memory.add_async("last_knowledge_question", query, session_id=self.session_id)
            await self.context.short_term_memory.add_async("last_knowledge_answer", answer, session_id=self.session_id)
            await self.context.short_term_memory.add_turn_async(message, answer, session_id=self.session_id)
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion=intent.action, confianza=intent.confidence, uso_llm=uso_llm, llm_metadata=llm_metadata,
                resultado="success",
            )
            return {"success": True, "action": "ask_knowledge_base", "message": answer, "result": answer}

        try:
            result = await self._execute_with_retries(intent)
            assistant_response = self._format_public_message(intent.action, result)
            await self.context.short_term_memory.add_turn_async(message, assistant_response, session_id=self.session_id)
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion=intent.action, confianza=intent.confidence, uso_llm=uso_llm, llm_metadata=llm_metadata,
                resultado="success",
            )
            return {
                **result,
                "message": assistant_response,
            }
        except ValueError as exc:
            assistant_response = str(exc)
            await self.context.short_term_memory.add_turn_async(message, assistant_response, session_id=self.session_id)
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion=intent.action, confianza=intent.confidence, uso_llm=uso_llm, llm_metadata=llm_metadata,
                resultado="error_negocio",
            )
            return {"success": False, "action": intent.action, "message": assistant_response, "reason": str(exc)}

    def _log_interaction(
        self,
        *,
        request_id: str,
        started_at: float,
        intencion: str,
        confianza: float | None,
        uso_llm: bool,
        llm_metadata: dict[str, Any] | None,
        resultado: str,
    ) -> None:
        """Emite el log de cierre de una interacción con los 12 campos mínimos de §A.5.

        Con estos campos se puede calcular coste por interacción y tasa de `clarify` sin
        instrumentación adicional. `tenant_id` queda fijo en "default" hasta el ítem 1.7
        (multi-tenant real); `modelo`/`tokens_*`/`latencia_ms_llm` quedan en None cuando la
        decisión se resolvió por regla y nunca se invocó al LLM.
        """
        metadata = llm_metadata or {}
        logger.info(
            "interaccion_completada",
            request_id=request_id,
            session_id=self.session_id,
            tenant_id="default",
            intencion=intencion,
            confianza=confianza,
            uso_llm=uso_llm,
            modelo=metadata.get("modelo"),
            tokens_entrada=metadata.get("tokens_entrada"),
            tokens_salida=metadata.get("tokens_salida"),
            latencia_ms_total=int((time.monotonic() - started_at) * 1000),
            latencia_ms_llm=metadata.get("latencia_ms_llm"),
            resultado=resultado,
        )

    async def _maybe_await(self, value: Any) -> Any:
        """Soporta routers síncronos y async: el port `LLMClient` (§A.1, ítem 1.6) es async de
        punta a punta en producción, pero muchos dobles de test siguen siendo síncronos —
        mismo patrón de despacho que `TaskService._invoke_repository_async`."""
        if inspect.isawaitable(value):
            return await value
        return value

    async def _extract_profile_facts(self, message: str, context_summary: str) -> list[dict[str, Any]]:
        if not hasattr(self.router, "extract_profile_facts"):
            return []

        try:
            extracted = await self._maybe_await(self.router.extract_profile_facts(message, context=context_summary))
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
                raise ValueError(
                    "Entiendo que quieres crear una tarea, pero me falta el título. ¿Qué tarea deseas crear?"
                )
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
