from __future__ import annotations

import asyncio
import unittest
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.domain.entities import UserProfileFact
from src.assistant_personal.infrastructure.persistence.mongo.long_term_memory_repository import (
    MongoLongTermMemoryRepository,
)

LOCAL_MONGO_URI = "mongodb://localhost:27018"
# Mismo criterio que tests/test_session_memory_integration.py: puerto 27018 del contenedor
# desechable de docker-compose.yml, nunca el 27017 estándar ni el Atlas de `.env`.


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
class LongTermMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Contra un MongoDB real: escribe un hecho de perfil con una instancia de
    `MongoLongTermMemoryRepository` y lo lee con una segunda instancia — simula un reinicio de
    proceso, el mismo patrón que `test_session_memory_integration.py` usa para memoria de sesión.
    """

    async def asyncSetUp(self) -> None:
        self.client = AsyncIOMotorClient(LOCAL_MONGO_URI, serverSelectionTimeoutMS=2000)
        self.db_name = "assistant_personal_test"
        self.user_id = f"integration-{uuid.uuid4()}"

    async def asyncTearDown(self) -> None:
        await self.client[self.db_name].user_profile_facts.delete_many({"user_id": self.user_id})
        self.client.close()

    def _build_repository(self) -> MongoLongTermMemoryRepository:
        async def _get_db(db_name: str):
            return self.client[db_name]

        return MongoLongTermMemoryRepository(db_name=self.db_name, get_db_fn=_get_db)

    async def test_fact_written_by_one_instance_survives_a_simulated_restart(self) -> None:
        first_repository = self._build_repository()
        await first_repository.upsert_fact_async(
            self.user_id, UserProfileFact(key="color_favorito", value="Azul", confidence=0.9), source="llm_extraction"
        )

        second_repository = self._build_repository()
        facts = await second_repository.get_facts_async(self.user_id)

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].key, "color_favorito")
        self.assertEqual(facts[0].value, "Azul")

    async def test_upsert_with_same_key_updates_instead_of_duplicating(self) -> None:
        repository = self._build_repository()
        await repository.upsert_fact_async(self.user_id, UserProfileFact(key="ciudad", value="Bogotá", confidence=0.9))
        await repository.upsert_fact_async(self.user_id, UserProfileFact(key="ciudad", value="Medellín", confidence=0.9))

        facts = await repository.get_facts_async(self.user_id)

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].value, "Medellín")

    async def test_delete_facts_removes_all_facts_for_the_user(self) -> None:
        repository = self._build_repository()
        await repository.upsert_fact_async(self.user_id, UserProfileFact(key="ciudad", value="Bogotá", confidence=0.9))
        await repository.upsert_fact_async(self.user_id, UserProfileFact(key="idioma", value="Español", confidence=0.9))

        deleted = await repository.delete_facts_async(self.user_id)
        facts_after_delete = await repository.get_facts_async(self.user_id)

        self.assertEqual(deleted, 2)
        self.assertEqual(facts_after_delete, [])


if __name__ == "__main__":
    unittest.main()
