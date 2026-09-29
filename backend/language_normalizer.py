# -*- coding: utf-8 -*-
"""Normalización lingüística conservadora para consultas del Censo 2024.

La capa corrige errores ortográficos solo contra un vocabulario cerrado del
propio visor (diccionario censal, geografía y alias documentados). También
expande abreviaciones y modismos sin borrar el texto original, de modo que las
reglas ya existentes siguen pudiendo reconocer la formulación del usuario.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from unidecode import unidecode

from dictionary import VARIABLES, referencia_geografica_por_codigo

try:
    from rapidfuzz import fuzz, process
    from rapidfuzz.distance import Levenshtein
except ImportError:  # pragma: no cover - solo como respaldo de instalación
    fuzz = process = Levenshtein = None


BASE_DIR = Path(__file__).resolve().parent
ALIAS_PATH = BASE_DIR / "semantic_aliases.json"

with open(ALIAS_PATH, encoding="utf-8") as f:
    ALIASES = json.load(f)

# Palabras funcionales, operadores y términos que no deben pasar por fuzzy.
_PROTEGIDAS = {
    "a", "al", "algo", "alguna", "alguno", "algunos", "ante", "bajo", "cada",
    "como", "con", "contra", "cual", "cuales", "cuando", "cuanta", "cuantas",
    "cuanto", "cuantos", "de", "del", "desde", "donde", "dos", "el", "ella",
    "ellas", "ellos", "en", "entre", "era", "es", "esa", "ese", "esta", "estan",
    "este", "esto", "fuera", "hace", "hay", "hasta", "la", "las", "lo", "los",
    "mas", "menos", "mi", "mis", "muy", "no", "o", "otra", "otro", "para",
    "pero", "por", "porque", "que", "quien", "se", "segun", "si", "sin", "sobre",
    "son", "su", "sus", "tiene", "tienen", "todo", "todos", "una", "uno", "unos",
    "y", "ya", "ver", "dame", "muestra", "muestrame", "quiero", "ciudad",
    "censo", "chile", "pais", "nivel", "total", "cantidad", "numero", "conteo",
    "porcentaje", "proporcion", "promedio", "media", "indice", "razon", "tasa",
    "region", "regiones", "provincia", "provincias", "comuna", "comunas",
    "persona", "personas", "hogar", "hogares", "vivienda", "viviendas",
    "particular", "particulares",
    "nacida", "nacidas", "nacido", "nacidos", "nacio", "nacieron",
}


def _norm_basica(texto: str) -> str:
    """Normaliza Unicode, tildes, puntuación y espacios sin perder números/% ."""
    texto = unicodedata.normalize("NFKC", str(texto or ""))
    texto = unidecode(texto).lower()
    texto = texto.replace("’", "'").replace("`", "'")
    # Conserva % y apóstrofes internos; el resto de signos se vuelve espacio.
    texto = re.sub(r"[^a-z0-9%'+]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    # "Censo 2024" describe la fuente, no una variable. Otros años se conservan.
    texto = re.sub(r"\bcenso(?:\s+de)?\s+2024\b", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _tokens(texto: str):
    return re.findall(r"[a-z0-9]+", texto)


# Palabras relacionales frecuentes que pueden quedar pegadas por un error de
# digitación (p.ej. ``sexomayores``). Se usan solo para segmentar un token
# desconocido cuando la separación es inequívoca; no se corrigen palabras
# válidas ni nombres geográficos ya presentes en el vocabulario.
_SEGMENTOS_FRECUENTES = {
    "mayor", "mayores", "menor", "menores", "anos", "edad", "sexo",
    "hombre", "hombres", "mujer", "mujeres", "ocupado", "ocupados",
    "desocupado", "desocupados", "personas", "hogares", "viviendas",
    "region", "provincia", "comuna", "tipologia", "nuclear", "rural",
    "rurales", "urbano", "urbanos", "departamento", "departamentos",
}


def _separar_token_concatenado(token: str):
    """Separa dos palabras válidas pegadas si existe una única partición segura."""
    if len(token) < 8 or token.isdigit():
        return None
    vocab = set(_vocabulario()) | _SEGMENTOS_FRECUENTES
    if token in vocab:
        return None
    candidatos = []
    # Se exigen segmentos de al menos 4 caracteres para evitar fragmentar
    # palabras válidas por coincidencias accidentales muy cortas.
    for i in range(4, len(token) - 3):
        izq, der = token[:i], token[i:]
        if izq in vocab and der in vocab:
            # Al menos uno de los segmentos debe ser un término semántico
            # frecuente del visor. Esto mantiene la segmentación conservadora.
            if izq in _SEGMENTOS_FRECUENTES or der in _SEGMENTOS_FRECUENTES:
                candidatos.append((izq, der))
    return candidatos[0] if len(candidatos) == 1 else None


def _separar_concatenaciones(texto: str):
    cambios = []
    salida = []
    for token in texto.split():
        partes = _separar_token_concatenado(token)
        if partes:
            salida.extend(partes)
            cambios.append({
                "original": token,
                "corregido": " ".join(partes),
                "score": 100.0,
                "tipo": "separacion",
            })
        else:
            salida.append(token)
    return " ".join(salida), cambios


@lru_cache(maxsize=1)
def _vocabulario():
    """Vocabulario permitido para corrección ortográfica cerrada al dominio."""
    vocab = set(_PROTEGIDAS)
    for tabla in ("personas", "hogares", "viviendas"):
        for variable, info in VARIABLES[tabla]["variables"].items():
            vocab.update(_tokens(_norm_basica(variable)))
            vocab.update(_tokens(_norm_basica(info.get("descripcion", ""))))
            for etiqueta in info.get("categorias", {}).values():
                vocab.update(_tokens(_norm_basica(etiqueta)))
    for nivel, valores in VARIABLES.get("geografia", {}).items():
        if isinstance(valores, dict):
            for nombre in valores.values():
                vocab.update(_tokens(_norm_basica(nombre)))
    for bloque in ("expansiones_seguras", "alias_geograficos", "rasgos_booleanos"):
        for item in ALIASES.get(bloque, []):
            for patron in item.get("patrones", []):
                vocab.update(_tokens(_norm_basica(patron)))
            vocab.update(_tokens(_norm_basica(item.get("canonico", ""))))
    for pais, variantes in ALIASES.get("paises_alias", {}).items():
        vocab.update(_tokens(_norm_basica(pais)))
        for variante in variantes:
            vocab.update(_tokens(_norm_basica(variante)))
    for item in ALIASES.get("ambiguos_no_sustituir", []):
        vocab.update(_tokens(_norm_basica(item.get("termino", ""))))
    return tuple(sorted(v for v in vocab if len(v) >= 2))


def _umbral(token: str):
    n = len(token)
    if n <= 3:
        return None
    if n <= 5:
        return 88.0, 1
    if n <= 8:
        return 86.0, 2
    return 88.0, 2


def _corregir_token(token: str):
    """Devuelve (token_corregido, score) o (token, None) si no es inequívoco."""
    vocab = _vocabulario()
    vocab_set = set(vocab)
    if (token in vocab_set or token in _PROTEGIDAS or token.isdigit()
            or any(ch.isdigit() for ch in token)):
        return token, None
    regla = _umbral(token)
    if not regla or process is None:
        return token, None
    score_min, max_dist = regla
    # Se recuperan candidatos desde 80 y luego se aplican umbrales por longitud
    # y distancia. Esto permite una sola sustitución como rejion -> region.
    candidatos = process.extract(token, vocab, scorer=fuzz.ratio, limit=2, score_cutoff=80.0)
    if not candidatos:
        return token, None
    mejor, score, _ = candidatos[0]
    distancia = Levenshtein.distance(token, mejor)
    if distancia > max_dist:
        return token, None
    # Una sola edición en palabras de 4+ caracteres es una señal fuerte aunque
    # el ratio quede algo bajo (p.ej. "rejion" -> "region").
    if distancia == 1 and score >= 80:
        pass
    elif score < score_min:
        return token, None
    # Si dos candidatos están casi empatados no se autocorrige.
    if len(candidatos) > 1 and score - candidatos[1][1] < 5:
        return token, None
    # Para palabras cortas exige al menos la misma letra inicial.
    if len(token) <= 5 and token[0] != mejor[0]:
        return token, None
    return mejor, round(float(score), 1)


def _corregir_ortografia(texto: str):
    correcciones = []
    salida = []
    for token in texto.split():
        # % puede quedar adosado a números y no se corrige.
        limpio = token.strip()
        corregido, score = _corregir_token(limpio)
        salida.append(corregido)
        if score is not None and corregido != limpio:
            correcciones.append({"original": limpio, "corregido": corregido, "score": score})
    return " ".join(salida), correcciones


def _normalizar_codigo_geografico(texto: str):
    """Convierte un código territorial explícito a su nombre oficial.

    Esta sustitución ocurre antes de los aliases generales. Así ``región 13``
    se vuelve ``region metropolitana de santiago`` y ``comuna 9101`` se
    vuelve ``comuna temuco``. Al quitar el código del texto, las reglas
    semánticas posteriores no lo confunden con edades, años u otros valores.
    """
    aplicado = []
    # En una pregunta normal solo existe un filtro territorial. El bucle deja
    # preparado el código para admitir más de una referencia si fuera necesario.
    for _ in range(3):
        referencia = referencia_geografica_por_codigo(texto)
        if not referencia:
            break
        nivel = referencia["nivel"]
        nombre = _norm_basica(referencia["nombre"])
        canonico = f"{nivel} {nombre}"
        original = texto[referencia["inicio"]:referencia["fin"]]
        texto = (texto[:referencia["inicio"]] + canonico +
                 texto[referencia["fin"]:])
        texto = re.sub(r"\s+", " ", texto).strip()
        aplicado.append({
            "tipo": "codigo_geografico",
            "patron": original,
            "canonico": canonico,
            "nivel": nivel,
            "codigo": str(referencia["codigo"]),
        })
    return texto, aplicado


def _patron_frase(frase: str):
    frase = _norm_basica(frase)
    return re.compile(r"(?<![a-z0-9])" + re.escape(frase) + r"(?![a-z0-9])")


def _expandir(texto: str, items, tipo: str):
    aplicados = []
    # Las frases largas se procesan antes para respetar "sin pega" antes de "pega".
    entradas = []
    for item in items:
        for patron in item.get("patrones", []):
            entradas.append((len(_norm_basica(patron)), patron, item))
    entradas.sort(reverse=True, key=lambda x: x[0])
    for _, patron, item in entradas:
        regex = _patron_frase(patron)
        if not regex.search(texto):
            continue
        canonico = _norm_basica(item.get("canonico", ""))
        # Expande en lugar de reemplazar. Así no se pierden señales del texto original.
        if canonico:
            texto = regex.sub(lambda m: f"{m.group(0)} {canonico}", texto)
        aplicados.append({"tipo": tipo, "patron": _norm_basica(patron), "canonico": canonico})
        texto = re.sub(r"\s+", " ", texto).strip()
    return texto, aplicados


def normalizar_consulta(consulta: str):
    """Normaliza una consulta y devuelve trazabilidad de correcciones/alias."""
    original = str(consulta or "")
    texto = _norm_basica(original)
    # Primero recupera espacios omitidos entre dos términos conocidos; después
    # aplica fuzzy matching. Así ``sexomayores`` se interpreta como
    # ``sexo mayores`` sin intentar corregir el token completo a otra palabra.
    texto, separaciones = _separar_concatenaciones(texto)
    texto, correcciones = _corregir_ortografia(texto)
    correcciones = separaciones + correcciones
    texto, codigos_geo = _normalizar_codigo_geografico(texto)
    texto, geo = _expandir(texto, ALIASES.get("alias_geograficos", []), "geografia")
    texto, aliases = _expandir(texto, ALIASES.get("expansiones_seguras", []), "alias")
    return {
        "original": original,
        "texto": re.sub(r"\s+", " ", texto).strip(),
        "correcciones": correcciones,
        "aliases_aplicados": codigos_geo + geo + aliases,
    }


def terminos_ambiguos_presentes(consulta_normalizada: str):
    """Informa términos documentados como ambiguos; no altera la consulta."""
    q = _norm_basica(consulta_normalizada)
    encontrados = []
    for item in ALIASES.get("ambiguos_no_sustituir", []):
        termino = _norm_basica(item.get("termino", ""))
        if termino and _patron_frase(termino).search(q):
            encontrados.append(item)
    return encontrados
