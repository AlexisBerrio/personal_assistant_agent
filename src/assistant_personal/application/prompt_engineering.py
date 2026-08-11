from __future__ import annotations


class PromptBuilder:
    """Construye un prompt base para un agente con guardrails y contexto."""

    def build_system_prompt(self) -> str:
        return (
            "Eres un asistente personal útil y seguro. "
            "Tu objetivo es ayudar a gestionar tareas de forma clara. "
            "Usa guardrails para rechazar peticiones vacías o ambiguas. "
            "Si una acción falla, intenta reintentos breves antes de informar el error."
        )

    def build_user_prompt(self, message: str, context: str | None = None) -> str:
        prompt = f"Mensaje del usuario: {message}"
        if context:
            prompt += f"\nContexto reciente: {context}"
        return prompt
