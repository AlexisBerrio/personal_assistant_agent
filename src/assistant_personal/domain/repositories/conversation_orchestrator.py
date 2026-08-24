from __future__ import annotations

from typing import Any, Protocol


class ConversationOrchestrator(Protocol):
    """Puerto del dominio para el componente que resuelve un turno de conversación completo
    (router + agente + memoria) y devuelve la respuesta de cara al usuario.

    `TaskOrchestrator` es la única implementación real hoy. El puerto existe para que
    `interfaces/` (CLI, y cualquier adaptador futuro — Alexa en Fase 6) programe contra esta
    firma en vez de la clase concreta, igual que ya hace con `TaskRepository`/
    `SessionMemoryRepository`/`LongTermMemoryRepository`/`LLMClient`.
    """

    async def handle_message_async(self, message: str) -> dict[str, Any]:
        ...

    def handle_message(self, message: str) -> dict[str, Any]:
        ...
