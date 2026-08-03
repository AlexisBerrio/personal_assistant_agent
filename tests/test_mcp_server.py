import unittest
from unittest.mock import patch

import mongo_mcp_server
from mongo_mcp_server import actualizar_tarea
from src.assistant_personal.infrastructure.mcp.tools.task_tools import register_task_tools


class DummyMcp:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


class MCPServerTests(unittest.TestCase):
    def test_register_task_tools_accepts_injected_service(self):
        class FakeService:
            def __init__(self):
                self.calls = []

            def list_tasks(self):
                self.calls.append("list")
                return [{"task_id": "task-123"}]

        dummy_mcp = DummyMcp()
        fake_service = FakeService()

        register_task_tools(dummy_mcp, fake_service)

        self.assertIn("listar_tareas", dummy_mcp.tools)
        result = dummy_mcp.tools["listar_tareas"]()

        self.assertEqual(result, [{"task_id": "task-123"}])
        self.assertEqual(fake_service.calls, ["list"])

    def test_main_calls_run_server(self):
        with patch("mongo_mcp_server.run_server") as mock_run_server:
            mongo_mcp_server.main()

        mock_run_server.assert_called_once_with()

    def test_actualizar_tarea_accepts_richer_business_fields(self):
        with patch("mongo_mcp_server.service.update_task", return_value={"task_id": "task-123"}) as mock_update_task:
            result = actualizar_tarea(
                task_id="task-123",
                title="Nueva propuesta",
                description="Revisar antes de enviar",
                status="In Progress",
                category="Work",
                tags=["oficina", "urgente"],
                priority={"level": "High", "score": 90},
                dates={"due_date": "2026-08-05T12:00:00"},
                recurrence={"is_recurring": False, "frequency": None},
                context_metadata={"source": "mcp", "location": "home"},
                steps=[{"step_id": 1, "text": "Revisar propuesta", "is_completed": False}],
                agent_notes=[{"timestamp": "2026-08-03T09:00:00", "note": "Actualizado desde MCP"}],
            )

        self.assertEqual(result, {"task_id": "task-123"})
        mock_update_task.assert_called_once_with(
            "task-123",
            {
                "title": "Nueva propuesta",
                "description": "Revisar antes de enviar",
                "status": "In Progress",
                "category": "Work",
                "tags": ["oficina", "urgente"],
                "priority": {"level": "High", "score": 90},
                "dates": {"due_date": "2026-08-05T12:00:00"},
                "recurrence": {"is_recurring": False, "frequency": None},
                "context_metadata": {"source": "mcp", "location": "home"},
                "steps": [{"step_id": 1, "text": "Revisar propuesta", "is_completed": False}],
                "agent_notes": [{"timestamp": "2026-08-03T09:00:00", "note": "Actualizado desde MCP"}],
            },
        )
