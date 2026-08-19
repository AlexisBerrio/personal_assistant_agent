from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Configuración central de la aplicación.

    Única fuente de verdad para variables de entorno (lee `.env` una sola vez).
    Prohibido usar `os.getenv` fuera de este módulo. Los secretos se tipan como
    `SecretStr` para que nunca aparezcan en logs ni en un `repr()` accidental.

    `.env` se ubica con una ruta absoluta anclada a la raíz del repo, no
    relativa al directorio de trabajo del proceso: así el comportamiento es el
    mismo sin importar desde dónde se invoque (CLI ejecutado desde su propia
    carpeta, tests, FastAPI, etc.).
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    mongo_uri: str
    mongo_db_name: str = "personal_management"

    openai_api_key: SecretStr | None = None
    openai_model: str | None = None

    llm_provider: str = "openai"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str | None = None

    # El SDK reintenta solo con esto seteado; su timeout por defecto (600s) es demasiado largo.
    llm_request_timeout_seconds: float = 5.0
    llm_max_retries: int = 2

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _strip_openai_api_key(cls, value: str | None) -> str | None:
        """Recorta espacios/saltos de línea colados al copiar la key (GitHub secrets, `.env`,
        variables de entorno de CI). Sin esto, un `\\n` final rompe el header HTTP `Authorization`
        con un error de bajo nivel (`httpcore.LocalProtocolError: Illegal header value`) que el
        SDK de OpenAI reporta como el genérico `APIConnectionError: Connection error.` — un
        síntoma que no delata su causa real."""
        return value.strip() if isinstance(value, str) else value

    @property
    def python_command(self) -> str | None:
        venv_python = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
        return str(venv_python) if venv_python.exists() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
