import unittest

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.infrastructure.persistence.mongo.mongo_repository import MongoTaskRepository


class FakeRepository:
    def __init__(self):
        self.calls = []

    def list_active_tasks(self, status=None, limit=20):
        self.calls.append("list")
        return [{"task_id": "task-1", "title": "Tarea demo"}]


class TaskServiceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_tasks_async_returns_repository_results(self):
        repository = FakeRepository()
        service = TaskService(repository=repository)

        result = await service.list_tasks_async()

        self.assertEqual(result[0]["title"], "Tarea demo")
        self.assertEqual(repository.calls, ["list"])

    async def test_repository_uses_async_client_shape(self):
        repository = MongoTaskRepository(get_db_fn=lambda _db_name: None)

        self.assertTrue(hasattr(repository, "list_active_tasks_async"))


if __name__ == "__main__":
    unittest.main()
