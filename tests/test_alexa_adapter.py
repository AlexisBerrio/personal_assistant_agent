from __future__ import annotations

import unittest

from src.assistant_personal.interfaces.alexa import AlexaSkillRequest, handle_alexa_request


class FakeOrchestrator:
    def __init__(self, message="Listo.", success=True, action="small_talk"):
        self.calls: list[tuple[str, str | None]] = []
        self._message = message
        self._success = success
        self._action = action

    async def handle_message_async(self, message, request_id=None):
        self.calls.append((message, request_id))
        return {"message": self._message, "success": self._success, "action": self._action}

    def handle_message(self, message, request_id=None):
        raise NotImplementedError


class OrchestratorBuilderSpy:
    def __init__(self, orchestrator: FakeOrchestrator):
        self.orchestrator = orchestrator
        self.session_ids: list[str] = []

    def __call__(self, session_id: str) -> FakeOrchestrator:
        self.session_ids.append(session_id)
        return self.orchestrator


def _launch_request(session_id: str = "amzn1.echo-api.session.abc") -> dict:
    return {
        "session": {"sessionId": session_id},
        "request": {"type": "LaunchRequest"},
    }


def _message_intent_request(text: str, session_id: str = "amzn1.echo-api.session.abc") -> dict:
    return {
        "session": {"sessionId": session_id},
        "request": {
            "type": "IntentRequest",
            "intent": {"name": "MensajeIntent", "slots": {"mensaje": {"name": "mensaje", "value": text}}},
        },
    }


def _system_intent_request(intent_name: str, session_id: str = "amzn1.echo-api.session.abc") -> dict:
    return {
        "session": {"sessionId": session_id},
        "request": {"type": "IntentRequest", "intent": {"name": intent_name, "slots": {}}},
    }


def _session_ended_request(session_id: str = "amzn1.echo-api.session.abc") -> dict:
    return {"session": {"sessionId": session_id}, "request": {"type": "SessionEndedRequest"}}


class HandleAlexaRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_request_sends_a_synthetic_greeting_to_the_orchestrator(self) -> None:
        """ítem 6.1: ni siquiera el saludo de bienvenida es un texto fijo — pasa por el mismo
        router/LLM que cualquier saludo real, mismo criterio que 'no static conversational
        replies'."""
        orchestrator = FakeOrchestrator(message="¡Hola! ¿En qué te ayudo?")
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_launch_request())

        response = await handle_alexa_request(payload, builder, request_id="req-1")

        self.assertEqual(orchestrator.calls, [("hola", "req-1")])
        self.assertEqual(response["response"]["outputSpeech"]["text"], "¡Hola! ¿En qué te ayudo?")
        self.assertFalse(response["response"]["shouldEndSession"])

    async def test_message_intent_forwards_the_slot_value_as_the_user_message(self) -> None:
        orchestrator = FakeOrchestrator(message="Tienes 2 tareas pendientes.")
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_message_intent_request("qué tareas tengo"))

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [("qué tareas tengo", None)])
        self.assertEqual(response["response"]["outputSpeech"]["text"], "Tienes 2 tareas pendientes.")
        self.assertFalse(response["response"]["shouldEndSession"])

    async def test_session_id_reuses_the_alexa_session_with_a_prefix(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(
            _message_intent_request("hola", session_id="amzn1.echo-api.session.xyz")
        )

        await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(builder.session_ids, ["alexa-amzn1.echo-api.session.xyz"])

    async def test_message_intent_without_a_slot_value_falls_back_without_calling_the_orchestrator(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_message_intent_request(""))

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [])
        self.assertIn("no entendí", response["response"]["outputSpeech"]["text"].lower())

    async def test_stop_intent_ends_the_session_without_calling_the_orchestrator(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_system_intent_request("AMAZON.StopIntent"))

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [])
        self.assertTrue(response["response"]["shouldEndSession"])

    async def test_cancel_intent_behaves_like_stop(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_system_intent_request("AMAZON.CancelIntent"))

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [])
        self.assertTrue(response["response"]["shouldEndSession"])

    async def test_help_intent_answers_without_ending_the_session_or_calling_the_orchestrator(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_system_intent_request("AMAZON.HelpIntent"))

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [])
        self.assertFalse(response["response"]["shouldEndSession"])
        self.assertTrue(response["response"]["outputSpeech"]["text"])

    async def test_session_ended_request_ends_the_session_without_calling_the_orchestrator(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_session_ended_request())

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [])
        self.assertTrue(response["response"]["shouldEndSession"])

    async def test_unrecognized_intent_falls_back_without_calling_the_orchestrator(self) -> None:
        orchestrator = FakeOrchestrator()
        builder = OrchestratorBuilderSpy(orchestrator)
        payload = AlexaSkillRequest.model_validate(_system_intent_request("AMAZON.FallbackIntent"))

        response = await handle_alexa_request(payload, builder, request_id=None)

        self.assertEqual(orchestrator.calls, [])
        self.assertIn("no entendí", response["response"]["outputSpeech"]["text"].lower())


if __name__ == "__main__":
    unittest.main()
