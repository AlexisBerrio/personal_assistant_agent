import asyncio
import os
import sys
import json
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Cargar variables de entorno del archivo .env de forma manual (reutilizando tu lógica nativa)


def load_dotenv(env_path=".env") -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_dotenv()

# Inicializar cliente OpenAI
openai_client = OpenAI()

# Determinar la ruta exacta del intérprete de Python en el entorno virtual
repo_root = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(repo_root, ".venv", "Scripts", "python.exe")
python_command = venv_python if os.path.exists(venv_python) else sys.executable

server_params = StdioServerParameters(
    command=python_command,
    args=["mongo_mcp_server.py"],
    env={**os.environ}
)

# =====================================================================
# AGENTE ESPECIALISTA (DATA ENGINEER)
# =====================================================================


async def agente_especialista_mongo(session: ClientSession, orden_orquestador: str) -> str:
    """
    Agente Especialista con Skill de Razonamiento Iterativo (Loop ReAct).
    Ejecuta herramientas en cadena hasta resolver la petición.
    """
    print(f"\n[ESPECIALISTA MONGO] Analizando orden: '{orden_orquestador}'")

    mcp_tools = await session.list_tools()
    openai_tools = []
    for tool in mcp_tools.tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database": {"type": "string", "description": "Nombre de la base de datos a consultar (ej: 'sample_mflix' para películas, o 'personal_management' para gestión personal)."},
                        "collection": {"type": "string", "description": "Colección de MongoDB."},
                        "filter_query": {"type": "string", "description": "Query BSON/JSON en string."},
                        "projection": {"type": "string", "description": "Campos a proyectar en string."},
                        "sort_query": {"type": "string", "description": "Diccionario JSON en string para ordenar. Use -1 para descendente y 1 para ascendente. Ej: '{\"awards.nominations\": -1}'"},
                        "limit": {"type": "integer", "description": "Límite de registros."}
                    },
                    "required": ["collection"]
                }
            }
        })

        openai_tools.append({
            "type": "function",
            "function": {
                "name": "aggregate_documents",
                "description": tool.description if tool.name == "aggregate_documents" else "...",
                # Para ahorrar espacio, puedes mapearlo dinámicamente o añadir el parámetro si lo haces manual:
                "properties": {
                            "collection": {"type": "string", "description": "Colección de MongoDB."},
                            "match_query": {"type": "string", "description": "Filtro JSON. Ej: '{\"genres\": \"Action\"}'"},
                            "group_by_field": {"type": "string", "description": "Campo para agrupar. Ej: 'year'"},
                            "avg_field": {"type": "string", "description": "Campo numérico para promediar. Ej: 'imdb.rating'"},
                            "sort_field": {"type": "string", "description": "Campo de ordenamiento. Ej: '_id'"},
                            "sort_order": {"type": "integer", "description": "1 o -1"}
                        },
                "required": ["collection"]
            }
        })

    # Historial de conversación del agente para que recuerde qué herramientas ya usó y qué respondieron
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un ingeniero de datos experto y generalista. Tienes acceso a una base de datos MongoDB a través de herramientas MCP.\n\n"

                "METODOLOGÍA DE TRABAJO OBLIGATORIA (FLUJO SECUENCIAL):\n"
                "0. MAPEO DE ENTORNO: Determina qué base de datos requieres según la naturaleza de la petición. Si el usuario habla de películas, usa la base de datos 'sample_mflix'. Si el usuario habla de sus pendientes, prioridades, tareas, Alexa o su día a día, estás obligado a pasar el parámetro database='personal_management'.\n"
                "1. IDENTIFICACIÓN: Identifica qué colección necesitas usar según la orden del orquestador.\n"
                "2. INSPECCIÓN DE ESQUEMA: Si no conoces la estructura exacta de esa colección o sospechas que hay campos anidados, estás OBLIGADO a ejecutar PRIMERO la herramienta 'inspect_collection_schema'. Analiza el documento de muestra para descubrir los nombres exactos y tipos de las propiedades.\n"
                "3. CONSTRUCCIÓN DE QUERIES: Basándote en la estructura real descubierta, construye tus consultas. No inventes ni alucines nombres de campos.\n\n"

                " REGLAS TÉCNICAS DE EJECUCIÓN:\n"
                "- REGLA DE TOPS/RANKINGS: Si la orden pide un 'Top', el más alto, el más bajo, el más reciente, etc., estás OBLIGADO a usar el parámetro 'sort_query' en 'query_documents'. Pasa un JSON string (ej: '{\"[campo]\": -1}' para descendente). Asegúrate de filtrar los campos que vas a ordenar para evitar nulos o vacíos en el tope usando el operador '$exists' (ej: '{\"awards.nominations\": {\"$exists\": true}}').\n"
                "- REGLA DE ANALÍTICA Y ESTADÍSTICA: Si la orden requiere calcular promedios, sumas, conteos masivos o agrupaciones por categorías, está PROHIBIDO procesar matemática masiva en el LLM o usar 'query_documents' para traer muchos registros. Usa OBLIGATORIAMENTE 'aggregate_documents' pasando el pipeline de MongoDB adecuado para que el motor de la base de datos calcule el resultado.\n\n"

                "RESOLUCIÓN DE CONFLICTOS Y MANEJO DE ESTADOS (SKILLS VITALES):\n"
                "- ESTADO DE ERROR DE SINTAXIS: Si la herramienta te devuelve un estado de 'error' o falla el parseo JSON, analiza el mensaje de error de Python/Mongo, corrige inmediatamente la estructura de los corchetes, llaves o comillas, y vuelve a intentar con la sintaxis corregida.\n"
                "- ESTADO DE RESPUESTA VACÍA (DATO INEXISTENTE): Si la herramienta responde con éxito ('status': 'success') pero los datos devueltos son una lista vacía [], la sintaxis es perfecta pero tus filtros son muy estrictos o incorrectos para el dataset.\n"
                "  Está PROHIBIDO volver a enviar la misma consulta. Debes cambiar inmediatamente tu estrategia en el siguiente paso:\n"
                "  A) Si usaste filtros cualitativos de texto (ej: 'status': 'in_progress' o 'genres': 'action'), recuerda que MongoDB es ESTRICTAMENTE SENSIBLE A MAYÚSCULAS/MINÚSCULAS (Case-Sensitive). Ejecuta inmediatamente 'inspect_collection_schema' para verificar cómo están escritos los valores reales en el documento de muestra (ej: 'In Progress' o 'Action').\n"
                "  B) Si el esquema ya es correcto, entonces amplía los rangos de búsqueda, elimina filtros restrictivos o busca los valores máximos/mínimos reales de los campos para descubrir el límite real de los datos."
                "Puedes iterar llamando herramientas secuencialmente hasta consolidar la realidad del clúster."
            )
        },
        {"role": "user", "content": orden_orquestador}
    ]

    # --- INICIO DE LA SKILL DE ITERACIÓN REFACTURADA ---
    for paso in range(1, 8):
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=openai_tools,
            tool_choice="auto"
        )

        msg = response.choices[0].message

        # Si el agente decide usar una o más herramientas
        if msg.tool_calls:
            # 1. ESENCIAL: Se guarda el mensaje del asistente en el historial una sola vez
            messages.append(msg)

            print(f"\n[ESPECIALISTA MONGO] (Paso {paso}) -> El LLM ha solicitado {len(msg.tool_calls)} operaciones en paralelo:")

            # 2. PROCESAMIENTO MULTI-TOOL: Iteramos sobre TODAS las llamadas generadas en este paso
            for idx, tool_call in enumerate(msg.tool_calls, 1):
                arguments_json = json.loads(tool_call.function.arguments)
                print(f"    └─ [Sub-tarea {idx}]: Llamando a '{tool_call.function.name}' con args: {arguments_json}")

                # Invocación al servidor MCP
                mcp_execution = await session.call_tool(name=tool_call.function.name, arguments=arguments_json)
                raw_data = mcp_execution.content[0].text

                print(f"[DEBUG INFRAESTRUCTURA] Respuesta cruda del servidor MCP para '{tool_call.function.name}': {raw_data}")

                # Anexar cada respuesta individual vinculada a su ID único
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": raw_data
                })

        else:
            # Si el modelo ya no genera tool_calls, significa que consolidó la información
            print(
                f"[ESPECIALISTA MONGO] -> Tarea finalizada con éxito en {paso+1} pasos."
            )
            return msg.content

    return "Se alcanzó el límite de pasos sin consolidar una respuesta."    
# =====================================================================
# AGENTE ORQUESTADOR
# =====================================================================


async def agente_orquestador(peticion_usuario: str):
    """
    Orquestador Inteligente: Clasifica la intención del usuario antes de actuar.
    Decide si la petición requiere infraestructura (MCP) o si se resuelve de forma nativa.
    """
    print(f"\n[ORQUESTADOR] Evaluando petición global: '{peticion_usuario}'")

    # 1. CAPA DE ENRUTAMIENTO (ROUTER)
    prompt_enrutador = (
        f"Analiza la siguiente petición del usuario: '{peticion_usuario}'.\n"
        f"Determina si para responderla se requiere consultar bases de datos de la empresa "
        f"(como películas, teatros, comentarios, usuarios, etc.).\n"
        f"Responde ÚNICAMENTE con una palabra:\n"
        f"- 'DATA' si requiere consultar la base de datos.\n"
        f"- 'NATIVO' si es cultura general, saludos, ayuda general o tareas de redacción."
    )

    decision_res = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_enrutador}],
        temperature=0.0  # Temperatura 0 para máxima consistencia en la clasificación
    )

    ruta = decision_res.choices[0].message.content.strip().upper()
    print(f"[ORQUESTADOR] -> Ruta seleccionada por el clasificador: {ruta}")

    # 2. EJECUCIÓN SEGÚN LA RUTA
    if "DATA" in ruta:
        print(
            "[ORQUESTADOR] -> Iniciando pipeline de datos. Conectando al Servidor MCP...")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                instruccion_a2a = (
                    f"El cliente necesita datos sobre: '{peticion_usuario}'. "
                    f"Usa tus herramientas para extraer la información real."
                )

                informe_tecnico = await agente_especialista_mongo(session, instruccion_a2a)

                # Consolidación final de negocio
                prompt_final = (
                    f"Petición original del usuario: '{peticion_usuario}'\n"
                    f"Informe de datos reales extraído por el especialista: {informe_tecnico}\n\n"
                    f"CONTRATO DE FIDELIDAD ESTRICTA (GUARDRAIL):\n"
                    f"1. Tu objetivo es responder a la petición usando ÚNICAMENTE la evidencia explícita provista en el informe del especialista.\n"
                    f"2. REGLA DE ORO DE INTEGRIDAD: Compara los criterios solicitados por el usuario contra los datos hallados. "
                    f"Si el especialista demuestra mediante sus consultas que NO existen registros exactos para los filtros solicitados, o que los límites de la base de datos no cubren el alcance de la petición, debes declarar abiertamente dicha limitación técnica.\n"
                    f"3. PROHIBICIÓN DE RELLENO (ANTI-PADDING): Está estrictamente prohibido inventar entidades, valores numéricos, categorías o registros que no figuren en el informe técnico para intentar 'complacer' la estructura de la pregunta original.\n"
                    f"4. Si los datos solicitados no existen pero el especialista halló datos adyacentes o históricos relacionados, presenta esos datos reales como el panorama disponible en el sistema."
                )

                conclusion = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Eres un Director de Tecnología (CTO) con rigor analítico extremo. Tu valor principal es la veracidad de los datos. "
                                "Prefieres reportar una limitación del sistema con datos reales antes que presentar un informe estético con datos ficticios. "
                                "Tu respuestas deben ser ejecutivas, directas y 100% fieles al informe técnico."
                            )
                        },
                        {"role": "user", "content": prompt_final}
                    ],
                    temperature=0.0  # Crucial: Forzamos la mínima variabilidad para evitar invenciones creativas
                )
                print(
                    "\n======================================================\n[RESPUESTA (RUTA DATA)]:")
                print(conclusion.choices[0].message.content)
                print("======================================================")

    else:
        print("[ORQUESTADOR] -> Resolviendo de forma nativa (No se requiere MCP).")
        # El Orquestador responde usando el conocimiento base del LLM
        respuesta_nativa = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asistente ejecutivo inteligente y eficiente. Responde de forma directa y concisa."},
                {"role": "user", "content": peticion_usuario}
            ]
        )
        print(
            "\n======================================================\n[RESPUESTA (RUTA NATIVA)]:")
        print(respuesta_nativa.choices[0].message.content)
        print("======================================================")


if __name__ == "__main__":
    user_query = "¿Cuál es la tarea que tengo en progreso con mayor score de prioridad y de qué plataforma proviene?"
    asyncio.run(agente_orquestador(user_query))
