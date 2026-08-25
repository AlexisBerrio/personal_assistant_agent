from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PROMPTS_DIR = Path(__file__).resolve().parent
_FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class LoadedPrompt:
    """Prompt versionado listo para usar, con su metadata y un identificador para
    correlacionar métricas con la versión exacta que generó cada resultado."""

    id: str
    version: str
    text: str
    description: str = ""
    model_recommended: str | None = None
    temperature: float | None = None
    inputs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def identifier(self) -> str:
        return f"{self.id}:v{self.version}"


def _parse_prompt_file(path: Path) -> LoadedPrompt:
    match = _FRONTMATTER_PATTERN.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"'{path}' no tiene frontmatter YAML válido (---...---)")

    metadata: dict[str, Any] = yaml.safe_load(match.group("frontmatter")) or {}
    prompt_id = metadata.get("id")
    version = metadata.get("version")
    if not prompt_id or not version:
        raise ValueError(f"'{path}': el frontmatter debe declarar 'id' y 'version'")
    if not _VERSION_PATTERN.match(version):
        raise ValueError(f"'{path}': versión '{version}' inválida, se espera semver (ej. '1.0.0')")

    return LoadedPrompt(
        id=prompt_id,
        version=version,
        text=match.group("body").strip(),
        description=metadata.get("description", ""),
        model_recommended=metadata.get("model_recommended"),
        temperature=metadata.get("temperature"),
        inputs=tuple(metadata.get("inputs", [])),
    )


@lru_cache
def load_prompt(name: str) -> LoadedPrompt:
    """Carga el prompt `name` desde `{id}.prompt.md`.

    `name` puede llevar namespace (ej. `"router/classify_intent"`); sin namespace se busca
    directamente bajo `prompts/`. Un solo archivo por prompt — la versión no vive en el nombre
    del archivo (sería redundante) sino únicamente en el frontmatter YAML (`id`, `version`
    semver, `description`, `model_recommended`, `temperature`, `inputs`); el historial de
    versiones anteriores lo lleva git, no el filesystem. `model_recommended`/`temperature` son
    metadata informativa hoy — no sobrescriben la configuración real de `Settings` ni la llamada
    al modelo; documentan la intención de quien escribió el prompt.
    """
    directory = _PROMPTS_DIR
    prompt_id = name
    if "/" in name:
        namespace, prompt_id = name.rsplit("/", 1)
        directory = _PROMPTS_DIR / namespace

    path = directory / f"{prompt_id}.prompt.md"
    if not path.exists():
        raise FileNotFoundError(f"No existe ningún prompt para '{name}' en {path}")

    return _parse_prompt_file(path)
