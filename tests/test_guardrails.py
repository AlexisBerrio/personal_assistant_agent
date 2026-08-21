import unittest

from src.assistant_personal.application.agent.guardrails import (
    Guardrails,
    GuardrailsConfig,
    StepDecision,
    build_default_guardrails,
)


def _make_guardrails(max_steps: int = 5, max_tokens: int = 4000) -> Guardrails:
    config = GuardrailsConfig(
        allowed_tools=frozenset({"listar_tareas", "crear_tarea", "eliminar_tarea"}),
        write_tools=frozenset({"crear_tarea", "eliminar_tarea"}),
        max_steps=max_steps,
        max_tokens=max_tokens,
    )
    return Guardrails(config)


class GuardrailsTests(unittest.TestCase):
    def test_allows_a_read_step_within_budget(self):
        guardrails = _make_guardrails()
        decision = guardrails.evaluate_step(tool_name="listar_tareas", steps_used=0, tokens_used=0)
        self.assertEqual(decision, StepDecision.ALLOW)

    def test_denies_a_tool_outside_the_whitelist(self):
        guardrails = _make_guardrails()
        decision = guardrails.evaluate_step(tool_name="tool_inexistente", steps_used=0, tokens_used=0)
        self.assertEqual(decision, StepDecision.DENY_TOOL_NOT_WHITELISTED)

    def test_denies_when_the_step_budget_is_exhausted(self):
        guardrails = _make_guardrails(max_steps=3)
        decision = guardrails.evaluate_step(tool_name="listar_tareas", steps_used=3, tokens_used=0)
        self.assertEqual(decision, StepDecision.DENY_STEP_BUDGET_EXCEEDED)

    def test_denies_when_the_token_budget_is_exhausted(self):
        guardrails = _make_guardrails(max_tokens=1000)
        decision = guardrails.evaluate_step(tool_name="listar_tareas", steps_used=0, tokens_used=1000)
        self.assertEqual(decision, StepDecision.DENY_TOKEN_BUDGET_EXCEEDED)

    def test_a_write_tool_without_confirmation_needs_confirmation(self):
        guardrails = _make_guardrails()
        decision = guardrails.evaluate_step(tool_name="crear_tarea", steps_used=0, tokens_used=0)
        self.assertEqual(decision, StepDecision.NEEDS_CONFIRMATION)

    def test_a_write_tool_with_confirmation_is_allowed(self):
        guardrails = _make_guardrails()
        decision = guardrails.evaluate_step(tool_name="crear_tarea", steps_used=0, tokens_used=0, confirmed=True)
        self.assertEqual(decision, StepDecision.ALLOW)

    def test_whitelist_is_checked_before_the_step_budget(self):
        """Un paso con tool desconocida se rechaza por whitelist aunque el presupuesto de pasos
        ya esté agotado — el motivo del rechazo debe ser el correcto, no el primero que aplique
        por casualidad de orden."""
        guardrails = _make_guardrails(max_steps=0)
        decision = guardrails.evaluate_step(tool_name="tool_inexistente", steps_used=0, tokens_used=0)
        self.assertEqual(decision, StepDecision.DENY_TOOL_NOT_WHITELISTED)

    def test_a_read_tool_never_needs_confirmation(self):
        guardrails = _make_guardrails()
        decision = guardrails.evaluate_step(tool_name="listar_tareas", steps_used=0, tokens_used=0, confirmed=False)
        self.assertEqual(decision, StepDecision.ALLOW)


class BuildDefaultGuardrailsTests(unittest.TestCase):
    def test_default_guardrails_whitelist_matches_the_real_tool_scopes(self):
        """Contra el `TOOL_SCOPES` real de `task_tools.py`, no una copia — si una tool nueva se
        agrega ahí sin decidir su scope, este test lo detecta."""
        from src.assistant_personal.infrastructure.mcp.tools.task_tools import TOOL_SCOPES

        guardrails = build_default_guardrails()
        self.assertEqual(guardrails.config.allowed_tools, frozenset(TOOL_SCOPES.keys()))
        expected_write_tools = frozenset(name for name, scope in TOOL_SCOPES.items() if scope == "write")
        self.assertEqual(guardrails.config.write_tools, expected_write_tools)

    def test_default_guardrails_marks_delete_and_create_as_write_tools(self):
        guardrails = build_default_guardrails()
        self.assertIn("eliminar_tarea", guardrails.config.write_tools)
        self.assertIn("crear_tarea", guardrails.config.write_tools)
        self.assertNotIn("listar_tareas", guardrails.config.write_tools)
        self.assertNotIn("buscar_tarea", guardrails.config.write_tools)


if __name__ == "__main__":
    unittest.main()
