from __future__ import annotations

import unittest

import httpx

from app import app, get_orchestrator_factory


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


class AlexaEndpointTests(unittest.IsolatedAsyncioTestCase):
    """Ejercita `/alexa` por HTTP (`httpx.ASGITransport`, sin lifespan), mismo patrón que
    `test_api_chat.py` — confirma que el endpoint solo resuelve dependencias (comparte
    `get_orchestrator_factory` con `/chat`) y delega toda la traducción a `interfaces/alexa.py`,
    ya cubierto en detalle por `test_alexa_adapter.py`."""

    async def asyncSetUp(self) -> None:
        self.orchestrator = FakeOrchestrator(message="Tienes 2 tareas pendientes.")
        self.builder = OrchestratorBuilderSpy(self.orchestrator)
        app.dependency_overrides[get_orchestrator_factory] = lambda: self.builder
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_orchestrator_factory, None)
        await self.client.aclose()

    async def test_message_intent_reaches_the_same_orchestrator_as_chat(self) -> None:
        response = await self.client.post(
            "/alexa",
            json={
                "session": {"sessionId": "amzn1.echo-api.session.abc"},
                "request": {
                    "type": "IntentRequest",
                    "intent": {"name": "MensajeIntent", "slots": {"mensaje": {"name": "mensaje", "value": "qué tareas tengo"}}},
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["response"]["outputSpeech"]["text"], "Tienes 2 tareas pendientes.")
        self.assertEqual(self.orchestrator.calls[0][0], "qué tareas tengo")
        self.assertEqual(self.builder.session_ids, ["alexa-amzn1.echo-api.session.abc"])

    async def test_passes_the_middleware_request_id_to_the_orchestrator(self) -> None:
        response = await self.client.post(
            "/alexa",
            json={
                "session": {"sessionId": "amzn1.echo-api.session.abc"},
                "request": {"type": "LaunchRequest"},
            },
        )

        header_request_id = response.headers["X-Request-ID"]
        self.assertEqual(self.orchestrator.calls[0], ("hola", header_request_id))

    async def test_missing_session_or_request_is_rejected_with_422(self) -> None:
        response = await self.client.post("/alexa", json={})

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
