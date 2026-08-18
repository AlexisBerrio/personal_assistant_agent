from __future__ import annotations

import asyncio
import unittest
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import MongoTaskRepository

LOCAL_MONGO_URI = "mongodb://localhost:27018"
# Puerto 27018, no el 27017 estándar: mismo motivo que en test_session_memory_integration.py —
# evita ambigüedad con un MongoDB nativo corriendo como servicio de Windows en la máquina de
# desarrollo. En CI apunta al service container de ci.yml, mapeado al mismo puerto.


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
class MongoTaskRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Regresión de docs/anexo_arquitectura_objetivo.md §A.12 (ítem 1.4).

    `Este test ejercita el ciclo completo de una tarea contra el Mongo local desechable,
    nunca contra Atlas.`
    """

    async def asyncSetUp(self) -> None:
        self.client = AsyncIOMotorClient(LOCAL_MONGO_URI, serverSelectionTimeoutMS=2000)
        self.db_name = "assistant_personal_test"
        self.task_id = f"integration-{uuid.uuid4()}"

    async def asyncTearDown(self) -> None:
        db = self.client[self.db_name]
        await db.personal_tasks.delete_many({"task_id": self.task_id})
        await db.task_history.delete_many({"task_id": self.task_id})
        self.client.close()

    def _build_repository(self) -> MongoTaskRepository:
        async def _get_db(db_name: str):
            return self.client[db_name]

        return MongoTaskRepository(db_name=self.db_name, get_db_fn=_get_db)

    async def test_task_lifecycle_persists_across_repository_instances(self) -> None:
        create_repository = self._build_repository()
        created = await create_repository.create_task_async(
            {"task_id": self.task_id, "title": "Tarea de integración", "status": "Pending"}
        )
        self.assertEqual(created["task_id"], self.task_id)

        read_repository = self._build_repository()
        fetched = await read_repository.get_task_by_id_async(self.task_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Tarea de integración")

        active_tasks = await read_repository.list_active_tasks_async()
        self.assertTrue(any(task["task_id"] == self.task_id for task in active_tasks))

        update_repository = self._build_repository()
        updated = await update_repository.update_task_async(self.task_id, {"title": "Tarea actualizada"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated["title"], "Tarea actualizada")

        complete_repository = self._build_repository()
        completion_result = await complete_repository.complete_task_async(self.task_id)
        self.assertEqual(completion_result["matched"], 1)

        history_repository = self._build_repository()
        history = await history_repository.get_task_history_async(self.task_id)
        changed_fields = {change["field"] for entry in history for change in entry["changes"]}
        self.assertIn("title", changed_fields)
        self.assertIn("status", changed_fields)

        delete_repository = self._build_repository()
        deletion_result = await delete_repository.delete_task_async(self.task_id)
        self.assertIsNotNone(deletion_result)
        self.assertEqual(deletion_result["task_id"], self.task_id)

        after_delete_repository = self._build_repository()
        after_delete = await after_delete_repository.get_task_by_id_async(self.task_id)
        self.assertIsNone(after_delete, "El borrado es lógico: no debe aparecer entre las tareas activas")

        raw_doc = await self.client[self.db_name].personal_tasks.find_one({"task_id": self.task_id})
        self.assertIsNotNone(raw_doc, "El borrado lógico no debe eliminar el documento físicamente")
        self.assertTrue(raw_doc["is_deleted"])


if __name__ == "__main__":
    unittest.main()
