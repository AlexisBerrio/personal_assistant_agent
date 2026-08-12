import unittest
from copy import deepcopy
from unittest.mock import patch

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.infrastructure.task_repository import build_default_task_repository


class InMemoryTaskRepository:
    def __init__(self):
        self.tasks = []
        self.history = []

    def check_connection(self):
        return True

    def list_active_tasks(self):
        return [deepcopy(task) for task in self.tasks if not task.get("is_deleted")]

    def get_task_by_id(self, task_id):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                return deepcopy(task)
        return None

    def get_task_history(self, task_id):
        return [deepcopy(entry) for entry in self.history if entry.get("task_id") == task_id]

    def create_task(self, payload):
        self.tasks.append(deepcopy(payload))
        return deepcopy(payload)

    def update_task(self, task_id, updates):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                previous = deepcopy(task)
                task.update(updates)
                self.history.append({"task_id": task_id, "changes": [{"field": key, "previous_value": previous.get(key), "new_value": value} for key, value in updates.items()]})
                return deepcopy(task)
        return None

    def complete_task(self, task_id):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                previous = deepcopy(task)
                task["status"] = "Completed"
                self.history.append({"task_id": task_id, "changes": [{"field": "status", "previous_value": previous.get("status"), "new_value": "Completed"}]})
                return {"matched": 1, "modified": 1}
        return {"matched": 0, "modified": 0}

    def delete_task(self, task_id):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                task["is_deleted"] = True
                task["status"] = "Deleted"
                self.history.append({"task_id": task_id, "changes": [{"field": "status", "previous_value": task.get("status"), "new_value": "Deleted"}]})
                return {"task_id": task_id, "deleted": True}
        return None


class Phase0CadenceTests(unittest.TestCase):
    def test_task_service_uses_infrastructure_repository_factory_by_default(self):
        fake_repo = object()

        with patch("src.assistant_personal.application.task_service.build_default_task_repository", return_value=fake_repo) as mock_factory:
            service = TaskService()

        self.assertIs(service.repository, fake_repo)
        self.assertEqual(mock_factory.call_count, 1)
        self.assertEqual(mock_factory.call_args.kwargs["db_name"], "personal_management")
        self.assertIn("get_db_fn", mock_factory.call_args.kwargs)

    def test_service_flow_supports_create_list_update_complete_and_history(self):
        repository = InMemoryTaskRepository()
        service = TaskService(repository=repository)

        created = service.create_task({"title": "Revisar plan", "status": "Pending"})
        self.assertEqual(created["title"], "Revisar plan")

        listed = service.list_tasks()
        self.assertEqual(len(listed), 1)

        updated = service.update_task(created["task_id"], {"description": "Detalle actualizado"})
        self.assertEqual(updated["description"], "Detalle actualizado")

        completed = service.complete_task(created["task_id"])
        self.assertEqual(completed["modified"], 1)

        history = service.get_task_history(created["task_id"])
        self.assertGreaterEqual(len(history), 2)

        self.assertEqual(build_default_task_repository.__name__, "build_default_task_repository")


if __name__ == "__main__":
    unittest.main()
