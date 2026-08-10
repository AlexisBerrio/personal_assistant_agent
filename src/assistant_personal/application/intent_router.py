from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class IntentResult:
    """Compatibilidad mínima para el router anterior."""

    action: str
    payload: dict[str, Any]


class IntentRouter:
    """Router simple usado solo como compatibilidad de legado."""

    def route(self, message: str) -> IntentResult:
        normalized_message = (message or "").strip().lower()

        if not normalized_message:
            return IntentResult(action="clarify", payload={"message": "No pude entender la petición."})

        if any(keyword in normalized_message for keyword in ["listar", "ver", "mostrar", "pendientes", "tareas", "qué tengo", "qué tareas", "mis tareas", "pendiente"]):
            return IntentResult(action="list_tasks", payload={})

        if any(keyword in normalized_message for keyword in ["crear", "añadir", "nueva tarea", "agregar", "nueva", "haz", "hacer", "recordar"]):
            title = self._extract_title(normalized_message)
            return IntentResult(action="create_task", payload={"title": title})

        if any(keyword in normalized_message for keyword in ["completar", "terminar", "marcar", "hecha", "hecho", "done", "finalizar", "cerrar"]):
            return IntentResult(action="complete_task", payload={})

        return IntentResult(action="clarify", payload={"message": "No pude identificar la acción que quieres realizar."})

    def _extract_title(self, message: str) -> str:
        cleaned = message.strip()
        for prefix in ["crear ", "añadir ", "agregar ", "nueva tarea "]:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break

        cleaned = re.sub(r"^(una|un|la|el|las|los)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(tarea|actividad|recordatorio)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned:
            return "Tarea nueva"
        if cleaned.lower().startswith("tarea"):
            return cleaned.capitalize()
        return f"Tarea {cleaned}".capitalize()
