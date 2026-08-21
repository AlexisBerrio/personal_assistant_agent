from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any

import structlog

from src.assistant_personal.application.memory.agent_context import AgentContext
from src.assistant_personal.application.memory.context_builder import ContextBuilder
from src.assistant_personal.domain.repositories.long_term_memory_repository import LongTermMemoryRepository
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.observabilidad import get_logger, get_tracer
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter
from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAISessionSummarizer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class TaskOrchestrator:
    """Orquesta una interacción simple entre router, guardrails y especialista."""

    def __init__(
        self,
        service: Any,
        router: Any = None,
        max_retries: int = 1,
        session_repository: SessionMemoryRepository | None = None,
        long_term_repository: LongTermMemoryRepository | None = None,
        context_builder: ContextBuilder | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        profile_confidence_threshold: float = 0.7,
    ) -> None:
        self.service = service
        self.router = router or ProductionIntentRouter()
        self.max_retries = max_retries
        self.session_repository = session_repository
        self.session_id = session_id or f"session-{uuid.uuid4()}"
        # Fijo en "default" hasta que exista multi-tenant real.
        self.tenant_id = tenant_id or "default"
        # Fijo en "default" hasta que exista identidad de usuario real (auth, Fase 6/8) — mismo
        # criterio que `tenant_id`.
        self.user_id = user_id or "default"
        self.profile_confidence_threshold = profile_confidence_threshold
        self.context = AgentContext(
            short_term_repository=self.session_repository,
            long_term_repository=long_term_repository,
            user_id=self.user_id,
            # Resumen incremental de sesión real por defecto — mismo criterio
            # que `self.router` arriba: se construye con OpenAI real salvo que el llamador
            # inyecte otra cosa (tests inyectan un `ContextBuilder()` sin summarizer).
            context_builder=context_builder or ContextBuilder(summarizer=OpenAISessionSummarizer()),
        )

    def handle_message(self, message: str) -> dict[str, Any]:
        return asyncio.run(self.handle_message_async(message))

    async def handle_message_async(self, message: str) -> dict[str, Any]:
        started_at = time.monotonic()
        # Cada turno es su propia "interacción" a efectos de observabilidad: un
        # request_id nuevo por turno, no reutilizado entre turnos del mismo CLI interactivo.
        # Si en el futuro esto se invoca dentro de una petición FastAPI ya instrumentada, esto
        # sobreescribe el request_id de la petición para los logs de la interacción — aceptable
        # hoy porque `TaskOrchestrator` no se usa todavía desde `app.py`.
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            with tracer.start_as_current_span("orquestador.ejecutar") as span:
                span.set_attribute("request_id", request_id)
                span.set_attribute("session_id", self.session_id)
                result = await self._handle_message(message, request_id=request_id, started_at=started_at)
                span.set_attribute("resultado_accion", str(result.get("action", "")))
                span.set_attribute("resultado_exito", bool(result.get("success", False)))
                return result
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
        # Resumen incremental de sesión: antes de armar el contexto de este
        # turno, comprime los turnos acumulados de turnos anteriores si ya llegaron al umbral.
        await self.context.maybe_summarize_session_async(session_id=self.session_id)
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
        """Emite el log de cierre de una interacción con sus campos mínimos, incluido
        `contexto_tokens`.

        Con estos campos se puede calcular coste por interacción y tasa de `clarify` sin
        instrumentación adicional. `tenant_id` queda fijo en "default" hasta que exista
        multi-tenant real; `modelo`/`tokens_*`/`latencia_ms_llm` quedan en None cuando la
        decisión se resolvió por regla y nunca se invocó al LLM. `prompt_version` identifica
        qué versión del prompt de sistema generó la decisión, para poder filtrar estas métricas
        por versión cuando se cambie la redacción de un prompt. `contexto_tokens` es el
        presupuesto medible: cuántos tokens (estimados) ocupó el contexto de sesión/perfil que
        se le mandó al LLM en este turno.
        """
        metadata = llm_metadata or {}
        logger.info(
            "interaccion_completada",
            request_id=request_id,
            session_id=self.session_id,
            tenant_id=self.tenant_id,
            intencion=intencion,
            confianza=confianza,
            uso_llm=uso_llm,
            modelo=metadata.get("modelo"),
            prompt_version=metadata.get("prompt_version"),
            tokens_entrada=metadata.get("tokens_entrada"),
            tokens_salida=metadata.get("tokens_salida"),
            latencia_ms_total=int((time.monotonic() - started_at) * 1000),
            latencia_ms_llm=metadata.get("latencia_ms_llm"),
            contexto_tokens=self.context.last_context_tokens,
            resultado=resultado,
        )

    async def _maybe_await(self, value: Any) -> Any:
        """Soporta routers síncronos y async: el port `LLMClient` es async de punta a punta en
        producción, pero muchos dobles de test siguen siendo síncronos — mismo patrón de
        despacho que `TaskService._invoke_repository_async`."""
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
                confidence = item.get("confidence", 0.8)
            else:
                key = getattr(item, "key", None)
                value = getattr(item, "value", None)
                confidence = getattr(item, "confidence", 0.8)
            if key and value is not None:
                facts.append({"key": str(key), "value": str(value), "confidence": float(confidence)})
        return facts

    async def _persist_profile_facts(self, facts: list[dict[str, Any]]) -> None:
        """Persiste en memoria de largo plazo — no en la de sesión, que es de
        corta vida y no es el almacén correcto para hechos de perfil estables. Solo se
        persisten los hechos cuya confianza supera `profile_confidence_threshold`: escribir todo
        lo que el usuario dice envenena el contexto de turnos futuros."""
        for fact in facts:
            if fact["confidence"] < self.profile_confidence_threshold:
                continue
            await self.context.long_term_memory.add_fact_async(
                fact["key"], fact["value"], confidence=fact["confidence"], source="llm_extraction"
            )

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

        if action == "delete_task":
            return "Tarea eliminada."

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

        if intent.action == "delete_task":
            task_id = intent.payload.get("task_id")
            if not task_id:
                raise ValueError("Guardrails: falta el identificador de tarea")
            result = await self._invoke_service("delete_task", task_id)
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
