import unittest

from src.assistant_personal.config import Settings


class SettingsOpenAIApiKeyTests(unittest.TestCase):
    """Regresión de docs/anexo_arquitectura_objetivo.md, ítem 2.4: un `OPENAI_API_KEY` con un
    salto de línea o espacios colados (típico al copiar un secret de CI) rompe el header HTTP
    `Authorization` con un error que el SDK de OpenAI reporta como `Connection error.` genérico,
    sin delatar la causa real."""

    def test_strips_trailing_newline_from_openai_api_key(self) -> None:
        settings = Settings(mongo_uri="mongodb://localhost:27017", openai_api_key="sk-test-key\n")

        self.assertEqual(settings.openai_api_key.get_secret_value(), "sk-test-key")

    def test_strips_surrounding_whitespace_from_openai_api_key(self) -> None:
        settings = Settings(mongo_uri="mongodb://localhost:27017", openai_api_key="  sk-test-key  ")

        self.assertEqual(settings.openai_api_key.get_secret_value(), "sk-test-key")

    def test_leaves_explicit_none_openai_api_key_as_none(self) -> None:
        settings = Settings(mongo_uri="mongodb://localhost:27017", openai_api_key=None)

        self.assertIsNone(settings.openai_api_key)


if __name__ == "__main__":
    unittest.main()
