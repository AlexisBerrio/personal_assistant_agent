from __future__ import annotations

_PUNCTUATION_CHARS = [",", ".", "!", "?", ";", ":", "¿", "¡"]


def normalize_for_matching(text: str) -> str:
    """Minúsculas, sin puntuación común, espacios colapsados — para comparar contra un
    conjunto cerrado de palabras clave (saludos, confirmaciones sí/no, comandos exactos).
    Nunca para comparación semántica."""
    normalized = text.lower().strip()
    for char in _PUNCTUATION_CHARS:
        normalized = normalized.replace(char, " ")
    return " ".join(normalized.split())
