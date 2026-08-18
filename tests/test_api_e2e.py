from __future__ import annotations

import asyncio
import unittest
import uuid

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from app import app, get_service
from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.infrastructure.persistence.mongo.client import MongoConnection
from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import MongoTaskRepository

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
    """Regresión de docs/anexo_arquitectura_objetivo.md §A.12 (ítem 1.9).

    Ejercita `app.py` completo por HTTP con `httpx.AsyncClient` (no `TestClient` síncrono):
    middleware de `request_id`, exception handlers de 0.11 y el flujo CRUD real contra Mongo.

    Crítico: `httpx.ASGITransport` NUNCA dispara el `lifespan` de FastAPI, así que
    `get_service` caería a su fallback (`TaskService()` sin argumentos → Mongo de `.env`,
    potencialmente Atlas de producción — el mismo incidente de §A.9, ítem 0.13). Por eso este
    test sustituye `app.dependency_overrides[get_service]` por un servicio explícitamente
    apuntado al Mongo local desechable, antes de enviar una sola petición.
    """

    db_name = "assistant_personal_test"

    async def asyncSetUp(self) -> None:
        self.connection = MongoConnection(mongo_uri=LOCAL_MONGO_URI, db_name=self.db_name)

        async def _get_db(db_name: str):
            return await self.connection.get_db(db_name)

        repository = MongoTaskRepository(db_name=self.db_name, get_db_fn=_get_db)
        self.test_service = TaskService(db_name=self.db_name, repository=repository)
        app.dependency_overrides[get_service] = lambda: self.test_service

        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.created_task_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_service, None)
        await self.client.aclose()

        db = self.connection.client[self.db_name]
        if self.created_task_ids:
            await db.personal_tasks.delete_many({"task_id": {"$in": self.created_task_ids}})
            await db.task_history.delete_many({"task_id": {"$in": self.created_task_ids}})

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

    async def test_creating_task_without_title_returns_400_with_request_id(self) -> None:
        response = await self.client.post("/tasks", json={"title": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertIn("request_id", response.json())

    async def test_getting_unknown_task_returns_404_with_request_id(self) -> None:
        response = await self.client.get(f"/tasks/no-existe-{uuid.uuid4().hex[:8]}")

        self.assertEqual(response.status_code, 404)
        self.assertIn("request_id", response.json())

    async def test_updating_task_with_empty_payload_returns_400(self) -> None:
        created = await self._create_task(f"Tarea E2E {uuid.uuid4().hex[:8]}")

        response = await self.client.patch(f"/tasks/{created['task_id']}", json={})

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
