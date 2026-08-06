from __future__ import annotations

from typing import Any

from src.assistant_personal.application.agent_context import AgentContext
from src.assistant_personal.application.intent_router import IntentRouter
from src.assistant_personal.application.prompt_engineering import PromptBuilder


class TaskOrchestrator:
    """Orquesta una interacción simple entre router, guardrails y especialista."""

    def __init__(self, service: Any, router: IntentRouter | None = None, max_retries: int = 1) -> None:
        self.service = service
        self.router = router or IntentRouter()
        self.max_retries = max_retries
        self.prompt_builder = PromptBuilder()
        self.context = AgentContext()

    def handle_message(self, message: str) -> dict[str, Any]:
        if not message or not message.strip():
            return {
                "success": False,
                "action": "clarify",
                "reason": "Guardrails: el mensaje está vacío.",
            }

        self.context.short_term_memory.add("user_message", message)
        prompt = self.prompt_builder.build_user_prompt(message)
        context_summary = self.context.build_context_summary()
        intent = self.router.route(message)
        if intent.action == "clarify":
            return {"success": False, "action": "clarify", "reason": intent.payload.get("message", "No se pudo interpretar")}

        try:
            result = self._execute_with_retries(intent)
            assistant_response = str(result)
            self.context.short_term_memory.add_turn(message, assistant_response)
            return {
                **result,
                "prompt": prompt,
                "context": context_summary,
            }
        except ValueError as exc:
            assistant_response = str(exc)
            self.context.short_term_memory.add_turn(message, assistant_response)
            return {"success": False, "action": intent.action, "reason": str(exc), "prompt": prompt, "context": context_summary}

    def _execute_with_retries(self, intent: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._dispatch(intent)
            except ValueError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
        raise last_error or ValueError("No se pudo completar la acción")

    def _dispatch(self, intent: Any) -> dict[str, Any]:
        if intent.action == "list_tasks":
            tasks = self.service.list_tasks()
            return {"success": True, "action": intent.action, "result": tasks}

        if intent.action == "create_task":
            title = intent.payload.get("title", "Tarea nueva")
            task_payload = {"title": title}
            if not title or not title.strip():
                raise ValueError("Guardrails: el título de la tarea es obligatorio")
            result = self.service.create_task(task_payload)
            return {"success": True, "action": intent.action, "result": result}

        if intent.action == "complete_task":
            task_id = intent.payload.get("task_id")
            if not task_id:
                raise ValueError("Guardrails: falta el identificador de tarea")
            result = self.service.complete_task(task_id)
            return {"success": True, "action": intent.action, "result": result}

        return {"success": False, "action": "clarify", "reason": "No se pudo ejecutar la acción"}
