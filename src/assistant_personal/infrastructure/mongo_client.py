import sys
from typing import Any

from pymongo import MongoClient

from src.assistant_personal.config import get_settings


settings = get_settings()


class MongoConnection:
    """Encapsula la conexión con MongoDB para no repetir lógica.

    Esta clase intenta abrir una conexión al cluster y comprobarla con un ping.
    Si falla, guarda el error para que el resto del sistema lo maneje bien.
    """

    def __init__(self) -> None:
        self.client: Any = None
        self.connection_error: str | None = None
        self._connect()

    def _connect(self) -> None:
        """Intenta conectar a MongoDB y validar la conexión."""
        try:
            self.client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
            self.client.admin.command("ping")
            self._ensure_task_indexes()
        except Exception as exc:  # pragma: no cover - fallback de conexión
            self.connection_error = str(exc)
            self.client = None
            print(f"[Mongo] No se pudo conectar: {exc}", file=sys.stderr)

    def _ensure_task_indexes(self) -> None:
        """Crea índices de negocio necesarios para la colección de tareas."""
        if self.client is None:
            return

        db = self.client[settings.mongo_db_name]
        db.personal_tasks.create_index([("task_id", 1)], unique=True)

    def get_db(self, db_name: str = settings.mongo_db_name):
        """Devuelve una base de datos si la conexión está disponible."""
        if self.connection_error or self.client is None:
            raise RuntimeError(
                "MongoDB no está disponible. Revisa la URI y la conectividad."
            )
        return self.client[db_name]


mongo_connection = MongoConnection()


def get_db(db_name: str = settings.mongo_db_name):
    """Función de conveniencia para obtener la base de datos desde otros módulos."""
    return mongo_connection.get_db(db_name)
