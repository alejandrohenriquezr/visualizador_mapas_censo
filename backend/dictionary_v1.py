# -*- coding: utf-8 -*-
"""
Carga los diccionarios de variables del Censo 2024 y de la cartografía,
y ofrece una búsqueda liviana de "candidatos" (variables y unidades
geográficas) relevantes para una consulta en lenguaje natural.

La idea es NO mandarle al LLM local todo el diccionario (sería demasiado
texto para un modelo liviano). En vez de eso, primero acotamos con un
buscador simple basado en texto, y solo esos candidatos (pocos) se le
pasan al LLM para que decida.
"""
import json
import re
from pathlib import Path
from unidecode import unidecode

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

with open(DATA_DIR / "diccionario_variables.json", encoding="utf-8") as f:
    VARIABLES = json.load(f)

with open(DATA_DIR / "diccionario_geografico.json", encoding="utf-8") as f:
    GEOGRAFIA_CAMPOS = json.load(f)

# Tablas disponibles y su archivo parquet correspondiente
TABLAS_PARQUET = {
    "personas": "personas_censo2024.parquet",
    "hogares": "hogares_censo2024.parquet",
    "viviendas": "viviendas_censo2024.parquet",
}

# Palabras vacías simples en español para no ensuciar la búsqueda
STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "en", "por", "un", "una", "con",
    "que", "y", "a", "para", "cuantas", "cuantos", "cuántas", "cuántos",
    "cual", "cuál", "es", "son", "hay", "muestrame", "muéstrame", "mapa",
    "quiero", "ver", "dame", "porcentaje", "cantidad", "numero", "número",
    "total", "segun", "según", "cada", "sobre", "tiene", "tienen",
}


def _norm(txt: str) -> str:
    return unidecode(str(txt)).lower()


def _tokens(txt: str):
    return [t for t in re.findall(r"[a-z0-9]+", _norm(txt)) if t and t not in STOPWORDS]


# ---------------------------------------------------------------------------
# Índice de variables: para cada (tabla, variable) guardamos un texto de
# búsqueda que junta descripción + etiquetas de categorías.
# ---------------------------------------------------------------------------
_VAR_INDEX = []
for tabla, contenido in VARIABLES.items():
    if tabla == "geografia":
        continue
    for nombre_var in contenido["orden"]:
        info = contenido["variables"][nombre_var]
        texto = info["descripcion"] + " " + " ".join(info["categorias"].values())
        _VAR_INDEX.append({
            "tabla": tabla,
            "variable": nombre_var,
            "descripcion": info["descripcion"],
            "categorias": info["categorias"],
            "texto_norm": _norm(texto),
            "tokens": set(_tokens(texto)),
        })


def buscar_variables(consulta: str, top_n: int = 6):
    """Devuelve las top_n variables más relacionadas con la consulta."""
    q_tokens = set(_tokens(consulta))
    q_norm = _norm(consulta)
    puntajes = []
    for item in _VAR_INDEX:
        score = 0
        # coincidencia de tokens completos
        score += 3 * len(q_tokens & item["tokens"])
        # coincidencia de subcadena directa (ej. "internet", "hacinamiento")
        for tok in q_tokens:
            if len(tok) >= 4 and tok in item["texto_norm"]:
                score += 1
        if score > 0:
            puntajes.append((score, item))
    puntajes.sort(key=lambda x: x[0], reverse=True)
    return [p[1] for p in puntajes[:top_n]]


# ---------------------------------------------------------------------------
# Índice geográfico: nombres de región/provincia/comuna normalizados
# ---------------------------------------------------------------------------
_GEO_INDEX = []
for nivel in ("region", "provincia", "comuna"):
    for codigo, nombre in VARIABLES["geografia"][nivel].items():
        _GEO_INDEX.append({
            "nivel": nivel,
            "codigo": codigo,
            "nombre": nombre,
            "nombre_norm": _norm(nombre),
        })


def buscar_geografia(consulta: str, top_n: int = 5):
    """Busca menciones de regiones/provincias/comunas dentro de la consulta."""
    q_norm = _norm(consulta)
    encontrados = []
    for item in _GEO_INDEX:
        # Solo consideramos nombres de 4+ caracteres para evitar falsos positivos
        if len(item["nombre_norm"]) >= 4 and item["nombre_norm"] in q_norm:
            encontrados.append(item)
    # Preferimos coincidencias más largas (más específicas) primero
    encontrados.sort(key=lambda x: len(x["nombre_norm"]), reverse=True)
    return encontrados[:top_n]


def detectar_nivel_geografico(consulta: str) -> str:
    """Detecta a qué nivel el usuario quiere agregar el mapa."""
    q = _norm(consulta)
    if "region" in q or "regiones" in q:
        return "region"
    if "provincia" in q:
        return "provincia"
    # comuna es el nivel por defecto (más útil visualmente)
    return "comuna"


def detectar_operacion(consulta: str) -> str:
    q = _norm(consulta)
    if "porcentaje" in q or "%" in q or "proporcion" in q or "tasa" in q:
        return "porcentaje"
    if "promedio" in q or "media" in q:
        return "promedio"
    return "conteo"
