from __future__ import annotations

from typing import Protocol

from src.assistant_personal.domain.entities import UserProfileFact


class LongTermMemoryRepository(Protocol):
    """Puerto del dominio para almacenar y recuperar hechos de perfil de usuario que deben
    sobrevivir a un reinicio (§A.9, ítem 2.5) — preferencias, hechos estables, no la memoria de
    sesión (`SessionMemoryRepository`), que es de corta vida.

    Mismo contrato dual sync/async que `SessionMemoryRepository`: los adaptadores con I/O real
    (ej. MongoDB) implementan las variantes `_async`; adaptadores puramente en memoria pueden
    exponer solo las versiones síncronas.
    """

    def upsert_fact(self, user_id: str, fact: UserProfileFact, source: str = "manual") -> None:
        ...

    def get_facts(self, user_id: str, limit: int = 10) -> list[UserProfileFact]:
        ...

    def delete_facts(self, user_id: str) -> int:
        ...

    async def upsert_fact_async(self, user_id: str, fact: UserProfileFact, source: str = "manual") -> None:
        ...

    async def get_facts_async(self, user_id: str, limit: int = 10) -> list[UserProfileFact]:
        ...

    async def delete_facts_async(self, user_id: str) -> int:
        ...
