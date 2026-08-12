# Plan de formación avanzado: del asistente personal a un producto real

## Cómo leer este plan

Este plan **no reemplaza el trabajo ya hecho**: parte de lo que ya existe (capas domain/application/infrastructure/interfaces, `TaskService`, `TaskOrchestrator`, `ProductionIntentRouter`, memoria de sesión desacoplada) y lo evoluciona. Cada fase tiene:

- **Objetivo de aprendizaje** — qué debes entender de verdad, no solo usar.
- **Temas y nivel de profundidad** — conceptual (entender), práctico (implementar), experto (optimizar/decidir entre alternativas).
- **Cómo evoluciona el proyecto** — qué cambia concretamente en el repo.
- **Entregable verificable** — algo que puedas demostrar que funciona, no solo "haber leído sobre esto".
- **Definition of Done (DoD)** — criterio objetivo para cerrar la fase.

No es un plan de "aprende teoría y luego aplícala". Cada fase modifica el mismo proyecto.

---

## Fase 0: Consolidación y orden (antes de sumar nada nuevo)

### Objetivo
Eliminar la deuda técnica y documental antes de construir encima. Sin esto, cada fase nueva hereda ambigüedad.

### Temas
- **Repository pattern** (práctico): extraer el acceso a `personal_tasks` de `mongo_client.py` a un repositorio explícito (`TaskRepository`), para que `TaskService` dependa de una interfaz, no de Mongo directamente — igual que ya hiciste con la memoria de sesión.
- **Single source of truth documental** (conceptual): un solo documento vivo de arquitectura (no tres archivos que se puedan desalinear). El plan de formación queda como guía de aprendizaje; la arquitectura y el PRD deben fusionarse o referenciarse entre sí sin duplicar contenido.
- **Definition of Done por fase** (conceptual): criterios verificables, no descriptivos.
- **Tests de integración del flujo completo** (práctico): CLI → router → orquestador → servicio → Mongo, con datos reales de prueba.

### Cómo evoluciona el proyecto
- Nuevo módulo `infrastructure/task_repository.py` + puerto `TaskRepositoryPort` en `domain/`.
- `TaskService` deja de importar Mongo directamente.
- Carpeta `docs/` con un único documento de arquitectura versionado.

### Entregable
Suite de tests de integración corriendo en CI local (aunque sea con `pytest` y un Mongo de prueba en Docker), y `TaskService` sin ninguna dependencia directa de `pymongo`.

### DoD
- 0 imports de Mongo fuera de `infrastructure/`.
- Tests de integración cubren: crear, listar, actualizar, completar, consultar historial.

---

## Fase 1: Fundamentos técnicos con profundidad real

### Objetivo
Dejar de "saber usar" FastAPI/Mongo/Python y empezar a **decidir con criterio** entre alternativas.

### Temas y profundidad
- **Python asíncrono** (práctico): `async/await`, cuándo de verdad importa (I/O-bound: llamadas a LLM, a Mongo, a MCP) vs cuándo es innecesario.
- **Pydantic v2** (práctico): validación de dominio, `model_validator`, serialización custom — reemplaza validaciones manuales sueltas en el servicio.
- **FastAPI en profundidad** (práctico): dependency injection real (no solo `def endpoint(): ...`), middlewares, manejo de excepciones centralizado, background tasks.
- **MongoDB más allá de CRUD** (conceptual + práctico): índices (¿por qué tu colección `personal_tasks` los necesita ya, con filtros por estado/prioridad/fecha?), agregaciones, transacciones cuando falla algo a mitad de una operación multi-documento.
- **Arquitectura limpia / hexagonal aplicada** (experto): no como teoría abstracta, sino auditando tu propio repo — ¿dónde se filtran detalles de infraestructura hacia el dominio?

### Cómo evoluciona el proyecto
- Migrar validaciones sueltas del `TaskService` a modelos Pydantic explícitos en `domain/task_models.py`.
- Añadir índices a `personal_tasks` según los patrones de consulta reales (pendientes, por prioridad, por fecha).
- Middleware de manejo de errores centralizado en `app.py`.

### Entregable
Un endpoint que falla de forma controlada y consistente (mismo formato de error) ante cualquier input inválido, con validación 100% delegada a Pydantic.

### DoD
- Ningún `if` de validación manual en `TaskService`; todo vive en los modelos.
- Consultas críticas usan índice (verificable con `explain()` en Mongo).

---

## Fase 2: Fundamentos de IA generativa con criterio de ingeniería

### Objetivo
Entender los LLMs como un componente de sistema con costos, límites y fallos — no como una caja mágica.

### Temas y profundidad
- **Prompting estructurado** (práctico): system prompts versionados como código, no strings sueltos en el código.
- **Function calling / tool use** (práctico): cómo un modelo decide llamar una herramienta, qué pasa cuando decide mal, cómo se valida el output.
- **Structured outputs** (práctico): forzar JSON válido desde el modelo, con esquemas explícitos (relevante para tu `ProductionIntentRouter`).
- **Gestión de contexto y tokens** (conceptual): por qué la memoria de sesión no puede crecer sin límite, estrategias de resumen/compactación.
- **Costos y latencia como restricción de diseño** (conceptual): cuándo usar un modelo grande vs uno pequeño (tu router ya usa un "Mini LLM" — formaliza el criterio de esa decisión).
- **Alucinaciones y mitigación** (conceptual): por qué ocurren, por qué no se "eliminan", solo se acotan.

### Cómo evoluciona el proyecto
- `PromptBuilder` pasa de generar strings a gestionar plantillas versionadas con control de cambios.
- El `ProductionIntentRouter` documenta explícitamente su criterio de escalado reglas → mini LLM → LLM grande.

### Entregable
Documento corto (interno) que explica, con datos reales de tu router, cuándo se usa cada nivel de clasificación y por qué.

### DoD
- Prompts versionados fuera del código Python (archivos separados o config).
- Al menos un caso de "salida no válida del modelo" manejado explícitamente (no solo un `try/except` genérico).

---

## Fase 3: MCP en profundidad

### Objetivo
Entender el protocolo, no solo "conectar un server". Saber cuándo MCP es la herramienta correcta y cuándo es sobre-ingeniería.

### Temas y profundidad
- **Arquitectura MCP** (conceptual): hosts, clients, servers; resources vs tools vs prompts como conceptos distintos del protocolo.
- **Diseño de herramientas MCP** (práctico): herramientas idempotentes, bien tipadas, con descripciones que el modelo pueda interpretar sin ambigüedad — auditar `listar_tareas`, `crear_tarea`, etc. bajo ese criterio.
- **MCP vs function calling directo** (experto): trade-offs reales — cuándo vale la pena el desacoplamiento de un servidor MCP separado vs exponer las funciones directamente al agente.
- **Seguridad en MCP** (conceptual + práctico): qué puede hacer una herramienta expuesta, control de permisos, por qué un servidor MCP con acceso a Mongo necesita límites explícitos (no todas las operaciones deberían estar disponibles para el agente).
- **Testing de servidores MCP** (práctico): probar las herramientas de forma aislada, sin depender de que el LLM las invoque correctamente.

### Cómo evoluciona el proyecto
- `mongo_mcp_server.py` expone las herramientas ya planeadas (`listar_tareas`, `crear_tarea`, `actualizar_tarea`, `completar_tarea`, `listar_tareas_pendientes`, `buscar_tareas_por_prioridad`), pero construidas **sobre el `TaskRepository`/`TaskService`** de la Fase 0, no accediendo a Mongo por su cuenta.
- Cada herramienta con esquema de entrada/salida explícito y tests unitarios propios.

### Entregable
Servidor MCP funcional, probado de forma aislada (sin agente), y luego conectado al orquestador existente.

### DoD
- Cada herramienta MCP tiene test unitario independiente del LLM.
- Ninguna herramienta MCP puede ejecutar una operación que el `TaskService` no permitiría igualmente vía API.

---

## Fase 4: Arquitectura de agentes, con decisiones explícitas

### Objetivo
Pasar de "tengo un orquestador" a entender **por qué** ese patrón y no otro, y poder justificar la elección frente a alternativas reales de la industria.

### Temas y profundidad
- **Patrones de arquitectura de agentes** (experto): agente único con herramientas vs orquestador-especialistas (el que ya tienes) vs grafos de estado (LangGraph-style) — comparar con lo que ya construiste y decidir si escalarlo o simplificarlo.
- **Memoria de agentes** (práctico + conceptual): corto plazo (ya tienes), largo plazo persistente, memoria episódica vs semántica — y cuándo cada una aporta valor real vs solo complejidad.
- **Evaluación de agentes** (práctico, poco cubierto en el plan anterior): datasets "golden" de conversaciones esperadas, LLM-as-judge, métricas de precisión de clasificación del router — esto es lo que separa un prototipo de un sistema confiable.
- **Guardrails avanzados** (práctico): más allá de bloquear mensajes vacíos — límites de acciones destructivas, confirmación humana antes de acciones irreversibles.
- **Manejo de errores y reintentos con criterio** (experto): cuándo reintentar, cuándo fallar rápido, circuit breakers para llamadas a LLM o a MCP.

### Cómo evoluciona el proyecto
- `TaskOrchestrator` y `ProductionIntentRouter` se documentan como una decisión arquitectónica explícita, comparada contra al menos una alternativa (por ejemplo, un grafo de estados).
- Suite de evaluación: conjunto de mensajes de prueba con la intención esperada, corrida automatizada que mide precisión del router.
- Guardrail nuevo: cualquier acción de "completar" o "eliminar" tarea requiere confirmación explícita si viene con ambigüedad.

### Entregable
Reporte de evaluación del router (precisión sobre un dataset de al menos 30-50 mensajes representativos) y un guardrail de confirmación funcionando.

### DoD
- Métrica de precisión del router medida y documentada (no solo "funciona cuando lo pruebo a mano").
- Al menos una acción destructiva protegida por confirmación.

---

## Fase 5: RAG y contexto avanzado (nuevo, no estaba en el plan anterior)

### Objetivo
Saber cuándo tu asistente necesita recuperación de información más allá de Mongo estructurado, y cuándo NO la necesita (evitar sobre-ingeniería).

### Temas y profundidad
- **Cuándo RAG tiene sentido** (conceptual): tu caso de tareas estructuradas probablemente NO lo necesita para el core, pero sí podría para notas largas, contexto histórico de conversaciones, o documentación que el asistente deba consultar.
- **Embeddings y búsqueda semántica** (conceptual + práctico): qué son, cómo se indexan, MongoDB Atlas Search vectorial como opción natural dado tu stack actual.
- **Chunking y estrategias de recuperación** (práctico, si aplica): solo si decides que tu asistente necesita buscar sobre texto libre (notas, historiales largos).

### Cómo evoluciona el proyecto
- Evaluación explícita: ¿el asistente necesita RAG o el modelo relacional/documental actual es suficiente? Documentar la decisión.
- Si aplica: colección de embeddings sobre notas o contexto extendido, usando el mismo Mongo (Atlas Vector Search) para no introducir una pieza de infraestructura nueva sin necesidad.

### Entregable
Documento de decisión (con justificación) sobre si RAG aplica a este proyecto, y si aplica, un prototipo mínimo funcionando.

### DoD
- Decisión documentada con criterio, no implementación por moda.

---

## Fase 6: Integración con Alexa

### Objetivo
Añadir voz como interfaz, entendiendo las restricciones reales del modelo de interacción de Alexa (no es "otro cliente HTTP más").

### Temas y profundidad
- **Alexa Skills Kit (ASK)** (práctico): intents, utterances, slots, session attributes.
- **Modelo de interacción por voz** (conceptual): por qué el diseño de utterances no es lo mismo que diseñar un prompt de texto.
- **Autenticación y seguridad del endpoint** (práctico): verificación de firma de Amazon, no solo un endpoint abierto.
- **Manejo de ambigüedad por voz** (práctico): fallback intents, reprompts, cómo se conecta esto con el guardrail de confirmación de la Fase 4.

### Cómo evoluciona el proyecto
- Endpoint dedicado que traduce intents de Alexa a las mismas acciones que ya expone el orquestador (reutilizando la lógica existente, no duplicándola).
- Verificación de firma de request de Alexa antes de procesar cualquier comando.

### Entregable
Skill de Alexa funcional en modo desarrollo, ejecutando al menos: crear tarea, listar pendientes, completar tarea — sobre el mismo backend, sin lógica de negocio duplicada.

### DoD
- Cero lógica de negocio nueva escrita específicamente para Alexa (todo reutiliza `TaskService`/orquestador).
- Firma de request verificada.

---

## Fase 7: Producción, seguridad y observabilidad

### Objetivo
Convertir el prototipo en algo operable por alguien que no seas tú mirando logs en la terminal.

### Temas y profundidad
- **Logging estructurado** (práctico): JSON logs con contexto (session_id, task_id), no `print()`.
- **Trazabilidad de agentes** (práctico, específico de este tipo de sistema): poder reconstruir por qué el router clasificó un mensaje de cierta forma.
- **Gestión de secretos** (práctico): variables de entorno gestionadas correctamente, nunca credenciales en código.
- **Rate limiting y circuit breakers** (práctico): proteger contra abuso y contra fallos en cascada cuando el LLM o Mongo no responden.
- **Autenticación de la API** (práctico): API keys o OAuth2 mínimo antes de exponer el backend a Alexa en producción.
- **Testing de agentes en CI** (experto): correr la suite de evaluación de la Fase 4 automáticamente en cada cambio.
- **Despliegue** (práctico): contenedor Docker, variables de entorno por ambiente, al menos un despliegue real (local con Docker Compose es un buen mínimo, cloud si quieres ir más allá).

### Cómo evoluciona el proyecto
- `docker-compose.yml` con la app, Mongo y variables de entorno.
- Middleware de autenticación en la API.
- Pipeline de CI (aunque sea GitHub Actions simple) que corre tests + evaluación del router.

### Entregable
Sistema desplegado en un contenedor, con logs estructurados consultables, y un pipeline de CI verde.

### DoD
- 0 secretos en el código.
- CI corre en cada cambio y falla si baja la precisión del router por debajo de un umbral definido.

---

## Fase 8: De proyecto educativo a idea de negocio

### Objetivo
Entender qué cambia técnicamente cuando un proyecto pasa de "mi asistente" a "un producto que otros usan".

### Temas y profundidad
- **Multi-tenancy** (conceptual + práctico): cómo aislar datos por usuario en Mongo (un `user_id` no es suficiente por sí solo — hay que pensarlo en el diseño de queries e índices).
- **Modelos de costos** (conceptual): cuánto cuesta cada conversación (tokens de LLM, infraestructura) y cómo eso afecta un modelo de pricing.
- **Escalabilidad** (conceptual): qué se rompe primero si pasas de 1 usuario a 1000 (conexiones a Mongo, rate limits de LLM, memoria de sesión).
- **Privacidad y datos personales** (conceptual): implicaciones de almacenar tareas y conversaciones de terceros, no solo tuyas.

### Cómo evoluciona el proyecto
- Diseño de esquema multi-tenant para `personal_tasks` y memoria de sesión.
- Documento breve de costos estimados por usuario activo.

### Entregable
Documento de viabilidad técnica para pasar de "mi proyecto" a "producto con usuarios reales", con los cambios concretos que eso exige en el código actual.

### DoD
- Esquema de datos revisado y compatible con múltiples usuarios sin reescritura completa.

---

## Cómo se relaciona esto con lo que ya tenías

- Las Fases 1-2 del plan anterior quedan absorbidas y profundizadas en la nueva Fase 0-1.
- MCP y arquitectura de agentes (antes Fases 3-4) se mantienen pero con evaluación, seguridad y testing explícitos que antes no estaban.
- Alexa (antes Fase 5) se mantiene igual en espíritu, más profunda en seguridad.
- Producción (antes Fase 6) se mantiene pero con criterios verificables (DoD) en vez de descripciones generales.
- Se agregan dos fases que el plan anterior no cubría: **RAG/contexto avanzado** y **de proyecto a producto**, que son justo las que conectan con tu objetivo de que esto se convierta en una idea de negocio.

## Nota sobre el orden

Las fases están numeradas de forma secuencial por claridad, pero MCP (Fase 3) y Arquitectura de agentes (Fase 4) están pensadas para avanzar en paralelo: las herramientas MCP no tienen sentido sin un agente que las use con criterio, y el agente no es completo sin herramientas reales que llamar. Trátalas como un mismo bloque de trabajo si lo prefieres.