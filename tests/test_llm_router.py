import unittest
from unittest.mock import patch

from src.assistant_personal.application.llm_router import LLMIntentRouter


class LLMRouterTests(unittest.TestCase):
    def test_uses_rule_based_router_when_no_api_key(self):
        router = LLMIntentRouter(api_key=None)
        result = router.route("listar mis tareas")

        self.assertEqual(result.action, "list_tasks")

    def test_parses_json_response_from_llm(self):
        router = LLMIntentRouter(api_key="fake-key")

        class FakeResponse:
            output_text = '{"action": "create_task", "title": "Estudiar"}'

        class FakeClient:
            api_key = "fake-key"

            class responses:
                @staticmethod
                def create(*args, **kwargs):
                    return FakeResponse()

        with patch("src.assistant_personal.application.llm_router.OpenAI", return_value=FakeClient()):
            result = router.route("crear una tarea para estudiar")

        self.assertEqual(result.action, "create_task")
        self.assertIn("estudiar", result.payload["title"].lower())


if __name__ == "__main__":
    unittest.main()
