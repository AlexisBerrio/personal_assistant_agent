"""Calibración del LLM-as-judge contra ~30 juicios humanos (ítem 4.6).

No evalúa el router ni el agente: evalúa si el juez (`OpenAIResponseJudge`) está de acuerdo con
un humano sobre la calidad de una respuesta ya escrita, tomada de `golden_judge.jsonl`. Requiere
`OPENAI_API_KEY` real: no hay modo grabado/replay (misma deuda conocida que `run_eval.py`).

Uso:
    uv run python tests/eval/run_eval_judge.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAIResponseJudge

_EVAL_DIR = Path(__file__).resolve().parent

# Modelo distinto del que típicamente genera las respuestas evaluadas (gpt-4o-mini) — un juez
# que se evalúa con el mismo modelo que produjo la respuesta no es fiable (ver rúbrica del prompt).
_JUEZ_MODEL = "gpt-5-nano"

# Umbral de acuerdo juez-humano antes de confiar en el juez para cualquier uso futuro.
_ACUERDO_MINIMO_PUNTUACION = 0.70  # dentro de +-1 punto sobre 5
_ACUERDO_MINIMO_BOOLEANOS = 0.80  # correcta/util/en_espanol coinciden exacto


@dataclass
class CaseResult:
    id: str
    mensaje: str
    categoria: str
    puntuacion_humana: int
    puntuacion_juez: int
    puntuacion_de_acuerdo: bool
    booleanos_de_acuerdo: bool
    justificacion_juez: str


@dataclass
class JudgeCalibrationReport:
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


async def evaluar_caso(juez: OpenAIResponseJudge, caso: dict[str, Any]) -> CaseResult:
    juicio_humano = caso["juicio_humano"]
    juicio_juez = await juez.judge_response(caso["mensaje"], caso["respuesta"], context=caso.get("contexto") or None)

    booleanos_de_acuerdo = (
        juicio_juez.correcta == juicio_humano["correcta"]
        and juicio_juez.util == juicio_humano["util"]
        and juicio_juez.en_espanol == juicio_humano["en_espanol"]
    )

    return CaseResult(
        id=caso["id"],
        mensaje=caso["mensaje"],
        categoria=caso["categoria"],
        puntuacion_humana=juicio_humano["puntuacion"],
        puntuacion_juez=juicio_juez.puntuacion,
        puntuacion_de_acuerdo=abs(juicio_juez.puntuacion - juicio_humano["puntuacion"]) <= 1,
        booleanos_de_acuerdo=booleanos_de_acuerdo,
        justificacion_juez=juicio_juez.justificacion,
    )


async def ejecutar_calibracion(
    casos: list[dict[str, Any]], juez: OpenAIResponseJudge | None = None
) -> JudgeCalibrationReport:
    juez = juez or OpenAIResponseJudge(model=_JUEZ_MODEL)
    resultados = [await evaluar_caso(juez, caso) for caso in casos]

    reporte = JudgeCalibrationReport(resultados=resultados)

    acuerdo_puntuacion = sum(r.puntuacion_de_acuerdo for r in resultados) / len(resultados)
    if acuerdo_puntuacion < _ACUERDO_MINIMO_PUNTUACION:
        reporte.fallas_umbral.append(
            f"acuerdo_puntuacion {acuerdo_puntuacion:.2%} < mínimo {_ACUERDO_MINIMO_PUNTUACION:.2%}"
        )

    acuerdo_booleanos = sum(r.booleanos_de_acuerdo for r in resultados) / len(resultados)
    if acuerdo_booleanos < _ACUERDO_MINIMO_BOOLEANOS:
        reporte.fallas_umbral.append(
            f"acuerdo_booleanos {acuerdo_booleanos:.2%} < mínimo {_ACUERDO_MINIMO_BOOLEANOS:.2%}"
        )

    return reporte


def imprimir_reporte(reporte: JudgeCalibrationReport) -> None:
    desacuerdos = [r for r in reporte.resultados if not (r.puntuacion_de_acuerdo and r.booleanos_de_acuerdo)]
    print(f"\n{len(reporte.resultados)} casos evaluados, {len(desacuerdos)} desacuerdos juez-humano.\n")
    for r in desacuerdos:
        print(
            f"  [{r.id}] '{r.mensaje}' -> humano={r.puntuacion_humana} juez={r.puntuacion_juez} "
            f"({r.justificacion_juez})"
        )

    if reporte.fallas_umbral:
        print("\nEl juez NO está calibrado:")
        for falla in reporte.fallas_umbral:
            print(f"  - {falla}")
    else:
        print("\nEl juez está calibrado (umbrales de acuerdo juez-humano cumplidos).")


async def main() -> int:
    casos = cargar_casos(_EVAL_DIR / "golden_judge.jsonl")
    reporte = await ejecutar_calibracion(casos)
    imprimir_reporte(reporte)
    return 0 if reporte.aprobado else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
