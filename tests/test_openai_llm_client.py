import unittest

from src.assistant_personal.domain.entities import IntentAction
from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAILLMRouterClient


class FakeChatCompletions:
    def create(self, **_kwargs):
        class FakeMessage:
            content = '{"action": "small_talk", "confidence": 0.95, "reasoning": "saludo", "source": "llm", "payload": {"text": "hola"}}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()


class OpenAILLMRouterClientTests(unittest.TestCase):
    def test_classify_intent_uses_chat_completions_when_responses_api_is_unavailable(self):
        client = OpenAILLMRouterClient.__new__(OpenAILLMRouterClient)
        client.model = "gpt-test"
        client.client = FakeOpenAIClient()

        decision = client.classify_intent("hola")

        self.assertEqual(decision.action, IntentAction.SMALL_TALK)
        self.assertEqual(decision.source, "llm")
        self.assertGreaterEqual(decision.confidence, 0.9)

    def test_classify_intent_raises_when_no_supported_api_is_available(self):
        client = OpenAILLMRouterClient.__new__(OpenAILLMRouterClient)
        client.model = "gpt-test"
        client.client = object()

        with self.assertRaises(RuntimeError):
            client.classify_intent("hola")


if __name__ == "__main__":
    unittest.main()
