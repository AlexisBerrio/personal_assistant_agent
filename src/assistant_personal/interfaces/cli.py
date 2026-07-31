from src.assistant_personal.application.task_service import TaskService


def main() -> None:
    service = TaskService()
    tasks = service.list_tasks()
    print("Tareas actuales:")
    for task in tasks:
        print(task)


if __name__ == "__main__":
    main()
