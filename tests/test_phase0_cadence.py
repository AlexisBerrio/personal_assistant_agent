import asyncio
import unittest
from copy import deepcopy
from unittest.mock import patch

from src.assistant_personal.application.tasks.task_service import TaskService
from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import build_default_task_repository


class InMemoryTaskRepository:
    def __init__(self):
        self.tasks = []
        self.history = []

    def check_connection(self):
        return True

    async def list_active_tasks_async(self, status=None, limit=20):
        active = [deepcopy(task) for task in self.tasks if not task.get("is_deleted")]
        if status is not None:
            active = [task for task in active if task.get("status") == status]
        return active[:limit]

    async def get_task_by_id_async(self, task_id):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                return deepcopy(task)
        return None

    async def get_task_history_async(self, task_id):
        return [deepcopy(entry) for entry in self.history if entry.get("task_id") == task_id]

    async def create_task_async(self, payload):
        self.tasks.append(deepcopy(payload))
        return deepcopy(payload)

    async def update_task_async(self, task_id, updates):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                previous = deepcopy(task)
                task.update(updates)
                self.history.append({"task_id": task_id, "changes": [{"field": key, "previous_value": previous.get(key), "new_value": value} for key, value in updates.items()]})
                return deepcopy(task)
        return None

    async def complete_task_async(self, task_id):
        for task in self.tasks:
            if task.get("task_id") == task_id and not task.get("is_deleted"):
                previous = deepcopy(task)
                task["status"] = "Completed"
                self.history.append({"task_id": task_id, "changes": [{"field": "status", "previous_value": previous.get("status"), "new_value": "Completed"}]})
                return {"matched": 1, "modified": 1}
        return {"matched": 0, "modified": 0}

    async def delete_task_async(self, task_id):
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

        with patch("src.assistant_personal.application.tasks.task_service.build_default_task_repository", return_value=fake_repo) as mock_factory:
            service = TaskService()

        self.assertIs(service.repository, fake_repo)
        self.assertEqual(mock_factory.call_count, 1)
        self.assertEqual(mock_factory.call_args.kwargs["db_name"], "personal_management")
        self.assertIn("get_db_fn", mock_factory.call_args.kwargs)

    def test_service_flow_supports_create_list_update_complete_and_history(self):
        repository = InMemoryTaskRepository()
        service = TaskService(repository=repository)

        created = asyncio.run(service.create_task_async({"title": "Revisar plan", "status": "Pending"}))
        self.assertEqual(created["title"], "Revisar plan")

        listed = asyncio.run(service.list_tasks_async())
        self.assertEqual(len(listed), 1)

        updated = asyncio.run(service.update_task_async(created["task_id"], {"description": "Detalle actualizado"}))
        self.assertEqual(updated["description"], "Detalle actualizado")

        completed = asyncio.run(service.complete_task_async(created["task_id"]))
        self.assertEqual(completed["modified"], 1)

        history = asyncio.run(service.get_task_history_async(created["task_id"]))
        self.assertGreaterEqual(len(history), 2)

        self.assertEqual(build_default_task_repository.__name__, "build_default_task_repository")


if __name__ == "__main__":
    unittest.main()
