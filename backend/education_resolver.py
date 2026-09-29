# -*- coding: utf-8 -*-
"""Resolución determinista de consultas sobre asistencia educacional.

Distingue la pregunta 33 (asistencia general a educación formal) de las
variables derivadas de asistencia por nivel. No infiere niveles que el
diccionario no permite aislar.
"""
import re

from dictionary import VARIABLES, _norm, categorias_validas
from categorical_resolver import AmbiguedadVariable

TABLA = "personas"
VARIABLE_GENERAL = "p33_edu_asiste"
VARIABLES_NIVEL = {
    "parvularia": "asistencia_parv",
    "basica": "asistencia_basica",
    "media": "asistencia_media",
    "superior": "asistencia_superior",
}
VARIABLES_EDUCACION = {VARIABLE_GENERAL, *VARIABLES_NIVEL.values()}

# Los patrones exigen contexto educativo para términos potencialmente ambiguos
# como "media" o "superior".
_PATRONES_NIVEL = {
    "parvularia": (
        r"\beducacion\s+(?:parvularia|preescolar)\b",
        r"\bensenanza\s+(?:parvularia|preescolar)\b",
        r"\b(?:nivel\s+)?(?:parvulari[oa]|preescolar)\b",
        r"\b(?:jardin(?:\s+infantil)?|sala\s+cuna|pre\s*kinder|prekinder|kinder)\b",
    ),
    "basica": (
        r"\beducacion\s+(?:basica|primaria)\b",
        r"\bensenanza\s+basica\b",
        r"\b(?:nivel\s+)?basic[ao]\b",
        r"\bprimaria\b",
        r"\b[1-8](?:ro|do|to|vo)?\s+basico\b",
    ),
    "media": (
        r"\beducacion\s+(?:media|secundaria)\b",
        r"\bensenanza\s+media\b",
        r"\b(?:nivel\s+)?secundari[ao]\b",
        r"\b[1-4](?:ro|do|to)?\s+medio\b",
        r"\bestudiantes?\s+(?:de|en)\s+(?:la\s+)?media\b",
        r"\balumn[oa]s?\s+(?:de|en)\s+(?:la\s+)?media\b",
    ),
    "superior": (
        r"\beducacion\s+superior\b",
        r"\bensenanza\s+superior\b",
        r"\b(?:nivel\s+)?superior\b",
        r"\b(?:universidad|universitari[oa]s?|instituto\s+profesional|centro\s+de\s+formacion\s+tecnica|cft)\b",
        r"\bestudiantes?\s+(?:de|en)\s+(?:la\s+)?u\b",
        r"\balumn[oa]s?\s+(?:de|en)\s+(?:la\s+)?u\b",
    ),
}

_PATRON_ESTUDIANTE = re.compile(
    r"\b(?:estudiantes?|alumn[oa]s?|escolares?|personas?\s+que\s+estudian|"
    r"personas?\s+que\s+asisten|asiste(?:n)?\s+(?:actualmente\s+)?a\s+la?\s*educacion)\b"
)
_PATRON_ASISTE_AFIRMATIVO = re.compile(
    r"\b(?:asiste|asisten|estudia|estudian|cursa|cursan|estudiantes?|alumn[oa]s?|escolares?)\b"
)
_PATRON_ASISTE_NEGATIVO = re.compile(
    r"\b(?:no\s+asiste|no\s+asisten|no\s+estudia|no\s+estudian)\b"
)
_PATRON_FORMAL = re.compile(r"\beducacion\s+formal\b")
_PATRON_ESPECIAL = re.compile(r"\beducacion\s+especial\b|\bensenanza\s+especial\b")


def _opcion(variable, puntaje=100):
    info = VARIABLES[TABLA]["variables"][variable]
    validas = categorias_validas(TABLA, variable)
    return {
        "tabla": TABLA,
        "variable": variable,
        "descripcion": info["descripcion"],
        "categorias_ejemplo": [
            str(info["categorias"].get(c, c)) for c in validas[:4]
        ],
        "puntaje": puntaje,
    }


def _nivel_explicito(q):
    encontrados = []
    for nivel, patrones in _PATRONES_NIVEL.items():
        if any(re.search(p, q) for p in patrones):
            encontrados.append(nivel)
    return encontrados[0] if len(encontrados) == 1 else None


def _operacion(q):
    if re.search(r"\b(?:porcentaje|proporcion|tasa)\b|%", q):
        return "porcentaje"
    return "conteo"


def _intencion_categoria(variable, categoria, q, origen):
    info = VARIABLES[TABLA]["variables"][variable]
    operacion = _operacion(q)
    etiqueta = str(info["categorias"].get(str(categoria), categoria))
    return {
        "tabla": TABLA,
        "variable": variable,
        "categoria_valor": str(categoria),
        "denominador_valores": categorias_validas(TABLA, variable),
        "operacion": operacion,
        "indicador_descripcion": f"{etiqueta}: {info['descripcion']}",
        "_origen_interpretacion": origen,
    }


def _intencion_distribucion(variable, origen):
    info = VARIABLES[TABLA]["variables"][variable]
    return {
        "tabla": TABLA,
        "variable": variable,
        "categoria_valor": None,
        "categorias_validas": categorias_validas(TABLA, variable),
        "operacion": "distribucion",
        "tipo_visualizacion": "tortas_mapa",
        "indicador_descripcion": f"Distribución de personas según {info['descripcion']}",
        "_origen_interpretacion": origen,
    }


def resolver_educacion(consulta, tabla_forzada=None, variable_forzada=None):
    """Resuelve asistencia educacional antes del catálogo categórico genérico.

    Reglas principales:
    - Nivel explícito -> variable derivada de asistencia de ese nivel.
    - Educación formal sin nivel -> pregunta 33.
    - "estudiantes" sin nivel -> solicita elegir entre P33 y cuatro niveles.
    - Una selección de interfaz se conserva y se interpreta como Sí/No según
      la redacción original.
    """
    q = _norm(consulta)

    if tabla_forzada and tabla_forzada != TABLA:
        return None
    if variable_forzada and variable_forzada not in VARIABLES_EDUCACION:
        return None

    nivel = _nivel_explicito(q)
    menciona_estudiante = bool(_PATRON_ESTUDIANTE.search(q))
    afirmativa = bool(_PATRON_ASISTE_AFIRMATIVO.search(q))
    negativa = bool(_PATRON_ASISTE_NEGATIVO.search(q))
    formal = bool(_PATRON_FORMAL.search(q))

    # El diccionario no ofrece una variable que permita aislar la asistencia
    # a educación especial. P33 la incluye dentro de educación formal, pero no
    # la separa; responder P33 sería metodológicamente incorrecto.
    if _PATRON_ESPECIAL.search(q) and not variable_forzada:
        raise ValueError(
            "La pregunta 33 incluye la educación especial dentro de la educación formal, "
            "pero el diccionario disponible no contiene una variable específica que permita "
            "aislar a quienes asisten a educación especial."
        )

    # Si el usuario ya eligió una de las alternativas, esa selección manda.
    if variable_forzada in VARIABLES_EDUCACION:
        if negativa:
            return _intencion_categoria(variable_forzada, "2", q, "seleccion_educacion")
        if afirmativa or menciona_estudiante:
            return _intencion_categoria(variable_forzada, "1", q, "seleccion_educacion")
        return _intencion_distribucion(variable_forzada, "seleccion_educacion")

    # Un nivel concreto siempre tiene prioridad sobre la pregunta 33 general.
    if nivel:
        variable = VARIABLES_NIVEL[nivel]
        if negativa:
            return _intencion_categoria(variable, "2", q, "educacion_nivel")
        if afirmativa or menciona_estudiante:
            return _intencion_categoria(variable, "1", q, "educacion_nivel")
        # Si solo nombra la variable (p.ej. "asistencia a educación media"),
        # mostrar Sí/No es más informativo que contar todas las personas.
        return _intencion_distribucion(variable, "educacion_nivel")

    # La mención inequívoca de educación formal corresponde a P33.
    if formal:
        if negativa:
            return _intencion_categoria(VARIABLE_GENERAL, "2", q, "educacion_general")
        if afirmativa or menciona_estudiante:
            return _intencion_categoria(VARIABLE_GENERAL, "1", q, "educacion_general")
        return _intencion_distribucion(VARIABLE_GENERAL, "educacion_general")

    # "Estudiante(s)" no especifica si se quiere la asistencia general o una
    # variable derivada por nivel. La ambigüedad es real y debe decidirla el usuario.
    if menciona_estudiante:
        opciones = [_opcion(VARIABLE_GENERAL, 100)]
        opciones.extend(_opcion(VARIABLES_NIVEL[n], 95) for n in (
            "parvularia", "basica", "media", "superior"
        ))
        raise AmbiguedadVariable(
            "La expresión 'estudiante(s)' puede referirse a la asistencia general a la "
            "educación formal (pregunta 33) o a la asistencia de un nivel específico. "
            "Selecciona la variable que deseas consultar.",
            opciones,
        )

    return None
