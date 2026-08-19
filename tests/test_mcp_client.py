import unittest
from typing import Any

from mcp.types import CallToolResult, TextContent

from src.assistant_personal.infrastructure.mcp.client import McpTaskServiceClient


class FakeSession:
    def __init__(self, results: dict[str, CallToolResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        self.calls.append((name, arguments))
        return self.results[name]


def _ok(structured: Any) -> CallToolResult:
    return CallToolResult(content=[], structuredContent=structured, isError=False)


def _error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], structuredContent=None, isError=True)


class McpTaskServiceClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_tasks_unwraps_the_tasks_key(self) -> None:
        """listar_tareas devuelve {"tasks": [...]} (ítem 3.5: contrato explícito, sin depender
        del wrapping automático de FastMCP para tipos no-objeto) — este test fija ese contrato."""
        session = FakeSession({"listar_tareas": _ok({"tasks": [{"task_id": "t-1"}]})})
        client = McpTaskServiceClient(session=session)

        tasks = await client.list_tasks_async()

        self.assertEqual(tasks, [{"task_id": "t-1"}])
        self.assertEqual(session.calls, [("listar_tareas", {})])

    async def test_create_task_forwards_the_payload_and_returns_structured_content(self) -> None:
        session = FakeSession({"crear_tarea": _ok({"task_id": "t-2", "title": "Comprar leche"})})
        client = McpTaskServiceClient(session=session)

        result = await client.create_task_async({"title": "Comprar leche"})

        self.assertEqual(result, {"task_id": "t-2", "title": "Comprar leche"})
        self.assertEqual(session.calls, [("crear_tarea", {"title": "Comprar leche"})])

    async def test_complete_task_sends_task_id(self) -> None:
        session = FakeSession({"completar_tarea": _ok({"matched": 1, "modified": 1})})
        client = McpTaskServiceClient(session=session)

        result = await client.complete_task_async("t-3")

        self.assertEqual(result, {"matched": 1, "modified": 1})
        self.assertEqual(session.calls, [("completar_tarea", {"task_id": "t-3"})])

    async def test_tool_error_raises_with_the_message_from_the_server(self) -> None:
        session = FakeSession({"crear_tarea": _error("El título es obligatorio")})
        client = McpTaskServiceClient(session=session)

        with self.assertRaises(RuntimeError) as ctx:
            await client.create_task_async({})

        self.assertIn("El título es obligatorio", str(ctx.exception))

    async def test_aclose_is_a_noop_when_the_session_was_injected(self) -> None:
        """El cliente no debe cerrar una sesión que no abrió él mismo (mismo patrón que otros
        adaptadores del proyecto: quien la crea, la cierra)."""
        session = FakeSession({})
        client = McpTaskServiceClient(session=session)

        await client.aclose()  # no debe lanzar ni tocar la sesión inyectada


if __name__ == "__main__":
    unittest.main()
