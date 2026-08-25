"""Wrapper de pytest para tests/eval/run_eval_judge.py.

Marcado `eval`: hace llamadas reales a OpenAI (costo + latencia). A diferencia de
`test_eval_router.py`, este NO está wireado en ningún workflow de CI — es deliberadamente
manual: calibra al LLM-as-judge contra juicios humanos, no protege ningún camino de producción
(el juez no se usa fuera de evaluación offline, ver ítem 4.6). Correr solo cuando se toque el
prompt del juez o el dataset de calibración.
"""

from __future__ import annotations

import os
import unittest

import pytest

from tests.eval.run_eval_judge import _EVAL_DIR, cargar_casos, ejecutar_calibracion, imprimir_reporte


@pytest.mark.eval
@unittest.skipUnless(os.getenv("OPENAI_API_KEY"), "requiere OPENAI_API_KEY real para llamar al juez")
class JudgeCalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_el_juez_concuerda_con_los_juicios_humanos(self) -> None:
        casos = cargar_casos(_EVAL_DIR / "golden_judge.jsonl")

        self.assertGreaterEqual(len(casos), 30, "el dataset de calibración debe tener al menos 30 casos")

        reporte = await ejecutar_calibracion(casos)
        imprimir_reporte(reporte)

        self.assertTrue(reporte.aprobado, f"el juez no está calibrado: {reporte.fallas_umbral}")


if __name__ == "__main__":
    unittest.main()
