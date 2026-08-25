# AGENTS.md

## Propósito de este archivo

Este archivo orienta a cualquier agente de IA que trabaje sobre este repositorio. Su objetivo es mantener el proyecto coherente, pedagógico y alineado con la arquitectura propuesta.

## Contexto del proyecto

Este repositorio implementa un asistente personal en Python con una arquitectura modular orientada al aprendizaje. El enfoque principal es demostrar cómo construir un sistema con:

- dominio claro para las tareas,
- servicios de aplicación,
- infraestructura para MongoDB,
- interfaces como API o CLI,
- y una evolución futura hacia agentes, MCP y Alexa.

El proyecto debe priorizar claridad sobre complejidad innecesaria.

## Principios de trabajo

Cuando hagas cambios en este repositorio, sigue estas reglas:

1. Mantén la arquitectura por capas.
   - Domain: modelos y reglas de negocio.
   - Application: casos de uso y servicios.
   - Infrastructure: acceso a bases de datos y servicios externos.
   - Interfaces: API, CLI o futuras interacciones con usuarios.

2. Prioriza el aprendizaje y la legibilidad.
   - Explica los cambios de forma sencilla.
   - Añade comentarios cuando ayuden a entender la lógica.
   - Evita soluciones excesivamente complejas si no aportan valor.

3. Mantén el código bien documentado.
   - Usa docstrings claros.
   - Si un cambio introduce un concepto nuevo, documenta por qué se hizo.

4. Haz cambios pequeños y progresivos.
   - No cambies demasiadas capas a la vez.
   - Mantén el sistema funcional después de cada cambio.

5. Actualiza la documentación cuando cambie el diseño.
   - Para futuras iteraciones, solo deben actualizarse los documentos ubicados en docs/.
   - Los demás documentos de la raíz del proyecto son legado y no deben modificarse salvo instrucción explícita.
   - Si cambias arquitectura, comportamiento o alcance, actualiza:
     - docs/arquitectura_y_prd.md

## Estructura del proyecto

- app.py: punto de entrada principal.
- mongo_mcp_server.py: servidor orientado a exponer capacidades o integraciones.
- multi_agent_system.py: base para trabajar con sistemas multiagente.
- src/assistant_personal/: núcleo del proyecto.
  - domain/: modelos del negocio.
  - application/: servicios de casos de uso.
  - infrastructure/: conexiones y dependencias externas.
  - interfaces/: entradas/salidas del sistema.
- tests/: pruebas unitarias del comportamiento principal.

## Convenciones recomendadas

- Usa nombres claros y explícitos para clases, métodos y variables.
- Prefiere español en nombres y comentarios si el proyecto está escrito en ese idioma.
- Mantén los imports limpios y consistentes.
- Si trabajas con MongoDB, evita mezclar lógica de negocio con acceso a datos directamente.
- Si añades una nueva capacidad al sistema, piensa si debería exponerse como herramienta o servicio para el agente.

## Recomendación para implementar cambios

Antes de modificar código:

1. Comprende el objetivo del cambio.
2. Revisa el contexto del PRD y la arquitectura.
3. Implementa la solución mínima necesaria.
4. Añade o adapta pruebas si aplica.
5. Documenta el cambio en los documentos del proyecto.

## Recomendaciones para pruebas

- Ejecuta las pruebas existentes antes de introducir cambios importantes.
- Si añades una nueva funcionalidad, intenta cubrirla con una prueba simple.
- Mantén los tests comprensibles y orientados a validar comportamiento real.

## Nota para agentes de IA

Este proyecto no es solo un ejercicio técnico; también es un proyecto de aprendizaje. Por eso, cada cambio debe ser:

- claro,
- bien explicado,
- modular,
- y fácil de seguir por otra persona o por otro agente en el futuro.
