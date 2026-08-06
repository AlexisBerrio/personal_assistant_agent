from __future__ import annotations


class ShortTermMemory:
    """Memoria temporal para la conversación actual."""

    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []
        self.turns: list[tuple[str, str]] = []

    def add(self, key: str, value: str) -> None:
        self._items.append((key, value))

    def add_turn(self, user_message: str, assistant_response: str) -> None:
        self.turns.append((user_message, assistant_response))

    def get_items(self) -> list[tuple[str, str]]:
        return list(self._items)

    def get_turns(self) -> list[tuple[str, str]]:
        return list(self.turns)


class LongTermMemory:
    """Memoria persistente con hechos clave del usuario."""

    def __init__(self) -> None:
        self._facts: dict[str, str] = {}

    def add_fact(self, key: str, value: str) -> None:
        self._facts[key] = value

    def get_facts(self) -> dict[str, str]:
        return dict(self._facts)


class AgentContext:
    """Agrega contexto de corto y largo plazo para un agente simple."""

    def __init__(self) -> None:
        self.short_term_memory = ShortTermMemory()
        self.long_term_memory = LongTermMemory()

    def build_context_summary(self) -> str:
        items = "; ".join(f"{key}={value}" for key, value in self.short_term_memory.get_items())
        turns = "; ".join(f"user:{user_msg} | assistant:{assistant_msg}" for user_msg, assistant_msg in self.short_term_memory.get_turns())
        facts = "; ".join(f"{key}={value}" for key, value in self.long_term_memory.get_facts().items())
        context_parts = [part for part in [items, turns, facts] if part]
        return f"Contexto reciente: {' | '.join(context_parts)}".strip()
