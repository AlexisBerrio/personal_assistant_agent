from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.assistant_personal.domain.entities import IntentAction, IntentDecision

load_dotenv()


class OpenAILLMRouterClient:
    """Cliente simple para clasificar intenciones mediante OpenAI Responses API."""

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
        if self.client is None:
            raise RuntimeError("OpenAI client unavailable")
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is required")

        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Eres un clasificador de intenciones para un asistente personal. "
                        "Devuelve únicamente un JSON con las claves action, confidence, reasoning, source y payload. "
                        "Las acciones permitidas son: list_tasks, create_task, complete_task, delete_task, ask_knowledge_base, small_talk, clarify."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
        )

        parsed = self._parse_response(response.output_text)
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
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
