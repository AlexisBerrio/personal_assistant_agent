from __future__ import annotations

import asyncio
import os
import unittest
import uuid

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from app import app, get_mcp_client
from src.assistant_personal.infrastructure.mcp.client import McpTaskServiceClient

LOCAL_MONGO_URI = "mongodb://localhost:27018"
# Puerto 27018: mismo motivo que en los demás tests de integración.


def _local_mongo_is_reachable() -> bool:
    async def _ping() -> bool:
        client = AsyncIOMotorClient(LOCAL_MONGO_URI, serverSelectionTimeoutMS=2000)
        try:
            await client.admin.command("ping")
            return True
        except Exception:
            return False
        finally:
            client.close()

    return asyncio.run(_ping())


@unittest.skipUnless(
    _local_mongo_is_reachable(),
    "Requiere el Mongo local desechable de docker-compose.yml: ejecuta `docker compose up -d mongo`",
)
class ApiEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """Ejercita `app.py` completo por HTTP con `httpx.AsyncClient` (no `TestClient` síncrono):
    middleware de `request_id`, exception handlers y el flujo CRUD real — vía el protocolo MCP
    real (ítem 4.10: el CRUD ya no llama a `TaskService` en proceso, mismo criterio que `/chat`).

    Crítico: `httpx.ASGITransport` NUNCA dispara el `lifespan` de FastAPI, así que
    `get_mcp_client` caería a su fallback (`request.app.state.mcp_client`, inexistente sin
    lifespan). Por eso este test sustituye `app.dependency_overrides[get_mcp_client]` por un
    cliente MCP real explícitamente apuntado al Mongo local desechable (mismo patrón que
    `test_mcp_client_integration.py`), nunca al Atlas de `.env`.

    La sesión stdio del cliente MCP se conecta perezosamente en el primer uso, dentro de la
    misma task que hace la llamada — y debe cerrarse (`aclose()`) al final de esa misma task, no
    en `asyncTearDown` (corre en una task distinta bajo `IsolatedAsyncioTestCase`, lo que rompe
    los cancel scopes de `anyio` que usa `stdio_client` internamente). Por eso cada test cierra
    su propio cliente al final, en vez de compartir una limpieza centralizada.
    """

    db_name = "assistant_personal_test"

    async def asyncSetUp(self) -> None:
        self.env = {**os.environ, "MONGO_URI": LOCAL_MONGO_URI, "MONGO_DB_NAME": self.db_name}
        self.mcp_client = McpTaskServiceClient(env=self.env)
        app.dependency_overrides[get_mcp_client] = lambda: self.mcp_client

        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.created_task_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_mcp_client, None)
        await self.client.aclose()

        motor_client = AsyncIOMotorClient(LOCAL_MONGO_URI)
        db = motor_client[self.db_name]
        if self.created_task_ids:
            await db.personal_tasks.delete_many({"task_id": {"$in": self.created_task_ids}})
            await db.task_history.delete_many({"task_id": {"$in": self.created_task_ids}})
        motor_client.close()

    async def _create_task(self, title: str) -> dict:
        response = await self.client.post("/tasks", json={"title": title})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.created_task_ids.append(body["task_id"])
        return body

    async def test_health_check_responds_ok(self) -> None:
        response = await self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_request_id_header_is_present_on_every_response(self) -> None:
        response = await self.client.get("/health")

        self.assertIn("X-Request-ID", response.headers)
        self.assertTrue(response.headers["X-Request-ID"])

    async def test_full_task_lifecycle_through_the_real_api(self) -> None:
        title = f"Tarea E2E {uuid.uuid4().hex[:8]}"
        created = await self._create_task(title)
        task_id = created["task_id"]
        self.assertEqual(created["title"], title)

        get_response = await self.client.get(f"/tasks/{task_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["title"], title)

        list_response = await self.client.get("/tasks")
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(any(task["task_id"] == task_id for task in list_response.json()))

        update_response = await self.client.patch(f"/tasks/{task_id}", json={"title": "Tarea E2E actualizada"})
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["title"], "Tarea E2E actualizada")

        complete_response = await self.client.patch(f"/tasks/{task_id}", json={"status": "Completed"})
        self.assertEqual(complete_response.status_code, 200)

        history_response = await self.client.get(f"/tasks/{task_id}/history")
        self.assertEqual(history_response.status_code, 200)
        self.assertGreaterEqual(len(history_response.json()), 1)

        delete_response = await self.client.delete(f"/tasks/{task_id}")
        self.assertEqual(delete_response.status_code, 200)

        after_delete_response = await self.client.get(f"/tasks/{task_id}")
        self.assertEqual(after_delete_response.status_code, 404)
        self.assertIn("request_id", after_delete_response.json())

        await self.mcp_client.aclose()

    async def test_creating_task_without_title_returns_400_with_request_id(self) -> None:
        response = await self.client.post("/tasks", json={"title": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertIn("request_id", response.json())

        await self.mcp_client.aclose()

    async def test_getting_unknown_task_returns_404_with_request_id(self) -> None:
        response = await self.client.get(f"/tasks/no-existe-{uuid.uuid4().hex[:8]}")

        self.assertEqual(response.status_code, 404)
        self.assertIn("request_id", response.json())

        await self.mcp_client.aclose()

    async def test_updating_task_with_empty_payload_returns_400(self) -> None:
        created = await self._create_task(f"Tarea E2E {uuid.uuid4().hex[:8]}")

        response = await self.client.patch(f"/tasks/{created['task_id']}", json={})

        self.assertEqual(response.status_code, 400)

        await self.mcp_client.aclose()


if __name__ == "__main__":
    unittest.main()
