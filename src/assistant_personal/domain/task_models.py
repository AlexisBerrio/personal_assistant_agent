from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Task(BaseModel):
    """Representa una tarea del asistente personal con validación de dominio en el modelo."""

    model_config = ConfigDict(extra="allow")

    title: str
    task_id: str | None = None
    tenant_id: str = "default"
    description: str | None = None
    status: str = "Pending"
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: dict[str, Any] | None = None
    dates: dict[str, Any] = Field(default_factory=dict)
    recurrence: dict[str, Any] = Field(default_factory=dict)
    context_metadata: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    agent_notes: list[dict[str, Any]] = Field(default_factory=list)
    is_deleted: bool = False
    deleted_at: str | None = None

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: Any) -> str:
        if value is None:
            raise ValueError("El título de la tarea es obligatorio")
        if not isinstance(value, str):
            raise ValueError("El título de la tarea es obligatorio")
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("El título de la tarea es obligatorio")
        return normalized_value

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        if value is None:
            return "Pending"
        if not isinstance(value, str) or not value.strip():
            raise ValueError("El estado de la tarea no puede estar vacío")

        normalized_status = value.strip().lower()
        status_map = {
            "pending": "Pending",
            "in progress": "In Progress",
            "completed": "Completed",
            "deleted": "Deleted",
        }
        if normalized_status not in status_map:
            allowed_values = {"Pending", "In Progress", "Completed", "Deleted"}
            allowed_values_str = ", ".join(sorted(allowed_values))
            raise ValueError(f"Estado no válido. Valores permitidos: {allowed_values_str}")
        return status_map[normalized_status]

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("La prioridad debe ser un objeto con un campo level")

        priority_level = value.get("level")
        if not isinstance(priority_level, str) or not priority_level.strip():
            raise ValueError("La prioridad debe incluir un nivel válido")

        normalized_priority = priority_level.strip().lower()
        priority_map = {"low": "Low", "medium": "Medium", "high": "High"}
        if normalized_priority not in priority_map:
            allowed_values = {"Low", "Medium", "High"}
            allowed_values_str = ", ".join(sorted(allowed_values))
            raise ValueError(f"Prioridad no válida. Valores permitidos: {allowed_values_str}")
        return {**value, "level": priority_map[normalized_priority]}

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("La categoría de la tarea no puede estar vacía")

        normalized_category = value.strip().lower()
        category_map = {
            "personal": "Personal",
            "work": "Work",
            "study": "Study",
            "health": "Health",
            "home": "Home",
        }
        if normalized_category not in category_map:
            allowed_values = {"Personal", "Work", "Study", "Health", "Home"}
            allowed_values_str = ", ".join(sorted(allowed_values))
            raise ValueError(f"Categoría no válida. Valores permitidos: {allowed_values_str}")
        return category_map[normalized_category]

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """Convierte valores no JSON serializables a formatos compatibles con la API."""
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return value.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(value, dict):
            return {k: Task._serialize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [Task._serialize_value(item) for item in value]
        return value

    def to_payload(self) -> dict[str, Any]:
        """Devuelve una representación serializada lista para persistencia o API."""
        payload = self.model_dump(exclude_none=False)
        return {key: self._serialize_value(value) for key, value in payload.items()}

    def apply_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Aplica cambios de negocio a la tarea y actualiza su estado si procede."""
        if not isinstance(updates, dict):
            raise TypeError("updates debe ser un diccionario")

        candidate = self.model_copy(deep=True)
        merged_payload = {**candidate.model_dump(exclude_none=False), **updates}
        try:
            validated_payload = self.__class__.model_validate(merged_payload)
        except Exception:
            validated_payload = self.__class__.model_construct(**merged_payload)

        changed_values: dict[str, Any] = {}
        for field_name, value in validated_payload.model_dump(exclude_none=False).items():
            if field_name in updates or field_name == "status":
                changed_values[field_name] = value
                setattr(self, field_name, value)

        if self.status == "Pending" and updates:
            self.status = "In Progress"
            changed_values["status"] = self.status

        return changed_values
