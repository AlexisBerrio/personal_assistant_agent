from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.assistant_personal.application.agent.guardrails import Guardrails, StepDecision, build_default_guardrails
from src.assistant_personal.domain.entities import TaskReferenceResolution
from src.assistant_personal.infrastructure.observabilidad import get_logger, get_tracer
from src.assistant_personal.infrastructure.routers.openai_llm_client import OpenAITaskReferenceResolver

logger = get_logger(__name__)
tracer = get_tracer(__name__)

# Por debajo de esto, una coincidencia "encontrada" por el resolver no es lo bastante confiable
# como para actuar sobre ella — se prefiere pedirle al usuario que sea más específico antes que
# arriesgar una escritura sobre la tarea equivocada.
_MIN_RESOLUTION_CONFIDENCE = 0.7


class TaskReferenceResolver(Protocol):
    async def resolve_task_reference(
        self, task_reference: str, candidate_tasks: list[dict[str, Any]]
    ) -> TaskReferenceResolution: ...


@dataclass
class AgentStepResult:
    """Resultado de que el agente intente completar una acción que el router no pudo despachar
    directo. `resolved=False` siempre viene con `message`: el agente nunca deja al orquestador
    sin una respuesta explicable para el usuario."""

    resolved: bool
    task_id: str | None = None
    task_title: str | None = None
    message: str | None = None


class Agent:
    """Ejecutor para acciones que el router no puede despachar con el 100% de lo necesario sin
    interpretar lenguaje natural resolver `task_reference` → `task_id` para completar/eliminar tareas.

    Cada paso que toca Mongo pasa por `Guardrails.evaluate_step` antes de proceder —
    no una copia de esa política, la misma instancia que consumirá cualquier otra acción futura
    del agente.
    """

    def __init__(
        self,
        service: Any,
        resolver: TaskReferenceResolver | None = None,
        guardrails: Guardrails | None = None,
    ) -> None:
        self.service = service
        self.resolver = resolver or OpenAITaskReferenceResolver()
        self.guardrails = guardrails or build_default_guardrails()

    async def resolve_task_reference_to_id(self, task_reference: str) -> AgentStepResult:
        """Busca entre las tareas activas del usuario cuál coincide con `task_reference` y
        devuelve su `task_id`. No ejecuta ninguna acción de escritura — solo identifica."""
        with tracer.start_as_current_span("agent.resolver_referencia") as span:
            span.set_attribute("task_reference", task_reference)

            lookup_decision = self.guardrails.evaluate_step(tool_name="listar_tareas", steps_used=0, tokens_used=0)
            if lookup_decision != StepDecision.ALLOW:
                span.set_attribute("guardrail_decision", lookup_decision.value)
                logger.warning("agent_guardrail_bloqueo", tool="listar_tareas", decision=lookup_decision.value)
                return AgentStepResult(
                    resolved=False,
                    message="No pude buscar tus tareas por una restricción de seguridad interna.",
                )

            raw_tasks = await self._invoke_service("list_tasks")
            active_tasks = [task for task in raw_tasks if task.get("status") != "Deleted"]
            if not active_tasks:
                return AgentStepResult(
                    resolved=False,
                    message=f'No tienes tareas activas que coincidan con "{task_reference}".',
                )

            resolution = await self.resolver.resolve_task_reference(task_reference, active_tasks)
            span.set_attribute("resuelto", resolution.task_id is not None)
            span.set_attribute("confianza", resolution.confidence)

            if resolution.task_id is None or resolution.confidence < _MIN_RESOLUTION_CONFIDENCE:
                return AgentStepResult(
                    resolved=False,
                    message=(
                        f'No logré identificar con certeza a qué tarea te refieres con "{task_reference}". '
                        "¿Puedes ser más específico, por ejemplo con el título exacto?"
                    ),
                )

            matched_task = next((task for task in active_tasks if task.get("task_id") == resolution.task_id), None)
            return AgentStepResult(
                resolved=True,
                task_id=resolution.task_id,
                task_title=matched_task.get("title") if matched_task else None,
            )

    async def _invoke_service(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        async_method = getattr(self.service, f"{method_name}_async", None)
        if callable(async_method):
            return await async_method(*args, **kwargs)

        sync_method = getattr(self.service, method_name, None)
        if callable(sync_method):
            return sync_method(*args, **kwargs)

        raise AttributeError(f"El servicio no implementa '{method_name}'")
