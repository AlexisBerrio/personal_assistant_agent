from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.assistant_personal.application.intent_router import IntentResult, IntentRouter

load_dotenv()


class LLMIntentRouter(IntentRouter):
    """Router de intención basado en un modelo."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        super().__init__()
        self.model = model or os.getenv("OPENAI_MODEL")
        self.client = None
        if OpenAI is not None:
            try:
                self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
            except Exception:
                self.client = None

    def route(self, message: str) -> IntentResult:
        if not message or not message.strip():
            return IntentResult(action="clarify", payload={"message": "No pude entender la petición."})

        if self.client is None or not getattr(self.client, "api_key", None):
            return super().route(message)

        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Clasifica el mensaje del usuario en una de estas acciones: "
                            "list_tasks, create_task, complete_task o clarify. "
                            "Devuelve solo un JSON con las claves action y title."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                temperature=0,
            )
            content = response.output_text.strip()
            parsed = self._parse_json(content)
            action = parsed.get("action", "clarify")
            title = parsed.get("title")
            return IntentResult(action=action, payload={"title": title} if title else {})
        except Exception:
            return super().route(message)

    def _parse_json(self, content: str) -> dict[str, Any]:
        import json

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
