import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    mongo_db_name: str = "sample_mflix"
    openai_model: str = "gpt-4o-mini"
    python_command: Optional[str] = None


def load_dotenv(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_dotenv()


def get_settings() -> Settings:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(repo_root, ".venv", "Scripts", "python.exe")
    python_command = venv_python if os.path.exists(venv_python) else None
    return Settings(
        mongo_uri=os.getenv("MONGO_URI"),
        mongo_db_name=os.getenv("MONGO_DB_NAME"),
        openai_model=os.getenv("OPENAI_MODEL"),
        python_command=python_command,
    )
