from __future__ import annotations

import logging
import re
from typing import Optional, Protocol

from src.assistant_personal.domain.entities import IntentAction, IntentDecision
from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAILLMRouterClient

logger = logging.getLogger(__name__)


class LLMStructuredClient(Protocol):
    """Interfaz para clientes LLM que soportan salida estructurada."""

    def classify_intent(self, text: str) -> IntentDecision:
        ...


class ProductionIntentRouter:
    """Router híbrido para producción: reglas rápidas + LLM estructurado + fallback seguro."""

    def __init__(self, llm_client: Optional[LLMStructuredClient] = None):
        self._llm_client = llm_client or OpenAILLMRouterClient()

    def route(self, user_message: str) -> IntentDecision:
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

        if self._llm_client:
            try:
                llm_decision = self._llm_client.classify_intent(clean_text)
                if llm_decision.confidence >= 0.7:
                    logger.info("[Router] Intención resuelta vía LLM (%s) con confianza %.2f", llm_decision.action, llm_decision.confidence)
                    return llm_decision
                logger.warning("[Router] LLM respondió con baja confianza (%.2f). Usando fallback.", llm_decision.confidence)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.error("[Router] Error llamando al LLM Router: %s", exc, exc_info=True)

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

        if any(token in text_lower for token in ["hola", "gracias", "buenos", "buenas", "como estás", "como te va", "qué tal"]):
            return IntentDecision(
                action=IntentAction.SMALL_TALK,
                payload={"text": text, "reply": "¡Hola! Estoy bien, gracias. ¿En qué te puedo ayudar hoy?"},
                confidence=0.95,
                source="rule",
            )

        if re.search(r"^\b(listar|ver|mostrar)\b", text_lower) and any(token in text_lower for token in ["tareas", "pendientes", "mis tareas", "qué tengo", "qué tareas"]):
            return IntentDecision(
                action=IntentAction.LIST_TASKS,
                confidence=1.0,
                source="rule",
                reasoning="Comando de listado detectado por regex.",
            )

        if re.search(r"^\b(completar|terminar|marcar|finalizar|cerrar)\b", text_lower):
            return IntentDecision(
                action=IntentAction.COMPLETE_TASK,
                payload={"task_id": None},
                confidence=0.85,
                source="rule",
                reasoning="Comando de finalización detectado.",
            )

        match_create_colon = re.search(r"^(crear|nueva)\s+tarea\s*:\s*(.+)$", text_lower)
        if match_create_colon:
            title = match_create_colon.group(2).strip().capitalize()
            return IntentDecision(
                action=IntentAction.CREATE_TASK,
                payload={"title": title},
                confidence=0.95,
                source="rule",
                reasoning="Sintaxis de creación explícita detectada.",
            )

        if re.search(r"^\b(crear|añadir|agregar|nueva|haz|hacer|recordar)\b", text_lower):
            title = self._extract_title(text)
            return IntentDecision(
                action=IntentAction.CREATE_TASK,
                payload={"title": title},
                confidence=0.9,
                source="rule",
                reasoning="Patrón de creación detectado por reglas heurísticas.",
            )

        if re.search(r"^\b(borrar|eliminar|quitar)\b", text_lower):
            return IntentDecision(
                action=IntentAction.DELETE_TASK,
                payload={"task_id": None},
                confidence=0.8,
                source="rule",
                reasoning="Comando de eliminación detectado.",
            )

        return None

    def _extract_title(self, message: str) -> str:
        cleaned = message.strip()
        for prefix in ["crear ", "añadir ", "agregar ", "nueva tarea ", "haz ", "hacer ", "recordar "]:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break

        cleaned = re.sub(r"^(una|un|la|el|las|los)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(tarea|actividad|recordatorio)\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned:
            return "Tarea nueva"
        if cleaned.lower().startswith("tarea"):
            return cleaned.capitalize()
        return f"Tarea {cleaned}".capitalize()
