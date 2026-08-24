from __future__ import annotations

import unittest

import httpx

from app import app, enforce_chat_rate_limit, get_orchestrator_factory


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
    """Doble de `get_orchestrator_factory`: registra con qué `session_id` se construyó el
    orquestador en cada llamada, sin tocar Mongo/MCP/LLM reales."""

    def __init__(self, orchestrator: FakeOrchestrator):
        self.orchestrator = orchestrator
        self.session_ids: list[str] = []

    def __call__(self, session_id: str) -> FakeOrchestrator:
        self.session_ids.append(session_id)
        return self.orchestrator


class ChatEndpointTests(unittest.IsolatedAsyncioTestCase):
    """Ejercita `/chat` por HTTP (`httpx.ASGITransport`, sin lifespan) con un `ConversationOrchestrator`
    falso inyectado vía `dependency_overrides` — el mismo patrón que `test_api_e2e.py` usa para
    `get_service`, evita spawnear el subproceso MCP real o llamar a un LLM real."""

    async def asyncSetUp(self) -> None:
        self.orchestrator = FakeOrchestrator()
        self.builder = OrchestratorBuilderSpy(self.orchestrator)
        app.dependency_overrides[get_orchestrator_factory] = lambda: self.builder
        # El rate limiter tiene su propia cobertura en test_rate_limiter.py (lógica) y
        # test_api_rate_limit.py (wiring 429) — aquí se desactiva para no interferir con estos
        # tests, que comparten el contador de todo el proceso de test.
        app.dependency_overrides[enforce_chat_rate_limit] = lambda: None
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_orchestrator_factory, None)
        app.dependency_overrides.pop(enforce_chat_rate_limit, None)
        await self.client.aclose()

    async def test_chat_returns_the_orchestrator_message_and_generates_a_session_id(self) -> None:
        response = await self.client.post("/chat", json={"message": "hola"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["message"], "Listo.")
        self.assertTrue(body["success"])
        self.assertEqual(body["action"], "small_talk")
        self.assertTrue(body["session_id"])

    async def test_chat_reuses_the_session_id_provided_by_the_client(self) -> None:
        response = await self.client.post("/chat", json={"message": "hola", "session_id": "sess-fija"})

        self.assertEqual(response.json()["session_id"], "sess-fija")
        self.assertEqual(self.builder.session_ids, ["sess-fija"])

    async def test_chat_generates_a_new_session_id_when_none_is_provided(self) -> None:
        response = await self.client.post("/chat", json={"message": "hola"})

        session_id = response.json()["session_id"]
        self.assertEqual(self.builder.session_ids, [session_id])

    async def test_chat_passes_the_middleware_request_id_to_the_orchestrator(self) -> None:
        """No debe generar un request_id propio para la interacción — reutiliza el que
        `RequestIdMiddleware` ya puso en el header `X-Request-ID` de la respuesta."""
        response = await self.client.post("/chat", json={"message": "hola"})

        header_request_id = response.headers["X-Request-ID"]
        self.assertEqual(self.orchestrator.calls[0], ("hola", header_request_id))

    async def test_chat_rejects_an_empty_message(self) -> None:
        response = await self.client.post("/chat", json={"message": ""})

        self.assertEqual(response.status_code, 422)

    async def test_chat_reuses_a_client_supplied_request_id(self) -> None:
        """`RequestIdMiddleware` (ASGI puro, ver ítem 4.10) sigue respetando un `X-Request-ID`
        que ya venga en la petición, igual que antes de reescribirlo desde `BaseHTTPMiddleware`."""
        response = await self.client.post(
            "/chat", json={"message": "hola"}, headers={"X-Request-ID": "req-fijo-123"}
        )

        self.assertEqual(response.headers["X-Request-ID"], "req-fijo-123")
        self.assertEqual(self.orchestrator.calls[0], ("hola", "req-fijo-123"))


if __name__ == "__main__":
    unittest.main()
