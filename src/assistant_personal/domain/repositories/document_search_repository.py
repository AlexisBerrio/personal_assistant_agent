from __future__ import annotations

from typing import Any, Protocol


class DocumentSearchRepository(Protocol):
    """Port de búsqueda de texto libre sobre documentos del dominio.

    Precondición de diseño de bajo costo para la decisión de RAG: el dominio actual
    (tareas) es estructurado y se consulta mejor con filtros e índices de Mongo que con
    similitud vectorial. Este port existe para que, si algún día aparece un corpus de texto
    libre que sí justifique RAG, baste con un adaptador nuevo —
    sin tocar `application/`. El primer adaptador usa `$text` de Mongo, no un motor vectorial.
    """

    async def buscar(
        self, consulta: str, filtros: dict[str, Any] | None = None, limite: int = 10
    ) -> list[dict[str, Any]]:
        ...
