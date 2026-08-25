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
        """listar_tareas devuelve {"tasks": [...]}, un contrato explícito en vez de depender del
        wrapping automático de FastMCP para tipos no-objeto — este test lo fija."""
        session = FakeSession({"listar_tareas": _ok({"tasks": [{"task_id": "t-1"}]})})
        client = McpTaskServiceClient(session=session)

        tasks = await client.list_tasks_async()

        self.assertEqual(tasks, [{"task_id": "t-1"}])
        self.assertEqual(session.calls, [("listar_tareas", {"limite": 20})])

    async def test_list_tasks_forwards_status_filter_as_estado(self) -> None:
        session = FakeSession({"listar_tareas": _ok({"tasks": []})})
        client = McpTaskServiceClient(session=session)

        await client.list_tasks_async(status="Completed", limit=5)

        self.assertEqual(session.calls, [("listar_tareas", {"estado": "Completed", "limite": 5})])

    async def test_create_task_forwards_the_payload_and_returns_structured_content(self) -> None:
        session = FakeSession({"crear_tarea": _ok({"task_id": "t-2", "title": "Comprar leche"})})
        client = McpTaskServiceClient(session=session)

        result = await client.create_task_async({"title": "Comprar leche"})

        self.assertEqual(result, {"task_id": "t-2", "title": "Comprar leche"})
        self.assertEqual(session.calls, [("crear_tarea", {"title": "Comprar leche"})])

    async def test_get_task_unwraps_the_task_key(self) -> None:
        session = FakeSession({"buscar_tarea": _ok({"task": {"task_id": "t-4", "title": "Comprar leche"}})})
        client = McpTaskServiceClient(session=session)

        task = await client.get_task_async("t-4")

        self.assertEqual(task, {"task_id": "t-4", "title": "Comprar leche"})
        self.assertEqual(session.calls, [("buscar_tarea", {"task_id": "t-4"})])

    async def test_get_task_returns_none_when_the_task_does_not_exist(self) -> None:
        session = FakeSession({"buscar_tarea": _ok({"task": None})})
        client = McpTaskServiceClient(session=session)

        task = await client.get_task_async("no-existe")

        self.assertIsNone(task)

    async def test_get_task_history_unwraps_the_history_key(self) -> None:
        session = FakeSession({"historial_tarea": _ok({"history": [{"task_id": "t-5", "changes": []}]})})
        client = McpTaskServiceClient(session=session)

        history = await client.get_task_history_async("t-5")

        self.assertEqual(history, [{"task_id": "t-5", "changes": []}])
        self.assertEqual(session.calls, [("historial_tarea", {"task_id": "t-5"})])

    async def test_update_task_forwards_task_id_and_updates_together(self) -> None:
        session = FakeSession({"actualizar_tarea": _ok({"task": {"task_id": "t-6", "title": "Nuevo título"}})})
        client = McpTaskServiceClient(session=session)

        updated = await client.update_task_async("t-6", {"title": "Nuevo título"})

        self.assertEqual(updated, {"task_id": "t-6", "title": "Nuevo título"})
        self.assertEqual(session.calls, [("actualizar_tarea", {"task_id": "t-6", "title": "Nuevo título"})])

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

    async def test_connect_is_a_noop_when_the_session_was_injected(self) -> None:
        """`connect()` solo importa para el caso real (spawnear el subproceso stdio explícito,
        en la task de quien llama, ítem 4.10); con una sesión ya inyectada no hay nada que
        establecer."""
        session = FakeSession({})
        client = McpTaskServiceClient(session=session)

        await client.connect()

        self.assertIs(await client._ensure_session(), session)

    async def test_aclose_is_a_noop_when_the_session_was_injected(self) -> None:
        """El cliente no debe cerrar una sesión que no abrió él mismo (mismo patrón que otros
        adaptadores del proyecto: quien la crea, la cierra)."""
        session = FakeSession({})
        client = McpTaskServiceClient(session=session)

        await client.aclose()  # no debe lanzar ni tocar la sesión inyectada


if __name__ == "__main__":
    unittest.main()
