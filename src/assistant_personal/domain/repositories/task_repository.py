from __future__ import annotations

from typing import Protocol, Any


class TaskRepository(Protocol):
    """Puerto del dominio para persistir tareas y su historial."""

    def check_connection(self) -> bool:
        ...

    def list_active_tasks(self) -> list[dict[str, Any]]:
        ...

    def get_task_by_id(self, task_id: str) -> dict[str, Any] | None:
        ...

    def get_task_history(self, task_id: str) -> list[dict[str, Any]]:
        ...

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def complete_task(self, task_id: str) -> dict[str, Any]:
        ...

    def delete_task(self, task_id: str) -> dict[str, Any] | None:
        ...
