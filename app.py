import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.assistant_personal.application.agent.orchestrator import TaskOrchestrator
from src.assistant_personal.config import get_settings
from src.assistant_personal.domain.repositories.conversation_orchestrator import ConversationOrchestrator
from src.assistant_personal.infrastructure.mcp.client import McpTaskServiceClient
from src.assistant_personal.infrastructure.observabilidad import configure_tracing, get_logger
from src.assistant_personal.infrastructure.persistence.mongo.long_term_memory_repository import (
    MongoLongTermMemoryRepository,
)
from src.assistant_personal.infrastructure.persistence.mongo.session_repository import MongoSessionRepository
from src.assistant_personal.infrastructure.security.alexa_signature import (
    AlexaSignatureError,
    verify_alexa_request,
)
from src.assistant_personal.interfaces.alexa import AlexaSkillRequest, handle_alexa_request

logger = get_logger(__name__)

GENERIC_ERROR_MESSAGE = "Ocurrió un error interno. Comparte el request_id con soporte si el problema persiste."

# Fijo hasta que exista identidad de usuario real (auth, Fase 6/8) — mismo criterio que
# `_CLI_USER_ID` en `interfaces/cli.py`: un único usuario implícito para toda la API.
_API_USER_ID = "api-default"


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Gestiona el ciclo de vida de recursos compartidos por la API."""
    configure_tracing()
    # MCP es la única vía de ejecución de acciones (ítem 3.1) — tanto para `/chat` como para el
    # CRUD estructurado de `/tasks` (ítem 4.10). Un solo cliente para toda la vida del proceso,
    # conectado aquí (no perezoso en la primera petición): la sesión stdio debe entrar y salir en
    # la misma task del lifespan, no en la task de una petición HTTP cualquiera — ver
    # `McpTaskServiceClient.connect()`.
    app_instance.state.mcp_client = McpTaskServiceClient()
    await app_instance.state.mcp_client.connect()
    app_instance.state.session_repository = MongoSessionRepository()
    app_instance.state.long_term_repository = MongoLongTermMemoryRepository()
    yield
    await app_instance.state.mcp_client.aclose()
    app_instance.state.mcp_client = None


# Creamos la aplicación FastAPI. Es el punto de entrada para recibir peticiones.
app = FastAPI(title="Asistente Personal", version="0.1.0", lifespan=lifespan)

if get_settings().otel_enabled:
    # Import perezoso: `opentelemetry-instrumentation-fastapi` vive en el extra `[otel]`, no en
    # las dependencias base — importarlo solo cuando el tracing está activo evita que instalar
    # la app sin ese extra rompa el arranque de `app.py`.
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


class RequestIdMiddleware:
    """Genera/propaga el request_id y lo ata a los logs de toda la petición.

    ASGI puro, no `BaseHTTPMiddleware`: éste corre el resto del stack en una task de anyio
    separada de la que espera la respuesta, lo que rompe cualquier librería aguas abajo que
    dependa de cancel scopes atados a la task internamente y fallaba con
    `RuntimeError: Attempted to exit a cancel scope in a different task`). ASGI puro ejecuta
    todo en la misma task, sin ese problema.

    `bind_contextvars` hace que cualquier `logger.info/error(...)` invocado durante esta
    petición (en cualquier módulo) incluya `request_id` automáticamente, sin tener que pasarlo
    explícitamente en cada log. `clear_contextvars` evita que el valor se filtre a la siguiente
    petición.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        # `Request.state` (usado en los exception handlers y en `/chat`) lee de este mismo dict
        # de scope — escribirlo aquí ya lo deja disponible aguas abajo sin construir un `Request`.
        scope.setdefault("state", {})["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.clear_contextvars()


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "") or "unknown"
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": request_id},
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "") or "unknown"
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": request_id})


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "") or "unknown"
    return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})


@app.exception_handler(RuntimeError)
async def handle_runtime_error(request: Request, exc: RuntimeError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "") or "unknown"
    logger.error("runtime_error_no_controlado", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR_MESSAGE, "request_id": request_id})


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    """Red de seguridad para cualquier excepción no cubierta por los handlers anteriores.

    Sin esto, un error inesperado (ej. de pymongo, del SDK de OpenAI, un
    AttributeError) se propagaba sin request_id y sin quedar registrado: el
    mismo patrón de fallo silencioso que ya se corrigió para la memoria de
    sesión, aplicado aquí a nivel de API.
    """
    request_id = getattr(request.state, "request_id", "") or "unknown"
    logger.error("excepcion_no_controlada", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR_MESSAGE, "request_id": request_id})


app.add_middleware(RequestIdMiddleware)


def get_mcp_client(request: Request) -> McpTaskServiceClient:
    """Único punto de override para tests: tanto `/chat` como `/tasks` (CRUD) pasan por aquí —
    MCP es la única vía de ejecución de acciones (ítem 3.1), sin excepción para el CRUD
    estructurado (ítem 4.10, tras la migración fuera de `TaskService` directo)."""
    return request.app.state.mcp_client


def get_alexa_signature_verifier() -> Callable[[bytes, Mapping[str, str]], Awaitable[None]]:
    """Único punto de override para tests: valida que un request a `/alexa` trae una firma real
    de Amazon. Desactivable con `ALEXA_SIGNATURE_VERIFICATION_ENABLED=false` para
    probar el endpoint a mano en local sin certificados reales."""
    if not get_settings().alexa_signature_verification_enabled:

        async def _skip_verification(raw_body: bytes, headers: Mapping[str, str]) -> None:
            return None

        return _skip_verification

    async def _verify(raw_body: bytes, headers: Mapping[str, str]) -> None:
        await verify_alexa_request(
            raw_body=raw_body,
            signature_b64=headers.get("signature"),
            cert_chain_url=headers.get("signaturecertchainurl"),
        )

    return _verify


def _record_audit_event(task_title: str, request_id: str) -> None:
    logger.info("task_created_audit", task_title=task_title, request_id=request_id)


def get_orchestrator_factory(
    request: Request, mcp_client: McpTaskServiceClient = Depends(get_mcp_client)
) -> Callable[[str], ConversationOrchestrator]:
    """Devuelve una fábrica `session_id -> ConversationOrchestrator`, no la instancia — la
    sesión depende del payload de la petición (aún no parseado en el punto en que FastAPI
    resuelve las dependencias), así que la construcción real ocurre dentro del endpoint."""

    def _build(session_id: str) -> ConversationOrchestrator:
        return TaskOrchestrator(
            service=mcp_client,
            session_repository=request.app.state.session_repository,
            long_term_repository=request.app.state.long_term_repository,
            session_id=session_id,
            user_id=_API_USER_ID,
        )

    return _build


class ChatRequest(BaseModel):
    """Un turno de la conversación."""

    message: str = Field(min_length=1, description="Mensaje del usuario en lenguaje natural.")
    session_id: str | None = Field(
        default=None,
        description="Id de sesión devuelto por un turno anterior, para mantener memoria "
        "conversacional entre peticiones. Si se omite, se crea una sesión nueva.",
    )


class ChatResponse(BaseModel):
    """Respuesta de un turno de la conversación."""

    message: str
    session_id: str
    success: bool
    action: str | None = None


@app.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    build_orchestrator: Callable[[str], ConversationOrchestrator] = Depends(get_orchestrator_factory),
) -> ChatResponse:
    """Turno conversacional completo: router + agente (MCP) + memoria de sesión/perfil.

    A diferencia de `/tasks` (CRUD estructurado), este es el único endpoint que ejecuta acciones
    interpretando lenguaje natural — precondición para cualquier frontend o canal de voz
    (Alexa, Fase 6).
    """
    session_id = payload.session_id or f"api-{uuid.uuid4()}"
    orchestrator = build_orchestrator(session_id)

    # Reutiliza el request_id de `RequestIdMiddleware` (mismo que ya viaja en el header
    # `X-Request-ID` de la respuesta) en vez de que el orquestador genere el suyo — así los logs
    # de esta interacción correlacionan con el resto de logs de la misma petición HTTP.
    request_id = getattr(request.state, "request_id", None)
    result = await orchestrator.handle_message_async(payload.message, request_id=request_id)

    return ChatResponse(
        message=result.get("message") or result.get("reason") or "No se pudo procesar la solicitud.",
        session_id=session_id,
        success=bool(result.get("success", False)),
        action=result.get("action"),
    )


@app.post("/alexa", response_model=None)
async def alexa_webhook(
    request: Request,
    build_orchestrator: Callable[[str], ConversationOrchestrator] = Depends(get_orchestrator_factory),
    verify_signature: Callable[[bytes, Mapping[str, str]], Awaitable[None]] = Depends(get_alexa_signature_verifier),
) -> dict[str, Any]:
    """Webhook de Alexa Skills Kit: mismas dependencias que `/chat`
    (`get_orchestrator_factory`) — toda la traducción del formato de Alexa vive en
    `interfaces/alexa.py`.

    Autenticado por verificación de firma en vez de una API key: Alexa exige validar que
    el request viene realmente de sus servidores, no un secreto compartido. Necesita el body
    crudo para verificar la firma antes de parsearlo a `AlexaSkillRequest`.
    """
    raw_body = await request.body()
    try:
        await verify_signature(raw_body, request.headers)
    except AlexaSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        payload = AlexaSkillRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc

    request_id = getattr(request.state, "request_id", None)
    return await handle_alexa_request(payload, build_orchestrator, request_id)


class TaskCreateRequest(BaseModel):
    """Modelo que define qué datos recibe la API para crear una tarea."""

    title: str = Field(
        min_length=1,
        description="Título principal de la tarea.",
        json_schema_extra={"example": "Revisar propuesta"},
    )
    description: str | None = Field(
        default=None,
        description="Descripción opcional de la tarea.",
        json_schema_extra={"example": "Confirmar los últimos cambios antes de enviar"},
    )
    status: str = Field(
        default="Pending",
        min_length=1,
        description="Estado de la tarea. Valores permitidos: Pending, In Progress, Completed, Deleted.",
        json_schema_extra={"example": "Pending"},
    )
    category: str | None = Field(
        default=None,
        description="Categoría de la tarea. Valores permitidos: Personal, Work, Study, Health, Home.",
        json_schema_extra={"example": "Work"},
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Etiquetas de clasificación.",
        json_schema_extra={"example": ["oficina", "urgente"]},
    )
    priority: dict[str, Any] | None = Field(
        default=None,
        description="Prioridad de la tarea. Debe incluir un campo level con uno de: Low, Medium, High.",
        json_schema_extra={"example": {"level": "High", "score": 90}},
    )
    due_date: str | None = Field(
        default=None,
        description="Fecha límite en formato ISO 8601 (ej. '2026-08-05' o '2026-08-05T12:00:00').",
        json_schema_extra={"example": "2026-08-05T12:00:00"},
    )
    recurrence: dict[str, Any] | None = Field(
        default=None,
        description="Reglas de recurrencia si aplica.",
        json_schema_extra={"example": {"is_recurring": False, "frequency": None}},
    )
    agent_notes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Notas del agente asociadas a la tarea.",
        json_schema_extra={
            "example": [{"timestamp": "2026-08-02T10:05:00", "note": "Tarea creada desde la API"}]
        },
    )


class TaskUpdateRequest(BaseModel):
    """Modelo que define qué datos admite la API para actualizar una tarea."""

    title: str | None = Field(
        default=None,
        description="Nuevo título para la tarea.",
        json_schema_extra={"example": "Revisar propuesta actualizada"},
    )
    description: str | None = Field(
        default=None,
        description="Nueva descripción de la tarea.",
        json_schema_extra={"example": "Confirmar los últimos cambios antes de enviar"},
    )
    status: str | None = Field(
        default=None,
        description="Estado de la tarea. Valores permitidos: Pending, In Progress, Completed, Deleted.",
        json_schema_extra={"example": "In Progress"},
    )
    category: str | None = Field(
        default=None,
        description="Categoría de la tarea. Valores permitidos: Personal, Work, Study, Health, Home.",
        json_schema_extra={"example": "Work"},
    )
    tags: list[str] | None = Field(
        default=None,
        description="Etiquetas de clasificación actualizadas.",
        json_schema_extra={"example": ["oficina", "urgente"]},
    )
    priority: dict[str, Any] | None = Field(
        default=None,
        description="Prioridad de la tarea. Debe incluir un campo level con uno de: Low, Medium, High.",
        json_schema_extra={"example": {"level": "High", "score": 90}},
    )
    due_date: str | None = Field(
        default=None,
        description="Fecha límite actualizada, en formato ISO 8601.",
        json_schema_extra={"example": "2026-08-05T12:00:00"},
    )
    recurrence: dict[str, Any] | None = Field(
        default=None,
        description="Reglas de recurrencia actualizadas.",
        json_schema_extra={"example": {"is_recurring": False, "frequency": None}},
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    """Endpoint simple para comprobar que la API responde."""
    return {"status": "ok"}


@app.post("/tasks", status_code=201, response_model=None)
async def create_task(
    payload: TaskCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    mcp_client: McpTaskServiceClient = Depends(get_mcp_client),
) -> dict[str, Any]:
    """Recibe una tarea desde el cliente y la crea vía MCP (tool `crear_tarea`, ítem 4.10) — el
    CRUD estructurado ya no llama a `TaskService` en proceso, mismo criterio que `/chat`."""
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="El título de la tarea es obligatorio")

    status = payload.status.strip()
    if not status:
        raise HTTPException(status_code=400, detail="El estado de la tarea no puede estar vacío")

    tool_payload = {
        "title": title,
        "description": payload.description,
        "status": status,
        "category": payload.category,
        "tags": payload.tags,
        "priority": payload.priority,
        "due_date": payload.due_date,
        "recurrence": payload.recurrence,
        "agent_notes": payload.agent_notes,
    }
    try:
        result = await mcp_client.create_task_async(tool_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request_id = getattr(request.state, "request_id", "") if request is not None else ""
    if background_tasks is not None:
        background_tasks.add_task(_record_audit_event, title, request_id)

    return result


@app.get("/tasks")
async def list_tasks(mcp_client: McpTaskServiceClient = Depends(get_mcp_client)) -> list[dict[str, object]]:
    """Devuelve una lista de tareas almacenadas en MongoDB."""
    return await mcp_client.list_tasks_async()


@app.get("/tasks/{task_id}")
async def get_task(
    task_id: str, mcp_client: McpTaskServiceClient = Depends(get_mcp_client)
) -> dict[str, object] | None:
    """Devuelve una tarea concreta a partir de su task_id."""
    task = await mcp_client.get_task_async(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


@app.get("/tasks/{task_id}/history")
async def get_task_history(
    task_id: str, mcp_client: McpTaskServiceClient = Depends(get_mcp_client)
) -> list[dict[str, object]]:
    """Devuelve el historial de cambios de una tarea."""
    history = await mcp_client.get_task_history_async(task_id)
    if not history:
        raise HTTPException(status_code=404, detail="No se encontró historial para la tarea")
    return history


@app.patch("/tasks/{task_id}")
async def update_task(
    task_id: str, payload: TaskUpdateRequest, mcp_client: McpTaskServiceClient = Depends(get_mcp_client)
) -> dict[str, object]:
    """Actualiza una tarea existente identificada por task_id.

    Si el payload incluye un estado "Completed", la tarea se marca como
    completada usando la misma ruta de actualización.
    """
    payload_data = payload.model_dump(exclude_unset=True)
    if not payload_data:
        raise HTTPException(status_code=400, detail="Se debe proporcionar al menos un campo para actualizar")

    if str(payload_data.get("status", "")).strip().lower() == "completed":
        return await mcp_client.complete_task_async(task_id)

    try:
        updated_task = await mcp_client.update_task_async(task_id, payload_data)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if updated_task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return updated_task


@app.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str, mcp_client: McpTaskServiceClient = Depends(get_mcp_client)
) -> dict[str, object]:
    """Marca una tarea como eliminada sin borrarla de la base de datos."""
    deleted_task = await mcp_client.delete_task_async(task_id)
    if deleted_task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return deleted_task
