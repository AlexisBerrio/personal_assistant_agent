# Arquitectura profesional actual del proyecto

> Este documento ha sido consolidado en [docs/arquitectura_y_prd.md](docs/arquitectura_y_prd.md). El contenido aquí se mantiene solo como referencia histórica y debe actualizarse a través del documento consolidado.

## Objetivo

Mantener una arquitectura clara y pedagógica, con separación de responsabilidades entre negocio, infraestructura e interfaces, mientras el proyecto evoluciona desde un prototipo funcional hacia un sistema más completo.

## Estructura actual

```text
app.py
src/
  assistant_personal/
    __init__.py
    config.py
    domain/
      __init__.py
      task_models.py
    application/
      __init__.py
      task_service.py
    infrastructure/
      __init__.py
      mongo_client.py
    interfaces/
      __init__.py
      cli.py
tests/
  test_task_service.py
```

## Capas del sistema

### 1. Dominio

Responsable de modelar la entidad principal del negocio.

- Define la clase Task.
- Representa los datos de una tarea de forma clara.
- Evita mezclar lógica de infraestructura con reglas de negocio.

### 2. Aplicación

Contiene los casos de uso del sistema.

- TaskService gestiona la creación, lectura, actualización y finalización de tareas.
- Se encarga de convertir los datos a un payload compatible con MongoDB.
- También serializa los resultados para devolver JSON limpio a la API.
- TaskOrchestrator actúa como orquestador de alto nivel para interpretar mensajes y decidir qué especialista o servicio ejecutar.
- ProductionIntentRouter actúa como gateway híbrido: reglas deterministas de alta precisión, clasificador Mini LLM y respuesta directa para conocimiento general.
- PromptBuilder y los guardrails ayudan a guiar el comportamiento del agente y a evitar ejecuciones peligrosas o vacías.
- AgentContext añade memoria de corto y largo plazo para que el sistema conserve contexto entre turnos.
- La aplicación depende de un puerto de memoria de sesión, no de MongoDB directamente.

Esta capa se añadió para demostrar cómo un sistema de tareas puede evolucionar desde una API directa hacia un flujo más parecido a un asistente conversacional, sin perder la separación entre negocio e infraestructura.

### 3. Infraestructura

Se encarga de integrar con servicios externos y capas técnicas.

- mongo_client.py abre la conexión con MongoDB.
- La base de datos usada actualmente es personal_management.
- La colección principal es personal_tasks.
- MongoSessionRepository implementa la persistencia de memoria conversacional por sesión.

### 4. Interfaces

Son los puntos de entrada del sistema.

- app.py expone una API REST con FastAPI.
- /health devuelve estado básico del servicio.
- /tasks permite listar y crear tareas.
- /tasks/{task_id} permite consultar o actualizar una tarea concreta, incluyendo marcarla como completada con un payload de estado.
- /tasks/{task_id}/history permite consultar el historial de cambios de una tarea.
- cli.py ofrece un flujo conversacional continuo desde terminal, orientado a preguntas del usuario y a la clasificación de intenciones.

## Flujo actual

1. El usuario interactúa por CLI o por una futura interfaz conversacional.
2. El router de intenciones clasifica el mensaje y decide si responde directamente, delega a tareas o requiere contexto.
3. El orquestador coordina la ejecución y la respuesta.
4. Cuando la intención implica persistencia o memoria de sesión, la capa de infraestructura opera sobre MongoDB.
5. La respuesta vuelve al usuario con datos serializados o con contenido conversacional.

## Qué aporta esta arquitectura

- Mantiene el negocio separado de la infraestructura.
- Facilita el aprendizaje y la comprensión del sistema.
- Hace posible escalar a agentes, MCP o Alexa sin reescribir todo desde cero.
- Permite introducir repositorios, validaciones más fuertes y servicios adicionales en fases futuras.

## Evolución recomendada

### Fase A: consolidar la base

- añadir validaciones más estrictas en la API,
- reforzar puertos y adaptadores para memoria conversacional y herramientas,
- mejorar los tests de integración.

### Fase B: conectar agentes y herramientas

- exponer tareas como herramientas para un agente,
- integrar un servidor MCP,
- orquestar flujos de negocio con LLMs.

### Fase C: experiencia conversacional

- integrar Alexa o una interfaz de voz,
- traducir comandos naturales a acciones del sistema.

## Recomendación pedagógica

El proyecto ya ha avanzado lo suficiente como para enseñar el patrón correcto de diseño:

1. dominio claro,
2. servicio de aplicación,
3. infraestructura aislada,
4. interfaces simples y bien definidas.

Ese orden es el que mejor prepara el proyecto para crecer hacia un asistente real y profesional.
