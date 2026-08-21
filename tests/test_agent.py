import unittest

from src.assistant_personal.application.agent.agent import Agent
from src.assistant_personal.application.agent.guardrails import Guardrails, GuardrailsConfig, build_default_guardrails
from src.assistant_personal.domain.entities import TaskReferenceResolution


class FakeService:
    def __init__(self, tasks):
        self._tasks = tasks

    async def list_tasks_async(self, status=None, limit=20):
        return self._tasks


class FakeResolver:
    def __init__(self, task_id=None, confidence=0.0, reasoning=None):
        self.calls = []
        self._task_id = task_id
        self._confidence = confidence
        self._reasoning = reasoning

    async def resolve_task_reference(self, task_reference, candidate_tasks):
        self.calls.append((task_reference, candidate_tasks))
        return TaskReferenceResolution(task_id=self._task_id, confidence=self._confidence, reasoning=self._reasoning)


_ACTIVE_TASKS = [
    {"task_id": "t-1", "title": "Llamar al banco", "status": "Pending"},
    {"task_id": "t-2", "title": "Ir al dentista", "status": "Pending"},
    {"task_id": "t-3", "title": "Tarea eliminada", "status": "Deleted"},
]


class AgentResolveTaskReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_a_confident_match(self):
        service = FakeService(_ACTIVE_TASKS)
        resolver = FakeResolver(task_id="t-2", confidence=0.9)
        agent = Agent(service=service, resolver=resolver, guardrails=build_default_guardrails())

        result = await agent.resolve_task_reference_to_id("la tarea del dentista")

        self.assertTrue(result.resolved)
        self.assertEqual(result.task_id, "t-2")
        self.assertEqual(result.task_title, "Ir al dentista")

    async def test_only_sends_active_tasks_as_candidates(self):
        """Las tareas ya eliminadas no deben ofrecerse como candidatas — no tiene sentido
        resolver una referencia hacia algo que ya no existe para el usuario."""
        service = FakeService(_ACTIVE_TASKS)
        resolver = FakeResolver(task_id="t-2", confidence=0.9)
        agent = Agent(service=service, resolver=resolver, guardrails=build_default_guardrails())

        await agent.resolve_task_reference_to_id("la tarea del dentista")

        _, candidates = resolver.calls[0]
        self.assertEqual({task["task_id"] for task in candidates}, {"t-1", "t-2"})

    async def test_does_not_resolve_below_the_confidence_threshold(self):
        service = FakeService(_ACTIVE_TASKS)
        resolver = FakeResolver(task_id="t-2", confidence=0.4)
        agent = Agent(service=service, resolver=resolver, guardrails=build_default_guardrails())

        result = await agent.resolve_task_reference_to_id("algo ambiguo")

        self.assertFalse(result.resolved)
        self.assertIsNotNone(result.message)

    async def test_does_not_resolve_when_the_resolver_finds_no_match(self):
        service = FakeService(_ACTIVE_TASKS)
        resolver = FakeResolver(task_id=None, confidence=0.0)
        agent = Agent(service=service, resolver=resolver, guardrails=build_default_guardrails())

        result = await agent.resolve_task_reference_to_id("una tarea que no existe")

        self.assertFalse(result.resolved)
        self.assertIsNotNone(result.message)

    async def test_returns_a_message_when_there_are_no_active_tasks_at_all(self):
        service = FakeService([])
        resolver = FakeResolver()
        agent = Agent(service=service, resolver=resolver, guardrails=build_default_guardrails())

        result = await agent.resolve_task_reference_to_id("cualquier cosa")

        self.assertFalse(result.resolved)
        self.assertIsNotNone(result.message)
        self.assertEqual(resolver.calls, [])  # no vale la pena llamar al LLM sin candidatos

    async def test_denies_the_lookup_when_the_tool_is_not_whitelisted(self):
        service = FakeService(_ACTIVE_TASKS)
        resolver = FakeResolver(task_id="t-2", confidence=0.9)
        empty_guardrails = Guardrails(GuardrailsConfig(allowed_tools=frozenset(), write_tools=frozenset()))
        agent = Agent(service=service, resolver=resolver, guardrails=empty_guardrails)

        result = await agent.resolve_task_reference_to_id("la tarea del dentista")

        self.assertFalse(result.resolved)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
