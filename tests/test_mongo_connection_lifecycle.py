import asyncio
import unittest

from src.assistant_personal.application.agent.orchestrator import TaskOrchestrator
from src.assistant_personal.application.memory.agent_context import InMemorySessionRepository
from src.assistant_personal.application.tasks.task_service import TaskService
from src.assistant_personal.domain.entities import IntentAction, IntentDecision
from src.assistant_personal.infrastructure.persistence.mongo.client import MongoConnection
from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import MongoTaskRepository

# Mongo local desechable de docker-compose.yml (puerto 27018, no el 27017 estándar —
# ver comentario en docker-compose.yml). Nunca el Atlas real de `.env`: este test crea
# tareas de verdad y no debe ensuciar datos productivos.
LOCAL_MONGO_URI = "mongodb://localhost:27018"
LOCAL_DB_NAME = "assistant_personal_test"


def _build_local_connection() -> MongoConnection:
    return MongoConnection(mongo_uri=LOCAL_MONGO_URI, db_name=LOCAL_DB_NAME)


def _local_mongo_is_reachable() -> bool:
    async def _ping() -> bool:
        connection = _build_local_connection()
        try:
            db = await connection.get_db()
            await db.command("ping")
            return True
        except Exception:
            return False

    return asyncio.run(_ping())


class SequentialCreateTaskRouter:
    """Simula el router real emitiendo create_task en cada turno, como haría el CLI interactivo."""

    def __init__(self):
        self.turn = 0

    def extract_profile_facts(self, _message, context=None):
        return None

    def route(self, _message, context=None):
        self.turn += 1
        return IntentDecision(
            action=IntentAction.CREATE_TASK,
            payload={"title": f"tarea de regresion {self.turn}"},
            confidence=1.0,
            source="rule",
        )


@unittest.skipUnless(
    _local_mongo_is_reachable(),
    "Requiere el Mongo local desechable de docker-compose.yml: ejecuta `docker compose up -d mongo`",
)
class MongoConnectionLifecycleTests(unittest.TestCase):
    """`MongoConnection` solía crear su índice con `asyncio.run` a nivel de módulo,
    dejando el cliente de Motor ligado a un loop que se cerraba enseguida. Reusar
    ese cliente desde un loop distinto (el patrón real del CLI interactivo, que
    antes abría un `asyncio.run` por turno) fallaba con
    `RuntimeError: Event loop is closed`. Este test reproduce exactamente ese
    patrón: dos operaciones reales de Mongo, cada una en su propio `asyncio.run`,
    reutilizando la misma instancia de `MongoConnection` — contra el Mongo local
    desechable, nunca contra datos productivos.
    """

    def setUp(self) -> None:
        self.connection = _build_local_connection()

        async def _get_db(db_name):
            return await self.connection.get_db(db_name)

        repository = MongoTaskRepository(db_name=LOCAL_DB_NAME, get_db_fn=_get_db)
        self.service = TaskService(db_name=LOCAL_DB_NAME, repository=repository)

    def tearDown(self) -> None:
        async def _cleanup() -> None:
            db = await self.connection.get_db()
            await db.personal_tasks.delete_many({"title": {"$regex": "^tarea de regresion"}})

        asyncio.run(_cleanup())

    def test_repository_survives_multiple_independent_event_loops(self):
        orchestrator = TaskOrchestrator(
            service=self.service,
            router=SequentialCreateTaskRouter(),
            session_repository=InMemorySessionRepository(),
        )

        first = orchestrator.handle_message("crear tarea uno")
        second = orchestrator.handle_message("crear tarea dos")

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])


if __name__ == "__main__":
    unittest.main()
