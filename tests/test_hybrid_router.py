import unittest

from src.assistant_personal.domain.entities import ConversationRoute, IntentAction, IntentClassification, UserProfileExtraction
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter


class FakeIntentClassifier:
    def __init__(self, response: IntentClassification | None = None, raise_error: bool = False):
        self.response = response
        self.raise_error = raise_error
        self.calls: list[tuple[str, str | None]] = []

    def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        self.calls.append((text, context))
        if self.raise_error:
            raise RuntimeError("classifier down")
        if self.response is None:
            return IntentClassification(route=ConversationRoute.CLARIFY, confidence=0.0, source="llm")
        return self.response


class FakeKnowledgeResponder:
    def __init__(self, answer: str = "respuesta"):
        self.answer = answer
        self.calls: list[tuple[str, str | None]] = []

    def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        self.calls.append((query, context))
        return self.answer


class FakeProfileExtractor:
    def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        return UserProfileExtraction()


class HybridRouterTests(unittest.TestCase):
    def test_fast_rule_resolves_create_task_with_explicit_syntax(self):
        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("nueva tarea: comprar leche")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.payload["title"], "Comprar leche")
        self.assertEqual(result.source, "rule")
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_help_command_is_handled_by_fast_rule(self):
        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("/help")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")

    def test_small_talk_exact_message_does_not_use_orchestrator(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.CREATE_TASK, confidence=0.99)
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("Hola")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    def test_small_talk_with_punctuation_still_matches_fast_rule(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.CREATE_TASK, confidence=0.99)
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("¡Hola!")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    def test_mixed_greeting_and_task_request_goes_to_classifier(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.CREATE_TASK,
                payload={"title": "Comprar leche mañana"},
                confidence=0.95,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("Hola, crea una tarea para mañana")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(classifier.calls), 1)

    def test_mixed_greeting_with_comma_is_not_treated_as_small_talk(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.CREATE_TASK,
                payload={"title": "Crear esta tarea"},
                confidence=0.95,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("hola, crea esta tarea")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(classifier.calls), 1)

    def test_general_knowledge_route_uses_knowledge_responder(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.GENERAL_KNOWLEDGE, confidence=0.96, source="llm")
        )
        responder = FakeKnowledgeResponder(answer="La procrastinación es posponer tareas.")
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=responder,
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("¿Qué significa procrastinar?")

        self.assertEqual(result.action, IntentAction.ASK_KNOWLEDGE_BASE)
        self.assertEqual(result.payload.get("answer"), "La procrastinación es posponer tareas.")
        self.assertEqual(len(responder.calls), 1)

    def test_low_confidence_returns_clarify_without_forcing_intent(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.CREATE_TASK,
                payload={"title": "Algo"},
                confidence=0.2,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("ayúdame con algo ambiguo")

        self.assertEqual(result.action, IntentAction.CLARIFY)
        self.assertEqual(result.source, "llm")

    def test_classifier_error_uses_safe_fallback_to_clarify(self):
        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(raise_error=True),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("Añade a mis tareas comprar leche mañana")

        self.assertEqual(result.action, IntentAction.CLARIFY)
        self.assertEqual(result.source, "fallback")

    def test_ambiguous_delete_without_reference_results_in_clarify(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.DELETE_TASK,
                payload={},
                confidence=0.94,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("Borra esa")

        self.assertEqual(result.action, IntentAction.CLARIFY)

    def test_natural_language_crud_is_delegated_to_orchestrator_route(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.CREATE_TASK,
                payload={"title": "Comprar leche mañana"},
                confidence=0.93,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
        )

        result = router.route("Añade a mis tareas comprar leche mañana")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")


if __name__ == "__main__":
    unittest.main()
