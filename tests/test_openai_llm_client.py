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


if __name__ == "__main__":
    unittest.main()
