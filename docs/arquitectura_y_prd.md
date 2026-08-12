# Arquitectura y PRD consolidado del asistente personal

## Propósito de este documento

Este documento es la fuente única de verdad para el alcance, la arquitectura y el estado actual del proyecto.

- El plan de formación sigue siendo la guía de aprendizaje y de progresión del proyecto.
- Este documento concentra el contexto de negocio, la arquitectura propuesta y los objetivos actuales.
- Si cambia la arquitectura, el alcance o el comportamiento del sistema, este documento debe actualizarse primero.

---

## 1. Visión del producto

Construir un asistente personal modular y pedagógico que permita:

- gestionar tareas desde una API y desde un flujo conversacional,
- persistir información en MongoDB,
- separar claramente negocio, infraestructura e interfaces,
- preparar el sistema para futuras integraciones con agentes, MCP y Alexa.

El enfoque no es solo demostrar un prototipo, sino enseñar cómo evolucionar un sistema desde una base funcional hacia una arquitectura más profesional.

---

## 2. Objetivo principal

Crear una base sólida para un asistente personal capaz de:

- crear, listar, consultar, actualizar y completar tareas,
- almacenar datos de forma persistente,
- interpretar intenciones simples desde lenguaje natural,
- preparar la arquitectura para agentes y herramientas.

---

## 3. Alcance actual

### Incluido

- estructura modular por capas: domain, application, infrastructure e interfaces,
- modelo de dominio para tareas,
- servicio de aplicación para crear, listar, consultar, actualizar y completar tareas,
- conexión con MongoDB,
- API REST con FastAPI,
- CLI conversacional orientado a interacción simple,
- router híbrido con reglas y LLM para clasificar intenciones,
- memoria conversacional de sesión con puerto desacoplado de la implementación MongoDB,
- tests unitarios y de flujo básico.

### No incluido todavía

- integración completa con agentes especializados,
- integración con Alexa,
- memoria conversacional robusta y avanzada,
- RAG y memoria semántica,
- seguridad y autenticación robustas,
- despliegue y observabilidad en producción.

---

## 4. Arquitectura actual

El proyecto sigue una arquitectura por capas.

### 4.1 Dominio

Responsable de representar el negocio y las reglas de dominio.

- entidades como Task,
- contratos de repositorio como TaskRepository y SessionMemoryRepository,
- reglas básicas de validación y de actualización de estado.

### 4.2 Application

Contiene los casos de uso y coordinación del sistema.

- TaskService para gestionar tareas,
- TaskOrchestrator para decidir qué acción ejecutar ante un mensaje,
- ProductionIntentRouter para clasificar intenciones,
- AgentContext para manejar contexto de conversación.

### 4.3 Infrastructure

Se encarga de adaptar el sistema a tecnologías concretas.

- repositorios MongoDB para tareas y memoria de sesión,
- conexión a MongoDB,
- servidor MCP y herramientas de tareas,
- adaptadores para interfaces externas.

### 4.4 Interfaces

Puntos de entrada del sistema.

- API REST en app.py,
- CLI en src/assistant_personal/interfaces/cli.py,
- futuras interfaces conversacionales como Alexa o agentes.

---

## 5. Flujo actual del sistema

1. El usuario interactúa por CLI o por una futura interfaz conversacional.
2. El router de intenciones clasifica el mensaje.
3. El orquestador decide si responde directamente, delega a tareas o necesita contexto.
4. La capa de infraestructura persiste datos si la acción lo requiere.
5. La respuesta vuelve al usuario con contexto y resultados serializados.

---

## 6. Requisitos funcionales

1. El sistema debe poder crear tareas con información básica o con estructura completa.
2. El sistema debe poder listar y consultar tareas almacenadas.
3. El sistema debe poder actualizar tareas de forma parcial.
4. El sistema debe poder completar tareas.
5. El sistema debe poder consultar el historial de cambios de una tarea.
6. El sistema debe validar que una tarea tenga un título.
7. El sistema debe validar los valores de estado, categoría y prioridad.
8. La API debe responder con errores claros ante entradas inválidas.
9. El sistema debe estar preparado para integrar agentes y herramientas en fases posteriores.

---

## 7. Requisitos no funcionales

- código legible y modular,
- separación clara entre negocio e infraestructura,
- diseño orientado al aprendizaje y a la escalabilidad,
- facilidad para evolucionar hacia agentes, MCP y voz.

---

## 8. Fases previstas

### Fase 0: consolidación y orden

Objetivo: cerrar deuda técnica y documental antes de sumar complejidad.

- repositorio explícito para tareas,
- tests de integración del flujo completo,
- documentación unificada y verificable.

#### Definition of Done de la Fase 0

La fase 0 se considera cerrada cuando se cumplen estas condiciones verificables:

- [x] El servicio de tareas depende de un repositorio explícito a través del puerto de dominio y no construye directamente la infraestructura Mongo en la capa de aplicación.
- [x] La infraestructura expone un factory por defecto para el repositorio de tareas, de forma que el punto de entrada de persistencia sea claro y reutilizable.
- [x] Existen pruebas que cubren al menos el flujo de negocio completo: crear, listar, actualizar, completar y consultar historial.
- [x] La documentación principal del proyecto apunta a un único documento consolidado de arquitectura y alcance.
- [x] Los documentos legacy de PRD y arquitectura dejan de ser la fuente de verdad y remiten al documento consolidado.

### Fase 1: fundamentos técnicos con profundidad real

- validaciones más formales,
- mejores decisiones de diseño sobre infraestructura y estructura.

### Fase 2: IA generativa con criterio de ingeniería

- prompts más estructurados,
- gestión de contexto y costes,
- manejo explícito de salidas inválidas del modelo.

### Fase 3: MCP en profundidad

- herramientas MCP bien diseñadas,
- tests unitarios aislados,
- integración con el orquestador.

### Fase 4: arquitectura de agentes

- evaluación del router,
- guardrails más fuertes,
- decisiones explícitas sobre diseño de agentes.

### Fase 5: RAG y contexto avanzado

- decidir si aplica o no al producto.

### Fase 6: Alexa

- integración por voz reutilizando la lógica del backend.

### Fase 7: producción y observabilidad

- seguridad, logging, CI y despliegue.

### Fase 8: producto real

- multi-tenancy, costos, privacidad y escalabilidad.

---

## 9. Criterios de aceptación actuales

El proyecto puede considerarse en una base estable si:

- el flujo de tareas funciona end-to-end con tests,
- el servicio de negocio no depende directamente de MongoDB en la capa de dominio,
- la API responde de forma consistente ante errores de validación,
- la documentación refleja el estado real del proyecto.

---

## 10. Referencias principales

- Guía de aprendizaje: [plan_formacion_asistente_personal.md](../plan_formacion_asistente_personal.md)
- Punto de entrada de la API: [app.py](../app.py)
- Módulo principal del dominio: [src/assistant_personal/domain](../src/assistant_personal/domain)
- Módulo de aplicación: [src/assistant_personal/application](../src/assistant_personal/application)
- Módulo de infraestructura: [src/assistant_personal/infrastructure](../src/assistant_personal/infrastructure)
