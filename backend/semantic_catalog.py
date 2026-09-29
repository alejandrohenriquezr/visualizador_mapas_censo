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



def _resolver_tamano_promedio_hogar(q):
    """Tamaño promedio = personas residentes en hogares / número de hogares."""
    if not re.search(r"\b(?:tamano|numero)\s+promedio\s+(?:del|de)\s+hogar\b|\bpersonas\s+por\s+hogar\b", q):
        return None
    # Se conserva una variable real de hogares para satisfacer el contrato común
    # del parser; el motor usa COUNT(*) en ambas tablas para este indicador.
    orden = VARIABLES["hogares"].get("orden") or list(VARIABLES["hogares"]["variables"])
    if not orden:
        raise ValueError("La tabla hogares no contiene variables en el diccionario.")
    return {
        "tabla": "hogares",
        "variable": orden[0],
        "categoria_valor": None,
        "operacion": "razon_tablas",
        "tabla_numerador": "personas",
        "tabla_denominador": "hogares",
        "factor": 1.0,
        # Según la estructura del proyecto, tipo_operativo=2 delimita la población
        # residente en hogares particulares y mantiene numerador/denominador comparables.
        "filtros_fijos_tablas": {
            "personas": {"tipo_operativo": 2},
            "hogares": {"tipo_operativo": 2},
        },
        "indicador_descripcion": "Tamaño promedio del hogar (personas por hogar)",
        "_origen_interpretacion": "catalogo_semantico",
    }


def resolver_indicador(consulta: str):
    """Resuelve indicadores cuya semántica o fórmula está verificada."""
    q = _norm(consulta)
    for resolver in (_resolver_tamano_promedio_hogar, _resolver_masculinidad,
                     _resolver_alfabetizacion, _resolver_viviendas_venta):
        intencion = resolver(q)
        if intencion is not None:
            return intencion
    return None
