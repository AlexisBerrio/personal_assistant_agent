import argparse
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.assistant_personal.application.orchestrator import TaskOrchestrator
from src.assistant_personal.application.task_service import TaskService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI para interactuar con el asistente personal")
    subparsers = parser.add_subparsers(dest="command")

    interactive_parser = subparsers.add_parser("interactive", help="Entrar en modo conversación continua")
    interactive_parser.set_defaults(func=_handle_interactive)

    return parser


def _handle_interactive(service: TaskService, args: argparse.Namespace) -> None:
    _run_interactive_loop(service)


def _run_interactive_loop(service: TaskService) -> None:
    orchestrator = TaskOrchestrator(service=service)
    print("Asistente personal activo. Escribe 'salir' para terminar.")

    while True:
        try:
            message = input("Usuario> ").strip()
        except EOFError:
            print("\nHasta pronto.")
            break

        if message.lower() in {"salir", "exit", "quit"}:
            print("Hasta pronto.")
            break

        if not message:
            print("Guardrails: el mensaje está vacío.")
            continue

        result = orchestrator.handle_message(message)
        public_message = result.get("message") or result.get("result") or result.get("reason") or "No se pudo procesar la solicitud."
        print(public_message)


def main(argv: Sequence[str] | None = None, service: TaskService | None = None) -> None:
    parser = build_parser()
    raw_args = list(argv) if argv is not None else sys.argv[1:]

    args = parser.parse_args(raw_args)

    if not args.command or args.command == "interactive":
        _run_interactive_loop(service or TaskService())
        return

    service = service or TaskService()
    args.func(service, args)


if __name__ == "__main__":
    main()
