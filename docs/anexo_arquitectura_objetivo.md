# Anexo A — Arquitectura objetivo industrializada

> **Estado:** propuesta de diseño. Este anexo no describe el sistema actual, sino el destino al que se
> converge de forma incremental a lo largo de las fases 0–8 ya definidas en el roadmap.
> **Alcance:** empaquetado, configuración, observabilidad, CI/CD, containerización, estrategia de agentes,
> memoria, RAG, seguridad, testing y multi-tenancy.
> **Regla de oro:** cada cambio debe dejar el sistema funcional, respetar la separación
> `domain / application / infrastructure / interfaces`, y no introducir complejidad que no se pueda explicar
> en una sesión de aprendizaje.

## A.0 Cómo leer este anexo: clasificación de propuestas

Cada propuesta no trivial está etiquetada con uno de estos tres niveles. La etiqueta es la parte
importante: dice **si adoptar ahora, si esperar a una fase, o si no adoptar todavía**.

| Etiqueta | Significado | Criterio de adopción |
| --- | --- | --- |
| 🟢 **Higiene inmediata** | Coste bajo (horas), beneficio inmediato, reduce riesgo de errores silenciosos. | Adoptar ya, en Fase 0 o 1. |
| 🟡 **Industrialización esperable** | Coste moderado (días), se justifica porque una fase próxima lo va a necesitar de todos modos. | Adoptar cuando entre la fase que la consume, no antes. |
| 🔴 **Vanguardia opcional** | Coste alto o complejidad conceptual alta. Riesgo real de adopción prematura. | Solo si se cumple el criterio concreto que se indica. Si el criterio no se cumple, **no adoptar** y dejarlo documentado como decisión consciente. |

Principio transversal: **la deuda técnica que produce fallos silenciosos se paga antes que la que produce
fallos ruidosos.** El bug de bridging sync/async de la memoria de sesión (§A.7) es el ejemplo canónico y es
la prioridad número uno de Fase 0.

---

## A.1 Arquitectura de componentes objetivo

```mermaid
graph TB
    subgraph clientes["Clientes"]
        CLI["CLI conversacional"]
        HTTP["Cliente HTTP / futuro frontend"]
        ALEXA["Alexa Skill (Fase 6)"]
        MCPC["Cliente MCP externo<br/>(Claude Desktop, IDE)"]
    end

    subgraph interfaces["interfaces/ — adaptadores de entrada"]
        API["FastAPI app.py<br/>routers + DI + middleware<br/>request-id, handlers, lifespan"]
        CLIA["Adaptador CLI"]
        MCPS["Servidor MCP (FastMCP)<br/>expone tools de tareas"]
        AUTHM["Middleware de auth<br/>(Fase 7)"]
    end

    subgraph application["application/ — casos de uso"]
        ORCH["TaskOrchestrator<br/>decide acción"]
        ROUTER["ProductionIntentRouter<br/>reglas -> LLM pequeño -> clarify"]
        TS["TaskService"]
        MEM["MemoryService (nuevo)<br/>corto + largo plazo"]
        CTX["AgentContext<br/>+ ContextBuilder"]
        GUARD["Guardrails<br/>(Fase 4)"]
    end

    subgraph domain["domain/ — núcleo puro"]
        ENT["Entidades: Task, Session,<br/>MemoryItem, Tenant"]
        PORTS["Ports (Protocols):<br/>TaskRepository, SessionMemoryRepository,<br/>LongTermMemoryRepository, LLMClient,<br/>IntentRouter, Clock, UnitOfWork"]
    end

    subgraph infrastructure["infrastructure/ — adaptadores de salida"]
        MONGOR["Repositorios Mongo (Motor async)"]
        LLMA["Adaptador LLM<br/>AsyncOpenAI + reintentos + presupuesto"]
        MCPT["Implementación de tools MCP"]
        OBS["Observabilidad<br/>structlog + OTel"]
        CFG["Settings (pydantic-settings)"]
        VEC["Adaptador vectorial<br/>(Atlas Vector Search) — condicional"]
    end

    subgraph externo["Infraestructura externa"]
        MDB[("MongoDB<br/>tasks, sessions, memory")]
        OAI["OpenAI API"]
        OTLP["Collector OTLP<br/>(Fase 7)"]
        SEC["Gestor de secretos<br/>(.env -> vault, Fase 7+)"]
    end

    CLI --> CLIA
    HTTP --> API
    ALEXA --> API
    MCPC --> MCPS
    API --> AUTHM
    AUTHM --> ORCH
    CLIA --> ORCH
    MCPS --> TS

    ORCH --> ROUTER
    ORCH --> TS
    ORCH --> MEM
    ORCH --> CTX
    ORCH --> GUARD
    ROUTER --> CTX

    ORCH -.usa ports.-> PORTS
    TS -.usa ports.-> PORTS
    MEM -.usa ports.-> PORTS
    ROUTER -.usa ports.-> PORTS
    PORTS --- ENT

    MONGOR -.implementa.-> PORTS
    LLMA -.implementa.-> PORTS
    VEC -.implementa.-> PORTS

    MONGOR --> MDB
    LLMA --> OAI
    OBS --> OTLP
    CFG --> SEC
    VEC --> MDB

    style domain fill:#f6f6f4,stroke:#333,stroke-width:2px
    style application fill:#f0f4f8,stroke:#333
    style infrastructure fill:#f8f4f0,stroke:#333
    style interfaces fill:#f4f0f8,stroke:#333
```

**Lecturas clave del diagrama**

- `domain/` no importa nada de las otras capas. Sigue siendo la regla estructural que no se negocia.
- Todo lo nuevo entra **como port + adaptador**, nunca como dependencia directa desde `application/`.
  Esto incluye el LLM: hoy el cliente OpenAI se usa de forma síncrona y acoplada; en el diseño objetivo es
  un `LLMClient` (Protocol) con un adaptador `AsyncOpenAI`.
- El servidor MCP es un **adaptador de entrada más**, no un caso de uso. Entra por `interfaces/` y baja a
  `TaskService`, exactamente igual que la API REST. Esa simetría es lo que permite que MCP y REST compartan
  reglas de negocio y validación sin duplicar lógica.
- Los componentes marcados con fase (`AUTHM`, `GUARD`, `OBS`, `VEC`) existen en el diagrama para fijar
  **dónde encajarán**, no para construirlos ya.

---

## A.2 Flujo de datos de una interacción típica

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant I as interfaces/<br/>API o CLI
    participant O as TaskOrchestrator
    participant M as MemoryService
    participant R as IntentRouter
    participant L as LLM (gpt-4o-mini)
    participant T as TaskService / tools MCP
    participant DB as MongoDB

    U->>I: "recuérdame llamar al banco mañana"
    I->>I: request-id + auth (Fase 7)
    I->>O: manejar_mensaje(mensaje, session_id, tenant_id)

    O->>M: cargar_contexto(session_id)
    M->>DB: leer sesión (await, sin bridging)
    DB-->>M: últimos N turnos + resumen
    M-->>O: AgentContext

    O->>R: clasificar(mensaje, contexto)
    R->>R: reglas rápidas (regex / keywords)
    alt regla coincide con confianza alta
        R-->>O: intención + entidades (coste 0, sin LLM)
    else sin coincidencia
        R->>L: clasificación estructurada (JSON schema)
        L-->>R: intención + confianza + entidades
        alt confianza < umbral
            R-->>O: intención = clarify
        else
            R-->>O: intención + entidades
        end
    end

    O->>O: guardrails: validar acción y parámetros (Fase 4)

    alt intención = clarify
        O-->>I: pregunta de desambiguación
    else acción ejecutable
        O->>T: crear_tarea(titulo, fecha, tenant_id)
        T->>DB: insert en tasks (índice por tenant_id)
        DB-->>T: Task persistida
        T-->>O: Task
    end

    O->>M: guardar_turno(session_id, mensaje, respuesta)
    M->>DB: upsert sesión
    O-->>I: respuesta en lenguaje natural
    I-->>U: "Anotado: llamar al banco, mañana."

    note over I,DB: Toda la interacción comparte un trace_id.<br/>Se registran: intención, si usó LLM,<br/>tokens, latencia por tramo y resultado.
```

**Invariantes del flujo**

1. **El camino barato va primero.** Reglas antes que LLM. Cada interacción registra si consumió LLM: es la
   métrica que permite discutir coste con datos y no con intuición.
2. **La baja confianza no adivina, pregunta.** `clarify` es una salida de primera clase, no un fallback
   avergonzado.
3. **La escritura en memoria ocurre después de la acción**, y su fallo se registra explícitamente. Nunca
   `except: pass`.
4. **`tenant_id` viaja por todo el flujo desde el día uno** como campo, aunque hoy valga siempre
   `"default"` (§A.11). Añadirlo después obliga a migrar datos; llevarlo desde ya cuesta un parámetro.

---

## A.3 Empaquetado y gestión de dependencias

**Objetivo:** que el proyecto se instale con un comando, que las dependencias sean explícitas y
reproducibles, y que desaparezcan los hacks de `sys.path`.

### 🟢 Higiene inmediata (Fase 0)

- ✅ **`pyproject.toml` con layout `src/`.** Metadatos y dependencias en un único fichero. Instalación
  editable: `pip install -e ".[dev,llm,mcp]"`. `sys.path` ya no se toca en ningún fichero del repo — se
  eliminó el hack de `interfaces/cli.py` (insertaba la raíz del repo a mano para que el CLI funcionara
  invocado desde su propia carpeta). Faltaron `__init__.py` en cinco paquetes (`assistant_personal/`,
  `infrastructure/mcp/`, `infrastructure/mcp/tools/`, `infrastructure/persistence/`,
  `infrastructure/routers/`) que "funcionaban" hoy solo por namespace packages implícitos (PEP 420) —
  se agregaron para que el auto-discovery de `setuptools` los encuentre de forma estándar.
  Configuración de `ruff`/`mypy` queda pendiente (no es bloqueante para el resto de Fase 0).
- ✅ **Declarar `motor` explícitamente**, y de paso `pydantic-settings` y `structlog` (ver 0.4/0.10). Toda
  dependencia importada en `src/` está declarada.
- ✅ **Separar grupos de dependencias:** base (`fastapi`, `pydantic-settings`, `motor`, `httpx`,
  `structlog`, `python-dotenv`), `[llm]` (`openai`), `[mcp]` (`mcp`), `[dev]` (`pytest`, `pytest-asyncio`).
  `ruff`/`mypy` quedan fuera de `[dev]` por ahora (no estaban en uso en el repo; agregarlos sin
  configurarlos sería ruido).
- **Fijar versiones con rangos conservadores y lockfile** — pendiente (depende de adoptar `uv`, Fase 1).
  **Hallazgo al migrar:** `requirements.txt` tenía dos inconsistencias reales sin detectar —
  `starlette>=0.40.0,<0.47.0` era incompatible con `fastapi==0.115.0` (que en realidad exige
  `starlette<0.39.0,>=0.37.2`), y `pymongo==4.8.0` era incompatible con `motor==3.7.1` (exige
  `pymongo>=4.9,<5.0`, y el entorno ya corría con pymongo 4.17.0 en la práctica). `pip install -r
  requirements.txt` nunca lo detectó porque instala línea por línea sin resolver dependencias de forma
  cruzada; `pip install -e .` con `pyproject.toml` sí lo bloqueó de inmediato. Se resolvió dejando que
  `fastapi`/`motor` gestionen esas dos como transitivas, sin pin explícito. `requirements.txt` se eliminó
  (duplicaba `pyproject.toml` y fue la causa raíz del drift).

### 🟡 Industrialización esperable (Fase 1)

- **Adoptar `uv` como gestor.** Sustituye a pip para resolución e instalación (`uv sync`, `uv run`,
  `uv lock`), genera lockfile determinista y es órdenes de magnitud más rápido en CI. Compatible con
  `pyproject.toml` estándar: si se abandona, se vuelve a pip sin reescribir nada. Es la elección
  recomendada frente a Poetry, que impone su propio flujo y aporta poco a un proyecto de este tamaño.
- **Versionado semántico + `CHANGELOG.md`.** Con propósito pedagógico: obliga a nombrar qué cambió en cada
  paso.

### Definition of Done

- [x] `git clone && uv sync && uv run pytest` funciona en una máquina limpia (ítem 1.1).
- [x] Ningún fichero del repo manipula `sys.path`.
- [x] `pip check` pasa sin avisos.
- [x] Toda librería importada en `src/` aparece en `pyproject.toml`.
- [x] Lockfile versionado (`uv.lock`, ítem 1.1).

---

## A.4 Configuración y secretos

**Objetivo:** una sola fuente de verdad de configuración, tipada y validada al arrancar; cero secretos en
el repo; fallo temprano y ruidoso ante configuración inválida.

### 🟢 Higiene inmediata (Fase 0)

- **Un único `Settings` con `pydantic-settings`** (`BaseSettings`), instanciado una vez en el `lifespan` de
  FastAPI e inyectado por `Depends`. Elimina los dos mecanismos actuales de carga de entorno: se prohíbe
  `os.getenv` fuera de `infrastructure/config`.
- **Resolver la inconsistencia de nombre de base de datos.** Un único campo `mongo_database` consumido por
  todos los repositorios. El repositorio de memoria de sesión no define su propio default. Este bug hace
  que datos que se creen mirar en una colección vivan en otra: es exactamente la clase de fallo silencioso
  que se paga primero.
- **`.env.example` versionado**, con todas las claves, valores de ejemplo no sensibles y un comentario por
  variable. Es la documentación operativa mínima del proyecto.
- **Rotar la API key de OpenAI expuesta** y confirmar que `.env` está en `.gitignore`. Una clave que
  estuvo en una máquina de desarrollo se considera comprometida por defecto.
- **Validación estricta al arrancar:** tipos, campos obligatorios y `SecretStr` para todo secreto (evita
  que aparezca en logs o en un `repr`). Si falta configuración, el proceso no arranca.

### 🟡 Industrialización esperable (Fase 7)

- **Secretos inyectados por el entorno de despliegue**, no por ficheros. En un despliegue de bajo coste
  (Fly.io, Railway, Render) basta el gestor de secretos de la plataforma.
- **Perfiles de entorno** (`local`, `ci`, `prod`) que solo cambien valores, nunca estructura.

### 🔴 Vanguardia opcional

- **Vault / AWS Secrets Manager con rotación automática.** **Criterio:** adoptar solo cuando exista más de
  un entorno productivo real con datos de terceros, o cuando más de dos personas necesiten acceso
  diferenciado a credenciales. Antes de eso, el gestor de secretos de la plataforma de despliegue cubre el
  caso con una fracción del coste operativo.
- **Feature flags dinámicos.** **Criterio:** solo cuando haya usuarios reales a los que exponer cambios de
  forma gradual. Hasta entonces, un campo booleano en `Settings` es suficiente y más legible.

### Definition of Done

- [ ] `grep -rn "os.getenv" src/` solo devuelve resultados en el módulo de configuración.
- [ ] Arrancar sin una variable obligatoria produce un error claro que la nombra.
- [x] `.env.example` cubre el 100 % de los campos de `Settings` (`mongo_uri`, `mongo_db_name`,
      `openai_api_key`, `openai_model`, `llm_provider`, `ollama_base_url`, `ollama_model`), con un comentario por variable.
- [ ] Ningún secreto aparece en logs ni en respuestas de error (test que lo verifique).
- [ ] Un único nombre de base de datos en todo el código, verificado por test.

---

## A.5 Observabilidad

**Objetivo:** poder responder, sobre cualquier interacción, qué intención se detectó, si se usó LLM, cuánto
costó y dónde se fue el tiempo. En un sistema con LLM esto no es lujo operativo: es el instrumento de
diagnóstico principal, porque los fallos son probabilísticos y no reproducibles a mano.

### 🟢 Higiene inmediata (Fase 0–1)

- ✅ **Eliminar todos los `print`.** Logging estructurado en JSON con `structlog`, un solo configurador en
  `infrastructure/observabilidad/logging.py` (`configure_logging`/`get_logger`, se autoconfigura al
  importarse). Reemplazados los dos `print` usados como diagnóstico (`client.py`: fallo de conexión a
  Mongo; `app.py`: evento de auditoría de creación de tarea). Los `print` de `interfaces/cli.py` se dejaron
  intactos a propósito: son la salida real del producto (lo que el usuario lee en la terminal), no logging.
- ✅ **Propagar el `request_id` existente** a todos los logs de la petición vía context vars. Se consolidó
  además el middleware duplicado que existía (`RequestIdMiddleware` + `add_request_id_header` hacían lo
  mismo, generando dos UUIDs independientes — se dejó solo uno) y se agregó
  `structlog.contextvars.bind_contextvars(request_id=...)`/`clear_contextvars()` en su `dispatch`, así que
  cualquier log emitido durante esa petición, en cualquier módulo, incluye `request_id` sin pasarlo a mano.
- **Campos mínimos por interacción conversacional:** `request_id`, `session_id`, `tenant_id`, `intencion`,
  `confianza`, `uso_llm` (bool), `modelo`, `tokens_entrada`, `tokens_salida`, `latencia_ms_total`,
  `latencia_ms_llm`, `resultado`. Con estos doce campos ya se puede calcular coste por interacción y tasa
  de `clarify` sin instrumentación adicional. **Pendiente** — el logging estructurado ya existe pero
  ninguna interacción emite todavía estos campos (depende del router/orquestador, Fase 2+).
- **Nunca registrar contenido sensible del usuario por defecto.** Pendiente de verificar con un test
  explícito (mismo pendiente que `SecretStr`, ver §A.11).

### 🟡 Industrialización esperable (Fase 7, adelantable a Fase 4)

- **OpenTelemetry con tracing distribuido.** Instrumentación automática de FastAPI y Motor, más spans
  manuales en los tramos que importan: `router.clasificar`, `llm.completar`, `orquestador.ejecutar`,
  `memoria.cargar`. Exportar por OTLP a un backend gratuito o autoalojado (Jaeger en local, Grafana Tempo
  o Langfuse en cloud).
- **Métricas** (contadores e histogramas): interacciones por intención, ratio de resolución por reglas vs
  LLM, latencia p50/p95 por tramo, tokens acumulados por día, errores por tipo.
- **Nota de secuencia:** si Fase 4 (agentes) llega antes que Fase 7, **adelantar el tracing a Fase 4**.
  Depurar un agente con múltiples saltos sin traces es la forma más rápida de perder días.

### 🔴 Vanguardia opcional

- **Plataforma de observabilidad específica de LLM** (Langfuse, Phoenix) con replay de prompts y
  anotación humana. **Criterio:** adoptar cuando el golden dataset del router (§A.10) supere ~200 casos o
  cuando haya más de un prompt en producción cuya calidad haya que comparar entre versiones. Antes de eso,
  logs estructurados + un script de análisis cubren el caso.
- **SLOs con alerting.** **Criterio:** solo con usuarios externos y alguien de guardia. Un SLO sin nadie
  que reaccione es decoración.

### Definition of Done

- [x] Cero `print` usados como logging en `src/` (los de `interfaces/cli.py` son salida del producto, no
      diagnóstico — ver nota arriba).
- [x] Todo log de una petición comparte `request_id` (contextvars en `RequestIdMiddleware`).
- [ ] Existe una consulta o script que devuelve coste estimado y tasa de `clarify` del último día.
- [ ] Un test verifica que los secretos y los prompts no se registran con la configuración por defecto.

---

## A.6 CI/CD con GitHub Actions

**Objetivo:** que ningún cambio que rompa formato, tipos, tests o la calidad del router llegue a `main`.
En un proyecto educativo la CI tiene un valor extra: convierte los principios en verificaciones automáticas
en vez de recordatorios.

### Pipeline objetivo

```mermaid
graph LR
    PR["Pull request"] --> LINT["ruff format --check<br/>ruff check"]
    PR --> TYPE["mypy --strict en domain/<br/>y application/"]
    PR --> UNIT["pytest unit<br/>cobertura mínima"]
    LINT --> INT
    TYPE --> INT
    UNIT --> INT["pytest integration<br/>service container Mongo"]
    INT --> SEC["pip-audit + gitleaks"]
    SEC --> EVAL["Evaluación del router<br/>golden dataset"]
    EVAL --> MERGE["Merge a main"]
    MERGE --> BUILD["Build imagen Docker<br/>(Fase 7)"]
    BUILD --> DEPLOY["Deploy a staging<br/>(Fase 7)"]
```

### 🟢 Higiene inmediata (Fase 0–1)

- **Job `calidad`:** `ruff format --check`, `ruff check`, `mypy` en modo estricto sobre `domain/` y
  `application/` (gradual en el resto: exigir estricto en todo el repo de golpe genera cientos de errores
  y se abandona).
- **Job `tests`:** unitarios con umbral de cobertura (empezar en el valor actual y subirlo, nunca bajarlo).
- **Matriz Python 3.10 y 3.12** para detectar dependencias de versión temprano.
- **`gitleaks`** en cada PR. Barato, y este proyecto ya tuvo un incidente de clave expuesta.
- **Caché de `uv`** en CI: reduce el tiempo de pipeline a segundos.

### 🟡 Industrialización esperable (Fase 1–4)

- **Job `integration` con Mongo real** como *service container* de GitHub Actions (§A.10).
- **Job `eval-router`** — la pieza más específica de este proyecto y la que más valor aporta:
  1. Ejecuta el router sobre el golden dataset versionado (`tests/eval/golden_router.jsonl`).
  2. Calcula accuracy global, accuracy por intención, tasa de `clarify` y coste en tokens.
  3. Compara contra los umbrales declarados en `tests/eval/umbrales.yaml`.
  4. **Falla el PR si la accuracy cae**; publica una tabla comparativa como comentario.
  5. Se ejecuta con `gpt-4o-mini` real solo en PRs con etiqueta `evaluar-router` o en `main` (para no
     pagar LLM en cada push); en el resto usa un cliente grabado tipo VCR.
- **`pip-audit`** para vulnerabilidades de dependencias.

### 🔴 Vanguardia opcional

- **Despliegue continuo automático a producción.** **Criterio:** solo cuando existan integration tests y
  el job de evaluación sea fiable. Hasta entonces, deploy manual con un botón (`workflow_dispatch`).
- **Entornos efímeros por PR.** **Criterio:** solo si hay revisores no técnicos que necesiten probar
  cambios. En un proyecto de una persona es coste puro.

### Definition of Done

- [ ] Un PR con error de formato, de tipos o test roto no se puede mergear.
- [ ] El pipeline de PR tarda menos de 3 minutos en la ruta rápida.
- [x] `eval-router` produce un informe legible y bloquea regresiones de accuracy (ítem 2.4).
- [ ] `main` está protegida y exige los checks anteriores.

---

## A.7 Containerización *(opcional — evaluar en Fase 7)*

**Objetivo:** entorno de desarrollo reproducible y artefacto de despliegue único.
**Trade-off honesto:** hasta Fase 7 el proyecto puede vivir perfectamente con `uv sync` y un Mongo local o
un cluster gratuito de Atlas. Docker añade una capa de conceptos (imágenes, redes, volúmenes) que compite
por atención con los objetivos de aprendizaje de las fases 1–6.

**Excepción recomendada:** un `docker-compose.yml` mínimo *solo con Mongo* (sin la aplicación) es 🟢
higiene inmediata útil desde Fase 1. Da un Mongo desechable para integration tests locales, cuesta diez
líneas y no obliga a containerizar la aplicación.

### 🟡 Industrialización esperable (Fase 7)

- **`Dockerfile` multi-stage:** stage `builder` con `uv` que resuelve dependencias en un venv, stage
  `runtime` sobre `python:3.12-slim` que copia solo el venv y `src/`. Usuario no root, `HEALTHCHECK`
  apuntando a `/health`, sin herramientas de build en la imagen final. Objetivo: imagen < 200 MB.
- **`docker-compose.yml` completo** (`api`, `mongo`, opcionalmente `collector` OTLP) con perfiles para
  levantar solo lo necesario.
- **`.dockerignore`** que excluya `.env`, `.git`, tests y caché.

### 🔴 Vanguardia opcional

- **Kubernetes / Helm.** **Criterio:** solo con múltiples servicios que escalen de forma independiente y
  tráfico que lo justifique. Para un servicio FastAPI, una plataforma PaaS es más barata y más simple en
  todos los ejes durante mucho tiempo.
- **Distroless / imágenes multi-arch.** **Criterio:** cuando haya un requisito real de superficie de
  ataque mínima o de despliegue en ARM.

### Definition of Done

- [x] `docker compose up mongo` deja un Mongo listo para integration tests locales. Verificado de punta a
      punta con Docker Desktop instalado: contenedor `assistant_personal_mongo` arriba y `(healthy)`, y un
      ciclo real de escritura/lectura con `motor` confirmado (`tests/test_session_memory_integration.py`,
      ítem 0.9). `docker compose down` deja el volumen (`personal_assistant_agent_mongo_data`) sin borrar
      entre sesiones.
      **Hallazgo durante la verificación:** el mapeo original a `27017:27017` daba un falso positivo en
      esta máquina — hay un MongoDB nativo corriendo como servicio de Windows en ese mismo puerto, así que
      un test contra `localhost:27017` seguía "pasando" incluso con el contenedor apagado, porque hablaba
      con el servicio nativo sin que nadie lo notara. Se remapeó a `27018:27017` para que el puerto del
      host sea inequívocamente el del contenedor desechable, nunca el de un Mongo que ya tengas instalado
      localmente.
- [ ] (Fase 7) `docker build` produce una imagen que arranca solo con variables de entorno.
- [ ] (Fase 7) La imagen no contiene secretos ni dependencias de desarrollo.

---

## A.8 Estrategia de agentes

### Diagnóstico del patrón actual

El diseño actual — `ProductionIntentRouter` (reglas → LLM pequeño → `clarify`) seguido de
`TaskOrchestrator` — no es una limitación, es una decisión buena y a contracorriente de la moda:

- **Coste y latencia bajo control.** Las reglas resuelven gratis los casos frecuentes; el LLM pequeño solo
  entra cuando hace falta.
- **Comportamiento predecible y testeable.** El router es una función clasificadora con entrada y salida
  acotadas: se puede evaluar con un dataset (§A.10). Un agente que decide libremente qué tool llamar es
  mucho más difícil de evaluar.
- **Excelente para enseñar.** Cada decisión del sistema es inspeccionable y explicable.
- **`clarify` como salida explícita** es una práctica que muchos sistemas en producción no tienen.

**Recomendación: mantener orchestrator + router y profundizar en él durante las fases 2–4.** No migrar
todavía.

### Comparativa de alternativas

| Patrón | Ventaja principal | Coste real | Veredicto |
| --- | --- | --- | --- |
| **Router + orquestador (actual)** | Predecible, barato, evaluable, pedagógico | Requiere código explícito por intención | 🟢 **Mantener y profundizar** (Fases 2–4) |
| **Single-agent-with-tools** (el LLM elige la tool vía MCP) | Menos código de routing; absorbe intenciones nuevas sin tocar código | Coste por llamada más alto, latencia mayor, comportamiento menos predecible, requiere guardrails desde el día uno | 🟡 **Añadir como fallback**, no como sustituto |
| **State graph (LangGraph)** | Estados y transiciones explícitos, checkpointing, flujos multi-turno complejos | Framework grande, opinionado, con su propio modelo mental; oscurece la arquitectura hexagonal que el proyecto quiere enseñar | 🔴 **Vanguardia opcional** — criterio abajo |

### Evolución recomendada por fases

**Fase 2 — Ingeniería de prompts y salidas** 🟢
Formalizar el contrato del router: salida estructurada validada con Pydantic (structured outputs / JSON
schema), no parsing de texto libre. Definir política explícita ante salida inválida: un reintento con el
error como contexto, luego `clarify`. Versionar los prompts como ficheros con identificador, para poder
correlacionar métricas con versión de prompt.

**Fase 3 — MCP como capa de tools canónica** 🟢
Que las tools MCP sean la **única** forma de ejecutar acciones, tanto para el orquestador como para un
cliente MCP externo. Esto elimina la duplicación de reglas de negocio y es la precondición técnica de
cualquier migración futura de patrón de agente: si las tools están bien definidas, cambiar quién las
invoca es un cambio local.

**Fase 4 — Patrón híbrido: router primero, agente como fallback** 🟡
La evolución de mejor relación coste/beneficio:

```mermaid
graph TD
    MSG["Mensaje de usuario"] --> RULES["Reglas rápidas"]
    RULES -->|coincide| EXEC["Ejecutar tool MCP"]
    RULES -->|no coincide| CLS["LLM clasificador pequeño"]
    CLS -->|confianza alta, 1 acción| EXEC
    CLS -->|confianza media| AGENT["Agente con tools MCP<br/>presupuesto máx. N pasos"]
    CLS -->|multi_task: 2+ acciones| AGENT
    CLS -->|confianza baja| CLAR["clarify: preguntar"]
    AGENT --> GUARD["Guardrails:<br/>whitelist de tools,<br/>límite de pasos,<br/>confirmación de escrituras"]
    GUARD --> EXEC
    AGENT -->|excede presupuesto| CLAR
    EXEC --> RESP["Respuesta en lenguaje natural"]
    CLAR --> RESP
```

`multi_task` es una ruta más del clasificador (mismo contrato de `IntentClassification`, no un esquema
paralelo): el mensaje pide 2+ acciones de dominio distintas. Hoy (ítem 2.8) esa detección ya existe pero
degrada a `clarify` porque no hay quién ejecute varias acciones en un turno; con el agente de 4.3 disponible,
`multi_task` deja de ser un callejón sin salida — el router entrega la intención completa y el agente la
descompone en llamadas MCP secuenciales, con los mismos guardrails que cualquier otro camino del agente.

Así el 90 % del tráfico sigue por la ruta barata y determinista, y solo los casos genuinamente ambiguos o
multi-paso pagan un agente. Guardrails obligatorios: whitelist de tools por rol, límite duro de pasos,
confirmación humana para operaciones destructivas, timeout y presupuesto de tokens por interacción.

**Criterio concreto para migrar a un state graph (LangGraph o equivalente):** adoptar **solo si se cumplen
al menos dos** de estas condiciones, medidas con datos y no por intuición:

1. Existen ≥ 3 flujos que requieren más de 2 turnos con estado intermedio (p. ej. planificar una semana
   completa negociando prioridades).
2. Se necesita persistir y reanudar ejecuciones a medias (human-in-the-loop diferido, aprobaciones).
3. El código de orquestación supera ~500 líneas de control de flujo condicional y las modificaciones
   empiezan a romper casos existentes de forma recurrente.
4. Hacen falta especialistas paralelos con agregación de resultados.

Si no se cumplen, el framework añade dependencia y complejidad conceptual sin resolver un problema real.
Mitigación de riesgo mientras se decide: mantener la orquestación detrás de un port de `domain/`, de modo
que un motor de grafo sería un adaptador más y no una reescritura.

### Definition of Done (Fase 4)

- [x] El router devuelve un objeto Pydantic validado; una salida inválida nunca propaga a la ejecución
      (ítem 2.1).
- [x] Los prompts están versionados y las métricas se pueden filtrar por versión de prompt (ítem 2.2).
- [ ] Toda acción se ejecuta a través de una tool MCP; no hay caminos alternativos de escritura. Parcial:
      cierto para el camino conversacional (orquestador, ítem 3.1); `app.py` (CRUD estructurado) sigue
      llamando a `TaskService` directo — pendiente decidir si eso es aceptable o si también debe pasar
      por MCP (ver ítem 4.10).
- [ ] El agente de fallback tiene límite de pasos, whitelist de tools y presupuesto de tokens, con test
      que verifica que se respetan.
- [ ] El router puede emitir `multi_task` (2+ acciones en un mensaje) y el agente las ejecuta en secuencia
      vía MCP, en vez de degradar siempre a `clarify` (ítem 4.9).
- [x] Las reglas rápidas solo hacen match en operaciones sin parámetros por interpretar; cualquier filtro
      o dato en lenguaje natural cae al agente, no solo las escrituras (ítem 4.11).
- [ ] Existe un documento de decisión que registra por qué **no** se adoptó un state graph, con los
      criterios anteriores evaluados.

---

## A.9 Estrategia de memoria

Este es el área con el bug más grave del sistema y la que más cambia la percepción de calidad del
asistente. Se separa en tres tipos con ciclos de vida distintos.

| Tipo | Contenido | Almacén | Fase |
| --- | --- | --- | --- |
| **Corto plazo (sesión)** | Últimos N turnos de la conversación, estado de desambiguación | Mongo, TTL de horas/días | 0 (✅ bridging corregido, ver abajo) |
| **Largo plazo (perfil)** | Preferencias, hechos estables ("trabajo hasta las 18h", "prefiero mañanas") | Mongo, persistente | 2 |
| **Episódica / semántica** | Historial largo consultable por significado | Solo si RAG aplica (§A.10) | 5 |

### 🟢 Fase 0 — Corregir el bridging sync/async (prioridad máxima)

El repositorio de memoria de sesión hace bridging sync/async y, dentro del event loop real de FastAPI,
probablemente no persiste y falla en silencio. Es el peor tipo de bug: los tests pasan (todo mockeado), la
API responde 200, y el asistente simplemente no recuerda.

**Estado: corregido.** `MongoSessionRepository` (`session_repository.py`) ya no usa `asyncio.run`/`_resolve_result`;
expone `append_turn_async`, `add_context_item_async` y `get_context_summary_async` con `await` puro sobre
Motor. `ShortTermMemory`/`AgentContext`/`TaskOrchestrator.handle_message_async` consumen estas variantes de
extremo a extremo (dispatcher `_invoke_repository_async`, mismo patrón que `TaskService`). Las variantes
síncronas de `ShortTermMemory`/`AgentContext` se conservan solo para `InMemorySessionRepository`
(CLI/tests), y fallan de forma ruidosa (`AttributeError`) si alguien las invoca con un repositorio async,
en vez de devolver `None` en silencio como antes.

Plan:

1. ~~**Convertir el repositorio a `async` de extremo a extremo.**~~ ✅ Hecho para la memoria de sesión.
   Eliminado `asyncio.run` / `run_until_complete` en `session_repository.py`.
2. **Prohibir el silencio.** Pendiente: los métodos async todavía no registran ni propagan fallos de
   escritura explícitamente (siguen sin `try/except` que oculte errores, pero tampoco hay logging
   estructurado — depende de §A.5, aún no implementado).
3. **Test de integración contra Mongo real.** ✅ Hecho. Además del test async con forma de Motor
   (`tests/test_orchestrator.py`, `tests/test_multi_turn_context.py`), existe
   `tests/test_session_memory_integration.py`: escribe un turno con una instancia de
   `MongoSessionRepository` y lo lee con otra, contra el Mongo real de `docker-compose.yml` (ítem 0.9,
   verificado con Docker Desktop). Se salta automáticamente si el contenedor no está arriba.
4. **Unificar el nombre de base de datos** con el `Settings` central (§A.4) — **pendiente**, no tocado en
   esta corrección. Sigue existiendo el default `"personal_management"` en varios sitios vs.
   `settings.mongo_db_name` (`"sample_mflix"` en `.env`).

**Hallazgo nuevo durante la verificación: corregido.** `infrastructure/persistence/mongo/client.py` creaba
`mongo_connection = MongoConnection()` a nivel de módulo y, si no había loop corriendo en el momento del
import, hacía `asyncio.run(self._ensure_task_indexes())` para crear el índice de `personal_tasks`. Ese
`asyncio.run` abría y cerraba su propio loop, dejando el cliente de Motor ligado a un loop ya cerrado.
Al verificar el fix se descubrió que el problema era más profundo que solo el bootstrap de índices: Motor
liga internamente su cliente (y el executor de hilos que usa) al loop que estaba activo la primera vez que
se ejecutó una operación real. Cualquier reuso del mismo singleton desde un loop distinto — el patrón real
del CLI interactivo, que antes abría un `asyncio.run` por turno — fallaba con
`RuntimeError: Event loop is closed`, reproducido contra Mongo real.

Corrección aplicada:
- `MongoConnection.get_db()` ahora verifica en cada llamada si el loop activo cambió desde la última vez
  que se creó el cliente, y si cambió, lo **recrea** (cerrando el anterior para no filtrar conexiones/hilos)
  en vez de asumir que sigue siendo válido. Con un loop de vida larga (FastAPI/uvicorn) esto no cuesta nada
  extra: el cliente se crea una sola vez, igual que antes.
- El CLI interactivo (`interfaces/cli.py`) dejó de abrir un `asyncio.run` por mensaje; ahora
  `_run_interactive_loop_async` corre dentro de un único `asyncio.run` para toda la sesión, evitando el
  cruce de loops en el caso más común de uso real.
- Test de regresión: `tests/test_mongo_connection_lifecycle.py`, que ejecuta dos operaciones reales contra
  Mongo (vía `.env`) cada una en su propio `asyncio.run`, reproduciendo exactamente la condición que fallaba
  antes. Se salta automáticamente si no hay conectividad a Mongo (no bloquea CI sin Mongo disponible).

### 🟡 Fase 2 — Memoria de largo plazo persistida

Hoy vive solo en memoria de proceso: se pierde en cada reinicio. Diseño objetivo:

- Colección `memoria_larga` con documentos `{tenant_id, usuario_id, clave, valor, confianza, origen,
  creado_en, actualizado_en, ttl?}`.
- **Escritura por extracción explícita, no automática.** Al cierre de una interacción relevante, un paso
  de extracción propone hechos candidatos; solo se persisten los que superan un umbral de confianza.
  Escribir todo lo que el usuario dice envenena el contexto y encarece cada llamada.
- **Lectura por relevancia acotada:** un `ContextBuilder` selecciona un presupuesto fijo de tokens
  (p. ej. máximo 10 hechos) en lugar de volcar toda la memoria en el prompt. Esta es la diferencia entre
  memoria útil y memoria que degrada la calidad.
- **Resumen incremental de sesión** para conversaciones largas: cada N turnos, un LLM pequeño comprime los
  turnos antiguos en un resumen y se descartan los originales del contexto activo.
- **Derecho al olvido desde el diseño:** un endpoint que borre memoria por usuario. Requisito de
  privacidad si el proyecto se productiza (§A.11), y trivial de añadir ahora frente a después.

### 🔴 Vanguardia opcional

- **Memoria vectorial semántica.** Ver §A.10: solo si el volumen y el tipo de dato lo justifican.
- **Grafo de conocimiento del usuario.** **Criterio:** solo si aparecen consultas que requieran relaciones
  multi-salto ("tareas del proyecto en el que trabaja la persona que me escribió el lunes"). Muy poco
  probable en un asistente de tareas.
- **Framework de memoria de terceros (mem0, Zep).** **Criterio:** solo si la gestión propia supera ~400
  líneas y aparecen necesidades de deduplicación y resolución de conflictos entre hechos. Escribirla a
  mano primero tiene valor pedagógico alto y es poco código.

### Definition of Done

- [x] Un test de integración prueba que un turno escrito en una petición se lee en la siguiente.
      `tests/test_session_memory_integration.py` (ítem 0.9), contra el Mongo real de `docker-compose.yml`,
      verificado con Docker Desktop instalado — más el test contra Mongo real del ciclo de vida de la
      conexión (`tests/test_mongo_connection_lifecycle.py`, ítem 0.12).
- [x] No queda bridging sync/async en el camino de ejecución de FastAPI. Corregido en la memoria de sesión
      (`session_repository.py`) y en el bootstrap de conexión (`client.py`: rebind automático del cliente
      Motor si el loop activo cambió, en vez de asumir que el cliente sigue siendo válido).
- [ ] Ningún fallo de memoria se silencia; todos se registran con contexto.
- [x] (Fase 2) La memoria de largo plazo sobrevive a un reinicio, verificado por test — ver ítem
      2.5 y `tests/test_long_term_memory_integration.py`.
- [x] (Fase 2) El contexto enviado al LLM respeta un presupuesto de tokens medible y registrado
      — ver ítem 2.6, `ContextBuilder` y el campo `contexto_tokens` del log estructurado.

---

## A.10 Framework de decisión para RAG

**Postura:** RAG no es una decisión binaria a priori, es la respuesta a un tipo concreto de consulta. Un
gestor de tareas es un dominio **estructurado**: título, fecha, estado, etiquetas. Ese dominio se consulta
mejor con filtros e índices de Mongo que con similitud vectorial, que es más caro, menos exacto y no
garantiza recall completo. "Muéstrame las tareas pendientes de esta semana" debe ser una query, nunca una
búsqueda semántica.

### Árbol de decisión

```mermaid
graph TD
    Q["¿Qué consulta necesito resolver?"] --> A{"¿El dato es estructurado<br/>(campos, fechas, estados)?"}
    A -->|Sí| MQ["Query Mongo con filtros e índices.<br/>NO usar RAG."]
    A -->|No, texto libre y largo| B{"¿Volumen > ~1.000 documentos<br/>o > ~500k tokens?"}
    B -->|No| CTX["Cabe en contexto o con búsqueda de texto.<br/>Usar $text de Mongo.<br/>NO usar RAG vectorial."]
    B -->|Sí| C{"¿Las consultas son semánticas<br/>('algo sobre el viaje')<br/>y no por palabra clave?"}
    C -->|No| TXT["Índice de texto completo<br/>(Atlas Search / $text)."]
    C -->|Sí| D{"¿Un fallo de recall es<br/>tolerable para el usuario?"}
    D -->|No, requiere exactitud| MQ2["Query estructurada + filtros.<br/>RAG no da garantías de completitud."]
    D -->|Sí| RAG["Atlas Vector Search justificado.<br/>Búsqueda híbrida: vectorial + filtros por tenant."]
```

### Criterios objetivos de adopción

Adoptar Atlas Vector Search **solo si se cumplen las cuatro** condiciones:

1. **Tipo de dato:** existe un corpus de texto libre y largo (notas extensas, transcripciones de voz de
   Alexa, documentos adjuntos), no solo campos de tareas.
2. **Volumen:** más de ~1.000 documentos o un corpus que no cabe en la ventana de contexto a un coste
   razonable.
3. **Naturaleza de la consulta:** los usuarios preguntan por significado, no por palabra clave ni por
   filtro. Medible: registrar consultas reales y contar cuántas fallan con búsqueda de texto.
4. **Tolerancia a fallos de recall:** el caso de uso admite que un documento relevante no aparezca. Si se
   necesita exactitud (facturación, cumplimiento), RAG es la herramienta equivocada.

Si se cumplen: **Atlas Vector Search es la elección correcta** — evita introducir una base de datos nueva,
soporta búsqueda híbrida con filtros (imprescindible para aislar por `tenant_id`, §A.11) y el tier
gratuito cubre la fase educativa.

**Precondición de diseño (Fase 1, coste casi nulo):** definir el port
`DocumentSearchRepository` en `domain/` con `buscar(consulta, filtros, limite)`. Primer adaptador: `$text`
de Mongo. Si algún día RAG aplica, se añade un adaptador vectorial sin tocar `application/`. Esto convierte
la decisión de RAG en un cambio local y reversible, que es exactamente el objetivo: **no decidir ahora, pero
quedar preparado para decidir barato.**

### Definition of Done

- [ ] Existe el port de búsqueda con al menos un adaptador no vectorial.
- [ ] Está registrado por escrito qué consultas de usuario fallan con búsqueda de texto (evidencia para la
      decisión de Fase 5).
- [ ] La decisión de Fase 5 se documenta evaluando los cuatro criterios, incluso si la conclusión es "no
      aplica".

---

## A.11 Seguridad

**Situación actual:** sin autenticación, sin autorización, tools MCP sin boundaries, y un incidente previo
de clave expuesta. Aceptable mientras el sistema corra solo en local; bloqueante antes de cualquier
exposición pública, incluida la integración con Alexa (Fase 6).

### 🟢 Higiene inmediata (Fase 0)

- ✅ Rotar la clave de OpenAI; `.env` en `.gitignore`; `gitleaks` en CI (§A.6).
- ✅ `SecretStr` para todo secreto (implementado en `config.py`, ver §A.4/0.4). Falta el test explícito que
  verifique que no aparecen en logs ni en respuestas de error (queda pendiente, es rápido de agregar).
- ✅ **Sanear los mensajes de error hacia el cliente.** `handle_runtime_error` y el nuevo handler catch-all
  (`Exception`) devuelven mensaje genérico + `request_id`, y registran el detalle completo (con traceback)
  vía `logging` — nunca en la respuesta. `handle_value_error`/`handle_http_exception` se dejaron sin tocar
  a propósito: son mensajes de negocio escritos por nosotros, no detalle interno filtrado.
- **Validación estricta de entrada** con Pydantic: longitud máxima de mensaje, tipos, límites en campos de
  texto. Barato y corta abusos triviales. Pendiente.

### 🟡 Industrialización esperable (Fase 6–7)

- **Autenticación de la API.** Recomendación para bajo coste: **API keys con hash para clientes máquina**
  (CLI, Alexa) y **JWT de vida corta** si aparece un frontend con usuarios. Evitar montar un servidor
  OAuth propio; si hacen falta usuarios reales, un proveedor gestionado con tier gratuito
  (Auth0/Clerk/Supabase Auth) es más seguro y más barato que implementarlo.
- **Autorización.** Un `Principal` (`usuario_id`, `tenant_id`, `roles`, `scopes`) creado en `interfaces/` y
  propagado a `application/`. Regla estructural: **todo repositorio filtra por `tenant_id`** y ningún caso
  de uso puede consultar sin él. Se verifica con un test que recorre las firmas de los repositorios.
- **Boundaries de seguridad de las tools MCP** — el punto que más suele descuidarse. Cada tool declara los
  scopes que exige; el servidor MCP valida el `Principal` antes de ejecutar; las tools de escritura y
  borrado exigen scope elevado; toda invocación se audita (`quién`, `qué tool`, `qué parámetros`,
  `resultado`). **Ninguna tool debe aceptar filtros arbitrarios que puedan cruzar tenants:** el
  `tenant_id` se inyecta desde el `Principal`, nunca se acepta como parámetro del LLM. Esta es la mitigación
  concreta contra inyección de prompt: aunque el modelo se deje convencer, no puede pedir datos de otro
  tenant porque no controla ese campo.
- **Rate limiting y presupuesto por tenant** (`slowapi` o límite en el gateway): protege contra abuso y
  contra facturas inesperadas de OpenAI, que en un proyecto personal es el riesgo económico más real.

### 🔴 Vanguardia opcional

- **Guardrails de contenido / detección de inyección de prompt con modelo dedicado.** **Criterio:** solo
  con usuarios no confiables y tools capaces de acciones destructivas o de gasto. Con tools acotadas y
  `tenant_id` inyectado por el servidor, la superficie ya es pequeña.
- **mTLS, WAF, pentesting externo.** **Criterio:** datos de terceros en producción con compromisos
  contractuales.
- **Cifrado a nivel de campo en Mongo.** **Criterio:** categorías especiales de datos personales (salud,
  finanzas) o requisito regulatorio explícito.

### Definition of Done

- [ ] Ningún endpoint muta datos sin autenticación (Fase 7).
- [ ] Toda consulta a Mongo incluye `tenant_id`, verificado por test.
- [ ] Cada tool MCP declara scopes y registra una entrada de auditoría por invocación.
- [ ] `tenant_id` nunca es un parámetro que el LLM pueda fijar.
- [x] Las respuestas de error no contienen stacktraces ni nombres internos (ítem 0.11, Fase 0).

---

## A.12 Testing

**Situación actual:** ~1850 líneas en 12 ficheros, buena cobertura de `application`, router y servicio,
pero **todo mockeado**. Esa es precisamente la razón por la que el bug de memoria de sesión (§A.9) pasa
inadvertido: los mocks confirman que el código llama a lo que espera, no que el dato acabe en Mongo.

**Regla no negociable, agregada tras un incidente real (ítem 0.13):** ningún test de integración toca el
Mongo de `.env` (Atlas, productivo). Todo test contra Mongo real usa el contenedor desechable de
`docker-compose.yml` (`mongodb://localhost:27018`, puerto no estándar para evitar chocar con un Mongo
nativo local), con `tearDown` que limpia lo que escribió. Se encontraron y borraron 7 documentos de
prueba (`"tarea de regresion N"`) que un test de integración había estado escribiendo en el Atlas real
durante varias corridas, porque construía `TaskService()` sin inyectar un repositorio — quedaba conectado
al singleton `mongo_connection`, que lee `Settings` (la URI real). `MongoConnection` ahora acepta
`mongo_uri`/`db_name` explícitos para que un test pueda aislarse sin tocar el `Settings` global.

### Pirámide objetivo

| Nivel | Qué prueba | Dependencias | Fase |
| --- | --- | --- | --- |
| **Unitarios** (base, ya existe) | Lógica de dominio y casos de uso | Todo mockeado, sin I/O | ✅ |
| **Integración** (falta) | Repositorios contra Mongo real, ciclo async completo | Mongo en contenedor | 🟢 Fase 0–1 |
| **Contrato de tools MCP** | Cada tool cumple su esquema declarado y sus boundaries | Mongo real, LLM mockeado | 🟡 Fase 3 |
| **E2E de API** | Flujo completo mensaje → respuesta | `httpx.AsyncClient` + Mongo, LLM grabado | 🟡 Fase 1–2 |
| **Evaluación del router** (falta, crítica) | Calidad de clasificación sobre golden dataset | LLM real o grabado | 🟡 Fase 2, **antes de Fase 4** |

### 🟢 Integration tests reales contra Mongo (Fase 0–1)

- Mongo efímero por `docker compose up mongo` en local y como *service container* en Actions.
- Fixture `pytest-asyncio` que crea una base de datos con nombre aleatorio por sesión de test y la elimina
  al final. Aislamiento real, sin dependencia de estado previo.
- **Cobertura mínima obligatoria:** ciclo completo de tareas (crear, listar, actualizar, completar,
  buscar), escritura y lectura de memoria de sesión entre peticiones distintas, comportamiento de índices
  y filtrado por `tenant_id`.
- Marcados con `@pytest.mark.integration` para poder ejecutar rápido solo los unitarios en desarrollo.

### 🟡 Evaluación del router: golden dataset (Fase 2, bloqueante para Fase 4)

Sin esto, cualquier cambio de prompt o de modelo es un cambio a ciegas. Es el prerrequisito no negociable
antes de trabajar en agentes: no se puede mejorar un router cuya calidad no se mide.

**Construcción del dataset** (`tests/eval/golden_router.jsonl`, versionado en git):

- 100–200 casos escritos a mano, en español y con el registro real de uso (informal, con typos,
  abreviaturas, mezclas de intención).
- Cada caso: `{id, mensaje, intencion_esperada, entidades_esperadas, categoria, notas}`.
- Distribución deliberada: casos fáciles resolubles por reglas, casos que exigen LLM, **casos ambiguos
  cuya respuesta correcta es `clarify`** (los más valiosos), casos adversarios (inyección de prompt,
  mensajes fuera de dominio), y casos multi-intención.
- Crecimiento por incidente: **todo fallo observado en uso real se convierte en un caso nuevo**. Es la
  disciplina que hace que el dataset mejore con el tiempo en vez de fosilizarse.

**Métricas y umbrales** (`tests/eval/umbrales.yaml`): accuracy global ≥ umbral, accuracy por intención
(evita que una intención rara se degrade sin que se note en la media), tasa de `clarify` dentro de una
banda — demasiado baja significa adivinar, demasiado alta significa un asistente inútil —, precisión de
extracción de entidades, coste medio en tokens y % de casos resueltos por reglas (métrica de eficiencia).

**LLM-as-judge** 🟡 — solo donde aporta. Para clasificación de intención no hace falta: la etiqueta correcta
es conocida y la comparación es exacta. Es útil para **evaluar la respuesta final en lenguaje natural**
(¿es correcta, útil, y en español?), donde no hay una única cadena válida. Reglas para que sea fiable:
modelo juez distinto del evaluado, rúbrica explícita con ejemplos, salida estructurada con puntuación y
justificación, y **calibración contra ~30 juicios humanos** antes de confiar en él. Un juez no calibrado
es un generador de números tranquilizadores.

### Definition of Done

- [ ] Existe al menos un integration test por repositorio, contra Mongo real.
- [x] El test de memoria de sesión entre peticiones pasa (cierra el bug de §A.9).
- [x] `golden_router.jsonl` tiene ≥ 100 casos, incluidos ambiguos y adversarios (109, ítem 2.3).
- [x] `eval-router` corre en CI y falla si la accuracy baja de los umbrales (ítem 2.4).
- [ ] Cada fallo observado en uso real se ha añadido como caso al dataset. Pendiente: varios bugs
      reales del ítem 2.10-2.16 (small_talk, confidence null, payload string) no se sumaron al
      golden dataset.
- [ ] Los umbrales están versionados y cada cambio de umbral se justifica en el commit.

---

## A.13 Escalabilidad y multi-tenancy (Fase 8)

**Objetivo:** que el salto de proyecto educativo a producto no exija reescribir el modelo de datos. La
mayor parte del coste de la multi-tenancy se paga si se añade tarde; casi nada si se prepara ahora.

### 🟢 Preparación de coste casi nulo (Fase 1)

- **`tenant_id` en toda entidad y en todo índice desde ahora**, aunque valga siempre `"default"`.
  Retrofitear un discriminador de tenant en datos existentes es una migración con riesgo; llevarlo desde
  el principio es un campo más.
- **Índices compuestos siempre con `tenant_id` primero:** `{tenant_id, estado, fecha_vencimiento}`,
  `{tenant_id, usuario_id}`. Esto determina el rendimiento de todas las consultas futuras.
- **`Principal` propagado por el flujo** (§A.11) para que el filtrado nunca dependa de que el
  desarrollador se acuerde.

### 🟡 Aislamiento de datos (Fase 8)

Estrategia recomendada: **base de datos compartida con `tenant_id` obligatorio**, con la defensa en el
adaptador, no en el caso de uso. El repositorio base inyecta el filtro de tenant en toda consulta; es
imposible construir una query sin él porque el filtro no es responsabilidad de quien llama. Ese es el
patrón que hace el aislamiento estructural en vez de disciplinario.

Escalado del aislamiento según se necesite:

1. **Compartida + filtro obligatorio** (por defecto): coste mínimo, adecuado hasta miles de tenants.
2. **Base de datos por tenant**: solo para clientes enterprise que lo exijan por contrato. Mismo código,
   distinta cadena de conexión resuelta por `tenant_id`.
3. **Infraestructura dedicada**: solo con requisitos de residencia de datos o cumplimiento específico.

### 🟡 Modelo de costos

El coste dominante no es la infraestructura, es el LLM. Diseño:

- **Medir por interacción** desde Fase 1 (§A.5): tokens de entrada y salida, modelo, y si se usó LLM. Sin
  esta métrica no se puede fijar precio.
- **Palancas de reducción, en orden de rentabilidad:** (1) maximizar la resolución por reglas — cada caso
  resuelto sin LLM cuesta cero; (2) caché de clasificaciones para mensajes repetidos; (3) presupuesto de
  tokens de contexto (§A.9) en vez de volcar toda la memoria; (4) modelo más pequeño para clasificar y
  reservar el grande solo para redacción; (5) prompt caching cuando el prefijo del prompt sea estable.
- **Presupuesto y cuota por tenant** con degradación explícita: al agotarse, el sistema funciona en modo
  solo-reglas y lo comunica, en vez de fallar o de generar una factura sorpresa.
- **Escalado de infraestructura:** FastAPI async escala verticalmente muy lejos. Antes de pensar en
  arquitecturas distribuidas: revisar índices de Mongo, activar connection pooling, y mover a tareas de
  fondo lo que no necesite respuesta inmediata (extracción de memoria, resúmenes, embeddings).

### 🟡 Privacidad

- **Minimización:** no almacenar el texto completo de conversaciones más allá de lo necesario; TTL en
  sesiones.
- **Derecho al olvido operativo:** borrado en cascada por `usuario_id` a través de todas las colecciones,
  con test que lo verifique.
- **Contrato con el proveedor de LLM:** documentar qué datos salen del sistema y con qué política de
  retención. Requisito de RGPD si hay usuarios europeos.
- **Anonimización antes del logging** de contenido de usuario, y contenido de usuario desactivado por
  defecto en logs (§A.5).

### 🔴 Vanguardia opcional

- **Sharding de Mongo, colas de mensajes, event sourcing.** **Criterio:** solo con métricas que demuestren
  el cuello de botella. Añadir infraestructura distribuida sin evidencia es la forma más común de matar un
  proyecto pequeño.
- **Facturación por consumo integrada.** **Criterio:** cuando existan clientes que paguen. Antes es
  producto imaginario.

### Definition of Done

- [ ] Toda entidad persistida tiene `tenant_id` y todo índice lo incluye primero.
- [ ] Un test demuestra que es imposible leer datos de otro tenant desde un caso de uso.
- [ ] Se puede calcular el coste de LLM por tenant y por día.
- [ ] El borrado por usuario elimina datos en todas las colecciones, verificado por test.
- [ ] Está documentado qué datos de usuario salen hacia el proveedor de LLM.

---

## A.14 Hoja de ruta de migración incremental

Nada de big-bang. Cada fila deja el sistema funcional y encaja en las fases ya definidas. Las etiquetas
mantienen el significado de §A.0.

### Fase 0 — Consolidación y orden *(en curso)*

Objetivo: **eliminar fallos silenciosos y desbloquear el resto de fases.**

| # | Cambio | Nivel | Área | Estado |
| --- | --- | --- | --- | --- |
| 0.1 | Rotar clave de OpenAI, verificar `.gitignore`, añadir `gitleaks` | 🟢 | §A.11 | ✅ Hecho — `.gitignore` cubre `.env` (nunca se commiteó, verificado en todo el historial); clave rotada en el dashboard de OpenAI; `.github/workflows/gitleaks.yml` escaneando cada push/PR |
| 0.2 | `pyproject.toml` + layout `src/`, instalable, sin `sys.path` | 🟢 | §A.3 | ✅ Hecho — `pip install -e ".[dev,llm,mcp]"`; se agregaron 5 `__init__.py` faltantes y se eliminó el hack de `sys.path` en `cli.py`; `requirements.txt` eliminado (duplicaba `pyproject.toml`) |
| 0.3 | Declarar `motor` y separar grupos de dependencias | 🟢 | §A.3 | ✅ Hecho — `motor`, `pydantic-settings`, `structlog` en dependencias base; `[llm]`/`[mcp]`/`[dev]` como grupos opcionales en `pyproject.toml`. De paso se corrigieron dos conflictos de versiones reales (`starlette` vs `fastapi`, `pymongo` vs `motor`) que `requirements.txt` nunca detectó |
| 0.4 | `Settings` único con `pydantic-settings`; eliminar el segundo mecanismo de entorno | 🟢 | §A.4 | ✅ Hecho — `config.py` reescrito con `pydantic-settings` (`SecretStr` para la API key, falla ruidoso si falta `MONGO_URI`); `openai_llm_client.py` ya no llama `load_dotenv()` ni lee `os.getenv` directo, consume `get_settings()` |
| 0.5 | Unificar el nombre de base de datos | 🟢 | §A.4 | ✅ Hecho — `TaskService`, `MongoTaskRepository`, `build_default_task_repository` y `MongoSessionRepository` ya no hardcodean `"personal_management"`: resuelven `db_name or get_settings().mongo_db_name`. Se corrigió `.env` (`MONGO_DB_NAME` apuntaba a `"sample_mflix"`, un dataset de ejemplo no relacionado — las tareas reales se estaban indexando en la base equivocada) |
| 0.6 | `.env.example` completo | 🟢 | §A.4 | ✅ Hecho — cubre los 7 campos de `Settings`, con un comentario por variable. *(2026-08-18: el barrido previo a Fase 1 detectó un octavo campo, `ollama_api_key`, sin documentar. Al revisarlo se decidió eliminarlo de `Settings` por completo — Ollama en local no valida API key, así que no tiene sentido como variable de configuración — y hardcodear el literal `"ollama"` directamente en `openai_llm_client.py`, que es lo único que el SDK de OpenAI exige para no fallar al construir el cliente)* |
| 0.7 | **Corregir el bridging sync/async de la memoria de sesión** | 🟢 | §A.9 | ✅ Hecho — `MongoSessionRepository` async de extremo a extremo, ver detalle en §A.9 |
| 0.8 | `docker-compose.yml` solo con Mongo, para tests locales | 🟢 | §A.7 | ✅ Hecho — verificado con Docker Desktop: `docker compose up -d mongo` levanta un contenedor `(healthy)`. Mapeado a `27018` en el host, no `27017` (ver hallazgo abajo) |
| 0.9 | Primer integration test: memoria de sesión entre peticiones (prueba 0.7) | 🟢 | §A.12 | ✅ Hecho — `tests/test_session_memory_integration.py`: escribe un turno con una instancia de `MongoSessionRepository` y lo lee con otra, contra el Mongo real de `docker-compose.yml`. Se salta (no falla) si el contenedor no está arriba |
| 0.10 | `structlog` en JSON, eliminar todos los `print` | 🟢 | §A.5 | ✅ Hecho — `infrastructure/observabilidad/logging.py` centraliza la configuración; `client.py`/`app.py` usan `get_logger`; `request_id` propagado por contextvars; de paso se eliminó un middleware duplicado que generaba dos UUIDs distintos por petición |
| 0.11 | Sanear mensajes de error hacia el cliente | 🟢 | §A.11 | ✅ Hecho — `handle_runtime_error` ya no devuelve `str(exc)`, responde un mensaje genérico + `request_id` y registra el detalle completo (con traceback) vía `logging`. Se agregó además un handler catch-all (`Exception`) como red de seguridad para errores no anticipados (antes se propagaban sin `request_id` ni registro). `handle_value_error`/`handle_http_exception` se dejaron igual a propósito: sus mensajes son texto de negocio escrito por nosotros mismos (ej. "El título de la tarea es obligatorio"), no detalle interno |
| 0.12 | *(hallazgo nuevo)* Corregir bridging sync/async en el bootstrap de conexión (`client.py`: cliente Motor rebindeado a un loop cerrado) | 🟢 | §A.9 | ✅ Hecho — `get_db()` rebindea el cliente si el loop activo cambió; CLI interactivo usa un único `asyncio.run` por sesión; test de regresión contra Mongo real en `tests/test_mongo_connection_lifecycle.py` |
| 0.13 | *(hallazgo nuevo)* `tests/test_mongo_connection_lifecycle.py` escribía tareas reales en el **Atlas de producción** (`.env`), no en un Mongo desechable | 🟢 | §A.12 | ✅ Hecho — `MongoConnection` ahora acepta `mongo_uri`/`db_name` explícitos (antes solo leía el `Settings` global), lo que permite construir una conexión aislada. El test se reescribió para usar el Mongo local de `docker-compose.yml` (`assistant_personal_test`) con `tearDown` que limpia sus propios datos. Se detectaron y borraron 7 documentos de basura (`"tarea de regresion N"`) que habían quedado en Atlas de corridas anteriores de este mismo test antes del fix |

**DoD de fase:** clone → `uv sync` → tests (unitarios + integración) en verde en máquina limpia; la memoria
de sesión persiste demostrablemente; ningún `print`; ningún secreto en el repo.

> **Estado real (2026-08-18):** `uv sync` ya es literal (ver 1.1 en Fase 1). Persistencia de memoria,
> ausencia de `print` y ausencia de secretos: verificados ✅. "Tests en verde" tenía una salvedad
> (`test_intent_router`/`test_mcp_server` huérfanos, `test_task_service` roto por un bug sin relación) —
> los dos primeros se resolvieron en el ítem 3.1; `test_task_service` sigue excluido de CI, deuda aparte.

### Fase 1 — Fundamentos técnicos con profundidad real

| # | Cambio | Nivel | Área | Estado |
| --- | --- | --- | --- | --- |
| 1.1 | Adoptar `uv` + lockfile en repo y CI | 🟢 | §A.3 | ✅ Hecho — `uv.lock` generado y versionado; `README.md` actualizado a `uv sync --extra dev --extra llm --extra mcp`; verificado con `uv run python -m unittest discover -s tests` (mismo resultado que con `pip`: 47/50, 3 errores preexistentes sin relación). El único workflow de CI (`gitleaks.yml`) no instala dependencias Python, así que no requirió cambios |
| 1.2 | GitHub Actions: lint + mypy estricto en `domain`/`application` + unitarios | 🟢 | §A.6 | ✅ Hecho — `.github/workflows/ci.yml` (nuevo, usa `uv`): `ruff check .` sobre todo el repo, `mypy --follow-imports=silent` acotado a `domain`/`application`, y `pytest` sobre `tests/`. De paso se corrigieron ~15 líneas reales que violaban `E501` en `src/` (funciones/imports/strings reformateados) y 4 errores reales de `mypy` en `task_service.py` (`no-any-return`, resueltos con `cast` explícito en los puntos donde `_invoke_repository_async` devuelve `Any` a propósito por su despacho dinámico sync/async). Se excluyeron del job `test_intent_router`/`test_mcp_server`/`test_task_service` — los tres bloqueados por el mismo bug preexistente de wiring MCP (ver nota en el DoD de Fase 0), fuera de alcance de este ítem. `app.py` y `tests/*` tienen `per-file-ignores` para `E501` (literales de esquema Pydantic y de fixtures, respectivamente — partirlos no mejora la legibilidad). *(Corrección: el primer run de CI falló porque el runner no tiene `.env` — correcto, nunca se commitea — y `Settings` exige `MONGO_URI`. Se agregaron `MONGO_URI`/`MONGO_DB_NAME`/`OPENAI_API_KEY`/`OPENAI_MODEL` dummy como `env:` del job; verificado localmente renombrando `.env` temporalmente y reproduciendo el mismo passthrough de variables que usa el workflow: 44/44 en verde)* |
| 1.3 | Job de integración con Mongo como service container | 🟡 | §A.6 | ✅ Hecho — `ci.yml` agrega `services.mongo` (`mongo:7`, mapeado a `27018:27017`, mismo puerto que `docker-compose.yml` en local) con healthcheck. Verificado localmente simulando el mismo escenario (Mongo real en 27018, sin `.env`): los 3 tests que antes se saltaban en CI (`test_session_memory_integration.py` x2, `test_mongo_connection_lifecycle.py`) ahora corren de verdad — 47/47 en verde, 0 skips |
| 1.4 | Integration tests para todos los repositorios | 🟢 | §A.12 | ✅ Hecho — `tests/test_mongo_task_repository_integration.py` (nuevo): ciclo completo de `MongoTaskRepository` (crear → leer → listar → actualizar → completar → verificar `task_history` → borrado lógico → confirmar que el borrado no elimina el documento físico) contra el Mongo local desechable, con una instancia de repositorio distinta por paso (mismo patrón que `test_session_memory_integration.py`). Cierra la asimetría: `MongoSessionRepository` ya tenía cobertura directa desde Fase 0, `MongoTaskRepository` solo tenía cobertura indirecta vía el orquestador (y solo para `create_task`). |
| 1.5 | `request_id` propagado a todos los logs + 12 campos por interacción | 🟢 | §A.5 | ✅ Hecho — `TaskOrchestrator._handle_message` emite un log `interaccion_completada` en cada camino de retorno (guardrail de mensaje vacío, `clarify`, `small_talk`, `ask_knowledge_base`, éxito, error de negocio) con los 12 campos de §A.5: `request_id` (nuevo por turno, vía `structlog.contextvars`), `session_id`, `tenant_id` (fijo en `"default"` hasta 1.7), `intencion`, `confianza`, `uso_llm`, `modelo`, `tokens_entrada`, `tokens_salida`, `latencia_ms_total`, `latencia_ms_llm`, `resultado`. `_OpenAITextClient._invoke_model` captura `modelo`/tokens/latencia reales de la respuesta de OpenAI (`usage.input_tokens`/`output_tokens` en Responses API, `usage.prompt_tokens`/`completion_tokens` en Chat Completions) en `self.last_call_metadata`; `ProductionIntentRouter` lo expone como `last_llm_metadata` después de cada `route()`. De paso se migró `hybrid_router.py` de `logging` estándar a `structlog` (inconsistencia que quedó de antes de 0.10). Verificado con un smoke test manual: log JSON con los 12 campos poblados correctamente; suite 48/48 en verde, `ruff`/`mypy` limpios |
| 1.6 | Port `LLMClient` + adaptador `AsyncOpenAI` (resuelve la inconsistencia sync/async) | 🟢 | §A.1 | ✅ Hecho — `domain/repositories/llm_client.py` (nuevo): port `LLMClient` async (`classify_intent`, `answer_general_knowledge`, `extract_profile_facts`). `openai_llm_client.py` migrado de `OpenAI` a `AsyncOpenAI`; las tres subclases y `OpenAILLMRouterClient` son async de punta a punta; `_invoke_model` sigue capturando `modelo`/tokens/latencia (1.5) pero ahora con `await`. `ProductionIntentRouter.route()`/`extract_profile_facts()` son async — ya no bloquean el event loop durante la llamada de red al LLM. `TaskOrchestrator` usa un helper `_maybe_await` (mismo patrón de despacho que `TaskService._invoke_repository_async`) para soportar tanto el router real (async) como los ~25 dobles de test síncronos existentes sin tener que reescribirlos todos. Sí se reescribieron `test_hybrid_router.py` y `test_openai_llm_client.py` (`IsolatedAsyncioTestCase`, fakes async) porque prueban `ProductionIntentRouter`/`OpenAIIntentClassifier` directamente, sin pasar por el orquestador. Verificado: 48/48 en verde, `ruff`/`mypy` limpios. *(Sin smoke test en vivo contra Ollama: no estaba corriendo localmente en el momento de la verificación — la forma async está cubierta por los fakes, que replican la forma real de `AsyncOpenAI.chat.completions.create` como coroutine)* |
| 1.7 | `tenant_id` en todas las entidades e índices (valor `"default"`) | 🟢 | §A.13 | ✅ Hecho — `Task` (`domain/task_models.py`) tiene `tenant_id: str = "default"`. `MongoTaskRepository`/`MongoSessionRepository` reciben `tenant_id` opcional (fijo en `"default"`), lo aplican en todos los filtros (`_active_task_filter`, `_session_filter`) y lo escriben en `create_task_async`/`_record_history`/`_upsert_session`. Índices compuestos en `client.py`: `personal_tasks` pasa de `{task_id:1}` a `{tenant_id:1, task_id:1}` único; `conversation_sessions` gana su primer índice, `{tenant_id:1, session_id:1}` único (antes no tenía ninguno). `TaskOrchestrator` gana un atributo `tenant_id` real (constructor, default `"default"`) que reemplaza el string mágico que había quedado hardcodeado en el log de 1.5. Verificado contra Mongo real: índices confirmados con `getIndexes()`, índice viejo pre-1.7 (`task_id_1`, sobrevivió a la recreación del contenedor porque el volumen de Docker persiste) detectado y eliminado explícitamente. 48/48 en verde, `ruff`/`mypy` limpios |
| 1.8 | Port `DocumentSearchRepository` con adaptador `$text` | 🟢 | §A.10 | ✅ Hecho — `domain/repositories/document_search_repository.py` (nuevo): port `buscar(consulta, filtros, limite)`. `MongoTextSearchRepository` (nuevo, `infrastructure/persistence/mongo/`) lo implementa con `$text` sobre `title`/`description` de `personal_tasks`, respetando `tenant_id` como cualquier otro filtro. Índice de texto agregado en `client.py._ensure_task_indexes`. `tests/test_mongo_document_search_integration.py` (nuevo) verifica búsqueda real por palabra y aislamiento por tenant contra Mongo real — usa `MongoConnection` (no un cliente crudo) porque `$text` exige que el índice exista antes de consultar, y solo `MongoConnection.get_db()` lo crea. 50/50 en verde, `ruff`/`mypy` limpios. *(Pendiente, no es parte de este ítem: la otra mitad del DoD de §A.10 — "registrar por escrito qué consultas de usuario fallan con búsqueda de texto" — depende de uso real, no de código; queda para cuando haya tráfico real que analizar)* |
| 1.9 | Tests E2E de API con `httpx.AsyncClient` | 🟡 | §A.12 | ✅ Hecho — `tests/test_api_e2e.py` (nuevo): ejercita `app.py` completo por HTTP (`httpx.AsyncClient` + `ASGITransport`, no `TestClient` síncrono) contra Mongo real — ciclo CRUD completo, `X-Request-ID` en cada respuesta, 400/404 con `request_id` en el body. Como `ASGITransport` nunca dispara el `lifespan` de FastAPI, el test sustituye `app.dependency_overrides[get_service]` por un `TaskService` apuntado al Mongo local desechable — si no, `get_service` caería a su fallback (`TaskService()` sin argumentos → Atlas de producción, el mismo incidente de 0.13). Se agregó `[tool.pytest.ini_options] pythonpath = ["."]` a `pyproject.toml`: sin eso, `from app import app` fallaba con `ModuleNotFoundError` bajo pytest (que inserta `tests/` en `sys.path`, no la raíz del repo). **Bug real encontrado y corregido**: `MongoTaskRepository.create_task_async` pasaba el mismo dict a `insert_one` y al valor de retorno; Motor muta ese dict in-place inyectándole `_id` (`ObjectId`), lo que rompía la serialización JSON de FastAPI con un `TypeError` — nunca se había detectado porque el único test que antes ejercitaba esa ruta HTTP completa (`test_task_service.py`) está excluido por el bug de MCP. Corregido pasando una copia a `insert_one`. 56/56 en verde, `ruff`/`mypy` limpios |

**DoD de fase:** CI bloquea PRs defectuosos; todo I/O del camino de FastAPI es async; existen métricas de
coste por interacción.

> **Estado real (2026-08-18):** los 9 ítems (1.1–1.9) están cerrados. Clausula por clausula:
> - "CI bloquea PRs defectuosos": ✅ — `ci.yml` corre lint + mypy + tests (con Mongo real) en cada push/PR a cualquier rama.
> - "todo I/O del camino de FastAPI es async": ✅ para lo que `app.py` expone hoy — los endpoints usan `TaskService` async de punta a punta contra Motor. **Salvedad importante**: `app.py` no usa `TaskOrchestrator` en absoluto (solo CRUD directo de tareas); el camino conversacional con LLM (router híbrido, memoria de sesión) hoy solo se ejerce desde el CLI, no desde la API HTTP.
> - "existen métricas de coste por interacción": 🟡 parcial — el log de 12 campos de 1.5 vive en `TaskOrchestrator._log_interaction`. Como `app.py` no usa el orquestador, **la API HTTP hoy no emite esas métricas**; solo las emite el CLI. Cerrar esto de verdad requiere conectar `app.py` al orquestador (fuera de alcance de Fase 1) o instrumentar `TaskService` por separado.
> De paso, 1.9 encontró y corrigió un bug real preexistente (`create_task_async` devolvía un `ObjectId` no serializable) que ningún test anterior había detectado.

### Fase 2 — IA generativa con criterio de ingeniería

| # | Cambio | Nivel | Área | Estado |
| --- | --- | --- | --- | --- |
| 2.1 | Salida estructurada validada con Pydantic en el router; política ante salida inválida | 🟢 | §A.8 | ✅ Hecho — `IntentClassification.model_validate` directo, sin casteo manual. Toda salida inválida del LLM cae en el mismo fallback (`clarify`/`source=fallback`); antes había dos políticas distintas según el tipo de error |
| 2.2 | Prompts versionados como ficheros con identificador | 🟢 | §A.8 | ✅ Hecho — `infrastructure/prompts/router/{id}.prompt.md`, un archivo por prompt con frontmatter semver (`id`, `version`, `description`); historial de versiones vive en git, no en el filesystem |
| 2.3 | **Golden dataset del router (≥100 casos) + umbrales** | 🟢 | §A.12 | ✅ Hecho — `tests/eval/golden_router.jsonl` (109 casos, 5 categorías: regla/llm_facil/llm_ambiguo/adversario/multi_intención) + `tests/eval/umbrales.yaml` (accuracy, tasa de `clarify`, coste de tokens, % resuelto por reglas). Corre solo bajo demanda (`pytest -m eval`), nunca automático — convención explícita para no quemar tokens de LLM en cada run. Sin modo grabación/replay: deuda conocida |
| 2.4 | Job `eval-router` en CI, bloqueante ante regresión | 🟢 | §A.6 | ✅ Hecho — `.github/workflows/eval-router.yml`, separado de `ci.yml`. El trigger no filtra por `paths:` (rompería el required check en PRs que no tocan el router); un step interno con `git diff` decide si vale la pena correr el eval real. Repo pasado a público para que la protección de rama sea efectiva (el plan gratuito no la aplica en privados); `eval-router` es required status check. Bug real encontrado: un salto de línea colado en el secret `OPENAI_API_KEY` rompía el header HTTP — fix con `.strip()` en `config.py` |
| 2.5 | Memoria de largo plazo persistida en Mongo, con extracción explícita | 🟢 | §A.9 | ✅ Hecho — `LongTermMemoryRepository` + `MongoLongTermMemoryRepository` (colección `user_profile_facts`, índice único `{tenant_id, user_id, key}`). `TaskOrchestrator._persist_profile_facts` escribe ahí en vez de en memoria de sesión (bug previo: TTL corto, no sobrevivía al reinicio); hechos con `confidence` bajo `profile_confidence_threshold` (0.7) se descartan |
| 2.6 | `ContextBuilder` con presupuesto de tokens + resumen incremental de sesión | 🟢 | §A.9 | ✅ Hecho — `application/context_builder.py`: presupuesto medible (`token_budget`, ~4 char/token) en vez de conteos fijos arbitrarios, prioriza hechos → resumen → turnos → notas. Resumen incremental cada N turnos vía `OpenAISessionSummarizer`; `contexto_tokens` queda en el log estructurado |
| 2.7 | Reintentos con backoff y timeouts en el adaptador LLM | 🟢 | §A.1 | ✅ Hecho — `AsyncOpenAI` recibe `timeout`/`max_retries` explícitos (`config.py`); el SDK ya reintenta con backoff, no hizo falta bucle propio |
| 2.8 | **Detección de solicitudes multi-intención en el router (`clarify` explícito)** | 🟢 | §A.12 | ✅ Hecho — dos o más acciones distintas en un turno → `clarify` pidiendo que se envíen por separado, en vez de ejecutar una y descartar la otra en silencio (`classify_intent.prompt.md` v1.2.0). Ejecutar ambas de verdad exige rediseñar el schema de salida del LLM — se decidió no hacerlo en Fase 2, queda como ítem 4.7 |
| 2.9 | **Actualizar `openai` para usar la Responses API que el código ya contempla** | 🟡 | §A.1 | Deuda — `openai==1.54.0` no tiene `client.responses`, así que `_invoke_model` siempre cae al branch de `chat.completions` aunque el código ya está preparado para la otra API |
| 2.10 | Agregar `ConversationRoute.SMALL_TALK` | 🟢 | §A.8 | ✅ Hecho — el clasificador no tenía ruta para saludos/presentaciones/despedidas naturales, caían en `clarify` por descarte (`classify_intent.prompt.md` v1.3.0 + branch nuevo en `hybrid_router.route()`) |
| 2.11 | `intent` inventado fuera de `route=orchestrator` | 🟢 | §A.8 | ✅ Hecho — el LLM rellenaba `intent` con valores fuera del enum (ej. `"greeting"`) aunque la ruta no fuera `orchestrator`, y el `ValidationError` resultante tiraba la clasificación a `clarify`. `classify_intent.prompt.md` v1.3.1 aclara que `intent` es `null` fuera de `orchestrator` |
| 2.12 | `confidence: null` + defensa en profundidad con JSON mode | 🟢 | §A.8 | ✅ Hecho — `confidence` es obligatorio y el LLM lo devolvía `null` (`classify_intent.prompt.md` v1.3.2). Además se activó `response_format=json_object` en clasificador y extractor de perfil (no en el responder de conocimiento general, que necesita texto libre) |
| 2.13 | `payload` devuelto como string en vez de objeto | 🟢 | §A.8 | ✅ Hecho — el clasificador generaba la respuesta final él mismo en vez de solo enrutar (ej. `payload: "Tu nombre es Alexis."`). `classify_intent.prompt.md` v1.3.3 aclara que el clasificador nunca contesta |
| 2.14 | `extract_profile_facts` sobre-extraía detalles de tareas como hechos de perfil | 🟢 | §A.9 | ✅ Hecho — 3 de 5 documentos reales en `user_profile_facts` eran detalles puntuales de una tarea (hora, confirmación), no hechos estables, con `confidence≈1.0` sin criterio. `extract_profile_facts.prompt.md` v1.1.0 agrega ejemplos de qué no extraer. |
| 2.15 | Regresión en `eval-router`: `small_talk`/`general_knowledge` permisivos ante manipulación + costo de tokens sobre el umbral | 🟢 | §A.12 | ✅ Hecho — una corrida del golden dataset tras 2.10–2.14 encontró prompt injection y pedidos de datos del sistema cayendo en `small_talk`/`general_knowledge` en vez de `clarify`, y el prompt (denso tras varias iteraciones) superando el costo medio de tokens permitido. `classify_intent.prompt.md` v1.4.0→v1.4.3: sección de seguridad explícita + reestructuración a bullets, con dos regresiones propias detectadas y corregidas en el camino |
| 2.16 | Respuesta de `small_talk` era un texto fijo, no generada | 🟢 | §A.8 | ✅ Hecho — la misma cadena salía sin importar lo que dijera el usuario. Nuevo `OpenAISmallTalkResponder` (texto libre) genera la respuesta por turno; `/help` se queda estático a propósito (es un menú, no charla) |

**DoD de fase:** la calidad del router es medible y se vigila en CI; la memoria de largo plazo sobrevive a
reinicios; el contexto enviado al LLM está acotado y registrado.

**Validado (2026-08-19):** Suites de integración contra Mongo real que
sustentan esta fase: `test_long_term_memory_integration.py`, `test_session_memory_integration.py`,
`test_context_builder.py`. Deuda abierta sin bloquear el DoD: 2.9 (Responses API) y el hueco
de 2.14/2.16 (fallos reales no sumados al golden dataset, ver §A.12 DoD) — ninguno afecta las tres garantías
de arriba. 

### Fase 3 — MCP en profundidad

| # | Cambio | Nivel | Área | Estado |
| --- | --- | --- | --- | --- |
| 3.1 | MCP como única vía de ejecución de acciones; eliminar caminos duplicados | 🟢 | §A.8 | ✅ Hecho — `TaskOrchestrator` (usado por el CLI) llamaba a `TaskService` directo, en paralelo a las tools MCP y a `app.py`: tres caminos distintos a Mongo. Nuevo `McpTaskServiceClient` (cliente MCP real por stdio, `infrastructure/mcp/client.py`) implementa la misma interfaz async que `TaskService` (`list_tasks_async`/`create_task_async`/`complete_task_async`), así que `_dispatch` no cambió — solo el `service` que recibe el orquestador. `cli.py` ahora construye `McpTaskServiceClient()` por defecto en vez de `TaskService()`. Hallazgo real: el SDK de MCP no hereda el entorno del proceso padre por defecto (solo una allowlist de seguridad sin `MONGO_URI`/`OPENAI_API_KEY`) — sin pasar el entorno explícito, el servidor no encontraba `.env`. Verificado E2E real (CLI → orquestador → cliente MCP → subproceso servidor → Mongo local), no solo con tests. `test_intent_router.py`/`test_mcp_server.py` (huérfanos, testeaban un `IntentRouter` y un `actualizar_tarea` que ya no existen) se borraron; reemplazados por `test_mcp_client.py` (unitario, sesión falsa) y `test_mcp_client_integration.py` (protocolo MCP real contra Mongo local). Gap de `delete_task` (preexistente, no una regresión) formalizado como ítem 3.6 |
| 3.2 | Tests de contrato por tool (esquema + comportamiento) | 🟡 | §A.12 | ✅ Hecho — `test_mcp_tools_contract.py` (8 tests, protocolo MCP real por stdio contra Mongo local, no mocks): esquema de las 6 tools vía `list_tools()` (nombres + campos requeridos), comportamiento por tool incluyendo casos borde (`crear_tarea` sin `title`, `actualizar_tarea` sin campos, `buscar_tarea`/`completar_tarea` con `task_id` inexistente, idempotencia de `completar_tarea`) |
| 3.3 | Scopes declarados por tool + auditoría de invocaciones | 🟡 | §A.11 | ✅ Hecho (subconjunto sin auth, ver §A.11) — `TOOL_SCOPES` en `task_tools.py` etiqueta cada tool como `read`/`write` (metadata, sin enforcement todavía: eso depende del `Principal` de Fase 6-7). Cada invocación registra `mcp_tool_invocada`/`mcp_tool_resultado` vía el logger estructurado existente, con el nombre de la tool, el scope y las *claves* de los parámetros recibidos (nunca sus valores, que pueden ser texto libre del usuario) |
| 3.4 | `tenant_id` inyectado por el servidor, nunca parámetro del LLM | 🟢 | §A.11 | ✅ Hecho — ya se cumplía de hecho: `MongoTaskRepository` fija `tenant_id` internamente (`"default"`), ninguna de las 6 tools lo declara como parámetro. Faltaba que estuviera garantizado por test, no solo por inspección. `test_mcp_tools_contract.py` ahora afirma que ninguna tool expone `tenant_id` en su `inputSchema` — verificado que el test realmente detecta la regresión (se probó agregando el parámetro a una tool y confirmando que falla, luego se revirtió) |
| 3.5 | `structuredContent` envuelve bajo `{"result": ...}` cuando el retorno anotado es `dict \| None`, pero no para un `dict` simple — inconsistente entre tools, obliga a cada consumidor a conocer el detalle por tool | 🟡 | §A.12 | ✅ Hecho — en vez de forzar un wrapping uniforme bajo la clave genérica `"result"`, se rediseñó el retorno de las 3 tools afectadas para que siempre sea un objeto con nombres de campo explícitos: `listar_tareas` → `{"tasks": [...]}`, `buscar_tarea`/`actualizar_tarea` → `{"task": {...} \| None}`. `crear_tarea`/`completar_tarea`/`health_check` no cambiaron, ya eran objetos simples. `McpTaskServiceClient.list_tasks_async` ajustado a la nueva clave; `test_mcp_client.py` y `test_mcp_tools_contract.py` actualizados, más una prueba nueva para el comportamiento de `listar_tareas` que no existía |
| 3.6 | `delete_task` sin tool MCP (`eliminar_tarea`) ni rama en `_dispatch` — el intent existe en el enum y el prompt lo enseña al LLM, pero ejecutarlo siempre devuelve el fallback genérico de fallo | 🟢 | §A.8 | ✅ Hecho — nueva tool `eliminar_tarea(task_id)` (auditada, ítem 3.3; retorna `{"task": {...} \| None}`, mismo contrato de 3.5), `McpTaskServiceClient.delete_task_async`, rama `delete_task` en `_dispatch` y en `_format_public_message` (antes caía al dump crudo del resultado). Cobertura: `test_mcp_tools_contract.py` (esquema + éxito + id inexistente) y `test_orchestrator.py` (dispatch end-to-end). Sigue sin resolver `task_reference`→`task_id` a propósito — eso es 3.7 |
| 3.7 | `complete_task`/`delete_task` solo ejecutan con `task_id` exacto; el usuario nunca da ese id (es un alfanumérico largo), siempre da una descripción (`task_reference`) | 🟡 | §A.8 | Bloqueado por 4.3, no es deuda a resolver aquí. Interpretar la descripción y buscarla en Mongo es responsabilidad completa del agente, sin repartirla con el orquestador. El router/clasificador no falla: extrae `task_reference` correctamente y esa es toda su responsabilidad; hoy no hay agente a quien entregársela |
| 3.8 | El logger estructurado escribía a `stdout`, el mismo canal que usa el protocolo JSON-RPC del servidor MCP en modo stdio — cualquier log de una tool corrompía el stream (verificado con lectura cruda del stdout del subproceso, no solo con el cliente MCP, que era tolerante al ruido y lo ocultaba) | 🟢 | §A.8 | ✅ Hecho — hallazgo propio al verificar 3.3 (el primer log real emitido desde dentro del servidor MCP). `logging.py`: `PrintLoggerFactory(file=sys.stdout)` → `sys.stderr`, que es el canal reservado para diagnóstico tanto en MCP-stdio como en la CLI (`stdout` es la salida real del producto). Verificado con lectura cruda de stdout/stderr del subproceso, no solo con el SDK cliente |
| 3.9 | Docstrings insuficientes para un consumidor LLM: no dicen forma de respuesta, comportamiento ante "no encontrado", límite de `listar_tareas` ni valores válidos de `status` | 🟢 | §A.12 | ✅ Hecho — los 7 docstrings de `task_tools.py` ahora documentan forma de retorno, semántica de "no encontrado", el límite de 10 de `listar_tareas` y los valores válidos de `status`. Solo texto, verificado contra el protocolo real (`list_tools()`), sin cambios de comportamiento ni tests |
| 3.10 | Retornos tipados `dict[str, Any]` → `outputSchema` de FastMCP vacío (verificado contra el protocolo); el docstring es el único contrato hoy | 🟡 | §A.12 | ✅ Hecho — modelos Pydantic reales por tool (`Task` del dominio reutilizado, más `ListarTareasResponse`/`TareaResponse`/`CompletarTareaResponse`/`EliminarTareaResponse`/`HealthCheckResponse`). `outputSchema` verificado contra el protocolo: ya trae propiedades, tipos y `required`. De paso: `crear_tarea` filtraba `inserted_id` de Mongo a la respuesta (quitado, no era dato de dominio); `eliminar_tarea` no devuelve una `Task` completa, solo un recibo, tipado aparte |
| 3.11 | `listar_tareas` limita a 10 de forma hardcodeada e invisible, sin filtros — reemplaza al 4.12 (mal ubicado en Fase 4, es trabajo de tools) | 🟡 | §A.11 | ✅ Hecho (parcial, ver 3.12) — `listar_tareas(estado?, limite?)`, propagado por `TaskService`/`MongoTaskRepository`/`McpTaskServiceClient`. `limite` por defecto 20 (antes 10 fijo), techo de 100 en servidor pase lo que se pida. Filtro por fecha separado como 3.12: `Task.dates` es un objeto libre sin clave canónica, filtrar contra eso no sería confiable |
| 3.12 | `Task.dates` no tiene una clave fija (ej. `due_date`) — sin eso, `listar_tareas` no puede filtrar por fecha de forma confiable | 🟡 | §A.11 | ✅ Hecho — también encontrado: `complete_task_async` nunca guardaba cuándo se completó una tarea, ese dato no existía en ningún lado. `Task` gana 3 campos de primer nivel (`str \| None`, formato ISO 8601 normalizado, mismo patrón que `deleted_at`): `created_at` (lo fija el sistema al crear), `due_date` (lo da el usuario, con validador que rechaza cualquier formato no-ISO), `completed_at` (lo fija `complete_task_async`, una sola vez — no se re-estampa en llamadas repetidas, para no romper la idempotencia). Los validadores no interpretan lenguaje natural ("el viernes"): traducir eso a ISO es responsabilidad de quien llama a la tool, documentado en los docstrings de `crear_tarea`/`actualizar_tarea`. Filtrar `listar_tareas` por estos campos queda para cuando haya un caso de uso real que lo pida. `dates` (el dict libre que estos campos reemplazan) se eliminó de `Task`, junto con `steps`/`context_metadata` — ninguno tenía consumidor real ni esquema, y `dates` en particular era el hueco original: `tests/test_task_service.py` (ya excluido de CI, bug ajeno) esperaba justo `dates.created_at`/`due_date`/`completed_at` anidados, nunca implementado |

**DoD de fase:** ninguna acción se puede ejecutar sin pasar por una tool MCP; cada invocación queda
auditada; ninguna tool acepta filtros que cruzen tenants.

### Fase 4 — Arquitectura de agentes

| # | Cambio | Nivel | Área | Estado |
| --- | --- | --- | --- | --- |
| 4.1 | Adelantar tracing OpenTelemetry si no se hizo ya (depurar agentes sin traces es inviable) | 🟡 | §A.5 | |
| 4.2 | Guardrails: whitelist de tools, límite de pasos, presupuesto de tokens, confirmación de escrituras | 🟡 | §A.8 | |
| 4.3 | Agente con tools MCP **como fallback** para confianza media | 🟡 | §A.8 | |
| 4.4 | Port de orquestación en `domain/` (habilita cambiar de motor sin reescribir) | 🟢 | §A.8 | |
| 4.5 | Documento de decisión: evaluar los 4 criterios de state graph y registrar la conclusión | 🟢 | §A.8 | |
| 4.6 | LLM-as-judge calibrado para la respuesta final | 🟡 | §A.12 | |
| 4.7 | Soporte de solicitudes multi-intención: ejecutar varias acciones de dominio en un mismo turno | 🟡 | §A.12 | Mitigado desde Fase 2 (ítem 2.8): 2+ acciones → `clarify` explícito en vez de ejecutar una y descartar la otra. La ejecución real es 4.9, que depende de 4.3 |
| 4.8 | Reordenar responsabilidades de `infrastructure/` mezcladas por la forma orgánica en que creció (router vs. LLM genérico, protocols vs. lógica de reglas) | 🟡 | §A.8 | Deuda anotada, no bug — el disparador natural es cuando arranque 4.3 y el agente necesite el mismo cliente LLM base |
| 4.9 | Router clasifica `multi_task` (2+ acciones en un mensaje) y el agente (4.3) las ejecuta en secuencia vía MCP, en vez de degradar siempre a `clarify` | 🟡 | §A.8 | Diseño: `multi_task` es una ruta más de `IntentClassification` (mismo contrato); el agente de 4.3 la descompone en llamadas MCP secuenciales bajo los guardrails de 4.2. Depende de 4.3 |
| 4.10 | Endpoint conversacional en `app.py` que expone el orquestador (router + agente) con respuesta en lenguaje natural — precondición para cualquier frontend o canal de voz (Alexa, Fase 6) | 🟡 | §A.1 | Hoy `app.py` es CRUD directo sin orquestador ni memoria de sesión (Fase 1). Depende de 4.3 y 4.9. Precondición confirmada con el usuario: ningún canal de cara al usuario se construye antes de esta pieza |
| 4.11 | Regla de decisión explícita router vs. agente (no es lectura vs. escritura): el router solo invoca una tool MCP directo si ya tiene el 100% de lo necesario sin interpretar lenguaje natural; si falta estructurar algo, pasa por el agente | 🟢 | §A.8 | ✅ Hecho — reglas duras (`EXACT_LIST_TASKS_COMMANDS`) ya cumplían por construcción. Gap real en el clasificador LLM: trataba "tareas de hoy"/"esta semana" como `list_tasks` sin filtro, perdiéndolo en silencio. `classify_intent.prompt.md` v1.5.0 agrega: lectura con filtro de fecha/estado en NL → `clarify`, no ejecuta consulta ciega. 3 casos nuevos + 3 corregidos en golden dataset; eval-router 111/112 (ruido preexistente no relacionado, grt-059). `coste_medio_tokens_maximo` 600→650 en `umbrales.yaml`, justificado ahí |

**4.12 (movido):** el trabajo de darle filtros a `listar_tareas` se reubicó como ítem **3.11** —
es mecánico (una tool más completa), no depende de que exista el agente. 4.11 sigue dependiendo de
que 3.11 exista para que las lecturas filtradas puedan ejecutarse una vez el agente decida hacerlo.

**DoD de fase:** el patrón híbrido funciona con la ruta barata cubriendo la mayoría del tráfico; los
guardrails están testeados; la decisión sobre state graph está documentada con criterios, no con
preferencia.

### Fase 5 — RAG y contexto avanzado

| # | Cambio | Nivel | Área |
| --- | --- | --- | --- |
| 5.1 | Evaluar los 4 criterios de §A.10 con datos reales de consultas | 🟢 | §A.10 |
| 5.2 | Si aplica: adaptador Atlas Vector Search sobre el port existente, con filtro por tenant | 🔴 | §A.10 |
| 5.3 | Si aplica: evaluación de recuperación (recall@k) antes de conectarlo al flujo | 🟡 | §A.12 |
| 5.4 | Si no aplica: documentar la decisión negativa y cerrar la fase | 🟢 | §A.10 |

**DoD de fase:** existe una decisión escrita y justificada. **"No aplica" es un resultado válido y
exitoso** de esta fase.

### Fase 6 — Integración con Alexa

| # | Cambio | Nivel | Área |
| --- | --- | --- | --- |
| 6.1 | Adaptador Alexa en `interfaces/`, reutilizando el orquestador sin cambios | 🟢 | §A.1 |
| 6.2 | Autenticación por API key con hash (Alexa es cliente máquina) | 🟡 | §A.11 |
| 6.3 | Rate limiting y presupuesto de LLM (primera exposición pública real) | 🟡 | §A.11 |
| 6.4 | Ajuste de respuestas para canal de voz: más cortas, sin markdown | 🟢 | §A.1 |

**DoD de fase:** Alexa funciona sin duplicar lógica de negocio; ningún endpoint público sin autenticación;
existe límite de gasto.

### Fase 7 — Producción y observabilidad

| # | Cambio | Nivel | Área |
| --- | --- | --- | --- |
| 7.1 | OpenTelemetry completo: spans, métricas, export OTLP | 🟡 | §A.5 |
| 7.2 | Dockerfile multi-stage + compose completo | 🟡 | §A.7 |
| 7.3 | Secretos desde el gestor de la plataforma; retirar `.env` de producción | 🟡 | §A.4 |
| 7.4 | Autorización con `Principal` y filtrado en el adaptador base | 🟡 | §A.11 |
| 7.5 | Deploy a staging automático, a producción manual | 🟡 | §A.6 |
| 7.6 | `pip-audit` en CI y dependencias actualizadas | 🟢 | §A.6 |
| 7.7 | Backups de Mongo y prueba de restauración | 🟢 | §A.13 |

**DoD de fase:** cualquier interacción es trazable de extremo a extremo; el despliegue es reproducible
desde una imagen; un backup se ha restaurado con éxito al menos una vez.

### Fase 8 — De proyecto educativo a idea de negocio

| # | Cambio | Nivel | Área |
| --- | --- | --- | --- |
| 8.1 | Multi-tenancy activa: filtrado obligatorio en el repositorio base | 🟡 | §A.13 |
| 8.2 | Coste de LLM por tenant y por día, con cuotas y degradación a modo solo-reglas | 🟡 | §A.13 |
| 8.3 | Borrado por usuario en cascada + política de retención documentada | 🟡 | §A.13 |
| 8.4 | Autenticación de usuarios con proveedor gestionado, si hay frontend | 🟡 | §A.11 |
| 8.5 | Base por tenant solo si un cliente lo exige por contrato | 🔴 | §A.13 |

**DoD de fase:** el aislamiento entre tenants está probado por test; el coste unitario por tenant es
conocido; la política de privacidad se corresponde con lo que el sistema hace realmente.

---

## A.15 Resumen ejecutivo de decisiones

**Lo que se mantiene sin discusión:** arquitectura hexagonal estricta; router de reglas + LLM pequeño con
`clarify` (es un buen diseño, no una limitación); MCP como capa de tools; FastAPI + Pydantic v2 + MongoDB;
nombres y comentarios en español; cambios pequeños e incrementales.

**Los cinco cambios de mayor impacto, en orden:**

1. **Corregir el bridging sync/async de la memoria de sesión** (Fase 0). ✅ **Hecho** (ver §A.9 y fila 0.7
   de §A.14). Bug de fallo silencioso: el asistente no recordaba y nada avisaba. El hallazgo relacionado en
   el bootstrap de conexión (`client.py`, fila 0.12) también quedó ✅ **hecho**.
2. **`pyproject.toml` + `Settings` único** (Fase 0). ✅ **Hecho** (filas 0.2 y 0.4). Desbloquea CI,
   containerización y despliegue.
3. **Integration tests contra Mongo real** (Fase 0–1). Es la única clase de test que detecta el bug
   anterior y los que vendrán. 🟡 Parcial: hay test async equivalente en forma a Motor para memoria de
   sesión, y ya existe un test contra Mongo real para el ciclo de vida de la conexión
   (`tests/test_mongo_connection_lifecycle.py`); falta un integration test de sesión contra Mongo real en
   contenedor (0.8).
4. **Golden dataset del router** (Fase 2). Prerrequisito no negociable de Fase 4: sin medición no hay
   mejora, solo cambios.
5. **Observabilidad estructurada con métricas de coste** (Fase 1). Convierte discusiones sobre coste y
   latencia en datos.

**Lo que se recomienda explícitamente NO adoptar todavía**, con su criterio de reevaluación:

| Tecnología | Criterio para reevaluar |
| --- | --- |
| LangGraph / state graph | ≥2 de los 4 criterios de §A.8 |
| RAG / Atlas Vector Search | Los 4 criterios de §A.10 |
| Kubernetes | Múltiples servicios con escalado independiente |
| Vault gestionado | >1 entorno productivo o >2 personas con acceso a credenciales |
| Framework de memoria de terceros | Gestión propia >400 líneas con conflictos entre hechos |
| Plataforma de observabilidad de LLM | Golden dataset >200 casos o >1 prompt en producción |

**Aviso sobre el equilibrio pedagógico.** Este anexo describe el destino, no una lista de tareas
simultáneas. Adoptar todo de golpe convertiría un proyecto de aprendizaje en un ejercicio de
configuración de herramientas. El orden propuesto está pensado para que cada incorporación llegue cuando
el proyecto ya tiene el problema que esa herramienta resuelve: así la herramienta se entiende, en vez de
solo copiarse.

---

> **Mantenimiento de este documento.** `docs/arquitectura_y_prd.md` es la única fuente de verdad de
> arquitectura. Cuando una propuesta de este anexo se implemente, debe reflejarse en el cuerpo principal
> del documento y marcarse aquí como adoptada, con la fecha y el commit. Cuando una propuesta 🔴 se evalúe
> y se descarte, registrar la decisión y los criterios evaluados: **una decisión negativa documentada vale
> tanto como una implementación.**
