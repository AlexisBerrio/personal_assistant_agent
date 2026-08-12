from __future__ import annotations

from typing import Any, Protocol


class SessionMemoryRepository(Protocol):
    """Puerto del dominio para almacenar y recuperar memoria conversacional por sesión."""

    def add_context_item(self, session_id: str, key: str, value: str) -> None:
        ...

    def append_turn(self, session_id: str, user_message: str, assistant_response: str) -> None:
        ...

    def get_context_summary(self, session_id: str, max_turns: int = 3, max_items: int = 5) -> dict[str, Any]:
        ...