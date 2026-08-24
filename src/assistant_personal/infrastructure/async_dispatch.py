from __future__ import annotations

import inspect
from typing import Any


async def maybe_await(value: Any) -> Any:
    """Devuelve el resultado, esperando la coroutine solo si hace falta — soporta puertos
    inyectados síncronos o asíncronos sin que el llamador tenga que saber cuál es cuál."""
    if inspect.isawaitable(value):
        return await value
    return value


async def invoke_repository_method(
    repository: Any, method_name: str, *args: Any, error_context: str, **kwargs: Any
) -> Any:
    """Llama `{method_name}_async` si el repositorio lo implementa; si no, cae a `method_name`
    — soporta adaptadores puramente síncronos (ej. en memoria) y adaptadores async de punta a
    punta (ej. Mongo) contra el mismo puerto. `error_context` identifica el tipo de repositorio
    en el mensaje de error (ej. "repositorio de sesión")."""
    for candidate_name in (f"{method_name}_async", method_name):
        method = getattr(repository, candidate_name, None)
        if callable(method):
            return await maybe_await(method(*args, **kwargs))

    raise AttributeError(f"El {error_context} no implementa '{method_name}'")
