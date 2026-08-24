from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from typing import Any

import structlog

from src.assistant_personal.application.agent.agent import Agent
from src.assistant_personal.application.memory.agent_context import AgentContext
from src.assistant_personal.application.memory.context_builder import ContextBuilder
from src.assistant_personal.domain.repositories.long_term_memory_repository import LongTermMemoryRepository
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.llm.openai_llm_client import OpenAISessionSummarizer
from src.assistant_personal.infrastructure.observabilidad import get_logger, get_tracer
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_PENDING_CONFIRMATION_KEY = "pending_confirmation"
_AFFIRMATIVE_CONFIRMATIONS = {
    "si", "sí", "s", "confirmo", "confirmado", "dale", "hazlo", "ok", "de acuerdo", "adelante", "claro", "yes",
}
_NEGATIVE_CONFIRMATIONS = {"no", "cancela", "cancelar", "no gracias", "mejor no", "detente"}


def _normalize_confirmation_text(text: str) -> str:
    normalized = text.lower().strip()
    for char in [",", ".", "!", "?", ";", ":", "¿", "¡"]:
        normalized = normalized.replace(char, " ")
    return " ".join(normalized.split())


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
        agent: Agent | None = None,
    ) -> None:
        self.service = service
        self.router = router or ProductionIntentRouter()
        self.agent = agent or Agent(mcp_client=service)
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

    def handle_message(self, message: str, request_id: str | None = None) -> dict[str, Any]:
        return asyncio.run(self.handle_message_async(message, request_id=request_id))

    async def handle_message_async(self, message: str, request_id: str | None = None) -> dict[str, Any]:
        started_at = time.monotonic()
        # Si el llamador ya tiene un request_id de la petición en curso (ej. `app.py`, que lo
        # genera en `RequestIdMiddleware` antes de invocar al orquestador), se reutiliza — así
        # los logs de esta interacción correlacionan con el resto de logs de esa misma petición
        # HTTP y con el `X-Request-ID` que ya viaja en la respuesta. Sin llamador (CLI), cada
        # turno sigue generando el suyo.
        request_id = request_id or str(uuid.uuid4())
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

        pending_confirmation = await self._get_pending_confirmation()
        if pending_confirmation is not None:
            normalized = _normalize_confirmation_text(message)
            if normalized in _AFFIRMATIVE_CONFIRMATIONS or normalized in _NEGATIVE_CONFIRMATIONS:
                # Regla rápida y gratis para el caso obvio.S in LLM cuando no hace falta.
                return await self._settle_pending_confirmation(
                    pending_confirmation,
                    confirmed=normalized in _AFFIRMATIVE_CONFIRMATIONS,
                    message=message, request_id=request_id, started_at=started_at,
                )

        peek_fast_rule_action = getattr(self.router, "peek_fast_rule_action", None)
        fast_action = peek_fast_rule_action(message) if peek_fast_rule_action else None

        if fast_action == "small_talk":
            # La regla rápida ya resuelve el saludo sin tocar el LLM clasificador
            # (`hybrid_router._check_fast_rules`) — extraer hechos de perfil de un saludo puro
            # no aporta nada, así que se salta del todo.
            intent = await self._maybe_await(self.router.route(message, context=context_summary))
        else:
            # Se mantiene el orden secuencial (no `gather`): `route()` debe poder ver, en este
            # mismo turno, los hechos que `_extract_profile_facts` acaba de persistir — un
            # mensaje que declara un dato y pregunta por él en la misma frase depende de eso.
            # Correr ambas llamadas en paralelo rompería esa garantía.
            profile_facts = await self._extract_profile_facts(message, context_summary)
            await self._persist_profile_facts(profile_facts)
            context_summary = await self.context.build_context_summary_async(session_id=self.session_id)
            intent = await self._maybe_await(self.router.route(message, context=context_summary))

        llm_metadata = getattr(self.router, "last_llm_metadata", None)
        uso_llm = intent.source == "llm"

        if pending_confirmation is not None and intent.action in ("confirm_pending_action", "cancel_pending_action"):
            return await self._settle_pending_confirmation(
                pending_confirmation,
                confirmed=intent.action == "confirm_pending_action",
                message=message, request_id=request_id, started_at=started_at,
            )

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
            result = await self._execute_with_retries(intent, message, context_summary)
            assistant_response = result.get("message") or self._format_public_message(intent.action, result)
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

    async def _get_pending_confirmation(self) -> dict[str, Any] | None:
        raw = await self.context.short_term_memory.get_item_async(_PENDING_CONFIRMATION_KEY, session_id=self.session_id)
        if not raw:
            return None
        try:
            parsed: dict[str, Any] = json.loads(raw)
            return parsed
        except json.JSONDecodeError:
            return None

    async def _clear_pending_confirmation(self) -> None:
        await self.context.short_term_memory.add_async(_PENDING_CONFIRMATION_KEY, "", session_id=self.session_id)

    async def _settle_pending_confirmation(
        self, pending: dict[str, Any], *, confirmed: bool, message: str, request_id: str, started_at: float
    ) -> dict[str, Any]:
        """Ejecuta o cancela una escritura irreversible pendiente de confirmación — sin volver
        a pasar por el agente. Punto único de salida tanto si la resolvió la regla rápida
        (`si`/`no` exactos) como si la resolvió `classify_intent` a partir del contexto
        (`confirm_pending_action`/`cancel_pending_action`, cualquier redacción natural)."""
        await self._clear_pending_confirmation()

        if not confirmed:
            response_message = "Entendido, no hice ningún cambio."
            await self.context.short_term_memory.add_turn_async(message, response_message, session_id=self.session_id)
            self._log_interaction(
                request_id=request_id, started_at=started_at,
                intencion="confirmation_cancelled", confianza=None, uso_llm=False, llm_metadata=None,
                resultado="confirmacion_cancelada",
            )
            return {"success": True, "action": "confirmation_cancelled", "message": response_message}

        agent_result = await self.agent.execute_confirmed_tool(pending["tool"], pending["arguments"])
        await self.context.short_term_memory.add_turn_async(message, agent_result.message, session_id=self.session_id)
        self._log_interaction(
            request_id=request_id, started_at=started_at,
            intencion="confirmation_confirmed", confianza=None, uso_llm=False, llm_metadata=None,
            resultado="success",
        )
        return {
            "success": True,
            "action": "confirmation_confirmed",
            "message": agent_result.message,
            "result": {"tool_calls": agent_result.tool_calls, "steps_used": agent_result.steps_used},
        }

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
            tasks = result.get("result") if isinstance(result, dict) else None
            if not tasks:
                return "No tienes tareas pendientes."
            lines = [f"- {task.get('title', 'Sin título')} ({task.get('status', 'Pending')})" for task in tasks]
            return "Tus tareas:\n" + "\n".join(lines)

        if action == "complete_task":
            return "Tarea completada."

        if action == "delete_task":
            return "Tarea eliminada."

        return str(result)

    async def _execute_with_retries(self, intent: Any, message: str, context: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._dispatch(intent, message, context)
            except ValueError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
        raise last_error or ValueError("No se pudo completar la acción")

    async def _dispatch(self, intent: Any, message: str, context: str) -> dict[str, Any]:
        """Despacha una acción ya clasificada.

        El camino barato (sin agente) solo aplica cuando el router ya tiene el 100% de lo
        necesario sin haber tenido que interpretar nada: `list_tasks` sin filtro, o `create_task`
        resuelto por una regla exacta. Un `create_task` que pasó por el clasificador LLM y podría
        traer atributos en lenguaje natural (prioridad, fecha, categoría...) tampoco toma el
        camino barato — igual que un `list_tasks` con un filtro de fecha/estado/negación descrito
        en lenguaje natural (`payload.filter_description`): la tool `listar_tareas` solo filtra
        por igualdad exacta de un único `estado`, así que decidir cómo traducir la descripción
        (una sola llamada, varias combinadas, o ninguna) requiere razonamiento del agente.
        """
        if intent.action == "list_tasks":
            if intent.payload.get("filter_description"):
                return await self._dispatch_to_agent(intent, message, context)
            tasks = await self._invoke_service("list_tasks")
            return {"success": True, "action": intent.action, "result": tasks}

        if intent.action == "create_task":
            if intent.source == "rule":
                title = intent.payload.get("title")
                if not title or not title.strip():
                    raise ValueError(
                        "Entiendo que quieres crear una tarea, pero me falta el título. ¿Qué tarea deseas crear?"
                    )
                result = await self._invoke_service("create_task", {"title": title})
                return {"success": True, "action": intent.action, "result": result}
            return await self._dispatch_to_agent(intent, message, context)

        if intent.action in ("complete_task", "delete_task", "multi_task"):
            return await self._dispatch_to_agent(intent, message, context)

        return {"success": False, "action": "clarify", "reason": "No se pudo ejecutar la acción"}

    async def _dispatch_to_agent(self, intent: Any, message: str, context: str) -> dict[str, Any]:
        agent_result = await self.agent.handle(message, context=context)
        if agent_result.pending_confirmation is not None:
            # No se ejecutó ninguna escritura todavía — queda pendiente hasta que el usuario
            # confirme en un turno posterior. Se guarda junto con la pregunta en lenguaje
            # natural (no solo tool/arguments): es lo que `classify_intent` va a leer desde
            # `context_summary` si la respuesta del usuario no matchea la regla rápida de
            # sí/no, para poder resolverla en cualquier redacción sin perder el hilo.
            pending_with_question = {**agent_result.pending_confirmation, "pregunta": agent_result.message}
            await self.context.short_term_memory.add_async(
                _PENDING_CONFIRMATION_KEY, json.dumps(pending_with_question), session_id=self.session_id
            )
            return {
                "success": True,
                "action": "needs_confirmation",
                "result": {"tool_calls": agent_result.tool_calls, "steps_used": agent_result.steps_used},
                "message": agent_result.message,
            }
        return {
            "success": True,
            "action": intent.action,
            "result": {"tool_calls": agent_result.tool_calls, "steps_used": agent_result.steps_used},
            "message": agent_result.message,
        }

    async def _invoke_service(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        async_method = getattr(self.service, f"{method_name}_async", None)
        if callable(async_method):
            return await async_method(*args, **kwargs)

        sync_method = getattr(self.service, method_name, None)
        if callable(sync_method):
            return sync_method(*args, **kwargs)

        raise AttributeError(f"El servicio no implementa '{method_name}'")
