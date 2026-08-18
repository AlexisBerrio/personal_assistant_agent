from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Configura logging estructurado en JSON para toda la aplicación.

    Idempotente por diseño: como este módulo solo se ejecuta una vez por
    proceso (caché de imports de Python), no hace falta guardia adicional.
    Cualquier punto de entrada (API, CLI, servidor MCP) que importe este
    paquete queda configurado igual, sin duplicar handlers.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Punto único para obtener un logger. Nunca uses `print` fuera de la CLI
    (donde `print` es la salida legítima del producto, no diagnóstico)."""
    return structlog.get_logger(name)


configure_logging()
