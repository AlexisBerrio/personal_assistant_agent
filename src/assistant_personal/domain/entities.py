from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntentAction(str, Enum):
    LIST_TASKS = "list_tasks"  # Ver, consultar o listar tareas pendientes.
    CREATE_TASK = "create_task"  # Registrar una nueva tarea.
    COMPLETE_TASK = "complete_task"  # Marcar una tarea como completada.
    DELETE_TASK = "delete_task"  # Eliminar una tarea.
    ASK_KNOWLEDGE_BASE = "ask_knowledge_base"  # El usuario pregunta información general.
    SMALL_TALK = "small_talk"  # Conversación casual o saludo.
    CLARIFY = "clarify"  # La solicitud es ambigua o incomprensible.


class ConversationRoute(str, Enum):
    """Ruta de alto nivel que decide qué componente debe procesar el mensaje."""

    GENERAL_KNOWLEDGE = "general_knowledge"
    ORCHESTRATOR = "orchestrator"
    CLARIFY = "clarify"


class IntentDecision(BaseModel):
    """Representa la salida estructurada y validada que devuelve el router."""

    action: IntentAction
    payload: dict[str, Any] = Field(default_factory=dict, description="Parámetros extraídos del mensaje")
    confidence: float = Field(ge=0.0, le=1.0, description="Nivel de confianza en la decisión [0.0 - 1.0]")
    reasoning: str | None = Field(default=None, description="Breve justificación de la elección")
    source: str = Field(description="Origen de la decisión: 'rule', 'llm', 'fallback'")


class IntentClassification(BaseModel):
    """Salida del clasificador LLM para enrutar la conversación."""

    route: ConversationRoute
    intent: IntentAction | None = Field(default=None, description="Intención del dominio cuando aplica")
    confidence: float = Field(ge=0.0, le=1.0, description="Confianza de la clasificación")
    reasoning: str | None = Field(default=None, description="Justificación de la clasificación")
    payload: dict[str, Any] = Field(default_factory=dict, description="Datos estructurados extraídos del mensaje")
    source: str = Field(default="llm", description="Origen de la clasificación")


class UserProfileFact(BaseModel):
    """Hecho de perfil detectado a partir del mensaje del usuario."""

    key: str = Field(description="Clave semántica del hecho, por ejemplo name o color_favorito")
    value: str = Field(description="Valor asociado al hecho")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Nivel de confianza del hecho")


class UserProfileExtraction(BaseModel):
    """Resultado estructurado de la extracción de memoria de perfil."""

    profile_facts: list[UserProfileFact] = Field(default_factory=list, description="Hechos de perfil detectados")


