from __future__ import annotations

import asyncio
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from src.assistant_personal.config import get_settings
from src.assistant_personal.infrastructure.observabilidad import get_logger

settings = get_settings()
logger = get_logger(__name__)


class MongoConnection:
    """Encapsula la conexión con MongoDB para mantener la infraestructura ordenada.

    Async de extremo a extremo: nunca se hace `asyncio.run`/bridging aquí dentro.
    Motor liga internamente su cliente (y el executor que usa para las llamadas)
    al event loop que estaba corriendo la primera vez que se usó. Si esta clase
    viviera como singleton de módulo y se reutilizara tal cual desde un loop
    distinto (típicamente porque el llamador abrió otro `asyncio.run`), fallaría
    con `RuntimeError: Event loop is closed`. Por eso `get_db` verifica el loop
    activo en cada llamada y **rebina** (recrea) el cliente si cambió, en vez de
    asumir que sigue siendo válido. Con un único loop de vida larga (ej. el de
    FastAPI/uvicorn) esto no cuesta nada extra: el cliente se crea una sola vez.
    """

    def __init__(self, mongo_uri: str | None = None, db_name: str | None = None) -> None:
        """`mongo_uri`/`db_name` son opcionales: por defecto usan `Settings` (la conexión real de la
        app). Pasarlos explícitamente permite construir una `MongoConnection` aislada — por ejemplo,
        para tests de integración contra el Mongo desechable de `docker-compose.yml` — sin tocar el
        singleton `mongo_connection` ni el `Settings` global compartido por el resto del proceso."""
        self._mongo_uri = mongo_uri or settings.mongo_uri
        self._db_name = db_name or settings.mongo_db_name
        self.client: Any = None
        self.connection_error: str | None = None
        self._indexes_ready = False
        self._indexes_lock = asyncio.Lock()
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._ensure_client_bound_to_current_loop()

    def _current_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    def _ensure_client_bound_to_current_loop(self) -> None:
        """Crea el cliente si no existe, o lo recrea si el loop activo cambió."""
        current_loop = self._current_loop()
        if self.client is not None and self._client_loop is current_loop:
            return

        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # pragma: no cover - cierre best-effort del cliente anterior
                pass

        try:
            self.client = AsyncIOMotorClient(self._mongo_uri, serverSelectionTimeoutMS=10000)
            self._client_loop = current_loop
            self._indexes_ready = False
            self._indexes_lock = asyncio.Lock()
            self.connection_error = None
        except Exception as exc:  # pragma: no cover - fallback de conexión
            self.connection_error = str(exc)
            self.client = None
            logger.error("mongo_connection_failed", error=str(exc))

    async def _ensure_task_indexes(self) -> None:
        """Crea índices de negocio necesarios para la colección de tareas."""
        db = self.client[self._db_name]
        await db.personal_tasks.create_index([("task_id", 1)], unique=True)

    async def _ensure_indexes_once(self) -> None:
        """Garantiza la creación de índices una sola vez por cliente, dentro del loop real que lo consume."""
        if self._indexes_ready or self.client is None:
            return
        async with self._indexes_lock:
            if self._indexes_ready:
                return
            await self._ensure_task_indexes()
            self._indexes_ready = True

    async def get_db(self, db_name: str | None = None):
        """Devuelve una base de datos si la conexión está disponible."""
        self._ensure_client_bound_to_current_loop()
        if self.connection_error or self.client is None:
            raise RuntimeError(
                "MongoDB no está disponible. Revisa la URI y la conectividad."
            )
        await self._ensure_indexes_once()
        return self.client[db_name or self._db_name]


mongo_connection = MongoConnection()


async def get_db(db_name: str = settings.mongo_db_name):
    """Función de conveniencia para obtener la base de datos desde otros módulos."""
    return await mongo_connection.get_db(db_name)
