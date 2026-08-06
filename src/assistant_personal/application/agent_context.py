from __future__ import annotations


class ShortTermMemory:
    """Memoria temporal para la conversación actual."""

    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []

    def add(self, key: str, value: str) -> None:
        self._items.append((key, value))

    def get_items(self) -> list[tuple[str, str]]:
        return list(self._items)


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
        facts = "; ".join(f"{key}={value}" for key, value in self.long_term_memory.get_facts().items())
        return f"Contexto reciente: {items}; Memoria persistente: {facts}".strip()
