from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.assistant_personal.application.task_service import TaskService
from src.assistant_personal.domain.task_models import Task

# Creamos la aplicación FastAPI. Es el punto de entrada para recibir peticiones.
app = FastAPI(title="Asistente Personal", version="0.1.0")
service = TaskService()


class TaskCreateRequest(BaseModel):
    """Modelo que define qué datos recibe la API para crear una tarea."""
    title: str
    description: str | None = None
    priority: str = "medium"
    due_date: str | None = None
    source: str = "manual"


@app.get("/health")
def health_check() -> dict[str, str]:
    """Endpoint simple para comprobar que la API responde."""
    return {"status": "ok"}


@app.post("/tasks", status_code=201)
def create_task(payload: TaskCreateRequest) -> dict[str, str]:
    """Recibe una tarea desde el cliente y la guarda usando el servicio."""
    task = Task(
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        due_date=payload.due_date,
        source=payload.source,
    )
    try:
        return service.create_task(task)
    except ValueError as exc:
        # Si falta información, devolvemos un error claro al cliente.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/tasks")
def list_tasks() -> list[dict[str, object]]:
    """Devuelve una lista de tareas almacenadas en MongoDB."""
    return service.list_tasks()
