"""Wrapper de pytest para tests/eval/run_eval.py (§A.10, ítem 2.3).

Marcado `eval`: hace llamadas reales a OpenAI (costo + latencia). El comando principal de
`.github/workflows/ci.yml` excluye la marca `eval` con `-m "not eval"`; el ítem 2.4 añadirá un
job dedicado que corra justo `pytest tests/ -m eval` con una key real. `skipUnless` es un
segundo cinturón para correr el archivo suelto en local sin filtrar por marca.
"""

from __future__ import annotations

import os
import unittest

import pytest

from tests.eval.run_eval import _EVAL_DIR, cargar_casos, cargar_umbrales, ejecutar_evaluacion, imprimir_reporte


@pytest.mark.eval
@unittest.skipUnless(os.getenv("OPENAI_API_KEY"), "requiere OPENAI_API_KEY real para llamar al router")
class GoldenRouterEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_cumple_los_umbrales_del_golden_dataset(self) -> None:
        casos = cargar_casos(_EVAL_DIR / "golden_router.jsonl")
        umbrales = cargar_umbrales(_EVAL_DIR / "umbrales.yaml")

        self.assertGreaterEqual(len(casos), 100, "el golden dataset debe tener al menos 100 casos")

        reporte = await ejecutar_evaluacion(casos, umbrales)
        imprimir_reporte(reporte)

        self.assertTrue(reporte.aprobado, f"umbrales incumplidos: {reporte.fallas_umbral}")


if __name__ == "__main__":
    unittest.main()
