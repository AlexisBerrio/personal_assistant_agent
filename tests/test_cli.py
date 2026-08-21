import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.assistant_personal.application.memory.agent_context import (
    InMemoryLongTermMemoryRepository,
    InMemorySessionRepository,
)
from src.assistant_personal.interfaces.cli import main


class FakeService:
    def list_tasks(self):
        return [{"title": "Tarea inicial"}]

    def create_task(self, task):
        return {"title": task["title"], "status": "Pending"}

    def complete_task(self, task_id):
        return {"task_id": task_id, "status": "Completed"}


class CliExecutionTests(unittest.TestCase):
    def test_cli_can_run_directly_from_its_folder(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        cli_dir = repo_root / "src" / "assistant_personal" / "interfaces"

        completed = subprocess.run(
            [sys.executable, "cli.py"],
            cwd=cli_dir,
            capture_output=True,
            input="salir\n",
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_cli_accepts_a_direct_user_message(self) -> None:
        # Repositorios en memoria explícitos: este test valida parseo de argumentos y formato
        # de salida del CLI, no persistencia real — no debe depender de que Mongo esté
        # disponible (el CLI usa Mongo real por defecto, ver interfaces/cli.py).
        output = StringIO()
        with redirect_stdout(output):
            main(
                ["nueva tarea: estudiar"],
                service=FakeService(),
                session_repository=InMemorySessionRepository(),
                long_term_repository=InMemoryLongTermMemoryRepository(),
            )

        result = output.getvalue()
        self.assertIn("tarea creada", result.lower())
        self.assertIn("estudiar", result.lower())

    def test_cli_enters_interactive_mode_when_requested(self) -> None:
        output = StringIO()
        with patch("builtins.input", side_effect=["salir"]), redirect_stdout(output):
            main(
                ["interactive"],
                service=FakeService(),
                session_repository=InMemorySessionRepository(),
                long_term_repository=InMemoryLongTermMemoryRepository(),
            )

        result = output.getvalue()
        self.assertIn("asistente personal activo", result.lower())
        self.assertIn("hasta pronto", result.lower())


if __name__ == "__main__":
    unittest.main()
