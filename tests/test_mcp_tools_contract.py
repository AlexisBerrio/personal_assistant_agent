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
    "eliminar_tarea": {"task_id"},
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
    """Contrato (esquema + comportamiento) de las 7 tools MCP, contra el protocolo real por
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

    # Ítem 3.5: las 6 tools devuelven siempre un objeto con nombres de campo explícitos
    # (`tasks`, `task`) en vez de depender del wrapping automático de FastMCP bajo `{"result":
    # ...}` para tipos no-objeto (`dict | None`, listas) — contrato uniforme, sin necesidad de
    # conocer por tool si hace falta desenvolver algo.
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
                schema = tools_by_name[name].inputSchema
                actual_required = set(schema.get("required", []))
                self.assertEqual(actual_required, expected_required, f"esquema de '{name}' cambió")
                # Ítem 3.4: tenant_id lo inyecta el servidor (MongoTaskRepository), nunca un
                # parámetro que el LLM pueda fijar — si alguien lo agrega a una tool, esto falla.
                self.assertNotIn(
                    "tenant_id",
                    schema.get("properties", {}),
                    f"'{name}' no debe aceptar tenant_id como parámetro",
                )
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

    async def test_listar_tareas_devuelve_las_tareas_bajo_la_clave_tasks(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)

            result = await session.call_tool("listar_tareas", {})
            self.assertFalse(result.isError)
            task_ids = {t["task_id"] for t in result.structuredContent["tasks"]}
            self.assertIn(created["task_id"], task_ids)
        finally:
            await stack.aclose()

    async def test_listar_tareas_filtra_por_estado(self) -> None:
        session, stack = await self._open_session()
        try:
            pending_title = f"mcp-contract-{uuid.uuid4()}"
            completed_title = f"mcp-contract-{uuid.uuid4()}"
            pending = await self._create_task(session, pending_title)
            completed = await self._create_task(session, completed_title)
            await session.call_tool("completar_tarea", {"task_id": completed["task_id"]})

            result = await session.call_tool("listar_tareas", {"estado": "Completed"})
            self.assertFalse(result.isError)
            task_ids = {t["task_id"] for t in result.structuredContent["tasks"]}
            self.assertIn(completed["task_id"], task_ids)
            self.assertNotIn(pending["task_id"], task_ids)
        finally:
            await stack.aclose()

    async def test_listar_tareas_respeta_el_limite_pedido(self) -> None:
        session, stack = await self._open_session()
        try:
            for _ in range(3):
                await self._create_task(session, f"mcp-contract-{uuid.uuid4()}")

            result = await session.call_tool("listar_tareas", {"limite": 2})
            self.assertFalse(result.isError)
            self.assertLessEqual(len(result.structuredContent["tasks"]), 2)
        finally:
            await stack.aclose()

    async def test_crear_tarea_devuelve_la_tarea_creada_con_task_id(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)
            self.assertEqual(created["title"], title)
            self.assertTrue(created["task_id"])
            self.assertTrue(created["created_at"])
            self.assertIsNone(created["due_date"])
            self.assertIsNone(created["completed_at"])
        finally:
            await stack.aclose()

    async def test_crear_tarea_normaliza_due_date_iso_y_rechaza_formato_invalido(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            result = await session.call_tool("crear_tarea", {"title": title, "due_date": "2026-08-28"})
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent["due_date"], "2026-08-28T00:00:00")

            invalid = await session.call_tool(
                "crear_tarea", {"title": f"{title}-invalida", "due_date": "el viernes"}
            )
            self.assertTrue(invalid.isError)
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
            self.assertEqual(found.structuredContent["task"]["title"], title)

            missing = await session.call_tool("buscar_tarea", {"task_id": "no-existe-999"})
            self.assertFalse(missing.isError)
            self.assertIsNone(missing.structuredContent["task"])
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
            self.assertEqual(result.structuredContent["task"]["title"], new_title)
        finally:
            await stack.aclose()

    async def test_eliminar_tarea_marca_como_eliminada_y_no_falla_sobre_id_inexistente(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)

            deleted = await session.call_tool("eliminar_tarea", {"task_id": created["task_id"]})
            self.assertFalse(deleted.isError)
            self.assertEqual(deleted.structuredContent["task"]["task_id"], created["task_id"])
            self.assertTrue(deleted.structuredContent["task"]["deleted"])

            missing = await session.call_tool("eliminar_tarea", {"task_id": "no-existe-999"})
            self.assertFalse(missing.isError)
            self.assertIsNone(missing.structuredContent["task"])
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

    async def test_completar_tarea_estampa_completed_at_una_sola_vez(self) -> None:
        session, stack = await self._open_session()
        try:
            title = f"mcp-contract-{uuid.uuid4()}"
            created = await self._create_task(session, title)
            task_id = created["task_id"]

            await session.call_tool("completar_tarea", {"task_id": task_id})
            after_first = await session.call_tool("buscar_tarea", {"task_id": task_id})
            completed_at = after_first.structuredContent["task"]["completed_at"]
            self.assertTrue(completed_at)

            await session.call_tool("completar_tarea", {"task_id": task_id})
            after_second = await session.call_tool("buscar_tarea", {"task_id": task_id})
            self.assertEqual(after_second.structuredContent["task"]["completed_at"], completed_at)
        finally:
            await stack.aclose()


if __name__ == "__main__":
    unittest.main()
