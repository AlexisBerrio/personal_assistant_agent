from dataclasses import dataclass
from typing import Optional


@dataclass
class Task:
    """Representa una tarea del asistente personal.

    Cada campo tiene un propósito claro:
    - title: nombre de la tarea.
    - description: detalles adicionales.
    - status: estado actual, por ejemplo To Do o Completed.
    - priority: importancia de la tarea.
    - due_date: fecha límite si la tiene.
    - source: de dónde vino la tarea, por ejemplo manual o voz.
    """

    title: str
    description: Optional[str] = None
    status: str = "To Do"
    priority: str = "medium"
    due_date: Optional[str] = None
    source: str = "manual"
