# personal_assistant_agent

Asistente personal agéntico con arquitectura modular, MongoDB y FastAPI.

## Qué incluye actualmente

- modelo de dominio para tareas,
- servicio de aplicación para crear y listar tareas,
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

### 4. Crear una tarea

Envío JSON a POST /tasks con un cuerpo como este:

```json
{
  "title": "Nueva tarea",
  "description": "Creada desde la API",
  "status": "In Progress",
  "category": "Work"
}
```

### 5. Ejecutar el CLI

```powershell
python -m src.assistant_personal.interfaces.cli
```

## Siguientes pasos

- integrar agentes y herramientas con MCP,
- añadir más validaciones y tests,
- preparar una interfaz por voz como Alexa.
