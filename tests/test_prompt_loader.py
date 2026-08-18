from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.assistant_personal.infrastructure.prompts.loader import load_prompt


class PromptLoaderTests(unittest.TestCase):
    def test_loads_the_real_classify_intent_prompt_with_its_metadata(self) -> None:
        prompt = load_prompt("router/classify_intent")

        self.assertEqual(prompt.id, "classify_intent")
        self.assertEqual(prompt.version, "1.2.0")
        self.assertEqual(prompt.identifier, "classify_intent:v1.2.0")
        self.assertIn("clasificador de intenciones", prompt.text)
        self.assertEqual(prompt.model_recommended, "gpt-4o-mini")
        self.assertEqual(prompt.temperature, 0.0)
        self.assertIn("user_message", prompt.inputs)

    def test_loads_general_knowledge_and_extract_profile_facts_prompts(self) -> None:
        general_knowledge = load_prompt("router/general_knowledge")
        extract_profile_facts = load_prompt("router/extract_profile_facts")

        self.assertEqual(general_knowledge.identifier, "general_knowledge:v1.0.0")
        self.assertEqual(extract_profile_facts.identifier, "extract_profile_facts:v1.0.0")

    def test_raises_when_no_prompt_file_exists_for_the_given_name(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_prompt("router/no_existe_este_prompt")

    def test_raises_when_frontmatter_version_is_not_valid_semver(self) -> None:
        from src.assistant_personal.infrastructure.prompts import loader as loader_module

        with (
            patch.object(loader_module, "_PROMPTS_DIR", Path(__file__).resolve().parent / "fixtures"),
            self.assertRaises(ValueError),
        ):
            loader_module.load_prompt.__wrapped__("invalid_version")

    def test_raises_when_frontmatter_is_missing(self) -> None:
        from src.assistant_personal.infrastructure.prompts import loader as loader_module

        with (
            patch.object(loader_module, "_PROMPTS_DIR", Path(__file__).resolve().parent / "fixtures"),
            self.assertRaises(ValueError),
        ):
            loader_module.load_prompt.__wrapped__("no_frontmatter")


if __name__ == "__main__":
    unittest.main()
