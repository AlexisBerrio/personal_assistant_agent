from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Task:
    """Representa una tarea del asistente personal.
    """

    title: str
    task_id: Optional[str] = None
    description: Optional[str] = None
    status: str = "Pending"
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    priority: Any = None
    dates: dict[str, Any] = field(default_factory=dict)
    recurrence: dict[str, Any] = field(default_factory=dict)
    context_metadata: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    agent_notes: list[dict[str, Any]] = field(default_factory=list)
    is_deleted: bool = False
    deleted_at: Optional[str] = None

    def apply_updates(self, updates: dict[str, Any]) -> None:
        """Aplica cambios de negocio a la tarea y actualiza su estado si procede."""
        for field, value in updates.items():
            setattr(self, field, value)

        if self.status == "Pending" and updates:
            self.status = "In Progress"
