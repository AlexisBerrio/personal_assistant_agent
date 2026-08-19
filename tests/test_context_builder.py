import unittest

from src.assistant_personal.application.agent_context import (
    InMemoryLongTermMemoryRepository,
    InMemorySessionRepository,
    LongTermMemory,
    ShortTermMemory,
)
from src.assistant_personal.application.context_builder import ContextBuilder, estimate_tokens


class FakeSummarizer:
    def __init__(self, summary: str = "resumen actualizado", error: Exception | None = None):
        self.summary = summary
        self.error = error
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    async def summarize_session(self, previous_summary: str, turns: list[tuple[str, str]]) -> str:
        self.calls.append((previous_summary, turns))
        if self.error:
            raise self.error
        return self.summary


def _short_term_memory() -> ShortTermMemory:
    return ShortTermMemory(repository=InMemorySessionRepository())


def _long_term_memory() -> LongTermMemory:
    return LongTermMemory(repository=InMemoryLongTermMemoryRepository(), user_id="test-user")


class EstimateTokensTests(unittest.TestCase):
    def test_empty_string_is_zero_tokens(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)

    def test_longer_text_estimates_more_tokens(self) -> None:
        self.assertGreater(estimate_tokens("a" * 400), estimate_tokens("a" * 40))


class ContextBuilderBuildContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_context_includes_facts_turns_and_items_within_budget(self) -> None:
        short_term = _short_term_memory()
        long_term = _long_term_memory()
        await short_term.add_turn_async("hola", "hola, ¿en qué te ayudo?", session_id="s1")
        await long_term.add_fact_async("nombre", "Alexis")

        builder = ContextBuilder(token_budget=800)
        context_text, tokens = await builder.build_context_async(short_term, long_term, "s1")

        self.assertIn("nombre=Alexis", context_text)
        self.assertIn("hola", context_text)
        self.assertGreater(tokens, 0)

    async def test_build_context_is_empty_string_with_no_history(self) -> None:
        builder = ContextBuilder(token_budget=800)
        context_text, tokens = await builder.build_context_async(_short_term_memory(), _long_term_memory(), "s1")

        self.assertEqual(context_text, "")
        self.assertEqual(tokens, 0)

    async def test_build_context_respects_a_tiny_token_budget(self) -> None:
        short_term = _short_term_memory()
        long_term = _long_term_memory()
        await long_term.add_fact_async("biografia", "x" * 2000)
        await short_term.add_turn_async("hola", "hola", session_id="s1")

        builder = ContextBuilder(token_budget=20)
        _context_text, tokens = await builder.build_context_async(short_term, long_term, "s1")

        self.assertLessEqual(tokens, 20)

    async def test_build_context_includes_session_summary_when_present(self) -> None:
        short_term = _short_term_memory()
        await short_term.compact_async("s1", "el usuario prefiere reuniones por la mañana", keep_last_turns=0)

        builder = ContextBuilder(token_budget=800)
        context_text, _ = await builder.build_context_async(short_term, _long_term_memory(), "s1")

        self.assertIn("prefiere reuniones por la mañana", context_text)


class ContextBuilderSummarizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarization_triggers_once_turn_threshold_is_reached(self) -> None:
        short_term = _short_term_memory()
        for i in range(5):
            await short_term.add_turn_async(f"mensaje {i}", f"respuesta {i}", session_id="s1")

        summarizer = FakeSummarizer(summary="resumen de los primeros 5 turnos")
        builder = ContextBuilder(summarizer=summarizer, summarize_every_n_turns=5)

        await builder.maybe_summarize_async(short_term, "s1")

        self.assertEqual(len(summarizer.calls), 1)
        raw = await short_term.get_raw_session_async("s1")
        self.assertEqual(raw["summary"], "resumen de los primeros 5 turnos")
        self.assertEqual(len(raw["turns"]), 1)

    async def test_summarization_does_not_trigger_below_threshold(self) -> None:
        short_term = _short_term_memory()
        await short_term.add_turn_async("hola", "hola", session_id="s1")

        summarizer = FakeSummarizer()
        builder = ContextBuilder(summarizer=summarizer, summarize_every_n_turns=5)

        await builder.maybe_summarize_async(short_term, "s1")

        self.assertEqual(summarizer.calls, [])

    async def test_no_summarizer_configured_is_a_noop(self) -> None:
        short_term = _short_term_memory()
        for i in range(5):
            await short_term.add_turn_async(f"mensaje {i}", f"respuesta {i}", session_id="s1")

        builder = ContextBuilder(summarizer=None, summarize_every_n_turns=5)

        await builder.maybe_summarize_async(short_term, "s1")

        raw = await short_term.get_raw_session_async("s1")
        self.assertEqual(len(raw["turns"]), 5)

    async def test_summarizer_failure_does_not_propagate_and_leaves_session_untouched(self) -> None:
        short_term = _short_term_memory()
        for i in range(5):
            await short_term.add_turn_async(f"mensaje {i}", f"respuesta {i}", session_id="s1")

        summarizer = FakeSummarizer(error=RuntimeError("LLM caído"))
        builder = ContextBuilder(summarizer=summarizer, summarize_every_n_turns=5)

        await builder.maybe_summarize_async(short_term, "s1")  # no debe lanzar

        raw = await short_term.get_raw_session_async("s1")
        self.assertEqual(raw["summary"], "")
        self.assertEqual(len(raw["turns"]), 5)


if __name__ == "__main__":
    unittest.main()
