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
            task = Task(title="Comprar pan", description="Para el desayuno", priority="high")
            result = service.create_task(task)

        self.assertEqual(result["inserted_id"], "abc123")
        self.assertIsInstance(fake_db.personal_tasks.last_insert_payload, dict)
        self.assertEqual(fake_db.personal_tasks.last_insert_payload["title"], "Comprar pan")
        self.assertEqual(fake_db.personal_tasks.last_insert_payload["priority"], "high")


if __name__ == "__main__":
    unittest.main()
