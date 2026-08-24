from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimitExceededError(Exception):
    """El cliente superó el límite de peticiones permitido en la ventana de tiempo."""


class SlidingWindowRateLimiter:
    """Rate limiter en memoria de proceso, ventana deslizante por clave (ej. IP del cliente).

    Solo válido para una instancia de proceso único (el conteo vive en un `dict` en memoria, no
    en un backend compartido) — encaja con el despliegue actual del proyecto. Un despliegue
    horizontal (varias réplicas) necesitaría un backend compartido (ej. Redis) para que el
    límite sea real entre procesos.
    """

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests < 1:
            raise ValueError("max_requests debe ser >= 1")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Registra una petición para `key`. Lanza `RateLimitExceededError` si ya alcanzó el
        máximo de peticiones dentro de la ventana — no registra la petición que la excede."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self._window_seconds:
            hits.popleft()
        if len(hits) >= self._max_requests:
            raise RateLimitExceededError(
                f"Límite de {self._max_requests} peticiones por {self._window_seconds:.0f}s excedido"
            )
        hits.append(now)
