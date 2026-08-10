from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IntentAction(str, Enum):
    LIST_TASKS = "list_tasks" #Ver, consultar o listar tareas pendientes.
    CREATE_TASK = "create_task" #Registrar una nueva tarea
    COMPLETE_TASK = "complete_task" #Marcar una tarea como completada
    DELETE_TASK = "delete_task" #Eliminar una tarea
    ASK_KNOWLEDGE_BASE = "ask_knowledge_base" #Si el usuario pregunta información general
    SMALL_TALK = "small_talk" #Conversación casual o saludo
    CLARIFY = "clarify" #Si la solicitud es totalmente ambigua o incomprensible.


class IntentDecision(BaseModel):
    """Representa la salida estructurada y validada que devuelve el router."""

    action: IntentAction
    payload: dict[str, Any] = Field(default_factory=dict, description="Parámetros extraídos del mensaje")
    confidence: float = Field(ge=0.0, le=1.0, description="Nivel de confianza en la decisión [0.0 - 1.0]")
    reasoning: Optional[str] = Field(default=None, description="Breve justificación de la elección")
    source: str = Field(description="Origen de la decisión: 'rule', 'llm', 'fallback'")
