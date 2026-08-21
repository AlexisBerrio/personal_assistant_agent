from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.assistant_personal.infrastructure.mcp.tools.task_tools import TOOL_SCOPES


class StepDecision(str, Enum):
    """Resultado de evaluar un paso propuesto (tool + parámetros) contra las políticas del
    agente."""

    ALLOW = "allow"
    DENY_TOOL_NOT_WHITELISTED = "deny_tool_not_whitelisted"
    DENY_STEP_BUDGET_EXCEEDED = "deny_step_budget_exceeded"
    DENY_TOKEN_BUDGET_EXCEEDED = "deny_token_budget_exceeded"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True)
class GuardrailsConfig:
    """Política de guardrails para un agente con tools MCP.

    `allowed_tools` es la whitelist completa (lectura + escritura); `write_tools` es el
    subconjunto que exige confirmación antes de ejecutarse — no una lista aparte que se pueda
    desincronizar de `allowed_tools`, sino un subconjunto explícito de la misma.
    """

    allowed_tools: frozenset[str]
    write_tools: frozenset[str]
    max_steps: int = 5
    max_tokens: int = 4000


class Guardrails:
    """Evalúa un paso propuesto contra whitelist de tools, límite de pasos, presupuesto de
    tokens y confirmación de escrituras — en ese orden. No ejecuta nada ni conoce MCP: solo
    decide si un paso puede proceder, dado cuánto ya se gastó en el turno."""

    def __init__(self, config: GuardrailsConfig) -> None:
        self.config = config

    def evaluate_step(
        self,
        *,
        tool_name: str,
        steps_used: int,
        tokens_used: int,
        confirmed: bool = False,
    ) -> StepDecision:
        if tool_name not in self.config.allowed_tools:
            return StepDecision.DENY_TOOL_NOT_WHITELISTED
        if steps_used >= self.config.max_steps:
            return StepDecision.DENY_STEP_BUDGET_EXCEEDED
        if tokens_used >= self.config.max_tokens:
            return StepDecision.DENY_TOKEN_BUDGET_EXCEEDED
        if tool_name in self.config.write_tools and not confirmed:
            return StepDecision.NEEDS_CONFIRMATION
        return StepDecision.ALLOW


def build_default_guardrails(max_steps: int = 5, max_tokens: int = 4000) -> Guardrails:
    """Construye `Guardrails` con la whitelist real de tools MCP (`TOOL_SCOPES` de
    `task_tools.py`) como fuente de verdad, para que la whitelist nunca se desincronice de las
    tools que el servidor MCP expone de verdad."""
    
    allowed_tools = frozenset(TOOL_SCOPES.keys())
    write_tools = frozenset(name for name, scope in TOOL_SCOPES.items() if scope == "write")
    return Guardrails(
        GuardrailsConfig(
            allowed_tools=allowed_tools,
            write_tools=write_tools,
            max_steps=max_steps,
            max_tokens=max_tokens,
        )
    )
