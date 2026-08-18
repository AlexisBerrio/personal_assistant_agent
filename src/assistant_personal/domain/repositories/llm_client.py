from __future__ import annotations

from typing import Protocol

from src.assistant_personal.domain.entities import IntentClassification, UserProfileExtraction


class LLMClient(Protocol):
    """Port para el cliente LLM usado por el router híbrido.

    Async de punta a punta. Antes de este port (docs/anexo_arquitectura_objetivo.md §A.1,
    ítem 1.6) el SDK de OpenAI se invocaba de forma síncrona dentro de un flujo async
    (`TaskOrchestrator.handle_message_async`), bloqueando el event loop entero durante cada
    llamada de red al LLM. El adaptador de infraestructura (`openai_llm_client.py`) implementa
    este port con `AsyncOpenAI`.
    """

    async def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        ...

    async def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        ...

    async def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        ...
