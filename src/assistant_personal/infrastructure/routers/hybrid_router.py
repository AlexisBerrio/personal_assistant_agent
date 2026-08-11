from __future__ import annotations

import logging
from typing import Optional, Protocol

from src.assistant_personal.domain.entities import (
    ConversationRoute,
    IntentAction,
    IntentClassification,
    IntentDecision,
    UserProfileExtraction,
)
from src.assistant_personal.infrastructure.routers.openai_llm_client import (
    OpenAIGeneralKnowledgeResponder,
    OpenAIIntentClassifier,
    OpenAIProfileFactExtractor,
)

logger = logging.getLogger(__name__)


class IntentClassifier(Protocol):
    """Contrato de clasificación de intención y ruta de conversación."""

    def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        ...


class GeneralKnowledgeResponder(Protocol):
    """Contrato para resolver preguntas de conocimiento general."""

    def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        ...


class ProfileFactExtractor(Protocol):
    """Contrato para extracción estructurada de hechos de perfil."""

    def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        ...


class ProductionIntentRouter:
    """Router híbrido para producción: reglas rápidas + LLM estructurado + fallback seguro."""

    def __init__(
        self,
        llm_client: Optional[IntentClassifier] = None,
        knowledge_responder: Optional[GeneralKnowledgeResponder] = None,
        profile_extractor: Optional[ProfileFactExtractor] = None,
        confidence_threshold: float = 0.7,
    ):
        self._intent_classifier = llm_client or OpenAIIntentClassifier()
        self._knowledge_responder = knowledge_responder or OpenAIGeneralKnowledgeResponder()
        self._profile_extractor = profile_extractor or OpenAIProfileFactExtractor()
        self._confidence_threshold = confidence_threshold

    def route(self, user_message: str, context: str | None = None) -> IntentDecision:
        clean_text = (user_message or "").strip()

        if not clean_text:
            return IntentDecision(
                action=IntentAction.CLARIFY,
                payload={"message": "El mensaje está vacío."},
                confidence=1.0,
                source="rule",
                reasoning="Entrada vacía detectada por regla.",
            )

        fast_decision = self._check_fast_rules(clean_text)
        if fast_decision:
            logger.info("[Router] Intención resuelta vía Regla: %s", fast_decision.action)
            return fast_decision

        try:
            classification = self._intent_classifier.classify_intent(clean_text, context=context)
        except Exception as exc:
            logger.warning("[Router] El clasificador LLM falló: %s", exc)
            return IntentDecision(
                action=IntentAction.CLARIFY,
                payload={"message": "No pude interpretar tu solicitud en este momento. ¿Podrías reformularla?"},
                confidence=0.0,
                source="fallback",
                reasoning="Fallo técnico del clasificador; fallback seguro a clarify.",
            )

        if classification.confidence < self._confidence_threshold:
            return IntentDecision(
                action=IntentAction.CLARIFY,
                payload={"message": "No tengo suficiente certeza para actuar. ¿Podrías dar más detalles?"},
                confidence=classification.confidence,
                source="llm",
                reasoning="Clasificación con confianza baja.",
            )

        if classification.route == ConversationRoute.GENERAL_KNOWLEDGE:
            answer = self._knowledge_responder.answer_general_knowledge(clean_text, context=context)
            return IntentDecision(
                action=IntentAction.ASK_KNOWLEDGE_BASE,
                payload={"query": clean_text, "answer": answer},
                confidence=classification.confidence,
                source="llm",
                reasoning=classification.reasoning or "Pregunta de conocimiento general.",
            )

        if classification.route == ConversationRoute.ORCHESTRATOR and classification.intent:
            if self._needs_clarification(classification):
                return IntentDecision(
                    action=IntentAction.CLARIFY,
                    payload={"message": "Entiendo la acción, pero me falta una referencia concreta. ¿Podrías especificarla?"},
                    confidence=classification.confidence,
                    source="llm",
                    reasoning="La intención requiere más datos para ejecutarse.",
                )
            return IntentDecision(
                action=classification.intent,
                payload=classification.payload,
                confidence=classification.confidence,
                source="llm",
                reasoning=classification.reasoning,
            )

        return IntentDecision(
            action=IntentAction.CLARIFY,
            payload={"message": "No pude entender tu solicitud con certeza. ¿Podrías ser más específico?"},
            confidence=0.0,
            source="fallback",
            reasoning="Ninguna regla coincidió y el LLM falló o devolvió baja confianza.",
        )

    def _check_fast_rules(self, text: str) -> Optional[IntentDecision]:
        text_lower = text.lower().strip()

        if text_lower in ["/start", "/help", "ayuda"]:
            return IntentDecision(
                action=IntentAction.SMALL_TALK,
                payload={"type": "help"},
                confidence=1.0,
                source="rule",
            )

        if self._is_pure_small_talk(text):
            return IntentDecision(
                action=IntentAction.SMALL_TALK,
                payload={"text": text, "reply": "¡Hola! Estoy bien, gracias. ¿En qué te puedo ayudar hoy?"},
                confidence=0.95,
                source="rule",
            )

        if text_lower.startswith(("crear tarea:", "nueva tarea:")):
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
        normalized = text.lower().strip()
        for char in [",", ".", "!", "?", ";", ":", "¿", "¡"]:
            normalized = normalized.replace(char, " ")
        normalized = " ".join(normalized.split())

        return normalized in {"hola", "gracias", "buenos dias", "buen día", "buen dia", "buenas"}

    def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        if not self._profile_extractor:
            return UserProfileExtraction()
        try:
            return self._profile_extractor.extract_profile_facts(text, context=context)
        except Exception as exc:
            logger.warning("[Router] No se pudieron extraer hechos de perfil: %s", exc)
            return UserProfileExtraction()

    def _needs_clarification(self, classification: IntentClassification) -> bool:
        if classification.route != ConversationRoute.ORCHESTRATOR:
            return False
        if classification.payload.get("needs_clarification") is True:
            return True

        if classification.intent in {IntentAction.DELETE_TASK, IntentAction.COMPLETE_TASK}:
            task_ref = classification.payload.get("task_id") or classification.payload.get("task_title") or classification.payload.get("task_reference")
            if not task_ref:
                return True

        return False
