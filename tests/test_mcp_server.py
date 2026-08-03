import unittest
from unittest.mock import patch

from mongo_mcp_server import actualizar_tarea


class MCPServerTests(unittest.TestCase):
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
