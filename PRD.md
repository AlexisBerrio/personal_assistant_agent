# PRD: Asistente personal con MongoDB, MCP, agentes y Alexa

## 1. Resumen del proyecto

Se está construyendo un asistente personal orientado a la gestión de tareas y contexto del usuario, con una arquitectura modular que combina:

- Python como lenguaje principal.
- MongoDB como base de datos documental.
- MCP para exponer herramientas a agentes.
- Agentes con LLM para interpretar peticiones en lenguaje natural.
- FastAPI como capa de API para interacción externa.
- Alexa como futura interfaz por voz.

El objetivo inicial es demostrar una arquitectura realista de un sistema de agentes capaz de crear, listar y gestionar tareas personales mediante herramientas externas y un modelo de lenguaje.

---

## 2. Objetivo principal

Crear una base profesional y pedagógica de un asistente personal que pueda:

- comprender peticiones en lenguaje natural,
- transformar esas peticiones en acciones concretas,
- almacenar información en MongoDB,
- exponer funcionalidades a través de una API,
- prepararse para integrar agentes, MCP y Alexa en fases posteriores.

---

## 3. Contexto del proyecto

Este proyecto nace como un ejercicio de aprendizaje y construcción práctica de sistemas de IA con agentes. La idea es no quedarse en un prototipo simple, sino organizar el desarrollo con una arquitectura pensada para ser escalable y comprensible.

Actualmente se está trabajando en la capa base de negocio:

- modelo de tareas,
- servicio de tareas,
- conexión con MongoDB,
- API REST mínima,
- estructura de proyecto modular.

---

## 4. Alcance actual

### Incluido

- Estructura de proyecto modular con carpetas por capas.
- Modelo de dominio para tareas.
- Servicio de aplicación para crear y listar tareas.
- Conexión básica a MongoDB.
- API FastAPI con endpoints de prueba.
- Documentación y comentarios para facilitar la comprensión.

### No incluido todavía

- Integración completa con agentes de IA.
- Integración con Alexa.
- RAG y memoria avanzada.
- Autenticación y seguridad robusta.
- Despliegue en producción.
- Tests exhaustivos de integración.

---

## 5. Arquitectura propuesta

El proyecto sigue una arquitectura por capas:

- Domain: modelos de negocio, por ejemplo Task.
- Application: servicios de casos de uso, por ejemplo TaskService.
- Infrastructure: integración con MongoDB y otros servicios externos.
- Interfaces: API y futuras interfaces como Alexa o CLI.

Esto permite separar responsabilidad, hacer el sistema más comprensible y preparar el camino para escalar.

---

## 6. Componentes principales

### 6.1 Modelo de dominio

Representa la entidad principal del negocio:

- título
- descripción
- estado
- prioridad
- fecha límite
- origen de la tarea

### 6.2 Servicio de tareas

Responsable de:

- convertir datos a un formato adecuado,
- validar entradas,
- crear tareas,
- listar tareas,
- marcar tareas como completadas.

### 6.3 Infraestructura MongoDB

Encargada de:

- conectar con MongoDB,
- abrir la base de datos correcta,
- ejecutar operaciones básicas.

### 6.4 API

Expone operaciones simples mediante FastAPI:

- GET /health
- POST /tasks
- GET /tasks

---

## 7. Requisitos funcionales

1. El sistema debe poder crear tareas con información básica.
2. El sistema debe poder listar tareas almacenadas.
3. El sistema debe validar que una tarea tenga un título.
4. La API debe responder con errores claros si la entrada es inválida.
5. El sistema debe estar preparado para integrar agentes y herramientas más adelante.

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

- El proyecto está pensado como una base educativa y profesional.
- El enfoque no es solo “hacer que funcione”, sino “hacer que se entienda y escale”.
- Se recomienda mantener el código claro, modular y documentado para que futuras IAs o desarrolladores puedan continuar el trabajo sin ambigüedades.

---

## 11. Resultado esperado

Al final de esta etapa, el proyecto debería tener una base sólida para continuar hacia un asistente personal real, con capacidad de gestionar tareas, interactuar con agentes, integrar herramientas externas y evolucionar hacia experiencias como Alexa o interfaces conversacionales más completas.
