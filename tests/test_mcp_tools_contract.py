from __future__ import annotations

import asyncio
import os
import sys
import unittest
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from motor.motor_asyncio import AsyncIOMotorClient

LOCAL_MONGO_URI = "mongodb://localhost:27018"
_SERVER_SCRIPT = Path(__file__).resolve().parents[1] / "mongo_mcp_server.py"

EXPECTED_TOOLS_REQUIRED_PARAMS = {
    "health_check": set(),
    "listar_tareas": set(),
    "crear_tarea": {"title"},
    "actualizar_tarea": {"task_id"},
    "completar_tarea": {"task_id"},
    "buscar_tarea": {"task_id"},
}


def _local_mongo_is_reachable() -> bool:
    async def _ping() -> bool:
        client = AsyncIOMotorClient(LOCAL_MONGO_URI, serverSelectionTimeoutMS=2000)
        try:
            await client.admin.command("ping")
            return True
        except Exception:
            return False
        finally:
            client.close()

    return asyncio.run(_ping())


@unittest.skipUnless(
    _local_mongo_is_reachable(),
    "Requiere el Mongo local desechable de docker-compose.yml: ejecuta `docker compose up -d mongo`",
)
class McpToolsContractTests(unittest.IsolatedAsyncioTestCase):
    """Contrato (esquema + comportamiento) de las 6 tools MCP, contra el protocolo real por
    stdio y Mongo local — no la Atlas de `.env`. Complementa test_mcp_client_integration.py
    (ítem 3.1, que solo prueba que el cliente funciona en el camino feliz): aquí se valida cada
    tool por separado, incluyendo casos borde, para que un cambio accidental de esquema o de
    comportamiento se detecte antes de que rompa a quien la invoque (hoy el router, más adelante
    el agente de Fase 4, ítem 3.2)."""

    def setUp(self) -> None:
        self.db_name = "assistant_personal_test"
        self.env = {**os.environ, "MONGO_URI": LOCAL_MONGO_URI, "MONGO_DB_NAME": self.db_name}

    async def asyncTearDown(self) -> None:
        motor_client = AsyncIOMotorClient(LOCAL_MONGO_URI)
        await motor_client[self.db_name].personal_tasks.delete_many({"title": {"$regex": "^mcp-contract-"}})
        motor_client.close()

    async def _open_session(self) -> tuple[ClientSession, AsyncExitStack]:
        # Una sesión (y subproceso) por test: igual que test_mcp_client_integration.py, cerrar
        # en un task distinto al que abrió la sesión rompe el cancel scope de anyio.
        stack = AsyncExitStack()
        params = StdioServerParameters(command=sys.executable, args=[str(_SERVER_SCRIPT)], env=self.env)
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session, stack

    # FastMCP envuelve structuredContent bajo {"result": ...} cuando el tipo de retorno anotado
    # es `dict | None` (buscar_tarea, actualizar_tarea) — igual que ya hace con arrays (ítem 3.1)
    # — pero no cuando es un `dict` simple (crear_tarea, completar_tarea). Confirmado con
    # smoke-testing real antes de escribir estos asserts, no es una suposición.
    async def _create_task(self, session: ClientSession, title: str) -> dict[str, Any]:
        result = await session.call_tool("crear_tarea", {"title": title})
        assert result.structuredContent is not None
        return result.structuredContent

    async def test_expone_exactamente_las_seis_tools_con_sus_campos_requeridos(self) -> None:
        session, stack = await self._open_session()
        try:
            tools = await session.list_tools()
            tools_by_name = {tool.name: tool for tool in tools.tools}

            self.assertEqual(set(tools_by_name), set(EXPECTED_TOOLS_REQUIRED_PARAMS))
            for name, expected_required in EXPECTED_TOOLS_REQUIRED_PARAMS.items():
                actual_required = set(tools_by_name[name].inputSchema.get("required", []))
                self.assertEqual(actual_required, expected_required, f"esquema de '{name}' cambió")
        finally:
            await stack.aclose()

    async def test_health_check_reporta_conexion_a_mongo(self) -> None:
        session, stack = await self._open_session()
        try:
            result = await session.call_tool("health_check", {})
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent["status"], "ok")
            self.assertEqual(result.structuredContent["database"], "connected")
        finally:
            await stack.aclose()

    async def test_crear_tarea_devuelve_la_tarea_creada_con_task_id(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)
            self.assertEqual(created["title"], title)
            self.assertTrue(created["task_id"])
        finally:
            await stack.aclose()

    async def test_crear_tarea_sin_title_falla_con_error_de_validacion(self) -> None:
        session, stack = await self._open_session()
        try:
            result = await session.call_tool("crear_tarea", {})
            self.assertTrue(result.isError)
            self.assertIn("title", result.content[0].text)
        finally:
            await stack.aclose()

    async def test_buscar_tarea_devuelve_la_tarea_existente_y_none_si_no_existe(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)

            found = await session.call_tool("buscar_tarea", {"task_id": created["task_id"]})
            self.assertFalse(found.isError)
            self.assertEqual(found.structuredContent["result"]["title"], title)

            missing = await session.call_tool("buscar_tarea", {"task_id": "no-existe-999"})
            self.assertFalse(missing.isError)
            self.assertIsNone(missing.structuredContent["result"])
        finally:
            await stack.aclose()

    async def test_actualizar_tarea_sin_campos_falla(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)

            result = await session.call_tool("actualizar_tarea", {"task_id": created["task_id"]})
            self.assertTrue(result.isError)
            self.assertIn("No se proporcionaron campos", result.content[0].text)
        finally:
            await stack.aclose()

    async def test_actualizar_tarea_aplica_el_campo_solicitado(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)
            new_title = f"{title}-actualizado"

            result = await session.call_tool("actualizar_tarea", {"task_id": created["task_id"], "title": new_title})
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent["result"]["title"], new_title)
        finally:
            await stack.aclose()

    async def test_completar_tarea_es_idempotente_y_no_falla_sobre_id_inexistente(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)
            task_id = created["task_id"]

            first = await session.call_tool("completar_tarea", {"task_id": task_id})
            self.assertEqual(first.structuredContent, {"matched": 1, "modified": 1})

            second = await session.call_tool("completar_tarea", {"task_id": task_id})
            self.assertEqual(second.structuredContent, {"matched": 1, "modified": 0})

            missing = await session.call_tool("completar_tarea", {"task_id": "no-existe-999"})
            self.assertFalse(missing.isError)
            self.assertEqual(missing.structuredContent, {"matched": 0, "modified": 0})
        finally:
            await stack.aclose()


if __name__ == "__main__":
    unittest.main()
