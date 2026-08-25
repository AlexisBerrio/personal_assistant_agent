from __future__ import annotations

from opentelemetry import trace

from src.assistant_personal.config import get_settings
from src.assistant_personal.infrastructure.observabilidad.logging import get_logger

logger = get_logger(__name__)

_configured = False


def configure_tracing() -> None:
    """Configura el `TracerProvider` global con export OTLP a Jaeger, si `OTEL_ENABLED=true`.

    Idempotente (mismo criterio que `configure_logging`): llamarla más de una vez en el mismo
    proceso no duplica el exporter. Si `OTEL_ENABLED` es falso (default), no hace nada —
    `get_tracer()` sigue siendo válido en cualquier caso: sin un `TracerProvider` real,
    OpenTelemetry usa un tracer no-op con costo ~cero, así que el código que crea spans no
    necesita saber si el tracing está activo.

    No falla si Jaeger no está arriba: `BatchSpanProcessor` exporta en un hilo aparte y absorbe
    los errores del exporter (reintentos/timeouts internos), nunca bloquea ni tumba el proceso.
    """
    global _configured
    if _configured:
        return
    _configured = True

    settings = get_settings()
    if not settings.otel_enabled:
        return

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: "assistant-personal"}))
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    PymongoInstrumentor().instrument()
    logger.info("tracing_configurado", endpoint=settings.otel_exporter_otlp_endpoint)


def get_tracer(name: str) -> trace.Tracer:
    """Punto único para obtener un tracer. Válido sin `configure_tracing()`: devuelve spans
    no-op si el tracing está apagado o no se configuró todavía."""
    return trace.get_tracer(name)
