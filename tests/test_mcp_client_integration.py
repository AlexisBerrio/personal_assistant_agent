from __future__ import annotations

import asyncio
import os
import unittest
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.infrastructure.mcp.client import McpTaskServiceClient

LOCAL_MONGO_URI = "mongodb://localhost:27018"
# Puerto 27018, no el 27017 estándar: mismo motivo que en test_session_memory_integration.py.


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
class McpTaskServiceClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Ejercita el protocolo MCP real de punta a punta: spawnea `mongo_mcp_server.py` como
    subproceso real por stdio y llama a sus tools, contra el Mongo local desechable — nunca
    contra el Atlas de `.env` (el subproceso recibe un entorno explícito con `MONGO_URI`
    apuntado al Mongo local). Es la prueba de que "MCP como única vía" funciona de verdad, no
    solo en teoría (ítem 3.1)."""

    def setUp(self) -> None:
        self.db_name = "assistant_personal_test"
        self.env = {**os.environ, "MONGO_URI": LOCAL_MONGO_URI, "MONGO_DB_NAME": self.db_name}
        self.client = McpTaskServiceClient(env=self.env)

    async def asyncTearDown(self) -> None:
        # `aclose()` NO va aquí: anyio exige que un cancel scope se cierre en la misma task en la
        # que se abrió, y `asyncTearDown` corre en una task distinta a la del test bajo
        # `IsolatedAsyncioTestCase` — cerrar el cliente al final del propio test evita el
        # `RuntimeError: Attempted to exit cancel scope in a different task`.
        motor_client = AsyncIOMotorClient(LOCAL_MONGO_URI)
        await motor_client[self.db_name].personal_tasks.delete_many({"title": {"$regex": "^mcp-e2e-"}})
        motor_client.close()

    async def test_create_list_and_complete_a_task_through_the_real_mcp_protocol(self) -> None:
        title = f"mcp-e2e-{uuid.uuid4()}"

        created = await self.client.create_task_async({"title": title})
        self.assertEqual(created["title"], title)
        task_id = created["task_id"]

        tasks = await self.client.list_tasks_async()
        self.assertTrue(any(t["task_id"] == task_id for t in tasks))

        completed = await self.client.complete_task_async(task_id)
        self.assertEqual(completed["matched"], 1)
        self.assertEqual(completed["modified"], 1)

        await self.client.aclose()


if __name__ == "__main__":
    unittest.main()
