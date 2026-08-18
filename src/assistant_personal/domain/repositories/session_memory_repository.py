from __future__ import annotations

from typing import Any, Protocol


class SessionMemoryRepository(Protocol):
    """Puerto del dominio para almacenar y recuperar memoria conversacional por sesión.

    Los adaptadores con I/O real (ej. MongoDB) deben implementar las variantes
    `_async`. Nunca se permite bridging sync/async (asyncio.run) dentro de un
    adaptador: si el I/O es asíncrono, el puerto se consume con await de extremo
    a extremo. Adaptadores puramente en memoria pueden exponer solo las
    versiones síncronas.
    """

    def add_context_item(self, session_id: str, key: str, value: str) -> None:
        ...

    def append_turn(self, session_id: str, user_message: str, assistant_response: str) -> None:
        ...

    def get_context_summary(self, session_id: str, max_turns: int = 3, max_items: int = 5) -> dict[str, Any]:
        ...

    async def add_context_item_async(self, session_id: str, key: str, value: str) -> None:
        ...

    async def append_turn_async(self, session_id: str, user_message: str, assistant_response: str) -> None:
        ...

    async def get_context_summary_async(
        self, session_id: str, max_turns: int = 3, max_items: int = 5
    ) -> dict[str, Any]:
        ...
