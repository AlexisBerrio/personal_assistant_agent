import unittest

from src.assistant_personal.application.agent.orchestrator import TaskOrchestrator
from src.assistant_personal.domain.entities import IntentAction, IntentDecision, UserProfileExtraction
from src.assistant_personal.infrastructure.persistence.mongo.session_repository import MongoSessionRepository


def _make_async_get_db(fake_db):
    """Simula la forma async real de `get_db` (Motor): una coroutine, no un valor plano."""
    async def _get_db(_db_name):
        return fake_db
    return _get_db


class FakeService:
    def __init__(self):
        self.calls = []

    def list_tasks(self):
        self.calls.append(("list", None))
        return [{"title": "Tarea inicial"}]

    def create_task(self, task):
        self.calls.append(("create", task))
        return {"title": task["title"], "status": "Pending"}

    def complete_task(self, task_id):
        self.calls.append(("complete", task_id))
        return {"task_id": task_id, "status": "Completed"}


class FakeConversationRouter:
    def __init__(self):
        self.calls = 0

    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction()

    def route(self, message, context=None):
        self.calls += 1
        if self.calls == 1:
            return IntentDecision(
                action=IntentAction.CREATE_TASK,
                payload={"title": "Tarea para estudiar"},
                confidence=1.0,
                source="rule",
            )
        return IntentDecision(
            action=IntentAction.LIST_TASKS,
            payload={},
            confidence=1.0,
            source="rule",
        )


class FakeSessionCollection:
    """Simula la forma async real de una colección Motor: los métodos devuelven coroutines."""

    def __init__(self):
        self.docs = {}

    async def find_one(self, filter_query):
        return self.docs.get(filter_query.get("session_id"))

    async def update_one(self, filter_query, update, upsert=False):
        session_id = filter_query.get("session_id")
        current = self.docs.get(session_id, {})
        if "$set" in update:
            current.update(update["$set"])
        if "$setOnInsert" in update:
            current.setdefault("created_at", update["$setOnInsert"].get("created_at"))
        self.docs[session_id] = current
        return type("Result", (), {"matched_count": 1, "modified_count": 1})()


class MultiTurnContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_accumulates_previous_turns_in_repository(self):
        """Regresión del bug de bridging sync/async: corre dentro de un event loop real,
        igual que el camino de FastAPI, para asegurar que la memoria de sesión persiste
        en vez de fallar en silencio."""
        service = FakeService()
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))
        orchestrator = TaskOrchestrator(service=service, router=FakeConversationRouter(), session_repository=repository, session_id="session-test")

        first = await orchestrator.handle_message_async("crear una tarea para estudiar")
        second = await orchestrator.handle_message_async("listar mis tareas")

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        summary = await repository.get_context_summary_async("session-test")
        self.assertEqual(len(summary["turns"]), 2)
        self.assertEqual(summary["turns"][0]["user_message"], "crear una tarea para estudiar")
        self.assertIn("Tarea creada", summary["turns"][0]["assistant_response"])


if __name__ == "__main__":
    unittest.main()
