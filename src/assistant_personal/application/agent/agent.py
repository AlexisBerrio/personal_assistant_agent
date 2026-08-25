from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from src.assistant_personal.application.agent.guardrails import Guardrails, StepDecision, build_default_guardrails
from src.assistant_personal.infrastructure.llm.openai_llm_client import OpenAIAgentLLM
from src.assistant_personal.infrastructure.observabilidad import get_logger, get_tracer
from src.assistant_personal.infrastructure.prompts.loader import load_prompt

logger = get_logger(__name__)
tracer = get_tracer(__name__)

# Tools que existen en el servidor MCP pero no tiene sentido ofrecerle al agente como una acción de negocio.
_EXCLUDED_FROM_CATALOG = {"health_check"}

_CONFIRMATION_VERBS: dict[str, str] = {
    "eliminar_tarea": "eliminar la tarea",
    "completar_tarea": "marcar como completada la tarea",
}
_CONFIRMED_SUCCESS_MESSAGES: dict[str, str] = {
    "eliminar_tarea": "Tarea eliminada.",
    "completar_tarea": "Tarea completada.",
}


class McpToolCatalog(Protocol):
    async def list_tools(self) -> list[Any]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class AgentLLM(Protocol):
    async def invoke_with_tools(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> tuple[Any, int]: ...


@dataclass
class AgentResult:
    """Resultado de que el agente maneje un mensaje de punta a punta — puede haber ejecutado
    cero o más tools antes de llegar a la respuesta final."""

    message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    steps_used: int = 0
    # No-`None` solo cuando el turno se detuvo porque una tool de escritura irreversible
    # necesita confirmación explícita del usuario antes de ejecutarse.
    pending_confirmation: dict[str, Any] | None = None


def _build_confirmation_prompt(tool_name: str, arguments: dict[str, Any]) -> str:
    accion = _CONFIRMATION_VERBS.get(tool_name, f"ejecutar {tool_name}")
    referencia = arguments.get("task_id") or arguments.get("title") or ""
    detalle = f" ({referencia})" if referencia else ""
    return f"¿Confirmas que quieres {accion}{detalle}?"


def _mcp_tool_to_openai_schema(tool: Any) -> dict[str, Any]:
    """Convierte un tool MCP (`name`/`description`/`inputSchema`) al formato `tools=[...]` de
    la API de OpenAI. Sin duplicar el esquema a mano: sale del servidor MCP real."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


class Agent:
    """Agente con tools MCP: dado un mensaje, decide qué tool(s) invocar (si alguna) y con qué
    argumentos, ejecuta cada paso bajo `Guardrails`, y devuelve una respuesta final en lenguaje
    natural."""

    def __init__(
        self,
        mcp_client: McpToolCatalog,
        llm: AgentLLM | None = None,
        guardrails: Guardrails | None = None,
    ) -> None:
        self.mcp_client = mcp_client
        self.llm = llm or OpenAIAgentLLM()
        self.guardrails = guardrails or build_default_guardrails()
        self._tools_schema_cache: list[dict[str, Any]] | None = None

    async def _get_tools_schema(self) -> list[dict[str, Any]]:
        if self._tools_schema_cache is None:
            mcp_tools = await self.mcp_client.list_tools()
            self._tools_schema_cache = [
                _mcp_tool_to_openai_schema(tool) for tool in mcp_tools if tool.name not in _EXCLUDED_FROM_CATALOG
            ]
        return self._tools_schema_cache

    async def execute_confirmed_tool(self, tool_name: str, arguments: dict[str, Any]) -> AgentResult:
        """Ejecuta directamente una tool que quedó pendiente de confirmación — el
        usuario ya confirmó en un turno posterior, así que no vuelve a pasar por el LLM: se
        ejecuta la misma tool con los mismos argumentos que el agente propuso originalmente."""
        with tracer.start_as_current_span("agent.confirmar") as span:
            span.set_attribute("tool", tool_name)
            decision = self.guardrails.evaluate_step(
                tool_name=tool_name, steps_used=0, tokens_used=0, confirmed=True
            )
            tool_call_entry = {"tool": tool_name, "arguments": arguments, "decision": decision.value}
            if decision != StepDecision.ALLOW:
                logger.warning("agent_guardrail_bloqueo", tool=tool_name, decision=decision.value)
                return AgentResult(message=f"No autorizado: {decision.value}", tool_calls=[tool_call_entry])

            try:
                await self.mcp_client.call_tool(tool_name, arguments)
            except Exception as exc:
                return AgentResult(
                    message=f"Error ejecutando la tool: {exc}", tool_calls=[tool_call_entry], steps_used=1
                )

            message = _CONFIRMED_SUCCESS_MESSAGES.get(tool_name, "Listo.")
            return AgentResult(message=message, tool_calls=[tool_call_entry], steps_used=1)

    async def handle(self, message: str, context: str | None = None) -> AgentResult:
        with tracer.start_as_current_span("agent.razonar") as span:
            tools_schema = await self._get_tools_schema()
            system_prompt = load_prompt("agent/agent_system")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            system_text = system_prompt.text.replace("{{today}}", today)

            messages: list[dict[str, Any]] = [{"role": "system", "content": system_text}]
            if context:
                messages.append({"role": "system", "content": f"Contexto reciente de la conversación: {context}"})
            messages.append({"role": "user", "content": message})

            steps_used = 0
            tokens_used = 0
            tool_calls_log: list[dict[str, Any]] = []
            max_steps = self.guardrails.config.max_steps

            while True:
                llm_message, tokens_this_call = await self.llm.invoke_with_tools(messages, tools_schema)
                tokens_used += tokens_this_call

                if not llm_message.tool_calls:
                    span.set_attribute("pasos_usados", steps_used)
                    span.set_attribute("tokens_usados", tokens_used)
                    return AgentResult(
                        message=llm_message.content or "", tool_calls=tool_calls_log, steps_used=steps_used
                    )

                messages.append(llm_message.model_dump(exclude_none=True))

                for tool_call in llm_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}

                    decision = self.guardrails.evaluate_step(
                        tool_name=tool_name, steps_used=steps_used, tokens_used=tokens_used, confirmed=False
                    )
                    if decision == StepDecision.NEEDS_CONFIRMATION:
                        logger.info("agent_requiere_confirmacion", tool=tool_name)
                        span.set_attribute("pasos_usados", steps_used)
                        span.set_attribute("tokens_usados", tokens_used)
                        span.set_attribute("requiere_confirmacion", True)
                        tool_calls_log.append(
                            {"tool": tool_name, "arguments": arguments, "decision": decision.value}
                        )
                        return AgentResult(
                            message=_build_confirmation_prompt(tool_name, arguments),
                            tool_calls=tool_calls_log,
                            steps_used=steps_used,
                            pending_confirmation={"tool": tool_name, "arguments": arguments},
                        )
                    if decision != StepDecision.ALLOW:
                        logger.warning("agent_guardrail_bloqueo", tool=tool_name, decision=decision.value)
                        result_text = f"No autorizado: {decision.value}"
                    else:
                        steps_used += 1
                        try:
                            raw_result = await self.mcp_client.call_tool(tool_name, arguments)
                            result_text = json.dumps(raw_result, ensure_ascii=False, default=str)
                        except Exception as exc:
                            result_text = f"Error ejecutando la tool: {exc}"

                    tool_calls_log.append({"tool": tool_name, "arguments": arguments, "decision": decision.value})
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_text})

                if steps_used >= max_steps:
                    span.set_attribute("pasos_usados", steps_used)
                    span.set_attribute("tokens_usados", tokens_used)
                    span.set_attribute("presupuesto_agotado", True)
                    return AgentResult(
                        message="Necesité más pasos de los permitidos para completar esto. ¿Puedes ser más específico?",
                        tool_calls=tool_calls_log,
                        steps_used=steps_used,
                    )
