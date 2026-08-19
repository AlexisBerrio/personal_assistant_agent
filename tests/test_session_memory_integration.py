from __future__ import annotations

import asyncio
import unittest
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.infrastructure.persistence.mongo.session_repository import MongoSessionRepository

LOCAL_MONGO_URI = "mongodb://localhost:27018"
# Puerto 27018, no el 27017 estándar: evita ambigüedad si además hay un MongoDB
# nativo corriendo como servicio de Windows en la máquina de desarrollo (ver
# docker-compose.yml). Con 27017 este test podría "pasar" hablando con ese
# servicio en vez de con el contenedor desechable, sin que nadie lo note.


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
class SessionMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Contra un MongoDB real (el contenedor desechable de `docker-compose.yml`,
    nunca el Atlas de `.env`): escribe un turno "en una petición" y lo lee "en
    otra" (una segunda instancia de `MongoSessionRepository`, el mismo patrón
    que tendría cada request de FastAPI reutilizando el cliente singleton de
    Mongo). Es la única clase de test que detecta de verdad el bug de bridging
    sync/async — un mock nunca lo habría hecho, porque
    nunca devuelve una coroutine real dentro de un event loop activo.
    """

    async def asyncSetUp(self) -> None:
        self.client = AsyncIOMotorClient(LOCAL_MONGO_URI, serverSelectionTimeoutMS=2000)
        self.db_name = "assistant_personal_test"
        self.session_id = f"integration-{uuid.uuid4()}"

    async def asyncTearDown(self) -> None:
        await self.client[self.db_name].conversation_sessions.delete_many({"session_id": self.session_id})
        self.client.close()

    def _build_repository(self) -> MongoSessionRepository:
        async def _get_db(db_name: str):
            return self.client[db_name]

        return MongoSessionRepository(db_name=self.db_name, get_db_fn=_get_db)

    async def test_turn_written_in_one_request_is_read_in_another(self) -> None:
        first_repository = self._build_repository()
        await first_repository.append_turn_async(
            self.session_id, "hola, soy Alexis", "hola Alexis, ¿en qué te ayudo?"
        )

        second_repository = self._build_repository()
        summary = await second_repository.get_context_summary_async(self.session_id)

        self.assertEqual(len(summary["turns"]), 1)
        self.assertEqual(summary["turns"][0]["user_message"], "hola, soy Alexis")
        self.assertEqual(summary["turns"][0]["assistant_response"], "hola Alexis, ¿en qué te ayudo?")

    async def test_context_items_persist_across_repository_instances(self) -> None:
        first_repository = self._build_repository()
        await first_repository.add_context_item_async(self.session_id, "nombre", "Alexis")

        second_repository = self._build_repository()
        summary = await second_repository.get_context_summary_async(self.session_id)

        self.assertTrue(
            any(item["key"] == "nombre" and item["value"] == "Alexis" for item in summary["items"])
        )

    async def test_compact_session_persists_summary_and_trims_turns(self) -> None:
        """El resumen incremental de sesión debe persistir contra Mongo real, igual que
        el resto de la memoria de sesión."""
        first_repository = self._build_repository()
        for i in range(3):
            await first_repository.append_turn_async(self.session_id, f"mensaje {i}", f"respuesta {i}")

        await first_repository.compact_session_async(
            self.session_id, "el usuario habló de tres cosas distintas", keep_last_turns=1
        )

        second_repository = self._build_repository()
        summary = await second_repository.get_context_summary_async(self.session_id)

        self.assertEqual(summary["summary"], "el usuario habló de tres cosas distintas")
        self.assertEqual(len(summary["turns"]), 1)
        self.assertEqual(summary["turns"][0]["user_message"], "mensaje 2")


if __name__ == "__main__":
    unittest.main()
