from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.entities import (
    ConversationRoute,
    IntentAction,
    IntentClassification,
    UserProfileExtraction,
)


class _OpenAITextClient:
    """Cliente base para compartir invocación y parseo estructurado con OpenAI."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        provider = (settings.llm_provider or "openai").strip().lower()
        base_url: str | None = None

        self._use_responses_api = provider != "ollama"

        if provider == "ollama":
            self.model = model or settings.ollama_model
            # Ollama no valida la API key, pero el SDK de OpenAI exige que venga un string no vacío.
            api_key_value = api_key or "ollama"
            base_url = settings.ollama_base_url
            if not self.model:
                raise RuntimeError("OLLAMA_MODEL is required when LLM_PROVIDER=ollama")
        else:
            self.model = model or settings.openai_model
            api_key_value = api_key or (settings.openai_api_key.get_secret_value() if settings.openai_api_key else None)
            if not api_key_value:
                raise RuntimeError("OPENAI_API_KEY is required")
            if not self.model:
                raise RuntimeError("OPENAI_MODEL is required")

        try:
            self.client = OpenAI(api_key=api_key_value, base_url=base_url)
        except Exception as exc:
            raise RuntimeError("Unable to initialize OpenAI client") from exc

    def _build_user_prompt(self, message: str, context: str | None = None) -> str:
        if context:
            return f"Mensaje del usuario: {message}\nContexto reciente: {context}"
        return f"Mensaje del usuario: {message}"

    def _ensure_ready(self) -> None:
        if self.client is None:
            raise RuntimeError("OpenAI client unavailable")
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is required")

    def _invoke_model(self, system_prompt: str, user_prompt: str) -> str:
        if getattr(self, "_use_responses_api", True) and hasattr(self.client, "responses"):
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            return getattr(response, "output_text", "") or ""

        if hasattr(self.client, "chat") and hasattr(self.client.chat, "completions"):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            return response.choices[0].message.content or ""

        raise RuntimeError("OpenAI client does not expose a supported API interface")

    def _parse_response(self, content: str) -> dict[str, Any]:
        if not content:
            raise RuntimeError("OpenAI returned an empty response")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            extracted = self._extract_json_object(content)
            if extracted is not None:
                return extracted
            raise RuntimeError("OpenAI returned invalid JSON") from exc

    def _extract_json_object(self, content: str) -> dict[str, Any] | None:
        cleaned = (content or "").strip()
        if not cleaned:
            return None

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3:
                cleaned = "\n".join(lines[1:-1]).strip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        candidate = cleaned[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


class OpenAIIntentClassifier(_OpenAITextClient):
    """Clasificador para enrutar la conversación."""

    def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        self._ensure_ready()
        system_prompt = (
            "Eres un clasificador de intenciones para un asistente personal. "
            "Tu tarea es enrutar la conversación con una salida estructurada. "
            "Usa el contexto de memoria de corto plazo si está disponible para entender referencias "
            "al usuario o conversaciones previas. "
            "Devuelve únicamente un JSON válido con las claves route, intent, confidence, reasoning, "
            "source y payload. "
            "Rutas permitidas: general_knowledge, orchestrator, clarify. "
            "Intenciones permitidas (cuando route sea orchestrator): list_tasks, create_task, "
            "complete_task, delete_task. "
            "Si route=orchestrator e intent=create_task, payload.title es obligatorio y debe ser "
            "específico (sin valores genéricos como 'Tarea nueva'). "
            "Si no puedes inferir un título específico incluso usando contexto reciente, usa route=clarify. "
            "Si no hay suficiente información para ejecutar una acción concreta, usa route=clarify."
        )
        payload = self._invoke_model(system_prompt, self._build_user_prompt(text, context))
        parsed = self._parse_response(payload)
        return self._build_classification(parsed)

    def _build_classification(self, parsed: dict[str, Any]) -> IntentClassification:
        raw_route = parsed.get("route", ConversationRoute.CLARIFY.value)
        raw_intent = parsed.get("intent")
        confidence = float(parsed.get("confidence", 0.0))
        reasoning = parsed.get("reasoning")
        payload = parsed.get("payload", {}) or {}
        source = parsed.get("source", "llm")

        try:
            route = ConversationRoute(raw_route)
        except ValueError:
            route = ConversationRoute.CLARIFY

        intent: IntentAction | None = None
        if isinstance(raw_intent, str):
            try:
                intent = IntentAction(raw_intent)
            except ValueError:
                intent = None

        if route == ConversationRoute.ORCHESTRATOR and intent is None:
            route = ConversationRoute.CLARIFY

        return IntentClassification(
            route=route,
            intent=intent,
            confidence=confidence,
            reasoning=reasoning,
            payload=payload,
            source=source,
        )


class OpenAIGeneralKnowledgeResponder(_OpenAITextClient):
    """Componente de respuesta para conocimiento general sin invocar al agente principal."""

    def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        self._ensure_ready()
        system_prompt = (
            "Responde de forma breve, directa y útil a preguntas generales de conocimiento. "
            "Usa el contexto de memoria de corto plazo si está disponible para responder a "
            "referencias al usuario o conversaciones previas. "
            "No uses listas largas ni explicaciones innecesarias."
        )
        return self._invoke_model(system_prompt, self._build_user_prompt(query, context)).strip()


class OpenAIProfileFactExtractor(_OpenAITextClient):
    """Extractor estructurado de hechos de perfil para memoria de corto plazo."""

    def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        self._ensure_ready()
        system_prompt = (
            "Eres un extractor de memoria de perfil para un asistente personal. "
            "Tu tarea es detectar hechos del usuario que puedan almacenarse como contexto persistente. "
            "Devuelve únicamente un JSON válido con la clave profile_facts, donde cada elemento tiene "
            "key, value y confidence. "
            "No uses reglas manuales ni expresiones regulares; infiere los hechos desde el lenguaje natural."
        )
        payload = self._invoke_model(system_prompt, self._build_user_prompt(text, context))
        parsed = self._parse_response(payload)
        return UserProfileExtraction.model_validate(parsed)


class OpenAILLMRouterClient:
    """Fachada de compatibilidad para el router híbrido."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.intent_classifier = OpenAIIntentClassifier(model=model, api_key=api_key)
        self.knowledge_responder = OpenAIGeneralKnowledgeResponder(model=model, api_key=api_key)
        self.profile_extractor = OpenAIProfileFactExtractor(model=model, api_key=api_key)

    def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        return self.intent_classifier.classify_intent(text, context=context)

    def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        return self.knowledge_responder.answer_general_knowledge(query, context=context)

    def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        return self.profile_extractor.extract_profile_facts(text, context=context)
