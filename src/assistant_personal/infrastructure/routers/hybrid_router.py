from __future__ import annotations

from typing import Any, Protocol

from src.assistant_personal.domain.entities import (
    ConversationRoute,
    IntentAction,
    IntentClassification,
    IntentDecision,
    UserProfileExtraction,
)
from src.assistant_personal.infrastructure.observabilidad import get_logger, get_tracer
from src.assistant_personal.infrastructure.routers.openai_llm_client import (
    OpenAIGeneralKnowledgeResponder,
    OpenAIIntentClassifier,
    OpenAIProfileFactExtractor,
    OpenAISmallTalkResponder,
)

logger = get_logger(__name__)
tracer = get_tracer(__name__)

EXACT_LIST_TASKS_COMMANDS = {
    "lista mis tareas",
    "lista mis tareas pendientes",
    "listar mis tareas",
    "listar mis tareas pendientes",
    "muestra mis tareas",
    "muestra mis tareas pendientes",
    "mostrar mis tareas",
    "mostrar mis tareas pendientes",
    "ver mis tareas",
    "ver mis tareas pendientes",
    "mis tareas",
    "mis tareas pendientes",
    "que tareas tengo",
    "qué tareas tengo",
    "que tareas tengo pendientes",
    "qué tareas tengo pendientes",
    "cuales son mis tareas",
    "cuáles son mis tareas",
    "cuales son mis tareas pendientes",
    "cuáles son mis tareas pendientes",
    "hola lista mis tareas",
    "hola lista mis tareas pendientes",
    "hola mostrar mis tareas",
    "hola mostrar mis tareas pendientes",
    "hola que tareas tengo",
    "hola qué tareas tengo",
    "hola que tareas tengo pendientes",
    "hola qué tareas tengo pendientes",
    "buenas lista mis tareas",
    "buenas lista mis tareas pendientes",
    "buenas mostrar mis tareas",
    "buenas mostrar mis tareas pendientes",
}

EXPLICIT_CREATE_TASK_PREFIXES = ("crear tarea:", "nueva tarea:")


class IntentClassifier(Protocol):
    """Contrato de clasificación de intención y ruta de conversación.

    Subconjunto async del port `LLMClient` (domain/repositories/llm_client.py) — async
    para no bloquear el event loop durante la llamada de red al LLM.
    """

    async def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        ...


class GeneralKnowledgeResponder(Protocol):
    """Contrato para resolver preguntas de conocimiento general. Ver `IntentClassifier`."""

    async def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        ...


class ProfileFactExtractor(Protocol):
    """Contrato para extracción estructurada de hechos de perfil. Ver `IntentClassifier`."""

    async def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        ...


class SmallTalkResponder(Protocol):
    """Contrato para generar la respuesta a small talk. Ver `IntentClassifier`."""

    async def answer_small_talk(self, text: str, context: str | None = None) -> str:
        ...


class ProductionIntentRouter:
    """Router híbrido para producción: reglas rápidas + LLM estructurado + fallback seguro."""

    def __init__(
        self,
        llm_client: IntentClassifier | None = None,
        knowledge_responder: GeneralKnowledgeResponder | None = None,
        profile_extractor: ProfileFactExtractor | None = None,
        small_talk_responder: SmallTalkResponder | None = None,
        confidence_threshold: float = 0.7,
    ):
        self._intent_classifier = llm_client or OpenAIIntentClassifier()
        self._knowledge_responder = knowledge_responder or OpenAIGeneralKnowledgeResponder()
        self._profile_extractor = profile_extractor or OpenAIProfileFactExtractor()
        self._small_talk_responder = small_talk_responder or OpenAISmallTalkResponder()
        self._confidence_threshold = confidence_threshold
        self.last_llm_metadata: dict[str, Any] | None = None

    async def route(self, user_message: str, context: str | None = None) -> IntentDecision:
        """Envoltorio del span `router.clasificar` alrededor de `_route`, para no
        re-indentar toda la lógica de reglas/LLM bajo un único `with`."""
        with tracer.start_as_current_span("router.clasificar") as span:
            decision = await self._route(user_message, context)
            span.set_attribute("accion", str(decision.action))
            span.set_attribute("fuente", decision.source)
            span.set_attribute("confianza", decision.confidence)
            return decision

    async def _route(self, user_message: str, context: str | None = None) -> IntentDecision:
        clean_text = (user_message or "").strip()
        self.last_llm_metadata = None

        if not clean_text:
            return self._build_decision(
                action=IntentAction.CLARIFY,
                payload={"message": "El mensaje está vacío."},
                confidence=1.0,
                source="rule",
                reasoning="Entrada vacía detectada por regla.",
            )

        fast_decision = self._check_fast_rules(clean_text)
        if fast_decision:
            logger.info("router_intencion_resuelta_por_regla", accion=fast_decision.action)
            if fast_decision.action == IntentAction.SMALL_TALK and "reply" not in fast_decision.payload:
                reply = await self._generate_small_talk_reply(clean_text, context)
                fast_decision = self._build_decision(
                    action=IntentAction.SMALL_TALK,
                    payload={**fast_decision.payload, "reply": reply},
                    confidence=fast_decision.confidence,
                    source=fast_decision.source,
                    reasoning=fast_decision.reasoning,
                )
            return fast_decision

        try:
            classification = await self._intent_classifier.classify_intent(clean_text, context=context)
            self.last_llm_metadata = getattr(self._intent_classifier, "last_call_metadata", None)
        except Exception as exc:
            logger.warning("router_clasificador_llm_fallo", error=str(exc))
            return self._build_decision(
                action=IntentAction.CLARIFY,
                payload={"message": "No pude interpretar tu solicitud en este momento. ¿Podrías reformularla?"},
                confidence=0.0,
                source="fallback",
                reasoning="Fallo técnico del clasificador; fallback seguro a clarify.",
            )

        if classification.confidence < self._confidence_threshold:
            return self._build_decision(
                action=IntentAction.CLARIFY,
                payload={"message": "No tengo suficiente certeza para actuar. ¿Podrías dar más detalles?"},
                confidence=classification.confidence,
                source="llm",
                reasoning="Clasificación con confianza baja.",
            )

        if classification.route == ConversationRoute.GENERAL_KNOWLEDGE:
            answer = await self._knowledge_responder.answer_general_knowledge(clean_text, context=context)
            return IntentDecision(
                action=IntentAction.ASK_KNOWLEDGE_BASE,
                payload={"query": clean_text, "answer": answer},
                confidence=classification.confidence,
                source="llm",
                reasoning=classification.reasoning or "Pregunta de conocimiento general.",
            )

        if classification.route == ConversationRoute.SMALL_TALK:
            reply = await self._generate_small_talk_reply(clean_text, context)
            return self._build_decision(
                action=IntentAction.SMALL_TALK,
                payload={"reply": reply},
                confidence=classification.confidence,
                source="llm",
                reasoning=classification.reasoning or "Saludo o charla casual detectada por el clasificador.",
            )

        if classification.route == ConversationRoute.ORCHESTRATOR and classification.intent:
            if self._needs_clarification(classification):
                return self._build_decision(
                    action=IntentAction.CLARIFY,
                    payload={
                        "message": "Entiendo la acción, pero me falta una referencia concreta. ¿Podrías especificarla?"
                    },
                    confidence=classification.confidence,
                    source="llm",
                    reasoning="La intención requiere más datos para ejecutarse.",
                )
            return self._build_decision(
                action=classification.intent,
                payload=classification.payload,
                confidence=classification.confidence,
                source="llm",
                reasoning=classification.reasoning,
            )

        return self._build_decision(
            action=IntentAction.CLARIFY,
            payload={"message": "No pude entender tu solicitud con certeza. ¿Podrías ser más específico?"},
            confidence=0.0,
            source="fallback",
            reasoning="Ninguna regla coincidió y el LLM falló o devolvió baja confianza.",
        )

    async def _generate_small_talk_reply(self, text: str, context: str | None) -> str:
        try:
            return await self._small_talk_responder.answer_small_talk(text, context=context)
        except Exception as exc:
            logger.warning("router_small_talk_llm_fallo", error=str(exc))
            return "¡Hola! ¿En qué te puedo ayudar?"

    def _build_decision(
        self,
        *,
        action: IntentAction,
        payload: dict[str, object],
        confidence: float,
        source: str,
        reasoning: str | None = None,
    ) -> IntentDecision:
        return IntentDecision(
            action=action,
            payload=payload,
            confidence=confidence,
            source=source,
            reasoning=reasoning,
        )

    def _check_fast_rules(self, text: str) -> IntentDecision | None:
        text_lower = text.lower().strip()

        if text_lower in ["/start", "/help", "ayuda"]:
            return IntentDecision(
                action=IntentAction.SMALL_TALK,
                payload={"type": "help"},
                confidence=1.0,
                source="rule",
            )

        if self._is_pure_small_talk(text) or self._is_pure_farewell(text):
            # Sin "reply" en el payload: `route()` genera la respuesta con el LLM antes de
            # devolver la decisión.
            return IntentDecision(
                action=IntentAction.SMALL_TALK,
                payload={"text": text},
                confidence=0.95,
                source="rule",
            )

        if self._is_explicit_list_tasks_command(text):
            return IntentDecision(
                action=IntentAction.LIST_TASKS,
                payload={},
                confidence=0.99,
                source="rule",
                reasoning="Comando explícito de listar tareas detectado por regla de alta precisión.",
            )

        if self._match_explicit_create_task_command(text_lower):
            title = text_lower.split(":", 1)[1].strip().capitalize()
            return IntentDecision(
                action=IntentAction.CREATE_TASK,
                payload={"title": title},
                confidence=0.95,
                source="rule",
                reasoning="Sintaxis de creación explícita detectada.",
            )

        return None

    def _is_pure_small_talk(self, text: str) -> bool:
        # Normaliza signos comunes sin regex para reconocer solo saludos puros.
        normalized = self._normalize_fast_rule_text(text)

        return normalized in {"hola", "gracias", "buenos dias", "buen día", "buen dia", "buenas"}

    def _is_pure_farewell(self, text: str) -> bool:
        normalized = self._normalize_fast_rule_text(text)
        return normalized in {"adios", "adiós", "hasta luego", "hasta pronto", "nos vemos", "chao", "chau", "bye"}

    def _is_explicit_list_tasks_command(self, text: str) -> bool:
        normalized = self._normalize_fast_rule_text(text)
        return normalized in EXACT_LIST_TASKS_COMMANDS

    def _match_explicit_create_task_command(self, normalized_text: str) -> bool:
        if not normalized_text.startswith(EXPLICIT_CREATE_TASK_PREFIXES):
            return False
        title = normalized_text.split(":", 1)[1].strip() if ":" in normalized_text else ""
        return bool(title)

    def _normalize_fast_rule_text(self, text: str) -> str:
        normalized = text.lower().strip()
        for char in [",", ".", "!", "?", ";", ":", "¿", "¡"]:
            normalized = normalized.replace(char, " ")
        return " ".join(normalized.split())

    async def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        if not self._profile_extractor:
            return UserProfileExtraction()
        try:
            return await self._profile_extractor.extract_profile_facts(text, context=context)
        except Exception as exc:
            logger.warning("router_extraccion_perfil_fallo", error=str(exc))
            return UserProfileExtraction()

    def _needs_clarification(self, classification: IntentClassification) -> bool:
        if classification.route != ConversationRoute.ORCHESTRATOR:
            return False
        if classification.payload.get("needs_clarification") is True:
            return True

        if classification.intent in {IntentAction.DELETE_TASK, IntentAction.COMPLETE_TASK}:
            task_ref = (
                classification.payload.get("task_id")
                or classification.payload.get("task_title")
                or classification.payload.get("task_reference")
            )
            if not task_ref:
                return True

        if classification.intent == IntentAction.CREATE_TASK:
            title = classification.payload.get("title")
            if not isinstance(title, str) or not title.strip():
                return True
            if title.strip().lower() in {"tarea nueva", "nueva tarea", "task", "new task"}:
                return True

        return False
