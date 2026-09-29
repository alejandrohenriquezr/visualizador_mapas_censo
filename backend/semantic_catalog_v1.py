# -*- coding: utf-8 -*-
"""Catálogo de indicadores derivados del diccionario oficial del Censo.

Las reglas no fijan códigos de variables ni de categorías: los buscan por
descripción y etiqueta en ``diccionario_variables.json``, generado desde el
Excel del usuario. Así una selección comprobada antecede al LLM local.
"""
import re

from dictionary import VARIABLES, _norm, categorias_validas


def _variable_unica(tabla, patrones_descripcion):
    """Localiza una sola variable cuyo texto satisface todos los patrones."""
    halladas = []
    for variable, info in VARIABLES[tabla]["variables"].items():
        descripcion = _norm(info["descripcion"])
        if all(re.search(patron, descripcion) for patron in patrones_descripcion):
            halladas.append(variable)
    if len(halladas) != 1:
        raise ValueError(
            f"El diccionario no permite identificar de forma única el indicador en {tabla}. "
            "Revisar sus descripciones y categorías."
        )
    return halladas[0]


def _categoria_unica(tabla, variable, patrones_etiqueta):
    """Obtiene un código por la etiqueta oficial, nunca por conocimiento externo."""
    halladas = []
    categorias = VARIABLES[tabla]["variables"][variable]["categorias"]
    for codigo, etiqueta in categorias.items():
        texto = _norm(etiqueta).strip().rstrip(".")
        if any(re.fullmatch(patron, texto) for patron in patrones_etiqueta):
            halladas.append(str(codigo))
    if len(halladas) != 1:
        raise ValueError(
            f"No se encontró una categoría única para {variable} en el diccionario."
        )
    return halladas[0]


def _intencion_porcentaje(tabla, variable, categoria, descripcion, nota=None):
    intencion = {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": categoria,
        "denominador_valores": categorias_validas(tabla, variable),
        "operacion": "porcentaje",
        "indicador_descripcion": descripcion,
        "_origen_interpretacion": "catalogo_semantico",
    }
    if nota:
        intencion["nota_interpretacion"] = nota
    return intencion


def _resolver_alfabetizacion(q):
    if not re.search(r"\b(?:porcentaje|proporcion|tasa)\b|%", q):
        return None
    if not re.search(r"\b(?:alfabetizacion|alfabetizad[oa]s?|saben? leer y escribir)\b", q):
        return None
    variable = _variable_unica("personas", (r"sabe leer", r"escribir"))
    categoria = _categoria_unica("personas", variable, (r"si",))
    return _intencion_porcentaje(
        "personas", variable, categoria,
        "Porcentaje de alfabetización de personas de 5 años o más",
    )


def _resolver_viviendas_venta(q):
    if not re.search(r"\b(?:porcentaje|proporcion|tasa)\b|%", q):
        return None
    if not re.search(r"\bviviendas?\b", q) or not re.search(r"\b(?:venta|arriendo)\b", q):
        return None
    variable = _variable_unica("viviendas", (r"estado de ocupacion", r"detalle"))
    categoria = _categoria_unica("viviendas", variable, (r"en venta o arriendo",))
    return _intencion_porcentaje(
        "viviendas", variable, categoria,
        "Porcentaje de viviendas particulares en venta o arriendo",
        "El diccionario censal reúne venta y arriendo en una sola categoría; no permite separarlos.",
    )


def _resolver_masculinidad(q):
    patron = (r"\bindice\s+(?:de\s+)?(?:masculinidad|marculinidad)\b|"
              r"\brazon\s+(?:de\s+)?hombres?\s+(?:por|cada)\s+mujeres?\b")
    if not re.search(patron, q):
        return None
    variable = _variable_unica("personas", (r"\bsexo\b",))
    hombres = _categoria_unica("personas", variable, (r"hombre", r"masculino"))
    mujeres = _categoria_unica("personas", variable, (r"mujer", r"femenino"))
    return {
        "tabla": "personas",
        "variable": variable,
        "categoria_valor": None,
        "numerador_valores": [hombres],
        "denominador_valores": [mujeres],
        "factor": 100.0,
        "operacion": "razon",
        "indicador_descripcion": "Índice de masculinidad (hombres por cada 100 mujeres)",
        "_origen_interpretacion": "catalogo_semantico",
    }

def _resolver_invejecimiento(q):
    patron = (r"\bindice\s+(?:de\s+)?(?:envejecimiento|embejecimiento)\b|"
              r"\brazon\s+(?:de\s+)?mayores de 65?\s+(?:por|cada)\s+cada 100 personas menores de 15 años?\b")
    if not re.search(patron, q):
        return None
    variable = _variable_unica("personas", (r"\bedad\b",))
    mayores = _categoria_unica("personas", variable, (r"de 85 o más", r"igual o mayor a 85"))
    menores = _categoria_unica("personas", variable, (r"menores de 10", r"<15"))
    return {
        "tabla": "personas",
        "variable": variable,
        "categoria_valor": None,
        "numerador_valores": [mayores],
        "denominador_valores": [menores],
        "factor": 100.0,
        "operacion": "razon",
        "indicador_descripcion": "Índice de envejecimiento (Cantidad de personas de 65 años o más por cada 100 personas menores de 15 años.)",
        "_origen_interpretacion": "catalogo_semantico",
    }

def resolver_indicador(consulta: str):
    """Resuelve indicadores cuya semántica o fórmula está verificada."""
    q = _norm(consulta)
    for resolver in (_resolver_masculinidad, _resolver_alfabetizacion,
                     _resolver_viviendas_venta, _resolver_invejecimiento):
        intencion = resolver(q)
        if intencion is not None:
            return intencion
    return None
