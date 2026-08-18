# personal_assistant_agent

Asistente personal agéntico con arquitectura modular, MongoDB y FastAPI.

> Documento de referencia consolidado: [docs/arquitectura_y_prd.md](docs/arquitectura_y_prd.md)

## Qué incluye actualmente

- modelo de dominio para tareas,
- servicio de aplicación para crear, listar, consultar, actualizar y completar tareas,
- conexión con MongoDB,
- API REST con FastAPI,
- CLI simple para consultar tareas,
- tests básicos del servicio,
- una capa inicial de orquestación para un agente que interpreta mensajes en lenguaje natural.
- un router híbrido con clasificación de intención y respuestas de conocimiento general,
- memoria conversacional de sesión con puerto desacoplado de la implementación MongoDB.

## Avance reciente: orquestación de agente

Se añadió una primera capa de agente orientada a aprendizaje y evolución del sistema.

### Qué se hizo

- se incorporó un orquestador que recibe un mensaje del usuario y decide qué acción ejecutar,
- se añadió un router de intención para clasificar peticiones como listar, crear o completar tareas,
- se incorporaron guardrails para rechazar mensajes vacíos o ambiguos,
- se añadieron reintentos simples para manejar fallos transitorios,
- se creó una memoria de corto y largo plazo para conservar contexto entre interacciones.
- se desacopló la memoria conversacional mediante un puerto de repositorio para no atar la capa de aplicación a MongoDB.

### Por qué se hizo

El objetivo era pasar de un backend CRUD funcional a un flujo más cercano a un asistente real. Esto permite demostrar, de forma pedagógica, cómo un sistema puede interpretar instrucciones naturales, protegerse frente a entradas inválidas y preparar la base para futuras integraciones con MCP, voz y agentes.

### Para qué se usa

Esta capa se usa para que el sistema pueda reaccionar a frases como:

- "crear una tarea para estudiar"
- "listar mis tareas"
- "completar la tarea de comprar pan"

y decidir la acción adecuada sin depender únicamente de un endpoint REST manual.

## Estructura del proyecto

```text
app.py
src/
  assistant_personal/
    domain/
      repositories/
    application/
    infrastructure/
    interfaces/
tests/
```

## Requisitos

- Python 3.10 o superior
- MongoDB accesible localmente o remoto
- dependencias declaradas en `pyproject.toml`

## Ejecución

### 1. Instalar el proyecto (modo editable)

```powershell
pip install -e ".[dev,llm,mcp]"
```

Instala el paquete en modo editable junto con los grupos opcionales: `llm` (SDK de OpenAI), `mcp`
(servidor MCP) y `dev` (pytest). Con esto los imports funcionan igual sin importar desde qué
directorio se invoque el CLI, la API o los tests — ya no depende de `sys.path` ni del directorio de
trabajo actual.

### 2. (Opcional) Levantar un MongoDB local desechable para tests

```powershell
docker compose up -d mongo
```

Da un Mongo local en `localhost:27017`, aislado del cluster de Atlas configurado en `.env`. Útil para
tests de integración sin depender de conectividad ni de credenciales reales. Para usarlo, apunta
`MONGO_URI` en `.env` a `mongodb://localhost:27017/personal_management`. Para tirarlo:
`docker compose down` (agrega `-v` si además quieres borrar los datos del volumen).

### 3. Levantar la API

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

### 4. Probar la API

- Health check: http://127.0.0.1:8000/health
- Listar tareas: http://127.0.0.1:8000/tasks
- Consultar una tarea: http://127.0.0.1:8000/tasks/{task_id}

### 5. Crear una tarea

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

### 6. Actualizar una tarea

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

### 7. Completar una tarea

Envío JSON a PATCH /tasks/{task_id} con el estado de la tarea:

```json
{
  "status": "Completed"
}
```

### 8. Historial de cambios

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

### 9. Ejecutar el CLI

```powershell
python -m src.assistant_personal.interfaces.cli
```

## Siguientes pasos

- consolidar tests de integración del flujo conversacional completo,
- integrar agentes y herramientas con MCP,
- preparar una interfaz por voz como Alexa.

## Conceptos clave de MCP

Para entender la transición hacia agentes, este proyecto ya incluye una guía introductoria en [docs/mcp_intro.md](docs/mcp_intro.md).

En ella se explica:

- qué es MCP y por qué se usa,
- la diferencia entre modelo, herramientas y contexto,
- cómo exponer herramientas desde un servidor MCP,
- cómo un agente decide cuándo invocar una herramienta,
- y cómo diseñar prompts para guiar al agente.
