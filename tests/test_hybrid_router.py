import unittest

from src.assistant_personal.domain.entities import (
    ConversationRoute,
    IntentAction,
    IntentClassification,
    UserProfileExtraction,
)
from src.assistant_personal.infrastructure.routers.hybrid_router import ProductionIntentRouter


class FakeIntentClassifier:
    def __init__(
        self,
        response: IntentClassification | None = None,
        raise_error: bool = False,
        error: Exception | None = None,
    ):
        self.response = response
        self.raise_error = raise_error
        self.error = error or RuntimeError("classifier down")
        self.calls: list[tuple[str, str | None]] = []

    async def classify_intent(self, text: str, context: str | None = None) -> IntentClassification:
        self.calls.append((text, context))
        if self.raise_error:
            raise self.error
        if self.response is None:
            return IntentClassification(route=ConversationRoute.CLARIFY, confidence=0.0, source="llm")
        return self.response


class FakeKnowledgeResponder:
    def __init__(self, answer: str = "respuesta"):
        self.answer = answer
        self.calls: list[tuple[str, str | None]] = []

    async def answer_general_knowledge(self, query: str, context: str | None = None) -> str:
        self.calls.append((query, context))
        return self.answer


class FakeProfileExtractor:
    async def extract_profile_facts(self, text: str, context: str | None = None) -> UserProfileExtraction:
        return UserProfileExtraction()


class FakeSmallTalkResponder:
    def __init__(self, reply: str = "respuesta de small talk"):
        self.reply = reply
        self.calls: list[tuple[str, str | None]] = []

    async def answer_small_talk(self, text: str, context: str | None = None) -> str:
        self.calls.append((text, context))
        return self.reply


class HybridRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_rule_resolves_create_task_with_explicit_syntax(self):
        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("nueva tarea: comprar leche")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.payload["title"], "Comprar leche")
        self.assertEqual(result.source, "rule")
        self.assertGreaterEqual(result.confidence, 0.9)

    async def test_create_task_without_delimiter_is_delegated_to_classifier(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.CREATE_TASK,
                payload={"title": "Comprar leche"},
                confidence=0.94,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("crear tarea comprar leche")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(classifier.calls), 1)

    async def test_help_command_is_handled_by_fast_rule(self):
        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("/help")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")

    async def test_small_talk_exact_message_does_not_use_orchestrator(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.CREATE_TASK, confidence=0.99)
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("Hola")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    async def test_small_talk_with_punctuation_still_matches_fast_rule(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.CREATE_TASK, confidence=0.99)
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("¡Hola!")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    async def test_farewell_is_handled_by_fast_rule(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.LIST_TASKS, confidence=0.99)
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("adios")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")
        self.assertEqual(result.payload.get("reply"), "respuesta de small talk")
        self.assertEqual(len(classifier.calls), 0)

    async def test_small_talk_reply_is_generated_not_static(self):
        """Regresión: la respuesta de small_talk no puede ser un texto fijo repetido en cada
        saludo — debe generarse (LLM) a partir de lo que el usuario dijo, para poder reaccionar
        a contenido real (su nombre, una pregunta directa) en vez de romper la conversación."""
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.LIST_TASKS, confidence=0.99)
        )
        responder = FakeSmallTalkResponder(reply="¡Hola de nuevo, Alexis!")
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=responder,
        )

        result = await router.route("hola")

        self.assertEqual(result.payload.get("reply"), "¡Hola de nuevo, Alexis!")
        self.assertEqual(responder.calls, [("hola", None)])

    async def test_small_talk_reply_falls_back_safely_when_responder_fails(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.LIST_TASKS, confidence=0.99)
        )

        class FailingSmallTalkResponder:
            async def answer_small_talk(self, text: str, context: str | None = None) -> str:
                raise RuntimeError("small talk LLM down")

        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FailingSmallTalkResponder(),
        )

        result = await router.route("hola")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertTrue(result.payload.get("reply"))

    async def test_farewell_with_punctuation_is_handled_by_fast_rule(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.ORCHESTRATOR, intent=IntentAction.LIST_TASKS, confidence=0.99)
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("¡Adiós!")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    async def test_mixed_greeting_and_task_request_goes_to_classifier(self):
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
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("Hola, crea una tarea para mañana")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(classifier.calls), 1)

    async def test_mixed_greeting_with_comma_is_not_treated_as_small_talk(self):
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
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("hola, crea esta tarea")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(classifier.calls), 1)

    async def test_explicit_list_tasks_with_greeting_uses_fast_rule(self):
        classifier = FakeIntentClassifier(raise_error=True)
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("hola, lista mis tareas")

        self.assertEqual(result.action, IntentAction.LIST_TASKS)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    async def test_explicit_list_tasks_without_greeting_uses_fast_rule(self):
        classifier = FakeIntentClassifier(raise_error=True)
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("listar mis tareas pendientes")

        self.assertEqual(result.action, IntentAction.LIST_TASKS)
        self.assertEqual(result.source, "rule")
        self.assertEqual(len(classifier.calls), 0)

    async def test_natural_language_list_request_is_delegated_to_classifier(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.LIST_TASKS,
                payload={"scope": "hoy"},
                confidence=0.94,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("muéstrame las tareas de hoy")

        self.assertEqual(result.action, IntentAction.LIST_TASKS)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(classifier.calls), 1)

    async def test_general_knowledge_route_uses_knowledge_responder(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.GENERAL_KNOWLEDGE, confidence=0.96, source="llm")
        )
        responder = FakeKnowledgeResponder(answer="La procrastinación es posponer tareas.")
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=responder,
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("¿Qué significa procrastinar?")

        self.assertEqual(result.action, IntentAction.ASK_KNOWLEDGE_BASE)
        self.assertEqual(result.payload.get("answer"), "La procrastinación es posponer tareas.")
        self.assertEqual(len(responder.calls), 1)

    async def test_small_talk_route_from_classifier_does_not_fall_to_clarify(self):
        """Regresión: 'hola, me llamo Alexis' no coincide con las reglas rápidas de saludo puro
        (no es un saludo exacto) ni encaja en general_knowledge/orchestrator, así que antes de
        agregar ConversationRoute.SMALL_TALK caía en clarify por descarte. Ver
        docs/anexo_arquitectura_objetivo.md, classify_intent v1.3.0."""
        classifier = FakeIntentClassifier(
            response=IntentClassification(route=ConversationRoute.SMALL_TALK, confidence=0.95, source="llm")
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("hola, me llamo Alexis")

        self.assertEqual(result.action, IntentAction.SMALL_TALK)
        self.assertEqual(result.source, "llm")
        self.assertIn("reply", result.payload)

    async def test_low_confidence_returns_clarify_without_forcing_intent(self):
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
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("ayúdame con algo ambiguo")

        self.assertEqual(result.action, IntentAction.CLARIFY)
        self.assertEqual(result.source, "llm")

    async def test_classifier_error_uses_safe_fallback_to_clarify(self):
        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(raise_error=True),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("Añade a mis tareas comprar leche mañana")

        self.assertEqual(result.action, IntentAction.CLARIFY)
        self.assertEqual(result.source, "fallback")

    async def test_validation_error_uses_the_same_safe_fallback_as_any_other_failure(self):
        """Un `ValidationError` real de Pydantic (salida del LLM que no cumple el esquema) debe
        caer en la misma política de fallback que cualquier otro fallo del clasificador — una
        sola política, no dos."""
        from pydantic import ValidationError

        try:
            IntentClassification.model_validate({"route": "no_existe"})
        except ValidationError as exc:
            validation_error = exc

        router = ProductionIntentRouter(
            llm_client=FakeIntentClassifier(raise_error=True, error=validation_error),
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("mensaje cualquiera")

        self.assertEqual(result.action, IntentAction.CLARIFY)
        self.assertEqual(result.source, "fallback")

    async def test_ambiguous_delete_without_reference_results_in_clarify(self):
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
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("Borra esa")

        self.assertEqual(result.action, IntentAction.CLARIFY)

    async def test_create_task_without_title_results_in_clarify(self):
        classifier = FakeIntentClassifier(
            response=IntentClassification(
                route=ConversationRoute.ORCHESTRATOR,
                intent=IntentAction.CREATE_TASK,
                payload={},
                confidence=0.93,
                source="llm",
            )
        )
        router = ProductionIntentRouter(
            llm_client=classifier,
            knowledge_responder=FakeKnowledgeResponder(),
            profile_extractor=FakeProfileExtractor(),
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("crea una tarea para investigar mas sobre eso")

        self.assertEqual(result.action, IntentAction.CLARIFY)

    async def test_natural_language_crud_is_delegated_to_orchestrator_route(self):
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
            small_talk_responder=FakeSmallTalkResponder(),
        )

        result = await router.route("Añade a mis tareas comprar leche mañana")

        self.assertEqual(result.action, IntentAction.CREATE_TASK)
        self.assertEqual(result.source, "llm")


if __name__ == "__main__":
    unittest.main()
