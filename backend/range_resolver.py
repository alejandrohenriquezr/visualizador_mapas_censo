# -*- coding: utf-8 -*-
"""Interpreta rangos numéricos usando variables existentes en el diccionario."""
import re

from dictionary import VARIABLES, TABLAS_PARQUET, _norm, detectar_operacion


# Palabras que no ayudan a distinguir una variable numérica de otra.
_VACIAS = {
    "cantidad", "numero", "porcentaje", "proporcion", "personas", "persona",
    "hogares", "hogar", "viviendas", "vivienda", "con", "de", "del", "la",
    "el", "los", "las", "en", "por", "para", "region", "regiones",
    "provincia", "provincias", "comuna", "comunas", "anos", "ano", "y",
    "o", "mas", "menos", "entre", "hasta", "desde", "que", "tiene", "tienen",
}


def _numero(texto):
    """Convierte números con coma o punto decimal a un valor seguro."""
    return float(str(texto).replace(",", "."))


def _extraer_limites(q):
    """Devuelve límites e inclusividad para expresiones habituales en español."""
    numero = r"(-?\d+(?:[\.,]\d+)?)"
    patrones = (
        # Los intervalos expresados con «entre» o «de ... a ...» son inclusivos.
        (rf"\bentre\s+{numero}\s+(?:y|e)\s+{numero}\b", "intervalo"),
        (rf"\bde\s+{numero}\s+(?:a|hasta)\s+{numero}\b", "intervalo"),
        # Límites superiores inclusivos y exclusivos.
        (rf"\b{numero}\s+anos?\s+o\s+menos\b", "max_inclusivo"),
        (rf"\b{numero}\s+(?:o\s+menos|o\s+menor(?:es)?|como\s+maximo)\b", "max_inclusivo"),
        (rf"\b(?:hasta|maximo(?:\s+de)?|menor\s+o\s+igual\s+(?:a\s+)?)\s*{numero}\b", "max_inclusivo"),
        (rf"(?:<=|≤)\s*{numero}", "max_inclusivo"),
        (rf"\b(?:menos\s+de|menor(?:es)?\s+(?:que|de))\s+{numero}\b", "max_exclusivo"),
        (rf"(?:<|＜)\s*{numero}", "max_exclusivo"),
        # Límites inferiores inclusivos y exclusivos.
        (rf"\b{numero}\s+anos?\s+o\s+mas\b", "min_inclusivo"),
        (rf"\b{numero}\s+(?:o\s+mas|o\s+mayor(?:es)?)\b", "min_inclusivo"),
        (rf"\b(?:al\s+menos|minimo(?:\s+de)?|mayor\s+o\s+igual\s+(?:a\s+)?)\s*{numero}\b", "min_inclusivo"),
        (rf"(?:>=|≥)\s*{numero}", "min_inclusivo"),
        (rf"\b(?:mas\s+de|mayor(?:es)?\s+(?:que|de))\s+{numero}\b", "min_exclusivo"),
        (rf"(?:>|＞)\s*{numero}", "min_exclusivo"),
    )
    for patron, tipo in patrones:
        coincidencia = re.search(patron, q)
        if not coincidencia:
            continue
        valores = [_numero(v) for v in coincidencia.groups() if v is not None]
        if tipo == "intervalo":
            minimo, maximo = sorted(valores[:2])
            return {"minimo": minimo, "maximo": maximo,
                    "incluir_minimo": True, "incluir_maximo": True}
        if tipo == "max_inclusivo":
            return {"minimo": None, "maximo": valores[0],
                    "incluir_minimo": True, "incluir_maximo": True}
        if tipo == "max_exclusivo":
            return {"minimo": None, "maximo": valores[0],
                    "incluir_minimo": True, "incluir_maximo": False}
        if tipo == "min_inclusivo":
            return {"minimo": valores[0], "maximo": None,
                    "incluir_minimo": True, "incluir_maximo": True}
        return {"minimo": valores[0], "maximo": None,
                "incluir_minimo": False, "incluir_maximo": True}
    return None


def _dominio_desde_diccionario(info):
    """Extrae el intervalo válido, por ejemplo 0:85, sin usar códigos especiales."""
    textos = []
    for clave in ("rango", "Rango"):
        if info.get(clave):
            textos.append(str(info[clave]))
    textos.extend(str(codigo) for codigo in info.get("categorias", {}))
    intervalos = []
    for texto in textos:
        for inicio, fin in re.findall(r"(-?\d+(?:[\.,]\d+)?)\s*:\s*(-?\d+(?:[\.,]\d+)?)", texto):
            inferior, superior = _numero(inicio), _numero(fin)
            if inferior <= superior:
                intervalos.append((inferior, superior))
    # Prefiere el intervalo no negativo más amplio; los negativos suelen ser
    # códigos de no respuesta o anonimización.
    validos = [rango for rango in intervalos if rango[0] >= 0]
    if validos:
        return max(validos, key=lambda rango: rango[1] - rango[0])
    return (None, None)


def _variable_unica(tabla, predicado, mensaje):
    """Exige una sola variable para evitar que una coincidencia dudosa llegue al SQL."""
    halladas = [variable for variable, info in VARIABLES[tabla]["variables"].items()
                if predicado(variable, _norm(info.get("descripcion", "")))]
    if len(halladas) != 1:
        raise ValueError(mensaje)
    return halladas[0]


def _resolver_variable(q, tabla):
    """Prioriza conceptos censales conocidos y usa similitud solo como respaldo."""
    if tabla == "personas" and re.search(r"\b(?:escolaridad|anos?\s+de\s+(?:estudio|educacion))\b", q):
        return _variable_unica(
            tabla,
            lambda variable, descripcion: "escolaridad" in descripcion,
            "No se identificó de forma única la variable de años de escolaridad.",
        )
    if tabla == "personas" and re.search(
            r"\b(?:hijas?\s+(?:e\s+)?hijos?|hijos?|hijas?)\s+nacid[oa]s?\b|"
            r"\bnumero\s+de\s+hijos?\b", q):
        return _variable_unica(
            tabla,
            lambda variable, descripcion: (
                ("tot_hijs_nac" in _norm(variable) or
                 ("ha tenido en total" in descripcion and "nacidos vivos" in descripcion))
                and "sobreviv" not in descripcion
            ),
            "No se identificó de forma única la variable del total de hijas e hijos nacidos vivos.",
        )
    if tabla == "personas" and (
            re.search(r"\bedad\b", q) or
            (re.search(r"\bpersonas?\b", q) and re.search(r"\banos?\b", q)
             and not re.search(r"\b(?:escolaridad|estudio|educacion)\b", q))):
        return _variable_unica(
            tabla,
            lambda variable, descripcion: (
                _norm(variable) == "edad" or "anos cumplidos" in descripcion
            ),
            "No se identificó de forma única la variable de edad en años cumplidos.",
        )

    # Respaldo genérico para otras variables continuas presentes en el
    # diccionario. Solo acepta una ventaja clara en la puntuación textual.
    consulta = {t for t in re.findall(r"[a-z0-9]+", q) if t not in _VACIAS}
    candidatos = []
    for variable, info in VARIABLES[tabla]["variables"].items():
        dominio = _dominio_desde_diccionario(info)
        if dominio == (None, None):
            continue
        descripcion = _norm(info.get("descripcion", ""))
        tokens = set(re.findall(r"[a-z0-9]+", descripcion + " " + _norm(variable))) - _VACIAS
        puntaje = len(consulta & tokens)
        if puntaje:
            candidatos.append((puntaje, variable))
    candidatos.sort(key=lambda item: (-item[0], item[1]))
    if not candidatos or (len(candidatos) > 1 and candidatos[0][0] == candidatos[1][0]):
        raise ValueError(
            "Se reconoció un rango, pero no una variable numérica única. "
            "Indicar expresamente edad, escolaridad, total de hijos u otra variable."
        )
    return candidatos[0][1]


def _tabla_consulta(q):
    """Determina la unidad censal mencionada en la pregunta."""
    coincidencias = []
    patrones = {
        "personas": r"\b(?:personas?|poblacion|mujeres?|hombres?)\b",
        "hogares": r"\bhogares?\b",
        "viviendas": r"\b(?:viviendas?|casas?)\b",
    }
    for tabla, patron in patrones.items():
        if tabla in TABLAS_PARQUET and re.search(patron, q):
            coincidencias.append(tabla)
    if len(coincidencias) == 1:
        return coincidencias[0]
    # Edad, escolaridad e hijos son variables de personas en este diccionario.
    if re.search(r"\b(?:edad|escolaridad|hijos?|hijas?)\b", q):
        return "personas"
    raise ValueError("Se reconoció un rango, pero no la unidad censal a la que se aplica.")


def _texto_rango(tabla, variable, descripcion, limites):
    """Genera una descripción cotidiana de los límites interpretados."""
    minimo, maximo = limites["minimo"], limites["maximo"]
    es_edad = _norm(variable) == "edad" or "anos cumplidos" in _norm(descripcion)
    es_escolaridad = "escolaridad" in _norm(descripcion)
    es_hijos = "tot_hijs_nac" in _norm(variable)
    if minimo is not None and maximo is not None:
        if es_edad:
            return f"personas entre {_mostrar(minimo)} y {_mostrar(maximo)} años"
        concepto = ("años de escolaridad" if es_escolaridad else
                    "hijas e hijos nacidos vivos" if es_hijos else descripcion.strip().rstrip(" ."))
        return f"{tabla} con {concepto} entre {_mostrar(minimo)} y {_mostrar(maximo)}"
    elif minimo is not None:
        if es_edad:
            return (f"personas de {_mostrar(minimo)} años o más" if limites["incluir_minimo"]
                    else f"personas mayores de {_mostrar(minimo)} años")
        concepto = ("años de escolaridad" if es_escolaridad else
                    "hijas e hijos nacidos vivos" if es_hijos else descripcion.strip().rstrip(" ."))
        detalle = (f"{_mostrar(minimo)} {concepto} o más" if limites["incluir_minimo"]
                   else f"más de {_mostrar(minimo)} {concepto}")
    else:
        if es_edad:
            return (f"personas de {_mostrar(maximo)} años o menos" if limites["incluir_maximo"]
                    else f"personas menores de {_mostrar(maximo)} años")
        concepto = ("años de escolaridad" if es_escolaridad else
                    "hijas e hijos nacidos vivos" if es_hijos else descripcion.strip().rstrip(" ."))
        detalle = (f"{_mostrar(maximo)} {concepto} o menos" if limites["incluir_maximo"]
                   else f"menos de {_mostrar(maximo)} {concepto}")
    return f"{tabla} con {detalle}"


def _mostrar(valor):
    """Evita decimales artificiales cuando el límite es entero."""
    return str(int(valor)) if float(valor).is_integer() else str(valor).replace(".", ",")


def resolver_rango_numerico(consulta):
    """Crea una intención ejecutable para conteos o porcentajes con rangos."""
    q = _norm(consulta)
    limites = _extraer_limites(q)
    if limites is None:
        return None
    operacion = detectar_operacion(consulta)
    if operacion not in ("conteo", "porcentaje"):
        raise ValueError("Los rangos numéricos se admiten en conteos y porcentajes.")
    tabla = _tabla_consulta(q)
    variable = _resolver_variable(q, tabla)
    info = VARIABLES[tabla]["variables"][variable]
    dominio_minimo, dominio_maximo = _dominio_desde_diccionario(info)
    # Como respaldo, las variables numéricas censales usan valores negativos
    # para códigos especiales. El cero evita incluirlos en consultas «o menos».
    if dominio_minimo is None:
        dominio_minimo = 0.0
    filtro = {
        "variable": variable,
        **limites,
        "dominio_minimo": dominio_minimo,
        "dominio_maximo": dominio_maximo,
    }
    if (limites["minimo"] is not None and dominio_maximo is not None
            and limites["minimo"] > dominio_maximo) or (
            limites["maximo"] is not None and limites["maximo"] < dominio_minimo):
        raise ValueError("El rango solicitado no intersecta el dominio válido de la variable.")
    nombre_operacion = "Porcentaje de" if operacion == "porcentaje" else "Cantidad de"
    return {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": None,
        "operacion": "porcentaje_rango" if operacion == "porcentaje" else "conteo",
        "rango_objetivo": filtro if operacion == "porcentaje" else None,
        "filtros_numericos": [] if operacion == "porcentaje" else [filtro],
        "indicador_descripcion": (
            f"{nombre_operacion} {_texto_rango(tabla, variable, info['descripcion'], limites)}"
        ),
        "_origen_interpretacion": "rango_numerico",
    }
