import unittest

from src.assistant_personal.application.intent_router import IntentRouter


class IntentRouterTests(unittest.TestCase):
    def test_routes_listing_intention(self):
        router = IntentRouter()

        result = router.route("listar mis tareas")

        self.assertEqual(result.action, "list_tasks")

    def test_routes_creation_intention(self):
        router = IntentRouter()

        result = router.route("crear una tarea para estudiar")

        self.assertEqual(result.action, "create_task")
        self.assertIn("estudiar", result.payload["title"].lower())

    def test_routes_completion_intention(self):
        router = IntentRouter()

        result = router.route("completar la tarea de comprar pan")

        self.assertEqual(result.action, "complete_task")


if __name__ == "__main__":
    unittest.main()
