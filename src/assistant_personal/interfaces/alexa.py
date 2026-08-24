from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.assistant_personal.domain.repositories.conversation_orchestrator import ConversationOrchestrator

# Nombre del intent y del slot que se configuran en la consola de desarrollador de Alexa para
# el "catch-all" de lenguaje natural libre — Alexa no tiene un tipo de slot de dictado
# totalmente libre para skills custom, así que el modelo de interacción define un único intent
# con un único slot que captura la frase completa del usuario.
_MESSAGE_INTENT_NAME = "MensajeIntent"
_MESSAGE_SLOT_NAME = "mensaje"

_STOP_INTENT_NAMES = {"AMAZON.StopIntent", "AMAZON.CancelIntent"}
_HELP_INTENT_NAME = "AMAZON.HelpIntent"

_LAUNCH_MESSAGE = "hola"
_STOP_SPEECH = "Hasta luego."
_HELP_SPEECH = "Puedes pedirme que cree, liste, complete o elimine tareas. ¿Qué necesitas?"
_FALLBACK_SPEECH = "No entendí lo que dijiste. ¿Podrías repetirlo?"


class AlexaSlot(BaseModel):
    name: str
    value: str | None = None


class AlexaIntent(BaseModel):
    name: str
    slots: dict[str, AlexaSlot] = Field(default_factory=dict)


class AlexaRequestBody(BaseModel):
    type: str
    intent: AlexaIntent | None = None


class AlexaSession(BaseModel):
    session_id: str = Field(alias="sessionId")

    model_config = ConfigDict(populate_by_name=True)


class AlexaSkillRequest(BaseModel):
    """Subconjunto del esquema real de Alexa Skills Kit que este adaptador necesita — el resto
    del payload (`context`, `application`, `user`, etc.) se ignora."""

    session: AlexaSession
    request: AlexaRequestBody

    model_config = ConfigDict(extra="ignore")


def _build_response(*, speech_text: str, should_end_session: bool) -> dict[str, Any]:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": speech_text},
            "shouldEndSession": should_end_session,
        },
    }


def _extract_user_message(request_body: AlexaRequestBody) -> str | None:
    """`None` cuando el tipo de request no debe llegar al orquestador como mensaje del
    usuario — un saludo sintético para `LaunchRequest` (mismo criterio de "sin respuestas
    conversacionales estáticas": pasa por el router/LLM igual que cualquier saludo real, no es
    un texto fijo devuelto directo), el valor del slot para el intent de mensaje libre, y nada
    para el resto (intents del propio Alexa, que se resuelven aparte)."""
    if request_body.type == "LaunchRequest":
        return _LAUNCH_MESSAGE
    if (
        request_body.type == "IntentRequest"
        and request_body.intent is not None
        and request_body.intent.name == _MESSAGE_INTENT_NAME
    ):
        slot = request_body.intent.slots.get(_MESSAGE_SLOT_NAME)
        return slot.value if slot and slot.value else None
    return None


async def handle_alexa_request(
    payload: AlexaSkillRequest,
    build_orchestrator: Callable[[str], ConversationOrchestrator],
    request_id: str | None,
) -> dict[str, Any]:
    """Traduce un request de Alexa Skills Kit al mismo `handle_message_async` que usa `/chat`
    — Alexa es un cliente más de la tubería conversacional existente (router + agente
    + memoria de sesión), sin lógica de negocio nueva. La sesión de Alexa (`session.sessionId`)
    se reutiliza como `session_id` del orquestador, con un prefijo para no colisionar con
    sesiones de `/chat`.

    Los intents de la propia plataforma (`AMAZON.StopIntent`/`CancelIntent`/`HelpIntent`,
    `SessionEndedRequest`) se resuelven aquí sin pasar por el orquestador: no son mensajes del
    usuario que el router deba interpretar, son controles de la skill.
    """
    session_id = f"alexa-{payload.session.session_id}"
    request_body = payload.request

    if request_body.type == "SessionEndedRequest":
        return _build_response(speech_text="", should_end_session=True)

    if request_body.type == "IntentRequest" and request_body.intent is not None:
        intent_name = request_body.intent.name
        if intent_name in _STOP_INTENT_NAMES:
            return _build_response(speech_text=_STOP_SPEECH, should_end_session=True)
        if intent_name == _HELP_INTENT_NAME:
            return _build_response(speech_text=_HELP_SPEECH, should_end_session=False)

    message = _extract_user_message(request_body)
    if not message:
        return _build_response(speech_text=_FALLBACK_SPEECH, should_end_session=False)

    orchestrator = build_orchestrator(session_id)
    result: dict[str, Any] = await orchestrator.handle_message_async(message, request_id=request_id)

    speech_text = result.get("message") or result.get("reason") or _FALLBACK_SPEECH
    return _build_response(speech_text=speech_text, should_end_session=False)
