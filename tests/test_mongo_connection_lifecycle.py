import asyncio
import unittest

from src.assistant_personal.application.agent_context import InMemorySessionRepository
from src.assistant_personal.application.orchestrator import TaskOrchestrator
from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.entities import IntentAction, IntentDecision
from src.assistant_personal.infrastructure.persistence.mongo.client import mongo_connection


def _mongo_is_reachable() -> bool:
    async def _ping() -> bool:
        try:
            db = await mongo_connection.get_db()
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


@unittest.skipUnless(_mongo_is_reachable(), "Requiere conectividad real a MongoDB (MONGO_URI en .env)")
class MongoConnectionLifecycleTests(unittest.TestCase):
    """Regresión de docs/anexo_arquitectura_objetivo.md §A.9 (ítem 0.12).

    `MongoConnection` solía crear su índice con `asyncio.run` a nivel de módulo,
    dejando el cliente de Motor ligado a un loop que se cerraba enseguida. Reusar
    ese cliente desde un loop distinto (el patrón real del CLI interactivo, que
    antes abría un `asyncio.run` por turno) fallaba con
    `RuntimeError: Event loop is closed`. Este test reproduce exactamente ese
    patrón: dos operaciones reales de Mongo, cada una en su propio `asyncio.run`.
    """

    def test_repository_survives_multiple_independent_event_loops(self):
        service = TaskService()
        orchestrator = TaskOrchestrator(
            service=service,
            router=SequentialCreateTaskRouter(),
            session_repository=InMemorySessionRepository(),
        )

        first = orchestrator.handle_message("crear tarea uno")
        second = orchestrator.handle_message("crear tarea dos")

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])


if __name__ == "__main__":
    unittest.main()
