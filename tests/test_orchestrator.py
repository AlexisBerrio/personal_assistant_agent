import unittest

from src.assistant_personal.application.orchestrator import TaskOrchestrator
from src.assistant_personal.domain.entities import IntentAction, IntentDecision


class FakeRouter:
    def route(self, _message):
        return IntentDecision(
            action=IntentAction.ASK_KNOWLEDGE_BASE,
            payload={"query": "cual es la capital de colombia"},
            confidence=1.0,
            source="rule",
        )


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


class FlakyService(FakeService):
    def __init__(self):
        super().__init__()
        self.failures = 0

    def create_task(self, task):
        self.failures += 1
        if self.failures == 1:
            raise ValueError("transient error")
        return super().create_task(task)


class TaskOrchestratorTests(unittest.TestCase):
    def test_creates_task_through_the_orchestrator(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service)

        response = orchestrator.handle_message("crear una tarea para estudiar")

        self.assertTrue(response["success"])
        self.assertEqual(response["action"], "create_task")
        self.assertEqual(response["result"]["title"], "Tarea para estudiar")
        self.assertEqual(service.calls[0][0], "create")

    def test_retries_once_when_a_specialist_fails(self):
        service = FlakyService()
        orchestrator = TaskOrchestrator(service=service, max_retries=2)

        response = orchestrator.handle_message("crear una tarea para revisar")

        self.assertTrue(response["success"])
        self.assertEqual(service.failures, 2)
        self.assertEqual(response["result"]["title"], "Tarea para revisar")

    def test_guardrails_block_empty_requests(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service)

        response = orchestrator.handle_message("   ")

        self.assertFalse(response["success"])
        self.assertEqual(response["action"], "clarify")
        self.assertIn("guardrails", response["reason"].lower())

    def test_general_knowledge_queries_are_answered_without_the_central_agent(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service, router=FakeRouter())

        response = orchestrator.handle_message("cual es la capital de colombia")

        self.assertTrue(response["success"])
        self.assertEqual(response["action"], "ask_knowledge_base")
        self.assertIn("Consulta de conocimiento", response["result"])


if __name__ == "__main__":
    unittest.main()
