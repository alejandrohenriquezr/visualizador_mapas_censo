# -*- coding: utf-8 -*-
"""Resolución determinista de discapacidad y dimensiones funcionales (P32).

La variable derivada ``discapacidad`` se mantiene separada de las seis
preguntas funcionales P32. El módulo nunca reconstruye una a partir de las
otras: solo interpreta la intención expresada por la persona usuaria.
"""
import re

from dictionary import VARIABLES, _norm, detectar_operacion
from categorical_resolver import AmbiguedadVariable


DIMENSIONES_P32 = (
    ("p32a_dificultad_ver", "Dificultad para ver"),
    ("p32b_dificultad_oir", "Dificultad para oír"),
    ("p32c_dificultad_mover", "Dificultad para caminar o subir escaleras"),
    ("p32d_dificultad_cogni", "Dificultad para recordar o concentrarse"),
    ("p32e_dificultad_cuidado", "Dificultad para realizar tareas de cuidado personal"),
    ("p32f_dificultad_comunic", "Dificultad para comunicarse"),
)

SEVERIDADES = {
    "1": "No, sin dificultad",
    "2": "Sí, algo de dificultad",
    "3": "Sí, mucha dificultad",
    "4": "No puede hacerlo",
}

# Nombres sintéticos que reutilizan el selector de variables de la interfaz.
PREFIJO_SELECCION_SEVERIDAD = "__p32_severidad_"


_PATRONES_DIMENSION = {
    "p32a_dificultad_ver": (
        r"\b(?:dificultad(?:es)?|problemas?)\s+(?:para\s+)?ver\b",
        r"\b(?:vision|visual|visuales)\b",
        r"\b(?:ciego|ciega|ciegos|ciegas)\b",
    ),
    "p32b_dificultad_oir": (
        r"\b(?:dificultad(?:es)?|problemas?)\s+(?:para\s+)?(?:oir|escuchar)\b",
        r"\b(?:auditiv[oa]s?)\b",
        r"\b(?:sordo|sorda|sordos|sordas)\b",
    ),
    "p32c_dificultad_mover": (
        r"\b(?:dificultad(?:es)?|problemas?)\s+(?:para\s+)?(?:caminar|moverse|subir escaleras)\b",
        r"\b(?:movilidad|motora|motoras|motor|motriz)\b",
        r"\b(?:caminar|subir escaleras)\b",
    ),
    "p32d_dificultad_cogni": (
        r"\b(?:dificultad(?:es)?|problemas?)\s+(?:para\s+)?(?:recordar|concentrarse|concentrar)\b",
        r"\b(?:memoria|cognitiv[oa]s?)\b",
        r"\b(?:recordar|concentrarse)\b",
    ),
    "p32e_dificultad_cuidado": (
        r"\b(?:dificultad(?:es)?|problemas?)\s+(?:para\s+)?(?:banarse|vestirse|cuidarse)\b",
        r"\b(?:cuidado personal|autocuidado)\b",
        r"\b(?:banarse|vestirse)\b",
    ),
    "p32f_dificultad_comunic": (
        r"\b(?:dificultad(?:es)?|problemas?)\s+(?:para\s+)?(?:hablar|comunicarse|comunicar)\b",
        r"\b(?:comunicacion|comunicativa|comunicativas)\b",
        r"\b(?:hablar|comunicarse|entender o ser entendido)\b",
    ),
}


def _es_tipo_discapacidad(q):
    return bool(re.search(
        r"\b(?:tipo|tipos|clase|clases)\s+de\s+discapacidad\b|"
        r"\b(?:por|segun)\s+(?:el\s+)?(?:tipo|tipos)\s+de\s+discapacidad\b|"
        r"\bdimensiones?\s+(?:de\s+)?(?:dificultad|funcionales?)\b",
        q,
    ))


def _severidad_explicita(q):
    """Devuelve código P32 cuando el grado aparece de forma inequívoca."""
    patrones = (
        ("1", (
            r"\bno[, ]+sin dificultad\b",
            r"\bsin dificultad(?:es)?\b",
        )),
        ("2", (
            r"\b(?:si[, ]+)?algo de dificultad\b",
            r"\balguna dificultad\b",
        )),
        ("3", (
            r"\b(?:si[, ]+)?mucha dificultad\b",
            r"\bmuchas dificultades\b",
        )),
        ("4", (
            r"\bno puede(?:n)? hacerlo\b",
            r"\bno logra(?:n)? hacerlo\b",
            r"\bno puede(?:n)?\s+(?:ver|oir|escuchar|caminar|moverse|subir escaleras|recordar|concentrarse|banarse|vestirse|hablar|comunicarse)\b",
        )),
    )
    encontrados = [codigo for codigo, pats in patrones
                   if any(re.search(p, q) for p in pats)]
    return encontrados[0] if len(encontrados) == 1 else None


def _opciones_severidad():
    opciones = []
    for codigo, etiqueta in SEVERIDADES.items():
        descripcion = etiqueta
        if codigo == "1":
            descripcion += " (ausencia de dificultad)"
        opciones.append({
            "tabla": "personas",
            "variable": f"{PREFIJO_SELECCION_SEVERIDAD}{codigo}",
            "descripcion": descripcion,
            "categorias_ejemplo": ["Comparar las 6 dimensiones funcionales de la pregunta 32"],
            "puntaje": 100,
        })
    return opciones


def _intencion_dimensiones(consulta, severidad, operacion=None):
    q = _norm(consulta)
    operacion_detectada = operacion or detectar_operacion(q)
    # "distribución" en este contexto significa comparar las seis dimensiones;
    # por defecto se muestran conteos. Si la persona pide porcentaje, se respeta.
    metrica = "porcentaje" if operacion_detectada == "porcentaje" else "conteo"
    return {
        "tabla": "personas",
        # Variable ancla válida para conservar compatibilidad con el contrato
        # general de intención. El motor usa variables_dimensiones.
        "variable": DIMENSIONES_P32[0][0],
        "variables_dimensiones": [variable for variable, _ in DIMENSIONES_P32],
        "etiquetas_dimensiones": {variable: etiqueta for variable, etiqueta in DIMENSIONES_P32},
        "categoria_valor": str(severidad),
        "operacion": "porcentaje" if metrica == "porcentaje" else "conteo",
        "metrica_dimensiones": metrica,
        "tipo_consulta": "dimensiones_funcionales",
        "tipo_visualizacion": "barras_mapa",
        "indicador_descripcion": (
            f"Personas por dimensión de dificultad funcional — {SEVERIDADES[str(severidad)]}"
        ),
        "nota_interpretacion": (
            "Las seis dimensiones funcionales no son categorías mutuamente excluyentes; "
            "una misma persona puede aparecer en más de una barra y los porcentajes no "
            "tienen por qué sumar 100 %."
        ),
        "_origen_interpretacion": "catalogo_discapacidad_p32",
    }


def _dimension_mencionada(q):
    halladas = []
    for variable, patrones in _PATRONES_DIMENSION.items():
        if any(re.search(p, q) for p in patrones):
            halladas.append(variable)
    # Si aparece una sola dimensión, es segura. Más de una se deja al resolver
    # genérico o a una futura consulta multidimensional explícita.
    return halladas[0] if len(halladas) == 1 else None


def _intencion_dimension_individual(consulta, variable):
    q = _norm(consulta)
    severidad = _severidad_explicita(q)
    operacion = detectar_operacion(q)
    info = VARIABLES["personas"]["variables"][variable]

    # «con dificultad para X» significa presencia de dificultad en P32:
    # cualquier categoría estrictamente mayor que 1 (2, 3 o 4). La frase
    # «dificultad para X» sin «con» conserva la distribución de los 4 grados.
    con_dificultad = bool(re.search(r"\bcon\s+dificultad(?:es)?\b", q))
    if severidad is None and con_dificultad:
        salida = {
            "tabla": "personas",
            "variable": variable,
            "categoria_valor": None,
            "categoria_valores": ["2", "3", "4"],
            "operacion": "porcentaje" if operacion == "porcentaje" else "conteo",
            "indicador_descripcion": (
                f"{'Porcentaje' if operacion == 'porcentaje' else 'Cantidad'} de personas "
                f"con dificultad — {info['descripcion']}"
            ),
            "_origen_interpretacion": "catalogo_discapacidad_p32",
        }
        if salida["operacion"] == "porcentaje":
            salida["denominador_valores"] = ["1", "2", "3", "4"]
        return salida

    if severidad is None:
        return {
            "tabla": "personas",
            "variable": variable,
            "categoria_valor": None,
            "categorias_validas": ["1", "2", "3", "4"],
            "operacion": "distribucion",
            "tipo_visualizacion": "tortas_mapa",
            "indicador_descripcion": f"Distribución de personas según {info['descripcion']}",
            "_origen_interpretacion": "catalogo_discapacidad_p32",
        }

    salida = {
        "tabla": "personas",
        "variable": variable,
        "categoria_valor": severidad,
        "operacion": "porcentaje" if operacion == "porcentaje" else "conteo",
        "indicador_descripcion": (
            f"{'Porcentaje' if operacion == 'porcentaje' else 'Cantidad'} de personas — "
            f"{info['categorias'][severidad]} — {info['descripcion']}"
        ),
        "_origen_interpretacion": "catalogo_discapacidad_p32",
    }
    if salida["operacion"] == "porcentaje":
        salida["denominador_valores"] = ["1", "2", "3", "4"]
    return salida


def _resolver_discapacidad_general(q):
    """Variable derivada: con/sin discapacidad o adjetivos equivalentes.

    La redacción natural puede usar tanto ``personas con discapacidad`` como
    ``personas discapacitadas``. Ambas expresiones apuntan a la variable
    derivada ``discapacidad``; no se reconstruyen categorías a partir de P32.
    """
    if not re.search(r"\bdiscapacidad\b|\bdiscapacitad[oa]s?\b", q):
        return None
    if re.search(r"\bdiscapacidad\s+(?:severa|severo|grave|moderada|moderado|leve)\b", q):
        raise ValueError(
            "La variable general 'discapacidad' no distingue grados. "
            "Las preguntas P32 sí distinguen sin dificultad, algo de dificultad, "
            "mucha dificultad y no puede hacerlo, pero el diccionario no define "
            "una equivalencia automática con 'discapacidad severa/moderada/leve'."
        )
    # Expresiones que claramente remiten a dimensiones P32 se resuelven antes.
    if _es_tipo_discapacidad(q):
        return None
    if re.search(r"\b(?:sin\s+discapacidad|no\s+discapacitad[oa]s?)\b", q):
        categoria = "2"
    elif re.search(r"\bcon\s+discapacidad\b|\bdiscapacitad[oa]s?\b", q):
        categoria = "1"
    else:
        categoria = None

    operacion = detectar_operacion(q)
    if categoria is None:
        return {
            "tabla": "personas", "variable": "discapacidad",
            "categoria_valor": None, "categorias_validas": ["1", "2"],
            "operacion": "distribucion", "tipo_visualizacion": "tortas_mapa",
            "indicador_descripcion": "Distribución de personas según discapacidad",
            "_origen_interpretacion": "catalogo_discapacidad_general",
        }
    salida = {
        "tabla": "personas", "variable": "discapacidad",
        "categoria_valor": categoria,
        "operacion": "porcentaje" if operacion == "porcentaje" else "conteo",
        "indicador_descripcion": (
            f"{'Porcentaje' if operacion == 'porcentaje' else 'Cantidad'} de personas "
            f"{VARIABLES['personas']['variables']['discapacidad']['categorias'][categoria].lower()}"
        ),
        "_origen_interpretacion": "catalogo_discapacidad_general",
    }
    if salida["operacion"] == "porcentaje":
        salida["denominador_valores"] = ["1", "2"]
    return salida


def resolver_discapacidad(consulta, tabla_forzada=None, variable_forzada=None):
    """Resuelve discapacidad general, P32 y la comparación de sus 6 dimensiones."""
    q = _norm(consulta)

    # Reentrada desde el selector de severidad sin requerir cambios en el modal.
    if variable_forzada and str(variable_forzada).startswith(PREFIJO_SELECCION_SEVERIDAD):
        if tabla_forzada != "personas":
            raise ValueError("La selección de grado P32 solo es válida para personas.")
        codigo = str(variable_forzada).removeprefix(PREFIJO_SELECCION_SEVERIDAD)
        if codigo not in SEVERIDADES:
            raise ValueError("El grado de dificultad seleccionado no existe.")
        return _intencion_dimensiones(consulta, codigo)

    if _es_tipo_discapacidad(q):
        severidad = _severidad_explicita(q)
        if severidad is None:
            # "discapacidad severa" tampoco se fuerza a una categoría P32: el
            # diccionario no establece una equivalencia metodológica.
            raise AmbiguedadVariable(
                "Para comparar las seis dimensiones de la pregunta 32, selecciona "
                "el grado de dificultad que deseas usar en todas ellas.",
                _opciones_severidad(),
            )
        return _intencion_dimensiones(consulta, severidad)

    dimension = _dimension_mencionada(q)
    if dimension:
        return _intencion_dimension_individual(consulta, dimension)

    return _resolver_discapacidad_general(q)
