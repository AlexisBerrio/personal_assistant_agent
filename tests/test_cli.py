import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
