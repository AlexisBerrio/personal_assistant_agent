import unittest

from src.assistant_personal.application.prompt_engineering import PromptBuilder


class PromptBuilderTests(unittest.TestCase):
    def test_builds_system_prompt_with_guardrails(self):
        builder = PromptBuilder()

        prompt = builder.build_system_prompt()

        self.assertIn("asistente personal", prompt.lower())
        self.assertIn("guardrails", prompt.lower())
        self.assertIn("reintentos", prompt.lower())


if __name__ == "__main__":
    unittest.main()
