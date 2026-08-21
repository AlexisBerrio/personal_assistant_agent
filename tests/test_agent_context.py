import unittest

from src.assistant_personal.application.memory.agent_context import AgentContext


class AgentContextTests(unittest.TestCase):
    def test_builds_context_summary_from_short_and_long_term_memory(self):
        context = AgentContext()
        context.short_term_memory.add("user_message", "crear una tarea para estudiar")
        context.long_term_memory.add_fact("user_prefers", "tareas breves")

        summary = context.build_context_summary()

        self.assertIn("crear una tarea para estudiar", summary)
        self.assertIn("tareas breves", summary)


if __name__ == "__main__":
    unittest.main()
