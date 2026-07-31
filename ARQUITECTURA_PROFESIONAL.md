# Arquitectura profesional actual del proyecto

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

- TaskService gestiona la creación y consulta de tareas.
- Se encarga de convertir los datos a un payload compatible con MongoDB.
- También serializa los resultados para devolver JSON limpio a la API.

### 3. Infraestructura

Se encarga de integrar con servicios externos y capas técnicas.

- mongo_client.py abre la conexión con MongoDB.
- La base de datos usada actualmente es personal_management.
- La colección principal es personal_tasks.

### 4. Interfaces

Son los puntos de entrada del sistema.

- app.py expone una API REST con FastAPI.
- /health devuelve estado básico del servicio.
- /tasks permite listar y crear tareas.
- cli.py ofrece una forma simple de inspeccionar tareas desde terminal.

## Flujo actual

1. El cliente envía una petición HTTP a la API.
2. FastAPI crea o recibe un objeto Task a partir del cuerpo JSON.
3. TaskService prepara el payload y lo persiste en MongoDB.
4. La respuesta vuelve al cliente con datos serializados y compatibles con JSON.

## Qué aporta esta arquitectura

- Mantiene el negocio separado de la infraestructura.
- Facilita el aprendizaje y la comprensión del sistema.
- Hace posible escalar a agentes, MCP o Alexa sin reescribir todo desde cero.
- Permite introducir repositorios, validaciones más fuertes y servicios adicionales en fases futuras.

## Evolución recomendada

### Fase A: consolidar la base

- añadir validaciones más estrictas en la API,
- separar aún más la lógica de acceso a datos,
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
