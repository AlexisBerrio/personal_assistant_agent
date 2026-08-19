import unittest
from typing import ClassVar

from pydantic import ValidationError

from src.assistant_personal.domain.entities import ConversationRoute, IntentAction
from src.assistant_personal.infrastructure.routers.openai_llm_client import (
    OpenAIGeneralKnowledgeResponder,
    OpenAIIntentClassifier,
    OpenAISmallTalkResponder,
)


class FakeChatCompletions:
    async def create(self, **_kwargs):
        class FakeMessage:
            content = '{"route": "orchestrator", "intent": "create_task", "confidence": 0.95, "reasoning": "crear tarea", "source": "llm", "payload": {"title": "Comprar leche"}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices: ClassVar = [FakeChoice()]
            usage = None

        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()


class RecordingChatCompletions:
    def __init__(self):
        self.received_kwargs = None

    async def create(self, **kwargs):
        self.received_kwargs = kwargs

        class FakeMessage:
            content = '{"route": "small_talk", "intent": null, "confidence": 0.9, "reasoning": "saludo", "source": "llm", "payload": {}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices: ClassVar = [FakeChoice()]
            usage = None

        return FakeResponse()


class RecordingOpenAIClient:
    def __init__(self):
        self.completions = RecordingChatCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


class FakeMarkdownChatCompletions:
    async def create(self, **_kwargs):
        class FakeMessage:
            content = '```json\n{"route": "general_knowledge", "intent": null, "confidence": 0.93, "reasoning": "pregunta factual", "source": "llm", "payload": {}}\n```'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices: ClassVar = [FakeChoice()]
            usage = None

        return FakeResponse()


class FakeWrappedTextChatCompletions:
    async def create(self, **_kwargs):
        class FakeMessage:
            content = 'Aquí tienes el JSON solicitado: {"route": "orchestrator", "intent": "list_tasks", "confidence": 0.91, "reasoning": "listado de tareas", "source": "llm", "payload": {}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices: ClassVar = [FakeChoice()]
            usage = None

        return FakeResponse()


class FakeUnknownRouteChatCompletions:
    async def create(self, **_kwargs):
        class FakeMessage:
            content = '{"route": "no_existe", "intent": null, "confidence": 0.9, "reasoning": "", "source": "llm", "payload": {}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices: ClassVar = [FakeChoice()]
            usage = None

        return FakeResponse()


class FakeOutOfRangeConfidenceChatCompletions:
    async def create(self, **_kwargs):
        class FakeMessage:
            content = '{"route": "orchestrator", "intent": "list_tasks", "confidence": 1.5, "reasoning": "", "source": "llm", "payload": {}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices: ClassVar = [FakeChoice()]
            usage = None

        return FakeResponse()


class FakeUnknownRouteOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeUnknownRouteChatCompletions()})()


class FakeOutOfRangeConfidenceOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeOutOfRangeConfidenceChatCompletions()})()


class FakeMarkdownOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeMarkdownChatCompletions()})()


class FakeWrappedTextOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeWrappedTextChatCompletions()})()


class OpenAIGeneralKnowledgeResponderTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_general_knowledge_does_not_request_json_mode(self):
        """Su prompt pide texto libre, no JSON — forzar response_format=json_object rompería la
        respuesta (y la propia API de OpenAI lo rechaza sin la palabra 'json' en el prompt)."""
        client = OpenAIGeneralKnowledgeResponder.__new__(OpenAIGeneralKnowledgeResponder)
        client.model = "gpt-test"
        client.client = RecordingOpenAIClient()

        await client.answer_general_knowledge("¿qué es la técnica pomodoro?")

        self.assertNotIn("response_format", client.client.completions.received_kwargs)


class OpenAISmallTalkResponderTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_small_talk_generates_reply_from_the_real_message(self):
        """La respuesta de small_talk no puede ser un texto fijo: se genera con el LLM a partir
        de lo que el usuario realmente dijo, igual que general_knowledge."""
        client = OpenAISmallTalkResponder.__new__(OpenAISmallTalkResponder)
        client.model = "gpt-test"
        client.client = FakeOpenAIClient()

        reply = await client.answer_small_talk("hola, me llamo Alexis")

        self.assertTrue(reply)

    async def test_answer_small_talk_does_not_request_json_mode(self):
        """Igual que general_knowledge: su prompt pide texto libre conversacional, no JSON."""
        client = OpenAISmallTalkResponder.__new__(OpenAISmallTalkResponder)
        client.model = "gpt-test"
        client.client = RecordingOpenAIClient()

        await client.answer_small_talk("hola, me llamo Alexis")

        self.assertNotIn("response_format", client.client.completions.received_kwargs)


class OpenAIIntentClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_classify_intent_uses_chat_completions_when_responses_api_is_unavailable(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeOpenAIClient()

        decision = await client.classify_intent("crear tarea comprar leche")

        self.assertEqual(decision.route, ConversationRoute.ORCHESTRATOR)
        self.assertEqual(decision.intent, IntentAction.CREATE_TASK)
        self.assertEqual(decision.source, "llm")
        self.assertGreaterEqual(decision.confidence, 0.9)

    async def test_classify_intent_requests_strict_json_mode(self):
        """Defensa en profundidad tras varios hallazgos de salida mal formada del LLM (route/intent
        inventados, confidence null): activa response_format=json_object en la llamada real a la API."""
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = RecordingOpenAIClient()

        await client.classify_intent("hola, me llamo Alexis")

        self.assertEqual(client.client.completions.received_kwargs["response_format"], {"type": "json_object"})

    async def test_classify_intent_raises_when_no_supported_api_is_available(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = object()

        with self.assertRaises(RuntimeError):
            await client.classify_intent("hola")

    async def test_classify_intent_recovers_json_from_markdown_fence(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeMarkdownOpenAIClient()

        decision = await client.classify_intent("cuantos años tenia bolivar cuando murio")

        self.assertEqual(decision.route, ConversationRoute.GENERAL_KNOWLEDGE)
        self.assertIsNone(decision.intent)
        self.assertGreaterEqual(decision.confidence, 0.9)

    async def test_classify_intent_recovers_json_from_wrapped_text(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeWrappedTextOpenAIClient()

        decision = await client.classify_intent("lista mis tareas")

        self.assertEqual(decision.route, ConversationRoute.ORCHESTRATOR)
        self.assertEqual(decision.intent, IntentAction.LIST_TASKS)

    async def test_classify_intent_raises_validation_error_on_unknown_route(self):
        """La salida cruda del LLM se valida con Pydantic, no con casteos manuales — un `route`
        fuera del enum debe levantar, no degradarse en silencio."""
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeUnknownRouteOpenAIClient()

        with self.assertRaises(ValidationError):
            await client.classify_intent("mensaje ambiguo")

    async def test_classify_intent_raises_validation_error_on_out_of_range_confidence(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeOutOfRangeConfidenceOpenAIClient()

        with self.assertRaises(ValidationError):
            await client.classify_intent("lista mis tareas")


if __name__ == "__main__":
    unittest.main()
