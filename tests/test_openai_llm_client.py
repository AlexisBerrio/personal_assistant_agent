import unittest

from src.assistant_personal.domain.entities import ConversationRoute, IntentAction
from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAIIntentClassifier


class FakeChatCompletions:
    def create(self, **_kwargs):
        class FakeMessage:
            content = '{"route": "orchestrator", "intent": "create_task", "confidence": 0.95, "reasoning": "crear tarea", "source": "llm", "payload": {"title": "Comprar leche"}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()


class FakeMarkdownChatCompletions:
    def create(self, **_kwargs):
        class FakeMessage:
            content = '```json\n{"route": "general_knowledge", "intent": null, "confidence": 0.93, "reasoning": "pregunta factual", "source": "llm", "payload": {}}\n```'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        return FakeResponse()


class FakeWrappedTextChatCompletions:
    def create(self, **_kwargs):
        class FakeMessage:
            content = 'Aquí tienes el JSON solicitado: {"route": "orchestrator", "intent": "list_tasks", "confidence": 0.91, "reasoning": "listado de tareas", "source": "llm", "payload": {}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        return FakeResponse()


class FakeMarkdownOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeMarkdownChatCompletions()})()


class FakeWrappedTextOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeWrappedTextChatCompletions()})()


class OpenAIIntentClassifierTests(unittest.TestCase):
    def test_classify_intent_uses_chat_completions_when_responses_api_is_unavailable(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeOpenAIClient()

        decision = client.classify_intent("crear tarea comprar leche")

        self.assertEqual(decision.route, ConversationRoute.ORCHESTRATOR)
        self.assertEqual(decision.intent, IntentAction.CREATE_TASK)
        self.assertEqual(decision.source, "llm")
        self.assertGreaterEqual(decision.confidence, 0.9)

    def test_classify_intent_raises_when_no_supported_api_is_available(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = object()

        with self.assertRaises(RuntimeError):
            client.classify_intent("hola")

    def test_classify_intent_recovers_json_from_markdown_fence(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeMarkdownOpenAIClient()

        decision = client.classify_intent("cuantos años tenia bolivar cuando murio")

        self.assertEqual(decision.route, ConversationRoute.GENERAL_KNOWLEDGE)
        self.assertIsNone(decision.intent)
        self.assertGreaterEqual(decision.confidence, 0.9)

    def test_classify_intent_recovers_json_from_wrapped_text(self):
        client = OpenAIIntentClassifier.__new__(OpenAIIntentClassifier)
        client.model = "gpt-test"
        client.client = FakeWrappedTextOpenAIClient()

        decision = client.classify_intent("lista mis tareas")

        self.assertEqual(decision.route, ConversationRoute.ORCHESTRATOR)
        self.assertEqual(decision.intent, IntentAction.LIST_TASKS)


if __name__ == "__main__":
    unittest.main()
