import os
import sys
import json
from datetime import datetime
from typing import Any
from bson import ObjectId, Decimal128, DBRef, Timestamp
from pydantic import BaseModel, Field
from pymongo import MongoClient
from mcp.server.fastmcp import FastMCP


def load_dotenv(env_path=".env") -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

load_dotenv()

# 1. Inicializar FastMCP
server = FastMCP("MongoDB-Atlas-Data-Engineer-Server")

# 2. Configurar la conexión a MongoDB Atlas de forma segura
MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "sample_mflix").strip()
CONNECTION_WARNING = None
CONNECTION_ERROR = None

if not MONGO_URI:
    CONNECTION_WARNING = (
        "La variable de entorno MONGO_URI no está configurada. "
        "El servidor está usando mongodb://localhost:27017/ como fallback. "
        "Si necesitas Atlas, define MONGO_URI antes de iniciar el servidor."
    )
    print(CONNECTION_WARNING, file=sys.stderr)
    MONGO_URI = "mongodb://localhost:27017/"

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
except Exception as e:
    CONNECTION_ERROR = str(e)
    client = None


def _serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal128):
        return str(value)
    if isinstance(value, Timestamp):
        return value.as_datetime().isoformat()
    if isinstance(value, DBRef):
        return {
            "$ref": value.collection,
            "$id": _serialize_value(value.id),
            **({"$db": value.database} if value.database else {}),
        }
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def _serialize_document(document: dict) -> dict:
    return {k: _serialize_value(v) for k, v in document.items()}


def _build_response(payload: dict) -> str:
    if "data" in payload:
        if isinstance(payload["data"], list):
            payload["data"] = [_serialize_document(doc) if isinstance(doc, dict) else doc for doc in payload["data"]]
        elif isinstance(payload["data"], dict):
            payload["data"] = _serialize_document(payload["data"])
    if "sample" in payload and isinstance(payload["sample"], dict):
        payload["sample"] = _serialize_document(payload["sample"])
    if CONNECTION_WARNING:
        payload["warning"] = CONNECTION_WARNING
    return json.dumps(payload, ensure_ascii=False)


def _convert_filter_objectids(obj):
    """Recursively convert _id hex strings inside filter dicts to ObjectId instances.

    Solo convierte claves exactamente llamadas '_id' y estructuras comunes como
    {'_id': 'hex'} o {'_id': {'$in': ['hex1','hex2']}}.
    """
    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            if k == "_id":
                # Direct hex string
                if isinstance(v, str):
                    try:
                        new[k] = ObjectId(v)
                        continue
                    except Exception:
                        pass
                # $in or other operator with list of hex strings
                if isinstance(v, dict):
                    new_v = {}
                    for op, val in v.items():
                        if op == "$in" and isinstance(val, list):
                            converted = []
                            for item in val:
                                if isinstance(item, str):
                                    try:
                                        converted.append(ObjectId(item))
                                        continue
                                    except Exception:
                                        pass
                                converted.append(item)
                            new_v[op] = converted
                        else:
                            new_v[op] = _convert_filter_objectids(val)
                    new[k] = new_v
                    continue
            # recurse normally
            new[k] = _convert_filter_objectids(v)
        return new
    if isinstance(obj, list):
        return [_convert_filter_objectids(i) for i in obj]
    return obj


def _ensure_db_available() -> None:
    if CONNECTION_ERROR:
        raise RuntimeError(
            "MongoDB no está disponible. Comprueba la URI y la DNS de Atlas. "
            f"Detalles: {CONNECTION_ERROR}"
        )
    if client is None:
        raise RuntimeError("MongoDB no está disponible.")
    

# Modifica la función de asegurar disponibilidad para que sea dinámica
def _get_db(db_name: str = MONGO_DB_NAME):
    """Retorna la instancia de la base de datos solicitada de forma dinámica."""
    _ensure_db_available()
    return client[db_name]

# =====================================================================
# HERRAMIENTAS EXPUESTAS AL AGENTE (TOOLS)
# =====================================================================

@server.tool()
def list_collections(database: str = MONGO_DB_NAME) -> str:
    """Retorna una lista con los nombres de todas las colecciones disponibles en la base de datos especificada."""
    try:
        db_instance = _get_db(database)
        collections = db_instance.list_collection_names()
        return _build_response({"status": "success", "collections": collections})
    except Exception as e:
        return _build_response({"status": "error", "message": str(e)})
    

@server.tool()
def query_documents(collection: str, database: str = MONGO_DB_NAME, filter_query: str = "{}", projection: str = "{}", sort_query: str = "{}", limit: int = 5) -> str:
    """
    Realiza búsquedas, filtrados y rankings en el clúster de MongoDB.
    
    Argumentos:
      database: OBLIGATORIO. Elige una de las siguientes bases de datos según el contexto:
                - 'personal_management': Si el usuario pide cosas de su día a día, tareas, Alexa o pendientes.
                - 'sample_mflix': Si el usuario pide analítica de películas, comentarios o cines.
                
      collection: OBLIGATORIO. Elige la colección real según la base de datos elegida:
                - Para 'personal_management', usa OBLIGATORIAMENTE 'personal_tasks'.
                - Para 'sample_mflix', usa 'movies', 'comments', 'users' o 'theaters'.
                
      filter_query: Filtro JSON. 
                ⚠️ REGLA DE ORO DE DATOS: 
                - En 'personal_management.personal_tasks', el campo 'status' es Case-Sensitive y usa mayúsculas: 'In Progress', 'Completed', 'To Do'.
                - En 'sample_mflix.movies', el campo 'genres' es Case-Sensitive: 'Action', 'Drama', etc.
                
      sort_query: JSON string para ordenar. Ej: '{"priority.score": -1}' para mayor prioridad, o '{"imdb.rating": -1}' para mejores películas.
    """
    try:
        db_instance = _get_db(database)
        coll = db_instance[collection]
        
        parsed_filter = json.loads(filter_query)
        parsed_filter = _convert_filter_objectids(parsed_filter)
        parsed_projection = json.loads(projection) if projection else None
        parsed_sort = json.loads(sort_query) if sort_query else {}
        sort_list = [(k, v) for k, v in parsed_sort.items()] if parsed_sort else None
        
        cursor = coll.find(parsed_filter, parsed_projection)
        if sort_list:
            cursor = cursor.sort(sort_list)
        cursor = cursor.limit(limit)
        
        # Al final de tu query_documents en mongo_mcp_server.py
        results = list(cursor)
        
        # Si la consulta da vacía, usamos el diagnóstico resiliente
        if not results:
            total_docs = coll.count_documents({})
            return _build_response({
                "status": "success",
                "message": "Filtros válidos pero no hay registros exactos.",
                "diagnostico": f"La colección tiene {total_docs} documentos.",
                "data": []
            })

        # Si hay datos, utilizamos el constructor de respuesta para serializar correctamente
        return _build_response({"status": "success", "data": results})

    except Exception as e:
        return _build_response({"status": "error", "message": str(e)})



@server.tool()
def insert_document(collection: str, document_json: str, database: str = MONGO_DB_NAME) -> str:
    """Inserta un nuevo documento estructurado (JSON) en la colección especificada."""
    try:
        db_instance = _get_db(database)
        coll = db_instance[collection]
        parsed_doc = json.loads(document_json)
        
        result = coll.insert_one(parsed_doc)
        return _build_response({"status": "success", "inserted_id": str(result.inserted_id)})
    except Exception as e:
        return _build_response({"status": "error", "message": str(e)})
    

@server.tool()
def inspect_collection_schema(collection: str, database: str = MONGO_DB_NAME) -> str:
    """Muestra un documento de ejemplo para deducir el esquema y nombres de campos."""
    try:
        db_instance = _get_db(database)
        coll = db_instance[collection]
        sample = coll.find_one()
        if not sample:
            return _build_response({"status": "success", "message": "Colección vacía."})
        return _build_response({"status": "success", "sample": sample})
    except Exception as e:
        return _build_response({"status": "error", "message": str(e)})
    

@server.tool()
def aggregate_documents(collection: str, database: str = MONGO_DB_NAME, match_query: str = "{}", group_by_field: str = "", avg_field: str = "", sort_field: str = "", sort_order: int = 1) -> str:
    """
    Ejecuta una agregación estructurada en MongoDB (Filtra -> Agrupa y Promedia -> Ordena).
    
    Argumentos:
      collection: Nombre de la colección (ej: 'movies').
      match_query: Filtro JSON en string. Ej: '{"genres": "Action", "year": {"$gte": 2015}}'
      group_by_field: Campo por el cual agrupar. Ej: 'year' (no anteponer $).
      avg_field: Campo del cual calcular el promedio numérico. Ej: 'imdb.rating'.
      sort_field: Campo para ordenar el resultado final. Ej: '_id'.
      sort_order: 1 para ascendente, -1 para descendente.
    """
    try:
        db_instance = _get_db(database)
        coll = db_instance[collection]

        pipeline = []
        if match_query and match_query != "{}":
            pipeline.append({"$match": json.loads(match_query)})
            
        if group_by_field and avg_field:
            pipeline.append({
                "$group": {
                    "_id": f"${group_by_field}",
                    "promedio": {"$avg": f"${avg_field}"}
                }
            })
            
        if sort_field:
            pipeline.append({"$sort": {sort_field: sort_order}})
            
        cursor = coll.aggregate(pipeline)
        results = list(cursor)
        
        if not results:
            total_docs = coll.count_documents({})
            return _build_response({
                "status": "success",
                "message": "La consulta no arrojó registros para esos filtros específicos.",
                "diagnostico_infraestructura": f"La colección '{collection}' en '{database}' está operativa y tiene {total_docs} documentos totales. Ajusta los filtros.",
                "data": []
            })
            
        return _build_response({"status": "success", "data": results})
        
    except Exception as e:
        return _build_response({"status": "error", "message": f"Fallo en la construcción del pipeline: {str(e)}"})

if __name__ == "__main__":
    # Arrancar el servidor bajo protocolo StdIO (Entrada/Salida Estándar)
    server.run()