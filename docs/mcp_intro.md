# Introducción a MCP en este proyecto

## Qué es MCP

MCP (Model Context Protocol) es un protocolo que permite a un agente usar herramientas externas de forma estructurada.

La idea principal es separar tres cosas:

- el modelo de lenguaje, que decide qué hacer,
- las herramientas, que ejecutan acciones concretas,
- y el contexto, que proporciona información relevante al agente.

## Diferencia entre modelo, herramientas y contexto

- Modelo: interpreta la intención del usuario y decide si necesita actuar.
- Herramientas: acciones concretas que el sistema puede ejecutar, como crear o listar tareas.
- Contexto: datos disponibles para el agente, como tareas activas, historial o preferencias del usuario.

En este proyecto, el flujo es:

1. El usuario pide algo como "crea una tarea para mañana".
2. El modelo analiza la intención.
3. Si necesita actuar, llama a una herramienta.
4. La herramienta usa la lógica de negocio y la infraestructura real.

## Cómo exponer herramientas desde un servidor MCP

Un servidor MCP expone funciones que el agente puede invocar.

En este proyecto, las herramientas están registradas desde:

- [src/assistant_personal/infrastructure/mcp/tools/task_tools.py](src/assistant_personal/infrastructure/mcp/tools/task_tools.py)

Y el servidor base está en:

- [src/assistant_personal/infrastructure/mcp/server.py](src/assistant_personal/infrastructure/mcp/server.py)

Las herramientas actuales cubren operaciones como:

- health_check
- listar_tareas
- crear_tarea
- actualizar_tarea
- completar_tarea
- buscar_tarea

## Cómo decide el agente cuándo llamar a una herramienta

El agente no debe usar herramientas por impulsos; debe decidir según la intención del usuario y la información disponible.

Regla práctica:

- si la petición requiere modificar o consultar datos persistidos, probablemente necesita una herramienta,
- si solo necesita responder con conocimiento general, no necesita una herramienta.

Ejemplo:

- "¿qué tareas tengo pendientes?" -> usar listar_tareas
- "añade una tarea nueva" -> usar crear_tarea
- "marca la tarea X como completada" -> usar completar_tarea

## Diseño de prompts para guiar al agente

Un buen prompt debe dejar claro:

- qué puede hacer el agente,
- cuándo debe usar cada herramienta,
- qué contexto debe considerar,
- y cómo responder si la herramienta falla.

Ejemplo de instrucción:

> Si el usuario pide gestionar tareas, usa las herramientas de tareas para consultar o modificar datos. No inventes información. Si no tienes suficiente contexto, pide una aclaración.

## Relación con este proyecto

Este repositorio ya está preparado para que el siguiente paso sea conectar un agente a estas herramientas y dejar que decida cuándo usarlas.
