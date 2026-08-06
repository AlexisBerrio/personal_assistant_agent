import unittest

from src.assistant_personal.application.orchestrator import TaskOrchestrator


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


class MultiTurnContextTests(unittest.TestCase):
    def test_context_accumulates_previous_turns(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service)

        first = orchestrator.handle_message("crear una tarea para estudiar")
        second = orchestrator.handle_message("listar mis tareas")

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertIn("user:crear una tarea para estudiar", second["context"])
        self.assertIn("assistant:", second["context"])


if __name__ == "__main__":
    unittest.main()
