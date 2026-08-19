import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence

from src.assistant_personal.application.orchestrator import TaskOrchestrator
from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.repositories.long_term_memory_repository import LongTermMemoryRepository
from src.assistant_personal.domain.repositories.session_memory_repository import SessionMemoryRepository
from src.assistant_personal.infrastructure.persistence.mongo.long_term_memory_repository import (
    MongoLongTermMemoryRepository,
)
from src.assistant_personal.infrastructure.persistence.mongo.session_repository import MongoSessionRepository

# Fijo hasta que exista identidad de usuario real (auth, Fase 6/8) — mismo criterio que
# `tenant_id`/`user_id` en TaskOrchestrator. Estable entre invocaciones del CLI a propósito: es
# lo que permite que la memoria de largo plazo (perfil) se vea persistir de una ejecución del
# proceso a la siguiente, aunque cada invocación abra una `session_id` nueva.
_CLI_USER_ID = "cli-default"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI para interactuar con el asistente personal")
    subparsers = parser.add_subparsers(dest="command")

    interactive_parser = subparsers.add_parser("interactive", help="Entrar en modo conversación continua")
    interactive_parser.set_defaults(func=_handle_interactive)

    return parser


def _handle_interactive(service: TaskService, args: argparse.Namespace) -> None:
    _run_interactive_loop(service)


def _format_result_message(result: dict[str, object]) -> str:
    return result.get("message") or result.get("result") or result.get("reason") or "No se pudo procesar la solicitud."


def _handle_single_message(
    service: TaskService,
    message: str,
    session_repository: SessionMemoryRepository | None = None,
    long_term_repository: LongTermMemoryRepository | None = None,
) -> None:
    orchestrator = TaskOrchestrator(
        service=service,
        session_repository=session_repository or MongoSessionRepository(),
        long_term_repository=long_term_repository or MongoLongTermMemoryRepository(),
        session_id=f"cli-{uuid.uuid4()}",
        user_id=_CLI_USER_ID,
    )
    result = orchestrator.handle_message(message)
    print(_format_result_message(result))


def _run_interactive_loop(
    service: TaskService,
    session_repository: SessionMemoryRepository | None = None,
    long_term_repository: LongTermMemoryRepository | None = None,
) -> None:
    """Punto de entrada síncrono: abre un único event loop para toda la sesión.

    Reutilizar `orchestrator.handle_message()` (que hace su propio `asyncio.run`)
    en cada turno abriría y cerraría un loop distinto por mensaje. El cliente de
    Motor queda ligado al primer loop en el que se usa; reutilizarlo desde un loop
    nuevo en el siguiente turno rompe con `RuntimeError: Event loop is closed`.
    Un único `asyncio.run` para toda la sesión evita ese cruce de loops.
    """
    asyncio.run(_run_interactive_loop_async(service, session_repository, long_term_repository))


async def _run_interactive_loop_async(
    service: TaskService,
    session_repository: SessionMemoryRepository | None = None,
    long_term_repository: LongTermMemoryRepository | None = None,
) -> None:
    orchestrator = TaskOrchestrator(
        service=service,
        session_repository=session_repository or MongoSessionRepository(),
        long_term_repository=long_term_repository or MongoLongTermMemoryRepository(),
        session_id=f"cli-{uuid.uuid4()}",
        user_id=_CLI_USER_ID,
    )
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

        result = await orchestrator.handle_message_async(message)
        print(_format_result_message(result))


def main(
    argv: Sequence[str] | None = None,
    service: TaskService | None = None,
    session_repository: SessionMemoryRepository | None = None,
    long_term_repository: LongTermMemoryRepository | None = None,
) -> None:
    parser = build_parser()
    raw_args = list(argv) if argv is not None else sys.argv[1:]

    if raw_args and raw_args[0] not in {"interactive"} and not raw_args[0].startswith("-"):
        _handle_single_message(
            service or TaskService(), " ".join(raw_args).strip(), session_repository, long_term_repository
        )
        return

    args = parser.parse_args(raw_args)

    if not args.command or args.command == "interactive":
        _run_interactive_loop(service or TaskService(), session_repository, long_term_repository)
        return

    service = service or TaskService()
    args.func(service, args)


if __name__ == "__main__":
    main()
