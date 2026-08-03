import argparse
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.assistant_personal.application.task_service import TaskService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI para interactuar con tareas del asistente personal")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="Listar tareas activas")
    list_parser.set_defaults(func=_handle_list)

    create_parser = subparsers.add_parser("create", help="Crear una nueva tarea")
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description", default=None)
    create_parser.add_argument("--status", default="Pending")
    create_parser.add_argument("--category", default=None)
    create_parser.set_defaults(func=_handle_create)

    update_parser = subparsers.add_parser("update", help="Actualizar una tarea existente")
    update_parser.add_argument("task_id")
    update_parser.add_argument("--title", default=None)
    update_parser.add_argument("--description", default=None)
    update_parser.add_argument("--status", default=None)
    update_parser.add_argument("--category", default=None)
    update_parser.set_defaults(func=_handle_update)

    complete_parser = subparsers.add_parser("complete", help="Completar una tarea")
    complete_parser.add_argument("task_id")
    complete_parser.set_defaults(func=_handle_complete)

    return parser


def _handle_list(service: TaskService) -> None:
    tasks = service.list_tasks()
    print("Tareas actuales:")
    for task in tasks:
        print(task)


def _handle_create(service: TaskService, args: argparse.Namespace) -> None:
    result = service.create_task({
        "title": args.title,
        "description": args.description,
        "status": args.status,
        "category": args.category,
    })
    print(result)


def _handle_update(service: TaskService, args: argparse.Namespace) -> None:
    updates = {}
    if args.title is not None:
        updates["title"] = args.title
    if args.description is not None:
        updates["description"] = args.description
    if args.status is not None:
        updates["status"] = args.status
    if args.category is not None:
        updates["category"] = args.category

    result = service.update_task(args.task_id, updates)
    print(result)


def _handle_complete(service: TaskService, args: argparse.Namespace) -> None:
    result = service.complete_task(args.task_id)
    print(result)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not hasattr(args, "func"):
        parser.print_help()
        return

    service = TaskService()
    args.func(service, args)


if __name__ == "__main__":
    main()
