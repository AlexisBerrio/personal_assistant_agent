from __future__ import annotations

import asyncio
import unittest
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.infrastructure.persistence.mongo.client import MongoConnection
from src.assistant_personal.infrastructure.persistence.mongo.document_search_repository import (
    MongoTextSearchRepository,
)

LOCAL_MONGO_URI = "mongodb://localhost:27018"
# Puerto 27018: mismo motivo que en los demás tests de integración — evita ambigüedad con un
# MongoDB nativo corriendo como servicio de Windows. En CI apunta al service container de ci.yml.


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
class MongoTextSearchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Verifica el primer adaptador (no vectorial) del port `DocumentSearchRepository` contra el
    índice de texto real de Mongo, y que respeta el filtro de `tenant_id` (nunca mezclar
    resultados de tenants distintos, ni siquiera con el único tenant `"default"` de hoy).
    """

    async def asyncSetUp(self) -> None:
        self.db_name = "assistant_personal_test"
        # `MongoConnection` (no un `AsyncIOMotorClient` crudo): el índice de texto que `buscar`
        # necesita solo existe si algo llama a `get_db()`, que crea los índices de negocio la
        # primera vez (client.py._ensure_task_indexes) — igual que en producción.
        self.connection = MongoConnection(mongo_uri=LOCAL_MONGO_URI, db_name=self.db_name)
        self.client = self.connection.client
        self.suffix = uuid.uuid4().hex[:8]
        self.matching_task_id = f"search-match-{self.suffix}"
        self.other_tenant_task_id = f"search-other-tenant-{self.suffix}"
        await self.connection.get_db()  # fuerza la creación de índices antes de insertar/buscar

    async def asyncTearDown(self) -> None:
        db = self.client[self.db_name]
        await db.personal_tasks.delete_many({"task_id": {"$in": [self.matching_task_id, self.other_tenant_task_id]}})
        self.client.close()

    def _build_repository(self, tenant_id: str = "default") -> MongoTextSearchRepository:
        async def _get_db(db_name: str):
            return self.client[db_name]

        return MongoTextSearchRepository(db_name=self.db_name, get_db_fn=_get_db, tenant_id=tenant_id)

    async def test_buscar_encuentra_por_palabra_y_respeta_tenant(self) -> None:
        db = self.client[self.db_name]
        unique_word = f"presupuesto{self.suffix}"
        await db.personal_tasks.insert_many([
            {
                "task_id": self.matching_task_id,
                "tenant_id": "default",
                "title": f"Revisar {unique_word} anual",
                "description": "",
                "is_deleted": False,
            },
            {
                "task_id": self.other_tenant_task_id,
                "tenant_id": "otro-tenant",
                "title": f"Revisar {unique_word} anual",
                "description": "",
                "is_deleted": False,
            },
        ])

        repository = self._build_repository(tenant_id="default")
        results = await repository.buscar(unique_word)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["task_id"], self.matching_task_id)

    async def test_buscar_sin_coincidencias_devuelve_lista_vacia(self) -> None:
        repository = self._build_repository()
        results = await repository.buscar(f"palabra-inexistente-{self.suffix}")

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
