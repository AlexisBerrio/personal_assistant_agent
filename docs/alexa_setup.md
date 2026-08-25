# Configurar y probar la skill de Alexa

Runbook para levantar el endpoint `/alexa` y conectarlo a una skill real (simulador o
dispositivo Echo). Complementa la Fase 6 de `anexo_arquitectura_objetivo.md` — acá está el
paso a paso operativo, no las decisiones de arquitectura.

## 1. Prueba local, sin Alexa real

Con Mongo local arriba (`docker compose up mongo`) y la API corriendo:

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

En `.env`, desactivá la verificación de firma (no vas a tener certificados reales de Amazon):

```
ALEXA_SIGNATURE_VERIFICATION_ENABLED="false"
```

POST a `http://127.0.0.1:8000/alexa` (Thunder Client, curl, etc.), body:

```json
{
  "session": { "sessionId": "amzn1.echo-api.session.test-1" },
  "request": {
    "type": "IntentRequest",
    "intent": { "name": "MensajeIntent", "slots": { "mensaje": { "name": "mensaje", "value": "qué tareas tengo" } } }
  }
}
```

Otros casos útiles en la misma colección: `LaunchRequest` (sin `intent`) y `SessionEndedRequest`.
Reutilizá el mismo `sessionId` entre requests para probar memoria conversacional entre turnos.

## 2. Exponer el endpoint con HTTPS público

Amazon no acepta HTTP ni certificados autofirmados:

```bash
ngrok http 8000
```

Anotá la URL HTTPS (cambia cada vez que reiniciás ngrok en el plan gratuito). El inspector web
en `http://127.0.0.1:4040` muestra cada request/response entrante — es la primera herramienta
de diagnóstico ante cualquier falla.

## 3. Crear la skill en el Developer Console

[developer.amazon.com/alexa/console/ask](https://developer.amazon.com/alexa/console/ask) →
*Create Skill* → modelo "Custom" → hosting "Provision your own".

### Modelo de interacción (pestaña *Interaction Model* → *JSON Editor*)

```json
{
  "interactionModel": {
    "languageModel": {
      "invocationName": "mi gestor de tareas",
      "intents": [
        { "name": "AMAZON.CancelIntent", "samples": [] },
        { "name": "AMAZON.StopIntent", "samples": [] },
        { "name": "AMAZON.HelpIntent", "samples": [] },
        {
          "name": "MensajeIntent",
          "slots": [{ "name": "mensaje", "type": "AMAZON.SearchQuery" }],
          "samples": [
            "dime {mensaje}",
            "di me {mensaje}",
            "quiero {mensaje}",
            "quiero saber {mensaje}",
            "necesito {mensaje}",
            "necesito saber {mensaje}",
            "por favor {mensaje}",
            "puedes decirme {mensaje}",
            "puedes ayudarme con {mensaje}",
            "ayúdame con {mensaje}",
            "quisiera {mensaje}",
            "me gustaría {mensaje}"
          ]
        }
      ]
    }
  }
}
```

`AMAZON.SearchQuery` es el slot built-in más cercano a dictado libre que admite un intent
custom — Alexa no tiene un tipo de slot totalmente libre. `invocationName` tiene que ser
específico, no genérico (ver Problema 3 abajo).

*Build Model* después de cualquier cambio — el simulador y el dispositivo siguen usando la
versión anterior hasta que lo hagas.

### Endpoint (pestaña *Endpoint*)

HTTPS, URL exacta `https://tu-url-ngrok.ngrok-free.app/alexa` (con el `/alexa` al final —
ver Problema 2), tipo de certificado "trusted certificate authority" (ngrok ya trae uno válido).

## 4. Probar en el simulador (pestaña *Test*, modo "Development")

Con `ALEXA_SIGNATURE_VERIFICATION_ENABLED="true"` en la API (acá sí Amazon firma cada request
de verdad). El panel "JSON Input"/"JSON Output" solo se llena si hacés clic en una burbuja del
historial de conversación — no se actualiza solo.

Cerrar sesión: decir `para`, `cancela`, `detente` o `adiós` (built-in, sin samples propios) —
mapea a `_STOP_SPEECH` en `interfaces/alexa.py`.

## 5. Habilitar en un dispositivo Echo real

1. El Echo tiene que estar en la **misma cuenta de Amazon** que creó la skill.
2. App de Alexa → `Más` → `Skills y Juegos` → buscar el nombre de la skill → `Habilitar` si no
   lo está ya (verla funcionar en el simulador del Developer Console no la habilita en el
   dispositivo).
3. El idioma del dispositivo tiene que coincidir con el locale del modelo (`es-MX`).
4. `uvicorn` y `ngrok` tienen que seguir corriendo — el dispositivo real pega al mismo endpoint.

## Mongo real vs. local

No hay nada que configurar específico de Alexa: el orquestador usa el mismo
`MongoSessionRepository`/`MongoLongTermMemoryRepository` sin importar el caller (`/chat`,
`/alexa`, CLI). A qué Mongo apunta lo determina únicamente `MONGO_URI` en `.env` **al momento
de arrancar `uvicorn`** — cambiarlo con el proceso ya corriendo no tiene efecto hasta reiniciar.

## Problemas conocidos y su fix

**1. "Sample utterance must include a carrier phrase"** — Amazon rechaza un sample que sea solo
`{mensaje}`. Cada sample necesita texto fijo antes o después del slot (`"dime {mensaje}"`, no
`"{mensaje}"`).

**2. Request 404 `{"detail": "Not Found"}`** — el campo *Endpoint* apunta a la URL base de
ngrok sin el sufijo `/alexa`. Corregir y no hace falta rebuild del modelo, solo guardar el
endpoint.

**3. El simulador abre una skill pública distinta con tu frase de invocación** — nombres de
invocación genéricos (`"mi asistente personal"`) colisionan con skills públicas ya habilitadas
en la cuenta; Alexa prioriza resolver hacia una skill pública antes que una en desarrollo ante
ambigüedad. Usar un `invocationName` específico y menos común.

**4. El simulador transcribe "dime" como "di me"** — el input de texto del simulador simula
entrada de voz (pasa por un pipeline tipo ASR), no manda el texto literal al NLU; esa
segmentación es un artefacto de esa simulación. Mitigación: declarar carrier phrases
alternativas (`"di me {mensaje}"`) y preferir frases sin esa ambigüedad al probar
(`"quiero saber..."` en vez de `"dime..."`).

**5. El NLU solo reconoce las carrier phrases declaradas, no lenguaje 100% libre** — a
diferencia de `/chat` (mensaje completo al router con LLM), Alexa necesita que la frase
"enganche" con algún sample conocido. No hay forma de eliminar esto del todo; se mitiga
declarando muchas variantes naturales de carrier phrase (10-15 cubre la mayoría de los casos
reales).
