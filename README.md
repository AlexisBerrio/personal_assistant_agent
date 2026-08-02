# personal_assistant_agent

Asistente personal agéntico con arquitectura modular, MongoDB y FastAPI.

## Qué incluye actualmente

- modelo de dominio para tareas,
- servicio de aplicación para crear, listar, consultar, actualizar y completar tareas,
- conexión con MongoDB,
- API REST con FastAPI,
- CLI simple para consultar tareas,
- tests básicos del servicio.

## Estructura del proyecto

```text
app.py
src/
  assistant_personal/
    domain/
    application/
    infrastructure/
    interfaces/
tests/
```

## Requisitos

- Python 3.10 o superior
- MongoDB accesible localmente o remoto
- dependencias listadas en requirements.txt

## Ejecución

### 1. Instalar dependencias

```powershell
pip install -r requirements.txt
```

### 2. Levantar la API

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

### 3. Probar la API

- Health check: http://127.0.0.1:8000/health
- Listar tareas: http://127.0.0.1:8000/tasks
- Consultar una tarea: http://127.0.0.1:8000/tasks/{task_id}

### 4. Crear una tarea

Envío JSON a POST /tasks con un cuerpo como este:

```json
{
  "title": "Nueva tarea",
  "description": "Creada desde la API",
  "status": "Pending",
  "category": "Work",
  "priority": {
    "level": "High",
    "score": 90
  }
}
```

Valores permitidos:
- status: Pending, In Progress, Completed, Deleted
- category: Personal, Work, Study, Health, Home
- priority.level: Low, Medium, High

```json
{
  "title": "Nueva tarea",
  "description": "Creada desde la API",
  "status": "Pending",
  "category": "Work"
}
```

### 5. Actualizar una tarea

Envío JSON a PATCH /tasks/{task_id} con solo los campos que quieras modificar:

```json
{
  "status": "In Progress",
  "title": "Nueva tarea actualizada",
  "category": "Work",
  "priority": {
    "level": "Medium",
    "score": 60
  }
}
```

### 6. Completar una tarea

Envío JSON a PATCH /tasks/{task_id} con el estado de la tarea:

```json
{
  "status": "Completed"
}
```

### 7. Historial de cambios

El proyecto también puede registrar cambios en una colección separada llamada `task_history` para no saturar la colección principal de tareas.

Puedes consultar ese historial con:

```http
GET /tasks/{task_id}/history
```

Ejemplo de documento para MongoDB:

```json
{
  "task_id": "task-123",
  "timestamp": "2026-07-31T10:30:00",
  "changes": [
    {
      "field": "status",
      "previous_value": "In Progress",
      "new_value": "Completed"
    },
    {
      "field": "description",
      "previous_value": "Tarea pendiente",
      "new_value": "Tarea finalizada"
    }
  ]
}
```

### 8. Ejecutar el CLI

```powershell
python -m src.assistant_personal.interfaces.cli
```

## Siguientes pasos

- integrar agentes y herramientas con MCP,
- añadir más validaciones y tests,
- preparar una interfaz por voz como Alexa.
