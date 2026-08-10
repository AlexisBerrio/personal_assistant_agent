import unittest

from src.assistant_personal.domain.entities import IntentAction, IntentDecision
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter


class HybridRouterTests(unittest.TestCase):
    def test_fast_rule_resolves_create_task(self):
        router = ProductionIntentRouter()

        result = router.route("nueva tarea: comprar leche")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.payload["title"], "Comprar leche")
        self.assertEqual(result.source, "rule")
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_fallback_when_llm_confidence_is_low(self):
        class LowConfidenceClient:
            def classify_intent(self, text: str) -> IntentDecision:
                return IntentDecision(
                    action=IntentAction.CREATE_TASK,
                    payload={"title": "Algo"},
                    confidence=0.2,
                    source="llm",
                    reasoning="No suficiente confianza",
                )

        router = ProductionIntentRouter(llm_client=LowConfidenceClient())

        result = router.route("ayúdame con algo ambiguo")

        self.assertEqual(result.action, IntentAction.CLARIFY)
        self.assertEqual(result.source, "fallback")


if __name__ == "__main__":
    unittest.main()
