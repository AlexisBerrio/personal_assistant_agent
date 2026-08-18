"""Evaluación del router híbrido contra el golden dataset (§A.10, ítem 2.3).

Ejecuta `ProductionIntentRouter.route()` con el clasificador OpenAI real sobre cada caso de
`golden_router.jsonl` y compara las métricas resultantes contra `umbrales.yaml`. Requiere
`OPENAI_API_KEY` real: no hay modo grabado/replay todavía (deuda conocida, ver el reporte).

Uso:
    uv run python tests/eval/run_eval.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.assistant_personal.domain.entities import IntentAction
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter

_EVAL_DIR = Path(__file__).resolve().parent


@dataclass
class CaseResult:
    id: str
    mensaje: str
    categoria: str
    intencion_esperada: str
    intencion_obtenida: str
    acierto: bool
    fuente: str
    tokens_totales: int | None
    entidad_esperada_presente: bool | None


@dataclass
class EvalReport:
    resultados: list[CaseResult] = field(default_factory=list)
    fallas_umbral: list[str] = field(default_factory=list)

    @property
    def aprobado(self) -> bool:
        return not self.fallas_umbral


def cargar_casos(path: Path) -> list[dict[str, Any]]:
    casos = []
    with path.open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                casos.append(json.loads(linea))
    return casos


def cargar_umbrales(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _entidad_presente(payload: dict[str, Any], claves_esperadas: list[str]) -> bool:
    return any(payload.get(clave) for clave in claves_esperadas)


async def evaluar_caso(router: ProductionIntentRouter, caso: dict[str, Any]) -> CaseResult:
    decision = await router.route(caso["mensaje"])
    intencion_obtenida = decision.action.value if isinstance(decision.action, IntentAction) else str(decision.action)

    entidades_esperadas = caso.get("entidades_esperadas") or []
    entidad_presente = _entidad_presente(decision.payload, entidades_esperadas) if entidades_esperadas else None

    tokens_totales = None
    if decision.source == "llm" and router.last_llm_metadata:
        entrada = router.last_llm_metadata.get("tokens_entrada") or 0
        salida = router.last_llm_metadata.get("tokens_salida") or 0
        tokens_totales = entrada + salida

    return CaseResult(
        id=caso["id"],
        mensaje=caso["mensaje"],
        categoria=caso["categoria"],
        intencion_esperada=caso["intencion_esperada"],
        intencion_obtenida=intencion_obtenida,
        acierto=intencion_obtenida == caso["intencion_esperada"],
        fuente=decision.source,
        tokens_totales=tokens_totales,
        entidad_esperada_presente=entidad_presente,
    )


async def ejecutar_evaluacion(
    casos: list[dict[str, Any]], umbrales: dict[str, Any], router: ProductionIntentRouter | None = None
) -> EvalReport:
    router = router or ProductionIntentRouter()
    resultados = [await evaluar_caso(router, caso) for caso in casos]

    reporte = EvalReport(resultados=resultados)

    accuracy_global = sum(r.acierto for r in resultados) / len(resultados)
    if accuracy_global < umbrales["accuracy_global_minima"]:
        reporte.fallas_umbral.append(
            f"accuracy_global {accuracy_global:.2%} < mínimo {umbrales['accuracy_global_minima']:.2%}"
        )

    por_intencion: dict[str, list[CaseResult]] = defaultdict(list)
    for r in resultados:
        por_intencion[r.intencion_esperada].append(r)
    for intencion, minimo in umbrales["accuracy_por_intencion_minima"].items():
        casos_intencion = por_intencion.get(intencion, [])
        if not casos_intencion:
            continue
        accuracy = sum(r.acierto for r in casos_intencion) / len(casos_intencion)
        if accuracy < minimo:
            reporte.fallas_umbral.append(
                f"accuracy['{intencion}'] {accuracy:.2%} < mínimo {minimo:.2%} ({len(casos_intencion)} casos)"
            )

    tasa_clarify = sum(r.intencion_obtenida == "clarify" for r in resultados) / len(resultados)
    if not (umbrales["tasa_clarify_minima"] <= tasa_clarify <= umbrales["tasa_clarify_maxima"]):
        reporte.fallas_umbral.append(
            f"tasa_clarify {tasa_clarify:.2%} fuera de banda "
            f"[{umbrales['tasa_clarify_minima']:.2%}, {umbrales['tasa_clarify_maxima']:.2%}]"
        )

    con_entidades = [r for r in resultados if r.entidad_esperada_presente is not None]
    if con_entidades:
        precision_entidades = sum(r.entidad_esperada_presente for r in con_entidades) / len(con_entidades)
        if precision_entidades < umbrales["precision_entidades_minima"]:
            reporte.fallas_umbral.append(
                f"precision_entidades {precision_entidades:.2%} < mínimo {umbrales['precision_entidades_minima']:.2%}"
            )

    con_tokens = [r.tokens_totales for r in resultados if r.tokens_totales is not None]
    if con_tokens:
        coste_medio = sum(con_tokens) / len(con_tokens)
        if coste_medio > umbrales["coste_medio_tokens_maximo"]:
            reporte.fallas_umbral.append(
                f"coste_medio_tokens {coste_medio:.1f} > máximo {umbrales['coste_medio_tokens_maximo']}"
            )

    pct_reglas = sum(r.fuente == "rule" for r in resultados) / len(resultados)
    if pct_reglas < umbrales["pct_resueltos_por_reglas_minimo"]:
        reporte.fallas_umbral.append(
            f"pct_resueltos_por_reglas {pct_reglas:.2%} < mínimo {umbrales['pct_resueltos_por_reglas_minimo']:.2%}"
        )

    return reporte


def imprimir_reporte(reporte: EvalReport) -> None:
    fallos = [r for r in reporte.resultados if not r.acierto]
    print(f"\n{len(reporte.resultados)} casos evaluados, {len(fallos)} fallos de clasificación.\n")
    for r in fallos:
        print(f"  [{r.id}] '{r.mensaje}' -> esperado={r.intencion_esperada} obtenido={r.intencion_obtenida}")

    if reporte.fallas_umbral:
        print("\nUmbrales incumplidos:")
        for falla in reporte.fallas_umbral:
            print(f"  - {falla}")
    else:
        print("\nTodos los umbrales de tests/eval/umbrales.yaml se cumplen.")


async def main() -> int:
    casos = cargar_casos(_EVAL_DIR / "golden_router.jsonl")
    umbrales = cargar_umbrales(_EVAL_DIR / "umbrales.yaml")
    reporte = await ejecutar_evaluacion(casos, umbrales)
    imprimir_reporte(reporte)
    return 0 if reporte.aprobado else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
