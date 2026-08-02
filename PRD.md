# PRD: Asistente personal con MongoDB, MCP, agentes y Alexa

## 1. Resumen del proyecto

Se está construyendo un asistente personal orientado a la gestión de tareas y contexto del usuario, con una arquitectura modular que combina:

- Python como lenguaje principal.
- MongoDB como base de datos documental.
- FastAPI como capa de API REST.
- MCP como evolución natural para exponer herramientas a agentes.
- Agentes con LLM y Alexa como futuras interfaces de interacción.

El objetivo inicial ya ha quedado materializado en una base funcional capaz de crear, listar, consultar, actualizar y completar tareas personales mediante una API y un servicio de negocio claro.

---

## 2. Objetivo principal

Crear una base profesional y pedagógica de un asistente personal que pueda:

- crear y consultar tareas desde una API,
- almacenar información en MongoDB,
- separar claramente negocio, infraestructura e interfaces,
- prepararse para integrar agentes, MCP y Alexa en fases posteriores.

---

## 3. Contexto del proyecto

Este proyecto nace como un ejercicio de aprendizaje y construcción práctica de sistemas de IA con agentes. La idea no es solo demostrar un prototipo, sino organizar el desarrollo con una arquitectura pensada para ser escalable, enseñable y extensible.

En esta etapa ya se ha consolidado la capa base de negocio y de interfaz:

- modelo de tareas,
- servicio de tareas,
- conexión con MongoDB,
- API REST mínima,
- CLI de prueba,
- tests unitarios básicos.

---

## 4. Alcance actual

### Incluido

- Estructura modular por capas: domain, application, infrastructure e interfaces.
- Modelo de dominio para tareas con campos como título, descripción, estado, categoría, etiquetas, prioridad, fechas, recurrencia, metadatos y pasos.
- Servicio de aplicación para crear, listar, consultar, actualizar y completar tareas.
- Conexión a MongoDB a través de una capa de infraestructura.
- API FastAPI con endpoints de salud y gestión de tareas.
- CLI para listar tareas desde la capa de aplicación.
- Tests unitarios que validan el comportamiento del servicio.

### No incluido todavía

- Integración completa con agentes de IA.
- Integración con Alexa.
- RAG y memoria avanzada.
- Autenticación y seguridad robusta.
- Despliegue en producción.
- Tests exhaustivos de integración.

---

## 5. Arquitectura actual

El proyecto sigue una arquitectura por capas:

- Domain: modelos de negocio, como Task.
- Application: servicios de casos de uso, como TaskService.
- Infrastructure: integración con MongoDB y servicios externos.
- Interfaces: API FastAPI, CLI y futuras experiencias conversacionales.

El flujo actual es:

1. La API recibe una petición HTTP.
2. El endpoint construye o delega en un Task.
3. TaskService prepara el payload y lo persiste en MongoDB.
4. La respuesta se serializa para que sea compatible con JSON.

---

## 6. Componentes principales

### 6.1 Modelo de dominio

Representa la entidad principal del negocio con la estructura actual de tareas:

- título
- descripción
- estado
- categoría
- etiquetas
- prioridad
- fechas
- recurrencia
- metadatos de contexto
- pasos
- notas del agente

### 6.2 Servicio de tareas

Responsable de:

- validar entradas y valores de negocio,
- aplicar reglas de dominio como el catálogo de estados permitidos,
- crear tareas,
- listar tareas,
- consultar tareas por task_id,
- actualizar campos parciales,
- completar tareas,
- serializar valores para devolver respuestas JSON compatibles.

#### Catálogo de valores de negocio

El campo status admite estos valores:
- Pending
- In Progress
- Completed
- Deleted

La categoría admite estos valores:
- Personal
- Work
- Study
- Health
- Home

La prioridad admite estos valores en el campo level:
- Low
- Medium
- High

- convertir datos a un formato adecuado,
- validar entradas,
- crear tareas,
- listar tareas,
- consultar tareas por task_id,
- actualizar campos parciales,
- completar tareas,
- serializar valores para devolver respuestas JSON compatibles.

### 6.3 Infraestructura MongoDB

Encargada de:

- conectar con MongoDB,
- abrir la base de datos correcta,
- ejecutar operaciones básicas sobre la colección personal_tasks.

### 6.4 API

Expone operaciones simples mediante FastAPI:

- GET /health
- POST /tasks
- GET /tasks
- GET /tasks/{task_id}
- GET /tasks/{task_id}/history
- PATCH /tasks/{task_id}

---

## 7. Requisitos funcionales

1. El sistema debe poder crear tareas con información básica o con estructura completa.
2. El sistema debe poder listar y consultar tareas almacenadas.
3. El sistema debe poder actualizar tareas de forma parcial mediante PATCH.
4. El sistema debe poder completar tareas mediante una actualización de estado.
5. El sistema debe poder consultar el historial de cambios de una tarea.
6. El sistema debe validar que una tarea tenga un título.
7. El sistema debe validar que el estado de una tarea use uno de los valores permitidos del catálogo.
8. La API debe responder con errores claros si la entrada es inválida.
9. El sistema debe estar preparado para integrar agentes y herramientas más adelante.

---

## 8. Requisitos no funcionales

- Código legible y bien comentado.
- Estructura modular y mantenible.
- Diseño orientado al aprendizaje y a la escalabilidad.
- Separación clara entre negocio, infraestructura e interfaces.

---

## 9. Fases previstas

### Fase 1: base funcional

- modelo de tareas
- servicio de tareas
- API mínima
- conexión con MongoDB
- CLI y tests básicos

### Fase 2: agentes y herramientas

- integración con MCP
- agentes que ejecuten acciones sobre tareas
- orquestación de flujos

### Fase 3: experiencia conversacional

- integración con Alexa o interfaz por voz
- comprensión de intenciones
- respuestas más naturales

### Fase 4: robustez y producción

- seguridad
- observabilidad
- tests
- despliegue
- RAG y memoria avanzada

---

## 10. Notas importantes

- El proyecto ya tiene una base funcional real y verificable.
- El enfoque sigue siendo educativo y profesional: hacer que el sistema sea comprensible, extensible y útil para continuar evolucionando.
- Se recomienda mantener el código claro, modular y documentado para que futuras IAs o desarrolladores puedan continuar el trabajo sin ambigüedades.

---

## 11. Resultado esperado de esta etapa

Al final de esta etapa, el proyecto cuenta con una base sólida para continuar hacia un asistente personal real, con capacidad de gestionar tareas, interactuar con APIs, persistir datos y evolucionar hacia experiencias como Alexa o interfaces conversacionales más completas.
