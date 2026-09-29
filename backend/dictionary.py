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

# Campos de identificación, geografía o control operativo que no deben competir
# como variables estadísticas ante una pregunta en lenguaje natural.
VARIABLES_NO_SEMANTICAS = {
    "id_vivienda", "id_hogar", "id_persona",
    "region", "provincia", "comuna", "comuna_bajo_umbral",
}

# Palabras vacías simples en español para no ensuciar la búsqueda
STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "en", "por", "un", "una", "con",
    "que", "y", "a", "para", "cuantas", "cuantos", "cuántas", "cuántos",
    "cual", "cuál", "es", "son", "hay", "muestrame", "muéstrame", "mapa",
    "quiero", "ver", "dame", "porcentaje", "cantidad", "numero", "número",
    "total", "segun", "según", "cada", "sobre", "tiene", "tienen",
}

# Equivalencias de uso cotidiano. Se expanden, no se reemplazan, para
# conservar la diferencia estadística entre la entidad vivienda y la
# categoría Casa de la variable «Tipo de vivienda particular».
SINONIMOS_BUSQUEDA = {
    "casa": {"casa", "vivienda"},
    "casas": {"casa", "vivienda"},
    "vivienda": {"vivienda"},
    "viviendas": {"vivienda"},
    "domicilio": {"vivienda"},
    "domicilios": {"vivienda"},
    "nacida": {"nacida", "nacimiento"},
    "nacidas": {"nacidas", "nacimiento"},
    "nacido": {"nacido", "nacimiento"},
    "nacidos": {"nacidos", "nacimiento"},
    "nacio": {"nacio", "nacimiento"},
    "nacieron": {"nacieron", "nacimiento"},
}


def _norm(txt: str) -> str:
    return unidecode(str(txt)).lower()


def _tokens(txt: str):
    """Tokeniza y agrega equivalencias controladas del dominio censal."""
    resultado = []
    for token in re.findall(r"[a-z0-9]+", _norm(txt)):
        if not token or token in STOPWORDS:
            continue
        resultado.extend(sorted(SINONIMOS_BUSQUEDA.get(token, {token})))
    return resultado


def es_ambito_nacional(consulta: str) -> bool:
    """Reconoce Chile como ámbito, sin confundirlo con lugar de nacimiento."""
    q = _norm(consulta)
    nacimiento = re.search(
        r"\b(?:nac(?:io|ieron|ida|ido|idas|idos)|nacimiento|fuera de chile)\b",
        q,
    )
    if nacimiento:
        return False
    return bool(re.search(
        r"\b(?:en|de|para)\s+(?:todo\s+)?chile\b|"
        r"\b(?:todo\s+)?(?:el\s+)?pais\b|"
        r"\b(?:a\s+)?nivel\s+nacional\b|"
        r"\bambito\s+nacional\b",
        q,
    ))


# ---------------------------------------------------------------------------
# Índice de variables: para cada (tabla, variable) guardamos un texto de
# búsqueda que junta descripción + etiquetas de categorías.
# ---------------------------------------------------------------------------
_VAR_INDEX = []
for tabla, contenido in VARIABLES.items():
    if tabla == "geografia":
        continue
    for nombre_var in contenido["orden"]:
        if nombre_var in VARIABLES_NO_SEMANTICAS:
            continue
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
    # En «casas en Chile», Chile define el ámbito y no una categoría. Así se
    # evita favorecer variables como lugar de nacimiento o nacionalidad.
    if es_ambito_nacional(consulta):
        q_tokens.difference_update({"chile", "pais", "nacional", "ambito"})
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
    salida = []
    for score, item in puntajes[:top_n]:
        copia = dict(item)
        copia["_score"] = score
        salida.append(copia)
    return salida


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

# Alias territoriales controlados. La clave usa el nombre oficial normalizado
# y el nivel; el código territorial siempre se recupera desde el diccionario.
ALIAS_TERRITORIALES = {
    ("comuna", "isla de pascua"): {"rapa nui", "rapanui"},
}

# Numeración romana que algunos usuarios todavía emplean para identificar
# regiones. Se interpreta como el código regional actual (I=1, ..., XVI=16).
_ROMANOS_REGION = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
    "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11,
    "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16,
}


def _item_geografico_por_codigo(nivel: str, codigo):
    """Recupera una unidad territorial por código, tolerando ceros iniciales."""
    texto = str(codigo).strip()
    if not texto.isdigit():
        return None
    numero = int(texto)
    candidatos = [
        item for item in _GEO_INDEX
        if item["nivel"] == nivel and str(item["codigo"]).isdigit()
        and int(item["codigo"]) == numero
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def referencia_geografica_por_codigo(consulta: str):
    """Reconoce códigos explícitos de región/provincia/comuna.

    Ejemplos admitidos: ``región 13``, ``región XIII``, ``XII región``,
    ``provincia 91``, ``comuna 9101`` y ``código de comuna 9101``.
    Solo actúa cuando el nivel territorial aparece junto al código, para no
    confundir edades, años, porcentajes u otros números de la consulta.
    """
    q = _norm(consulta)
    codigo_region = r"(?:\d{1,2}|xvi|xiv|xv|xiii|xii|xi|x|ix|viii|vii|vi|iv|v|iii|ii|i)"
    prefijo_codigo = r"(?:(?:n|nro|num|numero|codigo)\s+(?:de\s+)?(?:la\s+)?)?"

    patrones = [
        # Los patrones que comienzan por "código" van primero para sustituir
        # toda la frase ("código de comuna 9101"), no solo su tramo final.
        ("region", rf"\bcodigo\s+(?:de\s+)?(?:la\s+)?region\s+(?P<codigo>{codigo_region})\b"),
        ("region", rf"\bregion\s+(?:de\s+)?{prefijo_codigo}(?P<codigo>{codigo_region})\b"),
        ("region", rf"\b(?P<codigo>{codigo_region})\s+region\b"),
        ("provincia", r"\bcodigo\s+(?:de\s+)?(?:la\s+)?provincia\s+(?P<codigo>\d{1,3})\b"),
        ("provincia", r"\bprovincia\s+(?:de\s+)?(?:(?:n|nro|num|numero|codigo)\s+)?(?P<codigo>\d{1,3})\b"),
        ("comuna", r"\bcodigo\s+(?:de\s+)?(?:la\s+)?comuna\s+(?P<codigo>\d{3,5})\b"),
        ("comuna", r"\bcomuna\s+(?:de\s+)?(?:(?:n|nro|num|numero|codigo)\s+)?(?P<codigo>\d{3,5})\b"),
    ]

    for nivel, patron in patrones:
        match = re.search(patron, q)
        if not match:
            continue
        token = match.group("codigo").lower()
        if nivel == "region" and not token.isdigit():
            numero = _ROMANOS_REGION.get(token)
            if numero is None:
                raise ValueError(f"La numeración romana de región '{token.upper()}' no es válida.")
            codigo = str(numero)
        else:
            codigo = token
        item = _item_geografico_por_codigo(nivel, codigo)
        if item is None:
            etiqueta = token.upper() if nivel == "region" and not token.isdigit() else token
            raise ValueError(
                f"No existe una {nivel} con código {etiqueta} en el diccionario geográfico."
            )
        resultado = dict(item)
        resultado.update({
            "inicio": match.start(), "fin": match.end(),
            "referencia_original": match.group(0),
            "codigo_ingresado": token,
        })
        return resultado
    return None


def nombres_geograficos(item):
    """Alias de nombres conocidos; el código siempre proviene del diccionario."""
    nombre = item["nombre_norm"]
    corto = re.sub(r"^(?:region|provincia|comuna)\s+(?:de\s+)?", "", nombre)
    # Conserva variantes con y sin artículo («La Araucanía»/«Araucanía»).
    sin_articulo = re.sub(r"^(?:la|el|los|las)\s+", "", corto)
    nombres = {nombre, corto, sin_articulo}
    if item["nivel"] == "region" and re.search(r"\bmetropolitana\b", nombre):
        nombres.update({"metropolitana", "metropolitana de santiago"})
    # Incorpora denominaciones alternativas solo cuando existe en el
    # diccionario la unidad territorial oficial correspondiente.
    for (nivel, oficial), alias in ALIAS_TERRITORIALES.items():
        if item["nivel"] == nivel and oficial in {nombre, corto, sin_articulo}:
            nombres.update(alias)
    return sorted(nombres, key=len, reverse=True)


def buscar_geografia(consulta: str, top_n: int = 5):
    """Busca nombres completos o alias comprobados con límites de palabra."""
    q = _norm(consulta)
    encontrados = []
    for item in _GEO_INDEX:
        coincidencias = []
        for nombre in nombres_geograficos(item):
            if len(nombre) < 4:
                continue
            match = re.search(r"\b" + re.escape(nombre) + r"\b", q)
            if not match:
                continue
            # "Nacimiento" es también una comuna. En consultas sobre lugar de
            # nacimiento solo se interpreta como territorio si el nivel comuna
            # está explícito ("comuna de Nacimiento").
            if (item["nivel"] == "comuna" and nombre == "nacimiento"
                    and re.search(r"\b(?:nacimiento|nacid[oa]s?|nacio|nacieron)\b", q)):
                prefijo = q[max(0, match.start() - 25):match.start()]
                if not re.search(r"\bcomuna\s+(?:de\s+)?$", prefijo):
                    continue
            coincidencias.append(nombre)
        if coincidencias:
            encontrados.append((max(map(len, coincidencias)), item))
    encontrados.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in encontrados[:top_n]]


def detectar_nivel_geografico(consulta: str) -> str:
    """Prioriza niveles explícitos; en empate, comuna > provincia > región."""
    q = _norm(consulta)
    niveles = (("comuna", r"comunas?|comunal"),
               ("provincia", r"provincias?|provincial"),
               ("region", r"region(?:es)?|regional"))
    # Un nombre territorial después de «en/para la región» es un filtro.
    for nivel, patron in niveles:
        if re.search(r"\b(?:por|cada|a nivel de|a nivel|desglosad[oa]s? por)\s+"
                     r"(?:(?:la|las|el|los)\s+)?(?:" + patron + r")\b", q):
            return nivel
    # Una consulta nacional necesita un desglose territorial para producir un
    # mapa. Si el usuario no indicó otro nivel, se muestran las regiones.
    if es_ambito_nacional(consulta):
        return "region"
    # Descarta menciones singulares que introducen un lugar concreto.
    q = re.sub(r"\b(?:en|para|de)\s+(?:(?:la|el)\s+)?"
               r"(?:region|provincia|comuna)\b(?:\s+de(?:l)?)?", " ", q)
    for nivel, patron in niveles:
        if re.search(r"\b(?:" + patron + r")\b", q):
            return nivel
    # Cuando no se indica nivel territorial, el mapa nacional se presenta por
    # región. Los niveles explícitos revisados arriba mantienen prioridad.
    return "region"


def filtro_geografico_explicito(consulta: str):
    """Distingue lugares por código o por nombre con nivel explícito."""
    # Los códigos se resuelven antes que los nombres. Si el usuario escribió
    # explícitamente un código inexistente se informa el error, en vez de
    # degradar silenciosamente la consulta a todo el país.
    por_codigo = referencia_geografica_por_codigo(consulta)
    if por_codigo:
        return por_codigo

    q = _norm(consulta)
    encontrados = []
    for item in _GEO_INDEX:
        for nombre in nombres_geograficos(item):
            # Retira el prefijo cuando el nombre oficial ya lo contiene.
            nombre = re.sub(r"^(?:region|provincia|comuna)\s+(?:de\s+)?", "", nombre)
            patron = (r"\b" + item["nivel"] + r"\s+(?:de\s+|del\s+)?(?:(?:la|el|los|las)\s+)?"
                      + re.escape(nombre) + r"\b")
            if re.search(patron, q):
                encontrados.append(item)
                break
    encontrados.sort(key=lambda x: len(x["nombre_norm"]), reverse=True)
    return encontrados[0] if encontrados else None


def detectar_operacion(consulta: str) -> str:
    q = _norm(consulta)
    # Los índices y razones necesitan una fórmula registrada; no deben
    # degradarse silenciosamente a un conteo.
    if re.search(r"\b(?:indice|razon)\b", q):
        return "razon"
    if "porcentaje" in q or "%" in q or "proporcion" in q or "tasa" in q:
        return "porcentaje"
    if "promedio" in q or "media" in q:
        return "promedio"
    return "conteo"


def es_categoria_invalida(codigo, etiqueta) -> bool:
    """Reconoce códigos que no pertenecen al universo de un porcentaje."""
    codigo_norm = _norm(codigo).strip()
    etiqueta_norm = _norm(etiqueta).strip()
    if codigo_norm in {"", "na", "nan", "null", "none"} or codigo_norm.startswith("-"):
        return True
    patrones = (
        "no aplica", "no respuesta", "sin respuesta", "no responde",
        "valor suprimido", "valor ignorado", "anonimizado", "missing",
        "sin informacion", "dato no disponible",
    )
    return any(patron in etiqueta_norm for patron in patrones)


def categorias_validas(tabla: str, variable: str):
    """Devuelve códigos válidos usando exclusivamente el diccionario cargado."""
    info = VARIABLES.get(tabla, {}).get("variables", {}).get(variable, {})
    return [str(codigo) for codigo, etiqueta in info.get("categorias", {}).items()
            if not es_categoria_invalida(codigo, etiqueta)]
