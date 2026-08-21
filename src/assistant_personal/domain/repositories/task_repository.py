from __future__ import annotations

from typing import Any, Protocol


class TaskRepository(Protocol):
    """Puerto del dominio para persistir tareas y su historial.

    Async de punta a punta, con el sufijo `_async` que usa el resto de los ports del proyecto
    (`SessionMemoryRepository`, `LLMClient`) — refleja la única implementación real que existe
    (`MongoTaskRepository`), no una interfaz síncrona aspiracional que nadie implementa.
    """

    async def check_connection(self) -> bool:
        ...

    async def list_active_tasks_async(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        ...

    async def get_task_by_id_async(self, task_id: str) -> dict[str, Any] | None:
        ...

    async def get_task_history_async(self, task_id: str) -> list[dict[str, Any]]:
        ...

    async def create_task_async(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def update_task_async(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        ...

    async def complete_task_async(self, task_id: str) -> dict[str, Any]:
        ...

    async def delete_task_async(self, task_id: str) -> dict[str, Any] | None:
        ...
