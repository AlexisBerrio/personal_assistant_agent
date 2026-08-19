from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.assistant_personal.application.agent_context import LongTermMemory, ShortTermMemory


def estimate_tokens(text: str) -> int:
    """Aproximación simple (~4 caracteres por token, heurística común para inglés/español) para
    presupuestar el contexto sin agregar una dependencia nueva (ej. `tiktoken`) solo para esto —
    no es un conteo exacto, es suficiente para un presupuesto medible y comparable entre turnos."""
    return (len(text) + 3) // 4 if text else 0


class SessionSummarizer(Protocol):
    """Puerto mínimo para el resumen incremental de sesión (§A.9, ítem 2.6). Implementado por
    `OpenAISessionSummarizer` (infrastructure/routers/openai_llm_client.py)."""

    async def summarize_session(self, previous_summary: str, turns: list[tuple[str, str]]) -> str:
        ...


class ContextBuilder:
    """Arma el contexto que se envía al LLM respetando un presupuesto de tokens medible, y
    dispara el resumen incremental de sesión cada `summarize_every_n_turns` turnos — en vez
    de los conteos fijos arbitrarios ("últimos 3 turnos") que usaba `AgentContext`
    antes de este ítem.

    Prioridad al recortar por presupuesto (de más a menos importante): hechos de largo plazo,
    resumen de sesión, turnos recientes, notas de sesión sueltas. Cada sección se agrega entera
    si entra en el presupuesto restante; si no entra completa pero el presupuesto no está
    agotado, se trunca; si el presupuesto ya se agotó, la sección se omite.
    """

    def __init__(
        self,
        summarizer: SessionSummarizer | None = None,
        token_budget: int = 800,
        summarize_every_n_turns: int = 10,
    ) -> None:
        self._summarizer = summarizer
        self.token_budget = token_budget
        self.summarize_every_n_turns = summarize_every_n_turns

    # Márgenes de seguridad en caracteres para lo que la estimación por sección no puede prever
    # exactamente: el prefijo "Contexto reciente: ", los separadores " | " entre secciones, y el
    # "…" al truncar. Sin esto, el texto final puede quedar un poco por encima del presupuesto.
    _PREFIX = "Contexto reciente: "
    _TRUNCATION_SAFETY_CHARS = 8

    def _fit_section(self, label: str, text: str, remaining_tokens: int) -> tuple[str | None, int]:
        if not text or remaining_tokens <= 0:
            return None, remaining_tokens

        section = f"{label}: {text}"
        tokens = estimate_tokens(section)
        if tokens <= remaining_tokens:
            return section, remaining_tokens - tokens

        max_chars = remaining_tokens * 4 - len(label) - 2 - self._TRUNCATION_SAFETY_CHARS
        if max_chars <= 0:
            return None, remaining_tokens
        truncated = text[:max_chars].rstrip()
        return f"{label}: {truncated}…", 0

    async def build_context_async(
        self, short_term_memory: ShortTermMemory, long_term_memory: LongTermMemory, session_id: str = "default"
    ) -> tuple[str, int]:
        raw_session = await short_term_memory.get_raw_session_async(session_id, max_turns=self.summarize_every_n_turns)
        facts = list((await long_term_memory.get_facts_async()).items())
        summary = raw_session.get("summary", "")
        turns = [(t["user_message"], t["assistant_response"]) for t in raw_session.get("turns", [])]
        items = [(i["key"], i["value"]) for i in raw_session.get("items", [])]

        sections = [
            ("Hechos del usuario", "; ".join(f"{key}={value}" for key, value in facts)),
            ("Resumen de la conversación", summary),
            ("Turnos recientes", "; ".join(f"user:{u} | assistant:{a}" for u, a in turns)),
            ("Notas de sesión", "; ".join(f"{key}={value}" for key, value in items)),
        ]

        # Reserva del presupuesto para el prefijo antes de repartir entre secciones — si no, el
        # texto final puede superar `token_budget` aunque cada sección haya respetado su parte.
        remaining = max(0, self.token_budget - estimate_tokens(self._PREFIX))
        parts: list[str] = []
        for label, text in sections:
            section, remaining = self._fit_section(label, text, remaining)
            if section:
                parts.append(section)

        context_text = f"{self._PREFIX}{' | '.join(parts)}" if parts else ""
        return context_text, estimate_tokens(context_text)

    async def maybe_summarize_async(self, short_term_memory: ShortTermMemory, session_id: str = "default") -> None:
        if self._summarizer is None:
            return

        max_turns = self.summarize_every_n_turns + 5
        raw_session = await short_term_memory.get_raw_session_async(session_id, max_turns=max_turns)
        turns = [(t["user_message"], t["assistant_response"]) for t in raw_session.get("turns", [])]
        if len(turns) < self.summarize_every_n_turns:
            return

        previous_summary = raw_session.get("summary", "")
        try:
            new_summary = await self._summarizer.summarize_session(previous_summary, turns)
        except Exception:
            # El resumen es una mejora de contexto, no una operación crítica del turno — si el
            # LLM falla, se reintenta en el próximo turno en vez de romper la respuesta actual.
            return

        if new_summary:
            await short_term_memory.compact_async(session_id, new_summary, keep_last_turns=1)
