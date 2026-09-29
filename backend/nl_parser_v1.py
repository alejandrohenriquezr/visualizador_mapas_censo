# -*- coding: utf-8 -*-
"""
Interpreta una consulta en español en lenguaje natural y la transforma en
una "intención" estructurada que el motor de datos (data_engine.py) puede
ejecutar directamente contra los parquet + la cartografía.

Usa un LLM liviano corriendo LOCALMENTE vía Ollama (http://localhost:11434).
No se hace ninguna llamada a internet ni a APIs externas: si Ollama no está
corriendo, se usa un modo de respaldo (heurístico, sin LLM) para que la
aplicación nunca quede totalmente bloqueada.

Modelos locales recomendados (livianos, con buen español):
    ollama pull qwen2.5:3b-instruct     # recomendado, ~2 GB, rápido en CPU
    ollama pull llama3.2:3b             # alternativa liviana
    ollama pull gemma2:2b               # aún más liviano si tu equipo es limitado
"""
import json
import re
import requests

from dictionary import (
    buscar_variables,
    buscar_geografia,
    detectar_nivel_geografico,
    detectar_operacion,
    TABLAS_PARQUET,
)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODELO_LLM = "qwen2.5:3b-instruct"  # cambia esto si usas otro modelo local
TIMEOUT_SEG = 30


def _construir_prompt(consulta: str, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto):
    lineas_var = []
    for i, c in enumerate(candidatos_var):
        cats = ""
        if c["categorias"]:
            pares = ", ".join(f'{k}="{v}"' for k, v in list(c["categorias"].items())[:15])
            cats = f" | valores posibles: {pares}"
        lineas_var.append(f'{i}. tabla="{c["tabla"]}" variable="{c["variable"]}" ({c["descripcion"]}){cats}')

    lineas_geo = []
    for g in candidatos_geo:
        lineas_geo.append(f'- {g["nivel"]}: "{g["nombre"]}" (codigo={g["codigo"]})')

    prompt = f"""Eres un asistente que traduce preguntas en español sobre el Censo 2024 de Chile a un JSON estructurado. NO expliques nada, responde SOLO con el JSON, sin texto adicional ni comillas triples.

Pregunta del usuario: "{consulta}"

Variables candidatas (elige UNA, la más adecuada a la pregunta):
{chr(10).join(lineas_var) if lineas_var else "(ninguna encontrada, usa null)"}

Unidades geográficas detectadas en la pregunta (para filtrar el mapa a una zona específica, opcional):
{chr(10).join(lineas_geo) if lineas_geo else "(ninguna, no hay filtro geográfico específico)"}

Responde exactamente con este formato JSON (sin comentarios):
{{
  "tabla": "personas|hogares|viviendas",
  "variable": "nombre_exacto_de_la_variable_elegida_o_null",
  "categoria_valor": "codigo_de_categoria_elegida_o_null",
  "operacion": "conteo|porcentaje|promedio",
  "nivel_geografico": "region|provincia|comuna",
  "filtro_geografico_nivel": "region|provincia|comuna|null",
  "filtro_geografico_codigo": "codigo_o_null"
}}

Reglas:
- "operacion" por defecto es "{operacion_defecto}" salvo que la pregunta pida explícitamente otra cosa.
- "nivel_geografico" es el nivel al que se debe agregar y pintar el mapa; por defecto es "{nivel_defecto}".
- Si la pregunta no filtra a ninguna región/provincia/comuna en particular, deja filtro_geografico_nivel y filtro_geografico_codigo en null.
- "categoria_valor" solo se llena si la pregunta pide un valor específico de la variable (ej: sexo=mujer, área=rural). Si la variable es numérica continua (como edad, escolaridad) y se pide promedio, deja categoria_valor en null.
"""
    return prompt


def _llamar_ollama(prompt: str) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=TIMEOUT_SEG,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "")


def _extraer_json(texto: str):
    texto = texto.strip()
    texto = re.sub(r"^```(json)?", "", texto).strip()
    texto = re.sub(r"```$", "", texto).strip()
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError("El modelo no devolvió JSON reconocible")
    return json.loads(match.group(0))


def _respaldo_heuristico(consulta: str, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto):
    """Si el LLM local no está disponible o falla, se usa la mejor
    coincidencia por texto en vez de dejar la app sin respuesta."""
    if not candidatos_var:
        return None
    mejor = candidatos_var[0]
    categoria_valor = None
    q = consulta.lower()
    for codigo, etiqueta in mejor["categorias"].items():
        if etiqueta.lower() in q:
            categoria_valor = codigo
            break
    geo = candidatos_geo[0] if candidatos_geo else None
    return {
        "tabla": mejor["tabla"],
        "variable": mejor["variable"],
        "categoria_valor": categoria_valor,
        "operacion": operacion_defecto,
        "nivel_geografico": nivel_defecto,
        "filtro_geografico_nivel": geo["nivel"] if geo else None,
        "filtro_geografico_codigo": geo["codigo"] if geo else None,
    }


def interpretar_consulta(consulta: str) -> dict:
    """Punto de entrada principal: consulta en texto -> intención estructurada."""
    candidatos_var = buscar_variables(consulta, top_n=6)
    candidatos_geo = buscar_geografia(consulta, top_n=5)
    nivel_defecto = detectar_nivel_geografico(consulta)
    operacion_defecto = detectar_operacion(consulta)

    intencion = None
    origen = "llm_local"
    try:
        prompt = _construir_prompt(consulta, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto)
        texto_llm = _llamar_ollama(prompt)
        intencion = _extraer_json(texto_llm)
    except Exception as e:
        origen = f"respaldo_heuristico (LLM no disponible: {e})"
        intencion = _respaldo_heuristico(consulta, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto)

    if not intencion or not intencion.get("tabla") or not intencion.get("variable"):
        raise ValueError(
            "No se pudo identificar una variable del censo relacionada con la pregunta. "
            "Intenta reformularla usando términos como: sexo, edad, migración, "
            "pueblos indígenas, hacinamiento, internet, vivienda, escolaridad, etc."
        )

    # Validaciones de seguridad: que la tabla/variable existan de verdad
    if intencion["tabla"] not in TABLAS_PARQUET:
        intencion["tabla"] = candidatos_var[0]["tabla"] if candidatos_var else "personas"

    intencion.setdefault("operacion", operacion_defecto)
    intencion.setdefault("nivel_geografico", nivel_defecto)
    intencion.setdefault("filtro_geografico_nivel", None)
    intencion.setdefault("filtro_geografico_codigo", None)
    intencion["_origen_interpretacion"] = origen
    return intencion
