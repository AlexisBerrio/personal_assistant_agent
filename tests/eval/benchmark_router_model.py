"""Benchmark de modelo para `classify_intent`: gpt-4o-mini vs gpt-4.1-nano.

Corre el golden dataset (`golden_router.jsonl`) dos veces, una por modelo, midiendo accuracy,
latencia y costo real por caso. Es una herramienta de decisión puntual, no un gate — no falla el
build, no está wireada a CI, no tiene umbral de aprobado/reprobado. Requiere `OPENAI_API_KEY`
real.

Uso:
    uv run python tests/eval/benchmark_router_model.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.assistant_personal.domain.entities import IntentAction
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter
from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAIIntentClassifier

_EVAL_DIR = Path(__file__).resolve().parent

# USD por millón de tokens (input, output). Fuente: precios públicos de OpenAI, ago-2026.
_PRECIOS_POR_MILLON: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-nano": (0.10, 0.40),
}


@dataclass
class CaseResult:
    id: str
    categoria: str
    acierto: bool
    fuente: str
    latencia_ms: int | None
    tokens_entrada: int | None
    tokens_salida: int | None


@dataclass
class ModelBenchmark:
    modelo: str
    resultados: list[CaseResult] = field(default_factory=list)

    @property
    def casos_via_llm(self) -> list[CaseResult]:
        return [r for r in self.resultados if r.fuente == "llm"]

    @property
    def accuracy_global(self) -> float:
        return sum(r.acierto for r in self.resultados) / len(self.resultados)

    @property
    def latencia_media_ms(self) -> float | None:
        latencias = [r.latencia_ms for r in self.casos_via_llm if r.latencia_ms is not None]
        return sum(latencias) / len(latencias) if latencias else None

    @property
    def latencia_p95_ms(self) -> float | None:
        latencias = sorted(r.latencia_ms for r in self.casos_via_llm if r.latencia_ms is not None)
        if not latencias:
            return None
        indice = max(0, int(len(latencias) * 0.95) - 1)
        return latencias[indice]

    @property
    def costo_total_usd(self) -> float:
        precio_entrada, precio_salida = _PRECIOS_POR_MILLON.get(self.modelo, (0.0, 0.0))
        total = 0.0
        for r in self.casos_via_llm:
            total += (r.tokens_entrada or 0) / 1_000_000 * precio_entrada
            total += (r.tokens_salida or 0) / 1_000_000 * precio_salida
        return total

    @property
    def costo_medio_por_1000_casos_usd(self) -> float:
        if not self.casos_via_llm:
            return 0.0
        return self.costo_total_usd / len(self.casos_via_llm) * 1000


def cargar_casos(path: Path) -> list[dict[str, Any]]:
    casos = []
    with path.open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                casos.append(json.loads(linea))
    return casos


async def evaluar_caso(router: ProductionIntentRouter, caso: dict[str, Any]) -> CaseResult:
    started_at = time.monotonic()
    decision = await router.route(caso["mensaje"])
    elapsed_ms = int((time.monotonic() - started_at) * 1000)

    intencion_obtenida = decision.action.value if isinstance(decision.action, IntentAction) else str(decision.action)

    latencia_ms = None
    tokens_entrada = None
    tokens_salida = None
    if decision.source == "llm" and router.last_llm_metadata:
        latencia_ms = router.last_llm_metadata.get("latencia_ms_llm") or elapsed_ms
        tokens_entrada = router.last_llm_metadata.get("tokens_entrada")
        tokens_salida = router.last_llm_metadata.get("tokens_salida")

    return CaseResult(
        id=caso["id"],
        categoria=caso["categoria"],
        acierto=intencion_obtenida == caso["intencion_esperada"],
        fuente=decision.source,
        latencia_ms=latencia_ms,
        tokens_entrada=tokens_entrada,
        tokens_salida=tokens_salida,
    )


async def evaluar_modelo(modelo: str, casos: list[dict[str, Any]]) -> ModelBenchmark:
    router = ProductionIntentRouter(llm_client=OpenAIIntentClassifier(model=modelo))
    resultados = [await evaluar_caso(router, caso) for caso in casos]
    return ModelBenchmark(modelo=modelo, resultados=resultados)


def imprimir_comparacion(baseline: ModelBenchmark, candidato: ModelBenchmark) -> None:
    print(f"\n{'':25}{'gpt-4o-mini':>18}{'gpt-4.1-nano':>18}")
    print(f"{'accuracy_global':25}{baseline.accuracy_global:>17.2%} {candidato.accuracy_global:>17.2%}")

    base_lat = baseline.latencia_media_ms
    cand_lat = candidato.latencia_media_ms
    print(
        f"{'latencia_media_ms':25}"
        f"{f'{base_lat:.0f}' if base_lat is not None else 'n/a':>18}"
        f"{f'{cand_lat:.0f}' if cand_lat is not None else 'n/a':>18}"
    )

    base_p95 = baseline.latencia_p95_ms
    cand_p95 = candidato.latencia_p95_ms
    print(
        f"{'latencia_p95_ms':25}"
        f"{f'{base_p95:.0f}' if base_p95 is not None else 'n/a':>18}"
        f"{f'{cand_p95:.0f}' if cand_p95 is not None else 'n/a':>18}"
    )

    print(f"{'costo_usd_x1000_casos':25}{baseline.costo_medio_por_1000_casos_usd:>18.4f}{candidato.costo_medio_por_1000_casos_usd:>18.4f}")

    print("\nCasos donde un modelo acertó y el otro no:")
    por_id_candidato = {r.id: r for r in candidato.resultados}
    for r_base in baseline.resultados:
        r_cand = por_id_candidato[r_base.id]
        if r_base.acierto != r_cand.acierto:
            print(f"  [{r_base.id}] gpt-4o-mini={'OK' if r_base.acierto else 'FALLA'} gpt-4.1-nano={'OK' if r_cand.acierto else 'FALLA'}")


async def main() -> int:
    casos = cargar_casos(_EVAL_DIR / "golden_router.jsonl")

    print(f"Evaluando {len(casos)} casos con gpt-4o-mini...")
    baseline = await evaluar_modelo("gpt-4o-mini", casos)

    print(f"Evaluando {len(casos)} casos con gpt-4.1-nano...")
    candidato = await evaluar_modelo("gpt-4.1-nano", casos)

    imprimir_comparacion(baseline, candidato)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
