import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.task_models import Task


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count=1, modified_count=1):
        self.matched_count = matched_count
        self.modified_count = modified_count


class FakeHistoryCollection:
    def __init__(self):
        self.inserted_docs = []

    def insert_one(self, payload):
        self.inserted_docs.append(payload)
        return FakeInsertResult("hist123")


class FakeCollection:
    def __init__(self):
        self.last_insert_payload = None
        self.last_update_payload = None
        self.last_update_filter = None
        self.doc = None

    def insert_one(self, payload):
        self.last_insert_payload = payload
        return FakeInsertResult("abc123")

    def update_one(self, filter, update):
        self.last_update_filter = filter
        self.last_update_payload = update
        return FakeUpdateResult()

    def find_one(self, filter=None, projection=None):
        return self.doc


class FakeDatabase:
    def __init__(self):
        self.personal_tasks = FakeCollection()
        self.task_history = FakeHistoryCollection()


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
        self.assertTrue(result["task_id"])
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

    def test_list_tasks_serializes_datetime_values_for_api(self):
        fake_db = FakeDatabase()
        fake_db.personal_tasks.docs = [{
            "title": "Tarea con fecha",
            "description": "Demo",
            "status": "In Progress",
            "category": "Work",
            "tags": ["demo"],
            "priority": {"level": "High", "score": 90},
            "dates": {"created_at": datetime(2026, 5, 21, 8, 30), "due_date": datetime(2026, 5, 24, 18, 0), "completed_at": None},
            "recurrence": {"is_recurring": False, "frequency": None},
            "context_metadata": {"source": "Alexa"},
            "steps": [],
            "agent_notes": [],
        }]

        class FakeCursor:
            def __init__(self, docs):
                self.docs = docs

            def __iter__(self):
                return iter(self.docs)

            def limit(self, _limit):
                return self

        class FakeListCollection(FakeCollection):
            def find(self, *_args, **_kwargs):
                return FakeCursor(self.docs)

        fake_db.personal_tasks = FakeListCollection()
        fake_db.personal_tasks.docs = [{
            "title": "Tarea con fecha",
            "description": "Demo",
            "status": "In Progress",
            "category": "Work",
            "tags": ["demo"],
            "priority": {"level": "High", "score": 90},
            "dates": {"created_at": datetime(2026, 5, 21, 8, 30), "due_date": datetime(2026, 5, 24, 18, 0), "completed_at": None},
            "recurrence": {"is_recurring": False, "frequency": None},
            "context_metadata": {"source": "Alexa"},
            "steps": [],
            "agent_notes": [],
        }]

        with patch("src.assistant_personal.application.task_service.get_db", return_value=fake_db):
            service = TaskService()
            result = service.list_tasks()

        self.assertEqual(result[0]["dates"]["created_at"], "2026-05-21T08:30:00")
        self.assertEqual(result[0]["dates"]["due_date"], "2026-05-24T18:00:00")
        self.assertEqual(result[0]["dates"]["completed_at"], None)

    def test_service_can_use_an_injected_repository(self):
        class FakeRepository:
            def __init__(self):
                self.calls = []

            def list_active_tasks(self):
                self.calls.append("list")
                return [{"task_id": "task-123", "title": "Tarea desde repositorio"}]

        repository = FakeRepository()
        service = TaskService(repository=repository)

        result = service.list_tasks()

        self.assertEqual(result[0]["title"], "Tarea desde repositorio")
        self.assertEqual(repository.calls, ["list"])

    def test_get_task_by_id_endpoint_calls_service(self):
        with patch("app.service.get_task", return_value={"title": "Tarea demo", "task_id": "task-123"}) as mock_get_task:
            client = TestClient(app)
            response = client.get("/tasks/task-123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"title": "Tarea demo", "task_id": "task-123"})
        mock_get_task.assert_called_once_with("task-123")

    def test_get_task_history_endpoint_calls_service(self):
        with patch("app.service.get_task_history", return_value=[{"task_id": "task-123", "changes": []}]) as mock_get_history:
            client = TestClient(app)
            response = client.get("/tasks/task-123/history")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"task_id": "task-123", "changes": []}])
        mock_get_history.assert_called_once_with("task-123")

    def test_update_task_endpoint_calls_service(self):
        with patch("app.service.update_task", return_value={"task_id": "task-123", "title": "Actualizada"}) as mock_update_task:
            client = TestClient(app)
            response = client.patch("/tasks/task-123", json={"title": "Actualizada"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"task_id": "task-123", "title": "Actualizada"})
        mock_update_task.assert_called_once_with("task-123", {"title": "Actualizada"})

    def test_task_domain_model_marks_pending_tasks_as_in_progress_on_update(self):
        task = Task(title="Tarea pendiente", status="Pending")

        task.apply_updates({"description": "Actualizada"})

        self.assertEqual(task.status, "In Progress")

    def test_update_task_endpoint_accepts_steps_dates_and_recurrence(self):
        with patch("app.service.update_task", return_value={"task_id": "task-123", "steps": [{"step_id": 1, "text": "Revisar", "is_completed": False}]}) as mock_update_task:
            client = TestClient(app)
            response = client.patch(
                "/tasks/task-123",
                json={
                    "steps": [{"step_id": 1, "text": "Revisar", "is_completed": False}],
                    "dates": {"due_date": "2026-08-05T12:00:00"},
                    "recurrence": {"is_recurring": False, "frequency": None},
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_update_task.assert_called_once_with(
            "task-123",
            {
                "steps": [{"step_id": 1, "text": "Revisar", "is_completed": False}],
                "dates": {"due_date": "2026-08-05T12:00:00"},
                "recurrence": {"is_recurring": False, "frequency": None},
            },
        )

    def test_complete_task_endpoint_calls_service(self):
        with patch("app.service.complete_task", return_value={"matched": 1, "modified": 1}) as mock_complete_task:
            client = TestClient(app)
            response = client.patch("/tasks/task-123", json={"status": "Completed"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"matched": 1, "modified": 1})
        mock_complete_task.assert_called_once_with("task-123")

    def test_create_task_rejects_blank_title(self):
        service = TaskService()
        with self.assertRaises(ValueError) as context:
            service.create_task(Task(title="   "))

        self.assertIn("título", str(context.exception).lower())

    def test_create_task_uses_pending_as_default_status(self):
        fake_db = FakeDatabase()

        with patch("src.assistant_personal.application.task_service.get_db", return_value=fake_db):
            service = TaskService()
            service.create_task(Task(title="Nueva tarea"))

        self.assertEqual(fake_db.personal_tasks.last_insert_payload["status"], "Pending")

    def test_update_task_marks_task_as_in_progress_when_modified(self):
        fake_db = FakeDatabase()
        fake_db.personal_tasks.doc = {
            "task_id": "task-123",
            "title": "Tarea pendiente",
            "status": "Pending",
            "is_deleted": False,
            "deleted_at": None,
        }

        with patch("src.assistant_personal.application.task_service.get_db", return_value=fake_db):
            service = TaskService()
            service.update_task("task-123", {"description": "Actualizada"})

        self.assertEqual(fake_db.personal_tasks.last_update_payload["$set"]["status"], "In Progress")

    def test_create_task_rejects_invalid_priority(self):
        service = TaskService()
        with self.assertRaises(ValueError) as context:
            service.create_task({"title": "Tarea", "priority": "Critical"})

        self.assertIn("prioridad", str(context.exception).lower())

    def test_create_task_rejects_invalid_category(self):
        service = TaskService()
        with self.assertRaises(ValueError) as context:
            service.create_task({"title": "Tarea", "category": "Unknown"})

        self.assertIn("categoría", str(context.exception).lower())

    def test_delete_task_endpoint_calls_service(self):
        with patch("app.service.delete_task", return_value={"task_id": "task-123", "deleted": True}) as mock_delete_task:
            client = TestClient(app)
            response = client.delete("/tasks/task-123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"task_id": "task-123", "deleted": True})
        mock_delete_task.assert_called_once_with("task-123")


if __name__ == "__main__":
    unittest.main()
