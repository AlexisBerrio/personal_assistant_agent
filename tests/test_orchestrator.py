import unittest

import structlog

from src.assistant_personal.application.agent.orchestrator import TaskOrchestrator
from src.assistant_personal.application.memory.agent_context import ShortTermMemory
from src.assistant_personal.domain.entities import IntentAction, IntentDecision, UserProfileExtraction, UserProfileFact
from src.assistant_personal.infrastructure.persistence.mongo.session_repository import MongoSessionRepository


def _make_async_get_db(fake_db):
    """Simula la forma async real de `get_db` (Motor): una coroutine, no un valor plano."""
    async def _get_db(_db_name):
        return fake_db
    return _get_db


class FakeRouter:
    def route(self, _message, context=None):
        return IntentDecision(
            action=IntentAction.ASK_KNOWLEDGE_BASE,
            payload={"query": "cual es la capital de colombia"},
            confidence=1.0,
            source="rule",
        )


class FakeContextRouter:
    def __init__(self):
        self.received_contexts = []

    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction(profile_facts=[UserProfileFact(key="name", value="Alexis", confidence=1.0)])

    def route(self, _message, context=None):
        self.received_contexts.append(context)
        if context and "name=Alexis" in context:
            return IntentDecision(
                action=IntentAction.ASK_KNOWLEDGE_BASE,
                payload={"answer": "Tu nombre es Alexis."},
                confidence=1.0,
                source="rule",
            )
        return IntentDecision(
            action=IntentAction.CLARIFY,
            payload={"message": "No pude responder"},
            confidence=0.0,
            source="rule",
        )


class FakeSmallTalkRouter:
    def route(self, _message, context=None):
        return IntentDecision(
            action=IntentAction.SMALL_TALK,
            payload={"reply": "Hola, todo bien."},
            confidence=1.0,
            source="rule",
        )


class FakeGenericContextRouter:
    def __init__(self):
        self.received_contexts = []

    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction(profile_facts=[UserProfileFact(key="color_favorito", value="Azul", confidence=1.0)])

    def route(self, _message, context=None):
        self.received_contexts.append(context)
        if context and "color_favorito=Azul" in context:
            return IntentDecision(
                action=IntentAction.ASK_KNOWLEDGE_BASE,
                payload={"answer": "Tu color favorito es Azul."},
                confidence=1.0,
                source="rule",
            )
        return IntentDecision(
            action=IntentAction.CLARIFY,
            payload={"message": "No pude responder"},
            confidence=0.0,
            source="rule",
        )


class FakeStructuredProfileRouter:
    def __init__(self):
        self.extract_calls = []

    def extract_profile_facts(self, message, context=None):
        self.extract_calls.append((message, context))
        return UserProfileExtraction(profile_facts=[UserProfileFact(key="color_favorito", value="Azul", confidence=1.0)])

    def route(self, _message, context=None):
        return IntentDecision(
            action=IntentAction.ASK_KNOWLEDGE_BASE,
            payload={"answer": "Tu color favorito es Azul."},
            confidence=1.0,
            source="rule",
        )


class FakeLowConfidenceProfileRouter:
    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction(profile_facts=[UserProfileFact(key="color_favorito", value="Azul", confidence=0.3)])

    def route(self, _message, context=None):
        return IntentDecision(action=IntentAction.SMALL_TALK, payload={"reply": "ok"}, confidence=1.0, source="rule")


class FakeReadOnlyContextRouter:
    def __init__(self):
        self.received_contexts = []

    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction()

    def route(self, _message, context=None):
        self.received_contexts.append(context)
        if context and "name=Alexis" in context:
            return IntentDecision(
                action=IntentAction.ASK_KNOWLEDGE_BASE,
                payload={"answer": "Tu nombre es Alexis."},
                confidence=1.0,
                source="rule",
            )
        return IntentDecision(
            action=IntentAction.CLARIFY,
            payload={"message": "No pude responder"},
            confidence=0.0,
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

    def delete_task(self, task_id):
        self.calls.append(("delete", task_id))
        return {"task_id": task_id, "deleted": True}


class FakeCreateTaskRouter:
    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction()

    def route(self, message, context=None):
        title = "Tarea nueva"
        normalized = (message or "").lower()
        if "estudiar" in normalized:
            title = "Tarea para estudiar"
        if "revisar" in normalized:
            title = "Tarea para revisar"
        return IntentDecision(
            action=IntentAction.CREATE_TASK,
            payload={"title": title},
            confidence=1.0,
            source="rule",
        )


class FakeCreateWithoutTitleRouter:
    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction()

    def route(self, _message, context=None):
        return IntentDecision(
            action=IntentAction.CREATE_TASK,
            payload={},
            confidence=1.0,
            source="llm",
        )


class FakeDeleteTaskRouter:
    def extract_profile_facts(self, _message, context=None):
        return UserProfileExtraction()

    def route(self, _message, context=None):
        return IntentDecision(
            action=IntentAction.DELETE_TASK,
            payload={"task_id": "t-99"},
            confidence=1.0,
            source="rule",
        )


class FlakyService(FakeService):
    def __init__(self):
        super().__init__()
        self.failures = 0

    def create_task(self, task):
        self.failures += 1
        if self.failures == 1:
            raise ValueError("transient error")
        return super().create_task(task)


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


class TaskOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def test_creates_task_through_the_orchestrator(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service, router=FakeCreateTaskRouter())

        response = orchestrator.handle_message("crear una tarea para estudiar")

        self.assertTrue(response["success"])
        self.assertEqual(response["action"], "create_task")
        self.assertEqual(response["result"]["title"], "Tarea para estudiar")
        self.assertEqual(service.calls[0][0], "create")

    def test_deletes_task_through_the_orchestrator(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service, router=FakeDeleteTaskRouter())

        response = orchestrator.handle_message("borra la tarea t-99")

        self.assertTrue(response["success"])
        self.assertEqual(response["action"], "delete_task")
        self.assertEqual(response["result"]["task_id"], "t-99")
        self.assertEqual(service.calls[0], ("delete", "t-99"))

    def test_retries_once_when_a_specialist_fails(self):
        service = FlakyService()
        orchestrator = TaskOrchestrator(service=service, router=FakeCreateTaskRouter(), max_retries=2)

        response = orchestrator.handle_message("crear una tarea para revisar")

        self.assertTrue(response["success"])
        self.assertEqual(service.failures, 2)
        self.assertEqual(response["result"]["title"], "Tarea para revisar")

    def test_create_task_without_title_returns_clarify_instead_of_generic_task(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service, router=FakeCreateWithoutTitleRouter())

        response = orchestrator.handle_message("crea una tarea para investigar mas sobre eso")

        self.assertFalse(response["success"])
        self.assertEqual(response["action"], "create_task")
        self.assertIn("falta el título", response["message"].lower())
        self.assertEqual(service.calls, [])

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

    def test_follow_up_messages_are_not_exposed_with_internal_prompt_context(self):
        service = FakeService()
        orchestrator = TaskOrchestrator(service=service, router=FakeCreateTaskRouter())

        orchestrator.handle_message("crear una tarea para estudiar")
        follow_up = orchestrator.handle_message("¿qué tarea acabo de crear?")

        self.assertNotIn("prompt", follow_up)
        self.assertNotIn("context", follow_up)
        self.assertIn("message", follow_up)

    async def test_short_term_memory_keeps_only_the_most_recent_turns(self):
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))
        memory = ShortTermMemory(repository=repository, max_turns=2, max_items=2)

        await memory.add_turn_async("crear una tarea para estudiar", "tarea creada", session_id="session-test")
        await memory.add_turn_async("crear una tarea para entrenar", "tarea creada", session_id="session-test")
        await memory.add_turn_async("crear una tarea para cocinar", "tarea creada", session_id="session-test")

        turns = await memory.get_turns_async(session_id="session-test")
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0][0], "crear una tarea para entrenar")
        self.assertEqual(turns[1][0], "crear una tarea para cocinar")

    async def test_session_repository_persists_turns_and_context(self):
        """Regresión del bug de bridging sync/async: corre dentro de un event loop real
        para asegurar que el repositorio nunca devuelve None en silencio cuando ya hay
        un loop activo (el caso real de FastAPI)."""
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))

        await repository.append_turn_async("session-a", "hola", "hola, ¿en qué te ayudo?")
        await repository.add_context_item_async("session-a", "name", "Ana")

        summary = await repository.get_context_summary_async("session-a", max_turns=3, max_items=3)

        self.assertEqual(summary["turns"][0]["user_message"], "hola")
        self.assertEqual(summary["items"][0]["value"], "Ana")

    async def test_orchestrator_persists_and_reuses_session_context_from_repository(self):
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))
        router = FakeContextRouter()
        orchestrator = TaskOrchestrator(service=FakeService(), router=router, session_repository=repository)

        first_response = await orchestrator.handle_message_async("hola, soy Alexis")
        second_response = await orchestrator.handle_message_async("cuál es mi nombre")

        self.assertTrue(first_response["success"])
        self.assertEqual(second_response["message"], "Tu nombre es Alexis.")
        summary = await repository.get_context_summary_async(orchestrator.session_id)
        self.assertGreaterEqual(len(summary["turns"]), 1)
        self.assertTrue(any(context and "name=Alexis" in context for context in router.received_contexts))

    async def test_orchestrator_persists_generic_profile_facts_from_repository(self):
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))
        router = FakeGenericContextRouter()
        orchestrator = TaskOrchestrator(service=FakeService(), router=router, session_repository=repository)

        first_response = await orchestrator.handle_message_async("mi color favorito es azul")
        second_response = await orchestrator.handle_message_async("cuál es mi color favorito")

        self.assertTrue(first_response["success"])
        self.assertEqual(second_response["message"], "Tu color favorito es Azul.")
        self.assertTrue(any(context and "color_favorito=Azul" in context for context in router.received_contexts))

    async def test_orchestrator_persists_profile_facts_from_structured_extraction(self):
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))
        router = FakeStructuredProfileRouter()
        orchestrator = TaskOrchestrator(service=FakeService(), router=router, session_repository=repository)

        response = await orchestrator.handle_message_async("Amo el sushi")

        self.assertTrue(response["success"])
        self.assertTrue(router.extract_calls)
        # Los hechos de perfil se persisten en memoria de largo plazo, no en la de sesión:
        # sobreviven a un reinicio, la de sesión es de corta vida.
        long_term_facts = await orchestrator.context.long_term_memory.get_facts_async()
        self.assertEqual(long_term_facts.get("color_favorito"), "Azul")

    async def test_low_confidence_profile_facts_are_not_persisted(self):
        """Escribir todo lo que el usuario dice envenena el contexto. Un hecho con confianza
        por debajo del umbral (default 0.7) no debe llegar a la memoria de largo plazo."""
        orchestrator = TaskOrchestrator(
            service=FakeService(), router=FakeLowConfidenceProfileRouter(), session_id="low-confidence-session"
        )

        response = await orchestrator.handle_message_async("me gusta el azul, creo")

        self.assertTrue(response["success"])
        long_term_facts = await orchestrator.context.long_term_memory.get_facts_async()
        self.assertNotIn("color_favorito", long_term_facts)

    async def test_interaction_log_includes_measurable_context_tokens(self):
        """El presupuesto de contexto debe ser "medible y registrado" — verifica que el campo
        `contexto_tokens` llega al log estructurado de cierre de interacción."""
        orchestrator = TaskOrchestrator(
            service=FakeService(), router=FakeStructuredProfileRouter(), session_id="log-tokens-session"
        )

        with structlog.testing.capture_logs() as captured:
            await orchestrator.handle_message_async("Amo el sushi")

        interaction_logs = [entry for entry in captured if entry.get("event") == "interaccion_completada"]
        self.assertEqual(len(interaction_logs), 1)
        self.assertIsInstance(interaction_logs[0]["contexto_tokens"], int)
        self.assertGreaterEqual(interaction_logs[0]["contexto_tokens"], 0)

    async def test_orchestrator_does_not_reuse_context_from_other_session_ids(self):
        fake_collection = FakeSessionCollection()
        fake_db = type("FakeDb", (), {"conversation_sessions": fake_collection})()
        repository = MongoSessionRepository(db_name="test_db", get_db_fn=_make_async_get_db(fake_db))
        first_router = FakeContextRouter()
        second_router = FakeReadOnlyContextRouter()

        first = TaskOrchestrator(
            service=FakeService(),
            router=first_router,
            session_repository=repository,
            session_id="session-a",
        )
        second = TaskOrchestrator(
            service=FakeService(),
            router=second_router,
            session_repository=repository,
            session_id="session-b",
        )

        await first.handle_message_async("hola, soy Alexis")
        second_response = await second.handle_message_async("cuál es mi nombre")

        self.assertFalse(second_response["success"])
        self.assertEqual(second_response["action"], "clarify")
        summary_b = await repository.get_context_summary_async("session-b")
        self.assertFalse(any(item.get("key") == "name" for item in summary_b["items"]))


if __name__ == "__main__":
    unittest.main()
