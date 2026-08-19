from __future__ import annotations

import json
import time
from typing import Any

from openai import AsyncOpenAI

from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.entities import IntentClassification, UserProfileExtraction
from src.assistant_personal.infrastructure.prompts.loader import LoadedPrompt, load_prompt


class _OpenAITextClient:
    """Cliente base para compartir invocación y parseo estructurado con OpenAI."""

    # True en subclases cuyo prompt le pide al modelo devolver JSON (clasificación, extracción
    # de perfil) — activa `response_format={"type": "json_object"}` en `_invoke_model`, que le
    # exige a la API rechazar cualquier salida que no sea JSON sintácticamente válido. `False`
    # para `OpenAIGeneralKnowledgeResponder`: su prompt pide texto libre, y la API de OpenAI
    # exige que la palabra "json" aparezca en el prompt para aceptar ese modo — forzarlo ahí
    # rompería la respuesta en texto plano.
    _expects_json_response: bool = False

    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        provider = (settings.llm_provider or "openai").strip().lower()
        base_url: str | None = None

        self._use_responses_api = provider != "ollama"
        self.last_call_metadata: dict[str, Any] | None = None

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
            self.client = AsyncOpenAI(api_key=api_key_value, base_url=base_url)
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

    async def _invoke_model(self, system_prompt: LoadedPrompt, user_prompt: str) -> str:
        """Invoca el modelo (async, vía `AsyncOpenAI`: no bloquea el event loop durante la
        llamada de red — ver domain/repositories/llm_client.py) y registra en
        `self.last_call_metadata` los campos de observabilidad de §A.5 (`modelo`,
        `tokens_entrada`, `tokens_salida`, `latencia_ms_llm`) más `prompt_version` (§A.8, ítem
        2.2) para que el llamador (el router) los pueda leer después de cada invocación real."""
        started_at = time.monotonic()

        if getattr(self, "_use_responses_api", True) and hasattr(self.client, "responses"):
            response = await self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt.text},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            usage = getattr(response, "usage", None)
            self._record_call_metadata(
                started_at,
                prompt_version=system_prompt.identifier,
                tokens_entrada=getattr(usage, "input_tokens", None),
                tokens_salida=getattr(usage, "output_tokens", None),
            )
            return getattr(response, "output_text", "") or ""

        if hasattr(self.client, "chat") and hasattr(self.client.chat, "completions"):
            extra_kwargs: dict[str, Any] = {}
            if self._expects_json_response:
                extra_kwargs["response_format"] = {"type": "json_object"}
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt.text},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                **extra_kwargs,
            )
            usage = getattr(response, "usage", None)
            self._record_call_metadata(
                started_at,
                prompt_version=system_prompt.identifier,
                tokens_entrada=getattr(usage, "prompt_tokens", None),
                tokens_salida=getattr(usage, "completion_tokens", None),
            )
            return response.choices[0].message.content or ""

        raise RuntimeError("OpenAI client does not expose a supported API interface")

    def _record_call_metadata(
        self, started_at: float, *, prompt_version: str, tokens_entrada: int | None, tokens_salida: int | None
    ) -> None:
        self.last_call_metadata = {
            "modelo": self.model,
            "prompt_version": prompt_version,
            "tokens_entrada": tokens_entrada,
            "tokens_salida": tokens_salida,
            "latencia_ms_llm": int((time.monotonic() - started_at) * 1000),
        }

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

    _expects_json_response = True

    async def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        self._ensure_ready()
        system_prompt = load_prompt("router/classify_intent")
        payload = await self._invoke_model(system_prompt, self._build_user_prompt(text, context))
        parsed = self._parse_response(payload)
        return self._build_classification(parsed)

    def _build_classification(self, parsed: dict[str, Any]) -> IntentClassification:
        """Valida la salida cruda del LLM directamente con Pydantic (§A.8, ítem 2.1).

        Única tolerancia deliberada: `payload: null` se normaliza a `{}` (un capricho común
        del LLM que el tipo `dict[str, Any]` no aceptaría tal cual). Todo lo demás —enums
        desconocidos en `route`/`intent`, `confidence` fuera de `[0, 1]`, campos ausentes— se
        deja en manos de `IntentClassification.model_validate`, que levanta `ValidationError`.

        Política única ante salida inválida: esa excepción no se captura aquí. Sube hasta
        `ProductionIntentRouter.route()`, que ya tiene un `except Exception` que degrada a
        `route=clarify, source="fallback"` — el mismo camino para JSON malformado, esquema
        inválido o cualquier otro fallo de la respuesta del LLM. Una sola política, no dos.
        """
        normalized = dict(parsed)
        if normalized.get("payload") is None:
            normalized["payload"] = {}
        return IntentClassification.model_validate(normalized)


class OpenAIGeneralKnowledgeResponder(_OpenAITextClient):
    """Componente de respuesta para conocimiento general sin invocar al agente principal."""

    async def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        self._ensure_ready()
        system_prompt = load_prompt("router/general_knowledge")
        answer = await self._invoke_model(system_prompt, self._build_user_prompt(query, context))
        return answer.strip()


class OpenAIProfileFactExtractor(_OpenAITextClient):
    """Extractor estructurado de hechos de perfil para memoria de corto plazo."""

    _expects_json_response = True

    async def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        self._ensure_ready()
        system_prompt = load_prompt("router/extract_profile_facts")
        payload = await self._invoke_model(system_prompt, self._build_user_prompt(text, context))
        parsed = self._parse_response(payload)
        return UserProfileExtraction.model_validate(parsed)


class OpenAILLMRouterClient:
    """Implementación del port `LLMClient` (domain/repositories/llm_client.py) que unifica los
    tres componentes en un único cliente, para consumidores que prefieren una sola dependencia
    en vez de las tres separadas que usa `ProductionIntentRouter`."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.intent_classifier = OpenAIIntentClassifier(model=model, api_key=api_key)
        self.knowledge_responder = OpenAIGeneralKnowledgeResponder(model=model, api_key=api_key)
        self.profile_extractor = OpenAIProfileFactExtractor(model=model, api_key=api_key)

    async def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        return await self.intent_classifier.classify_intent(text, context=context)

    async def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        return await self.knowledge_responder.answer_general_knowledge(query, context=context)

    async def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        return await self.profile_extractor.extract_profile_facts(text, context=context)
