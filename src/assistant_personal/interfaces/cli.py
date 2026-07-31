import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.assistant_personal.application.task_service import TaskService


def main() -> None:
    service = TaskService()
    tasks = service.list_tasks()
    print("Tareas actuales:")
    for task in tasks:
        print(task)


if __name__ == "__main__":
    main()
