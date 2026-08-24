from __future__ import annotations

import unittest

import httpx

from app import (
    app,
    enforce_alexa_rate_limit,
    enforce_chat_rate_limit,
    get_alexa_signature_verifier,
    get_orchestrator_factory,
)


class FakeOrchestrator:
    async def handle_message_async(self, message, request_id=None):
        return {"message": "Listo.", "success": True, "action": "small_talk"}

    def handle_message(self, message, request_id=None):
        raise NotImplementedError


class RateLimitWiringTests(unittest.IsolatedAsyncioTestCase):
    """Confirma que `/chat` y `/alexa` responden 429 cuando la dependencia de rate limiting lo
    exige — la lógica de conteo en sí (ventana deslizante, claves independientes) ya está
    cubierta sin HTTP en test_rate_limiter.py; aquí solo se prueba el wiring."""

    async def asyncSetUp(self) -> None:
        app.dependency_overrides[get_orchestrator_factory] = lambda: (lambda session_id: FakeOrchestrator())
        app.dependency_overrides[get_alexa_signature_verifier] = lambda: self._noop_verifier
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    @staticmethod
    async def _noop_verifier(raw_body: bytes, headers: object) -> None:
        return None

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_orchestrator_factory, None)
        app.dependency_overrides.pop(get_alexa_signature_verifier, None)
        app.dependency_overrides.pop(enforce_chat_rate_limit, None)
        app.dependency_overrides.pop(enforce_alexa_rate_limit, None)
        await self.client.aclose()

    async def test_chat_returns_429_when_the_limit_is_exceeded(self) -> None:
        def _always_exceeded() -> None:
            from fastapi import HTTPException

            raise HTTPException(status_code=429, detail="límite excedido")

        app.dependency_overrides[enforce_chat_rate_limit] = _always_exceeded

        response = await self.client.post("/chat", json={"message": "hola"})

        self.assertEqual(response.status_code, 429)

    async def test_alexa_returns_429_when_the_limit_is_exceeded(self) -> None:
        def _always_exceeded() -> None:
            from fastapi import HTTPException

            raise HTTPException(status_code=429, detail="límite excedido")

        app.dependency_overrides[enforce_alexa_rate_limit] = _always_exceeded

        response = await self.client.post(
            "/alexa",
            json={
                "session": {"sessionId": "amzn1.echo-api.session.abc"},
                "request": {"type": "LaunchRequest"},
            },
        )

        self.assertEqual(response.status_code, 429)

    async def test_chat_succeeds_when_under_the_limit(self) -> None:
        app.dependency_overrides[enforce_chat_rate_limit] = lambda: None

        response = await self.client.post("/chat", json={"message": "hola"})

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
