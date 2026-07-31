# Arquitectura profesional propuesta para el proyecto

## Objetivo

Convertir el proyecto actual en una arquitectura más cercana a una implementación real de producto, con separación de responsabilidades, facilidad para escalar y claridad pedagógica.

## Estructura propuesta

```text
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
```

## Capas del sistema

### 1. Configuración

Responsable de cargar variables de entorno y centralizar ajustes del sistema.

- Se encarga de leer .env.
- Define valores como URI de MongoDB, modelo OpenAI y comandos de ejecución.

### 2. Dominio

Representa las reglas y entidades del negocio.

- Aquí van modelos como Task.
- Se evitan lógicas de infraestructura en esta capa.

### 3. Aplicación

Contiene los casos de uso.

- Crear una tarea.
- Listar tareas.
- Completar una tarea.
- Consultar tareas por prioridad o estado.

### 4. Infraestructura

Se encarga de integrar con servicios externos.

- MongoDB.
- OpenAI.
- MCP.
- Alexa o APIs externas.

### 5. Interfaces

Es el punto de entrada del sistema.

- CLI.
- API HTTP.
- Integración con Alexa.
- Future UI.

## Cómo esta arquitectura ayuda

- Facilita entender el flujo real de una solución profesional.
- Separa negocio de infraestructura.
- Hace más fácil agregar nuevas funcionalidades.
- Permite escalar sin mezclar todo en un único archivo.

## Siguiente evolución recomendada

### Fase A: consolidar capas

- Añadir repositorios para abstraer MongoDB.
- Separar validación de datos de la lógica de negocio.
- Crear un servicio de tareas más robusto.

### Fase B: introducir una API

- Añadir FastAPI.
- Exponer endpoints para crear y consultar tareas.

### Fase C: integrar agentes y herramientas

- Conectar el servicio de tareas con el agente MCP.
- Añadir un orquestador que decida cuándo usar herramientas.

### Fase D: Alexa

- Crear un endpoint para intents de Alexa.
- Mapear comandos de voz a acciones del sistema.

## Recomendación pedagógica

Aprende el proyecto en este orden:

1. Configuración.
2. Dominio.
3. Casos de uso.
4. Infraestructura.
5. Interfaces.

Así comprenderás cómo se construye una implementación real, no solo un script experimental.
