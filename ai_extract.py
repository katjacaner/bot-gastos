"""Convierte texto libre ("gasté 30000 en el super") en un gasto estructurado usando Gemini."""

import json
import os
import time
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

# Modelos a probar, en orden. Son alias que Google mantiene apuntando a la versión vigente
# (los nombres con número, como "gemini-2.5-flash", se retiran con el tiempo).
# En la capa gratuita cada modelo tiene su propio cupo diario: si uno se agota o está
# saturado, pasamos al siguiente. Se puede cambiar con GEMINI_MODELS=modelo1,modelo2 en el .env.
MODELOS = os.getenv("GEMINI_MODELS", "gemini-flash-lite-latest,gemini-flash-latest").split(",")
MONTO_MAXIMO = Decimal("9999999999.99")  # el máximo que entra en NUMERIC(12, 2)

PROMPT = """Sos un asistente que registra gastos personales en pesos argentinos.
Leé el mensaje del usuario y respondé SOLO con un objeto JSON con estas claves:

- "es_gasto": true si el mensaje describe un gasto; false si no (saludos, preguntas, etc.)
- "monto": número, sin símbolo ni separador de miles ("50 mil" -> 50000, "1.500" -> 1500)
- "categoria": exactamente una de estas: {categorias}
- "descripcion": frase corta que describa el gasto

Mensaje del usuario: {texto}"""


class ErrorExtraccion(Exception):
    """La IA no devolvió un gasto válido. El mensaje es apto para mostrarle al usuario."""


def extraer_gasto(texto, categorias):
    """Devuelve {"monto": Decimal, "categoria": str, "descripcion": str} o lanza ErrorExtraccion."""
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    ultimo_codigo = None
    for modelo in MODELOS:
        for intento in (1, 2):
            try:
                respuesta = cliente.models.generate_content(
                    model=modelo.strip(),
                    contents=PROMPT.format(categorias=", ".join(categorias), texto=texto),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",  # le pedimos JSON...
                        temperature=0,                          # ...y respuestas lo más predecibles posible
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                return validar(respuesta.text, categorias)
            except errors.APIError as e:
                ultimo_codigo = e.code
                if e.code in (500, 503) and intento == 1:
                    time.sleep(3)  # Google saturado: suele ser pasajero, reintentamos una vez
                    continue
                if e.code in (404, 429, 500, 503):
                    break  # modelo retirado (404), cupo agotado (429) o sigue saturado: probamos el siguiente
                # Cualquier otro error (key inválida, etc.) no se arregla cambiando de modelo.
                raise ErrorExtraccion(f"No pude consultar a la IA ({e.code}).")

    if ultimo_codigo == 429:
        raise ErrorExtraccion("Se agotó el cupo gratuito de la IA por hoy. Probá de nuevo mañana.")
    raise ErrorExtraccion(f"No pude consultar a la IA ({ultimo_codigo}). Probá de nuevo en un rato.")


def validar(texto_json, categorias):
    """Nunca confiamos a ciegas en la IA: revisamos cada campo antes de usarlo."""
    # 1) ¿Es JSON de verdad?
    try:
        datos = json.loads(texto_json)
    except (json.JSONDecodeError, TypeError):
        raise ErrorExtraccion("La IA respondió algo que no pude interpretar.")
    if not isinstance(datos, dict):
        raise ErrorExtraccion("La IA respondió algo que no pude interpretar.")

    # 2) ¿Es un gasto?
    if datos.get("es_gasto") is not True:
        raise ErrorExtraccion('Eso no parece un gasto. Probá algo como "gasté 5000 en el super".')

    # 3) ¿El monto es un número razonable?
    try:
        monto = Decimal(str(datos.get("monto")))
    except InvalidOperation:
        raise ErrorExtraccion("No entendí el monto.")
    if not monto.is_finite() or monto <= 0 or monto > MONTO_MAXIMO:
        raise ErrorExtraccion("El monto no es válido.")

    # 4) ¿La categoría existe? Si la IA inventó una, va a "otros".
    categoria = str(datos.get("categoria", "")).strip().lower()
    if categoria not in categorias:
        categoria = "otros"

    descripcion = str(datos.get("descripcion") or "").strip()[:200]

    return {
        "monto": monto.quantize(Decimal("0.01")),
        "categoria": categoria,
        "descripcion": descripcion,
    }


if __name__ == "__main__":
    # Prueba manual:  python ai_extract.py "gasté 30000 en el super"
    # (el bot real va a leer las categorías de la base de datos)
    import sys

    categorias = ["supermercado", "comida", "transporte", "servicios", "salud", "entretenimiento", "otros"]
    texto = " ".join(sys.argv[1:]) or "gasté 30000 en el super"
    try:
        print(extraer_gasto(texto, categorias))
    except ErrorExtraccion as e:
        print("Rechazado:", e)
