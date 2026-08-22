import unittest
from dataclasses import dataclass, field

from src.assistant_personal.application.agent.agent import Agent
from src.assistant_personal.application.agent.guardrails import Guardrails, GuardrailsConfig, build_default_guardrails


class FakeMcpTool:
    def __init__(self, name, description, input_schema):
        self.name = name
        self.description = description
        self.inputSchema = input_schema


class FakeMcpClient:
    def __init__(self, tools, call_results=None):
        self._tools = tools
        self.calls = []
        self._call_results = call_results or {}

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        result = self._call_results.get(name, {})
        if isinstance(result, Exception):
            raise result
        return result


@dataclass
class FakeFunctionCall:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunctionCall
    type: str = "function"


class FakeLLMMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls or None}
        if exclude_none:
            data = {key: value for key, value in data.items() if value is not None}
        return data


@dataclass
class FakeAgentLLM:
    """Reproduce el bucle de tool-calling con una lista de respuestas guionadas, en orden."""

    responses: list
    calls: list = field(default_factory=list)

    async def invoke_with_tools(self, messages, tools):
        self.calls.append((list(messages), tools))
        return self.responses.pop(0)


_LISTAR_TAREAS_TOOL = FakeMcpTool(
    "listar_tareas", "Devuelve las tareas activas", {"type": "object", "properties": {}}
)
_CREAR_TAREA_TOOL = FakeMcpTool(
    "crear_tarea",
    "Crea una tarea",
    {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
)
_COMPLETAR_TAREA_TOOL = FakeMcpTool(
    "completar_tarea",
    "Completa una tarea",
    {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
)
_HEALTH_CHECK_TOOL = FakeMcpTool("health_check", "Chequea la salud del servidor", {"type": "object", "properties": {}})


def _tool_call(tool_id, name, arguments_json):
    return FakeToolCall(id=tool_id, function=FakeFunctionCall(name=name, arguments=arguments_json))


class AgentToolSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_the_openai_schema_directly_from_the_mcp_tool_definition(self):
        mcp_client = FakeMcpClient(tools=[_LISTAR_TAREAS_TOOL])
        agent = Agent(mcp_client=mcp_client, llm=FakeAgentLLM(responses=[]), guardrails=build_default_guardrails())

        schema = await agent._get_tools_schema()

        self.assertEqual(len(schema), 1)
        self.assertEqual(schema[0]["type"], "function")
        self.assertEqual(schema[0]["function"]["name"], "listar_tareas")
        self.assertEqual(schema[0]["function"]["description"], "Devuelve las tareas activas")
        self.assertEqual(schema[0]["function"]["parameters"], _LISTAR_TAREAS_TOOL.inputSchema)

    async def test_excludes_health_check_from_the_catalog(self):
        mcp_client = FakeMcpClient(tools=[_LISTAR_TAREAS_TOOL, _HEALTH_CHECK_TOOL])
        agent = Agent(mcp_client=mcp_client, llm=FakeAgentLLM(responses=[]), guardrails=build_default_guardrails())

        schema = await agent._get_tools_schema()

        self.assertEqual({tool["function"]["name"] for tool in schema}, {"listar_tareas"})


class AgentHandleTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_final_answer_without_calling_any_tool(self):
        mcp_client = FakeMcpClient(tools=[_LISTAR_TAREAS_TOOL])
        llm = FakeAgentLLM(responses=[(FakeLLMMessage(content="No hace falta ninguna acción."), 50)])
        agent = Agent(mcp_client=mcp_client, llm=llm, guardrails=build_default_guardrails())

        result = await agent.handle("hola")

        self.assertEqual(result.message, "No hace falta ninguna acción.")
        self.assertEqual(result.steps_used, 0)
        self.assertEqual(mcp_client.calls, [])

    async def test_calls_a_tool_then_returns_the_final_answer(self):
        mcp_client = FakeMcpClient(
            tools=[_LISTAR_TAREAS_TOOL, _COMPLETAR_TAREA_TOOL],
            call_results={"listar_tareas": {"tasks": [{"task_id": "t-2", "title": "Ir al dentista"}]}},
        )
        llm = FakeAgentLLM(
            responses=[
                (FakeLLMMessage(tool_calls=[_tool_call("call-1", "listar_tareas", "{}")]), 100),
                (FakeLLMMessage(content="Encontré y completé la tarea del dentista."), 60),
            ]
        )
        agent = Agent(mcp_client=mcp_client, llm=llm, guardrails=build_default_guardrails())

        result = await agent.handle("termina la tarea odontologica")

        self.assertEqual(result.message, "Encontré y completé la tarea del dentista.")
        self.assertEqual(result.steps_used, 1)
        self.assertEqual(mcp_client.calls, [("listar_tareas", {})])

    async def test_passes_the_conversation_context_to_the_first_message(self):
        mcp_client = FakeMcpClient(tools=[_LISTAR_TAREAS_TOOL])
        llm = FakeAgentLLM(responses=[(FakeLLMMessage(content="ok"), 10)])
        agent = Agent(mcp_client=mcp_client, llm=llm, guardrails=build_default_guardrails())

        await agent.handle("hola", context="name=Alexis")

        first_call_messages, _ = llm.calls[0]
        self.assertTrue(any("name=Alexis" in (m.get("content") or "") for m in first_call_messages))

    async def test_denies_a_tool_the_llm_hallucinated_outside_the_whitelist(self):
        mcp_client = FakeMcpClient(tools=[_LISTAR_TAREAS_TOOL])
        llm = FakeAgentLLM(
            responses=[
                (FakeLLMMessage(tool_calls=[_tool_call("call-1", "tool_fantasma", "{}")]), 50),
                (FakeLLMMessage(content="No pude completar la acción."), 20),
            ]
        )
        agent = Agent(mcp_client=mcp_client, llm=llm, guardrails=build_default_guardrails())

        result = await agent.handle("haz algo raro")

        self.assertEqual(mcp_client.calls, [])  # nunca se ejecutó
        self.assertEqual(result.tool_calls[0]["decision"], "deny_tool_not_whitelisted")

    async def test_stops_when_the_step_budget_is_exhausted(self):
        mcp_client = FakeMcpClient(tools=[_LISTAR_TAREAS_TOOL], call_results={"listar_tareas": {"tasks": []}})
        limited_guardrails = Guardrails(
            GuardrailsConfig(allowed_tools=frozenset({"listar_tareas"}), write_tools=frozenset(), max_steps=1)
        )
        llm = FakeAgentLLM(responses=[(FakeLLMMessage(tool_calls=[_tool_call("call-1", "listar_tareas", "{}")]), 50)])
        agent = Agent(mcp_client=mcp_client, llm=llm, guardrails=limited_guardrails)

        result = await agent.handle("busca algo")

        self.assertEqual(result.steps_used, 1)
        self.assertIn("más pasos", result.message.lower())
        self.assertEqual(len(llm.calls), 1)  # no siguió preguntándole al LLM tras agotar el presupuesto

    async def test_handles_malformed_tool_arguments_without_crashing(self):
        mcp_client = FakeMcpClient(tools=[_CREAR_TAREA_TOOL], call_results={"crear_tarea": {"title": "x"}})
        llm = FakeAgentLLM(
            responses=[
                (FakeLLMMessage(tool_calls=[_tool_call("call-1", "crear_tarea", "no es json")]), 50),
                (FakeLLMMessage(content="Listo."), 10),
            ]
        )
        agent = Agent(mcp_client=mcp_client, llm=llm, guardrails=build_default_guardrails())

        result = await agent.handle("crea una tarea")

        self.assertEqual(result.message, "Listo.")
        self.assertEqual(mcp_client.calls, [("crear_tarea", {})])


if __name__ == "__main__":
    unittest.main()
