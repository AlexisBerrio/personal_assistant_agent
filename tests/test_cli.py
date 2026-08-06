import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

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
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_cli_accepts_a_direct_user_message(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            main(["crear una tarea para estudiar"], service=FakeService())

        result = output.getvalue()
        self.assertIn("create_task", result.lower())
        self.assertIn("tarea para estudiar", result.lower())


if __name__ == "__main__":
    unittest.main()
