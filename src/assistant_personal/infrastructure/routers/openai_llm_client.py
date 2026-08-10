from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.assistant_personal.domain.entities import IntentAction, IntentDecision

load_dotenv()


class OpenAILLMRouterClient:
    """Cliente LLM para clasificación de intenciones y respuestas generales del router."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.getenv("OPENAI_MODEL")
        api_key_value = api_key or os.getenv("OPENAI_API_KEY")

        if not api_key_value:
            raise RuntimeError("OPENAI_API_KEY is required")
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is required")

        try:
            self.client = OpenAI(api_key=api_key_value)
        except Exception as exc:
            raise RuntimeError("Unable to initialize OpenAI client") from exc

    def classify_intent(self, text: str) -> IntentDecision:
        self._ensure_ready()
        system_prompt = (
            "Eres un clasificador de intenciones para un asistente personal. "
            "Tu tarea es decidir la acción más adecuada para el mensaje del usuario. "
            "Devuelve únicamente un JSON válido con las claves action, confidence, reasoning, source y payload. "
            "Las acciones permitidas son: list_tasks, create_task, complete_task, delete_task, ask_knowledge_base, small_talk, clarify."
        )
        payload = self._invoke_model(system_prompt, text)
        parsed = self._parse_response(payload)
        return self._build_decision(parsed)

    def answer_general_knowledge(self, query: str) -> str:
        self._ensure_ready()
        system_prompt = (
            "Responde de forma breve, directa y útil a preguntas generales de conocimiento. "
            "No uses listas largas ni explicaciones innecesarias."
        )
        return self._invoke_model(system_prompt, query).strip()

    def _ensure_ready(self) -> None:
        if self.client is None:
            raise RuntimeError("OpenAI client unavailable")
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is required")

    def _invoke_model(self, system_prompt: str, user_prompt: str) -> str:
        if hasattr(self.client, "responses"):
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

    def _build_decision(self, parsed: dict[str, Any]) -> IntentDecision:
        action = parsed.get("action", "clarify")
        payload = parsed.get("payload", {}) or {}
        confidence = float(parsed.get("confidence", 0.5))
        reasoning = parsed.get("reasoning")
        source = parsed.get("source", "llm")

        if isinstance(action, str):
            try:
                action_enum = IntentAction(action)
            except ValueError:
                action_enum = IntentAction.CLARIFY
        else:
            action_enum = IntentAction.CLARIFY

        return IntentDecision(
            action=action_enum,
            payload=payload,
            confidence=confidence,
            reasoning=reasoning,
            source=source,
        )

    def _parse_response(self, content: str) -> dict[str, Any]:
        if not content:
            raise RuntimeError("OpenAI returned an empty response")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI returned invalid JSON") from exc
