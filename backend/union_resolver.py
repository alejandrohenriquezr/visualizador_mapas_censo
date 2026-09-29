# -*- coding: utf-8 -*-
"""Resolución explícita de la ambigüedad semántica de «Unión».

En el visor, «Unión» puede significar:
1) la comuna de La Unión (código 14201),
2) parentesco: Conviviente por unión civil,
3) estado conyugal o civil: Conviviente civil (con acuerdo de unión civil).

La resolución reutiliza el selector de variables existente mediante opciones
sintéticas que el parser intercepta antes de validar nombres de variables.
"""
from __future__ import annotations

import re

from categorical_resolver import AmbiguedadVariable
from dictionary import _norm

UNION_COMUNA = "__union_comuna_la_union"
UNION_PARENTESCO = "__union_parentesco_union_civil"
UNION_ESTADO_CIVIL = "__union_estado_civil_union_civil"
CODIGO_LA_UNION = "14201"


_OPCIONES = [
    {
        "tabla": "geografia",
        "variable": UNION_COMUNA,
        "descripcion": "Comuna de La Unión (Región de Los Ríos)",
        "categorias_ejemplo": ["Territorio geográfico · comuna 14201"],
        "puntaje": 100,
    },
    {
        "tabla": "personas",
        "variable": UNION_PARENTESCO,
        "descripcion": "Parentesco: Conviviente por unión civil",
        "categorias_ejemplo": ["Pregunta de parentesco · categoría 3"],
        "puntaje": 100,
    },
    {
        "tabla": "personas",
        "variable": UNION_ESTADO_CIVIL,
        "descripcion": "Estado conyugal o civil: Conviviente civil (con acuerdo de unión civil)",
        "categorias_ejemplo": ["Estado conyugal o civil · categoría 3"],
        "puntaje": 100,
    },
]


def resolver_ambiguedad_union(texto, tabla_seleccionada=None, variable_seleccionada=None):
    """Devuelve la selección de «Unión» o fuerza una elección si corresponde."""
    if variable_seleccionada in {UNION_COMUNA, UNION_PARENTESCO, UNION_ESTADO_CIVIL}:
        return variable_seleccionada

    if re.search(r"\bunion\b", _norm(texto)):
        raise AmbiguedadVariable(
            "La palabra ‘Unión’ puede referirse a un territorio o a dos conceptos censales. "
            "Selecciona qué significado deseas usar en esta consulta.",
            list(_OPCIONES),
        )
    return None


def consulta_sin_union_territorial(texto):
    """Retira el bloque semántico de unión civil cuando se eligió la comuna.

    La idea es que, si el usuario escoge La Unión como territorio, palabras
    como «conviviente», «acuerdo» y «civil» no vuelvan a activar variables de
    parentesco o estado civil por la misma expresión ambigua.
    """
    q = _norm(texto)
    patrones = (
        r"\bconviviente(?:\s+civil)?\s+(?:por|con)\s+acuerdo\s+de\s+union\s+civil\b",
        r"\bconviviente\s+por\s+union\s+civil\b",
        r"\bunion\s+civil\b",
        r"\bla\s+union\b",
        r"\bunion\b",
    )
    for patron in patrones:
        q = re.sub(patron, " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def consulta_sin_union_geografica(texto):
    """Retira «Unión» solo para la detección geográfica.

    Mantiene el resto de la frase para que el planificador pueda resolver
    correctamente parentesco o estado conyugal cuando esa fue la elección.
    """
    q = _norm(texto)
    q = re.sub(r"\bla\s+union\b|\bunion\b", " ", q)
    return re.sub(r"\s+", " ", q).strip()
