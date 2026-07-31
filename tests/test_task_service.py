import unittest
from unittest.mock import patch

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.task_models import Task


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeCollection:
    def __init__(self):
        self.last_insert_payload = None

    def insert_one(self, payload):
        self.last_insert_payload = payload
        return FakeInsertResult("abc123")


class FakeDatabase:
    def __init__(self):
        self.personal_tasks = FakeCollection()


class TaskServiceTests(unittest.TestCase):
    def test_create_task_converts_domain_model_to_plain_dictionary(self):
        fake_db = FakeDatabase()

        with patch("src.assistant_personal.application.task_service.get_db", return_value=fake_db):
            service = TaskService()
            task = Task(
                title="Comprar pan",
                description="Para el desayuno",
                status="In Progress",
                category="Personal",
                tags=["Home", "Morning"],
                priority={"level": "Medium", "score": 50},
                dates={"created_at": "2026-01-01T00:00:00", "due_date": "2026-01-02T00:00:00", "completed_at": None},
                recurrence={"is_recurring": False, "frequency": None},
                context_metadata={"source": "manual", "location_restriction": "Home", "estimated_minutes": 15},
                steps=[{"step_id": 1, "text": "Ir al supermercado", "is_completed": False}],
                agent_notes=[{"timestamp": "2026-01-01T08:00:00", "note": "Tarea creada desde la prueba"}],
            )
            result = service.create_task(task)

        self.assertEqual(result["inserted_id"], "abc123")
        self.assertIsInstance(fake_db.personal_tasks.last_insert_payload, dict)
        payload = fake_db.personal_tasks.last_insert_payload
        self.assertEqual(payload["title"], "Comprar pan")
        self.assertEqual(payload["category"], "Personal")
        self.assertEqual(payload["tags"], ["Home", "Morning"])
        self.assertEqual(payload["priority"]["level"], "Medium")
        self.assertEqual(payload["dates"]["due_date"], "2026-01-02T00:00:00")
        self.assertEqual(payload["recurrence"]["is_recurring"], False)
        self.assertEqual(payload["context_metadata"]["source"], "manual")
        self.assertEqual(payload["steps"][0]["text"], "Ir al supermercado")
        self.assertEqual(payload["agent_notes"][0]["note"], "Tarea creada desde la prueba")
        self.assertNotIn("source", payload)
        self.assertNotIn("due_date", payload)


if __name__ == "__main__":
    unittest.main()
