# -*- coding: utf-8 -*-
"""Resolutores deterministas para expresiones coloquiales y territorios específicos."""
from __future__ import annotations

import json
import re
from pathlib import Path

from dictionary import (
    VARIABLES, _norm, categorias_validas, detectar_operacion,
    buscar_geografia, nombres_geograficos,
)

BASE_DIR = Path(__file__).resolve().parent
with open(BASE_DIR / "semantic_aliases.json", encoding="utf-8") as f:
    ALIASES = json.load(f)


def _patron(frase: str):
    frase = _norm(frase).strip()
    return re.compile(r"(?<![a-z0-9])" + re.escape(frase) + r"(?![a-z0-9])")


def resolver_rasgo_booleano(consulta: str):
    """Resuelve rasgos Sí/No cuando el texto identifica inequívocamente la variable."""
    q = _norm(consulta)
    operacion = detectar_operacion(q)
    if operacion not in ("conteo", "porcentaje"):
        return None
    coincidencias = []
    for item in ALIASES.get("rasgos_booleanos", []):
        for frase in item.get("patrones", []):
            m = _patron(frase).search(q)
            if m:
                coincidencias.append((len(frase), m.start(), m.end(), item, frase))
                break
    if not coincidencias:
        return None
    coincidencias.sort(reverse=True, key=lambda x: x[0])
    # Si se mencionan explícitamente dos tecnologías distintas, no se adivina una.
    variables = {(c[3]["tabla"], c[3]["variable"]) for c in coincidencias}
    if len(variables) != 1:
        return None
    _, inicio, fin, item, frase = coincidencias[0]
    tabla, variable = item["tabla"], item["variable"]
    if variable not in VARIABLES[tabla]["variables"]:
        raise ValueError(f"Alias configurado para una variable inexistente: {tabla}.{variable}")

    contexto_previo = q[max(0, inicio - 50):inicio]
    contexto_total = q[max(0, inicio - 20):min(len(q), fin + 20)]
    negativo = bool(re.search(
        r"\b(?:sin|no\s+(?:tiene|tienen|dispone|disponen|cuenta|cuentan)(?:\s+con)?)\b",
        contexto_previo + " " + contexto_total,
    ))
    codigo = str(item["no"] if negativo else item["si"])
    if codigo not in {str(c) for c in VARIABLES[tabla]["variables"][variable]["categorias"]}:
        raise ValueError(f"Código booleano {codigo} no existe en {tabla}.{variable}")
    intencion = {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": codigo,
        "operacion": operacion,
        "indicador_descripcion": (
            ("Porcentaje de " if operacion == "porcentaje" else "Cantidad de ")
            + ("unidades sin " if negativo else "")
            + item.get("descripcion", variable)
        ),
        "_origen_interpretacion": "alias_booleano",
    }
    if operacion == "porcentaje":
        intencion["denominador_valores"] = categorias_validas(tabla, variable)
    return intencion


def _indice_territorios_especificos():
    """Códigos territoriales específicos normalizados: países, continentes y Chile."""
    fuente = VARIABLES.get("geografia", {}).get("territoriales_especificos", {})
    salida = {}
    for codigo, etiqueta in fuente.items():
        try:
            if int(str(codigo)) >= 1000:
                continue  # desde 1000 comienzan regiones/comunas chilenas
        except ValueError:
            continue
        nombre = _norm(etiqueta).strip()
        # Quita aclaraciones parentéticas para permitir "Venezuela" y "Bolivia".
        corto = re.sub(r"\s*\([^)]*\)\s*", " ", nombre)
        corto = re.sub(r"\s+", " ", corto).strip()
        salida[corto] = (str(codigo), etiqueta)
        salida[nombre] = (str(codigo), etiqueta)
    # Alias/demónimos documentados. El contexto decidirá nacimiento/nacionalidad.
    for pais, variantes in ALIASES.get("paises_alias", {}).items():
        objetivo = next((v for k, v in salida.items() if k == _norm(pais)), None)
        if objetivo:
            for variante in variantes:
                salida[_norm(variante)] = objetivo
    return salida


_TERRITORIOS_ESP = _indice_territorios_especificos()


def detectar_territorio_especifico(consulta: str):
    """Devuelve el territorio específico más largo mencionado en el texto.

    Antes de buscar países/demónimos retira nombres de regiones, provincias y
    comunas ya reconocidos. Esto evita, por ejemplo, interpretar la palabra
    "chilena" dentro de "Magallanes y de la Antártica Chilena" como una
    referencia a nacionalidad.
    """
    q = _norm(consulta)
    for geo in buscar_geografia(consulta, top_n=100):
        for nombre in nombres_geograficos(geo):
            if len(nombre) >= 4:
                q = re.sub(r"\b" + re.escape(nombre) + r"\b", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    hallados = []
    for alias, (codigo, etiqueta) in _TERRITORIOS_ESP.items():
        if len(alias) < 4:
            continue
        if _patron(alias).search(q):
            hallados.append((len(alias), alias, codigo, etiqueta))
    if not hallados:
        return None
    hallados.sort(reverse=True)
    _, alias, codigo, etiqueta = hallados[0]
    return {"alias": alias, "codigo": codigo, "etiqueta": etiqueta}


def concepto_territorio_especifico(consulta: str):
    """Identifica si el territorio alude a nacimiento, nacionalidad, residencia o trabajo."""
    q = _norm(consulta)
    if re.search(r"\b(?:nacimiento|nacer|nacid[oa]s?|nacio|nacieron)\b", q):
        return "nacimiento"
    if re.search(r"\b(?:nacionalidad|nacional(?:es)?)\b", q):
        return "nacionalidad"
    if (re.search(r"\b(?:vivia|residia|residencia)\b", q)
            and re.search(r"\b(?:2019|hace\s+(?:5|cinco)\s+anos?)\b", q)):
        return "residencia_2019"
    if re.search(r"\b(?:lugar\s+de\s+trabajo|trabaja|trabajan|trabajaba)\b", q):
        return "trabajo"
    return None


def resolver_territorio_especifico(consulta: str):
    """Resuelve país/territorio específico solo cuando el concepto es explícito.

    Si aparece un demónimo sin decir nacimiento o nacionalidad, devuelve un
    marcador de ambigüedad para que nl_parser ofrezca ambas variables.
    """
    territorio = detectar_territorio_especifico(consulta)
    if not territorio:
        return None
    concepto = concepto_territorio_especifico(consulta)
    q = _norm(consulta)

    if concepto is None:
        # Los nombres de países precedidos por "en" pueden describir lugar,
        # pero un demónimo desnudo ("venezolanos") no define nacimiento/nacionalidad.
        demomino = any(
            _patron(variante).search(q)
            for variantes in ALIASES.get("paises_alias", {}).values()
            for variante in variantes
        )
        if demomino:
            return {"_ambiguedad": "nacimiento_nacionalidad", "territorio": territorio}
        return None

    operacion = detectar_operacion(consulta)
    if operacion not in ("conteo", "porcentaje"):
        return None

    codigo = territorio["codigo"]
    etiqueta = territorio["etiqueta"]

    # En "nacidas fuera de Chile", Chile delimita la exclusión y no es la
    # categoría objetivo. La regla histórica de "otro país" resuelve el caso.
    if (codigo == "152" and concepto == "nacimiento"
            and re.search(r"\b(?:fuera de chile|extranjero|otro pais)\b", q)):
        return None

    # Chile se resuelve mejor con las variables recodificadas Sí/No.
    if codigo == "152" and concepto == "nacimiento":
        variable, categoria = "p25_lug_nacimiento_rec", "1"
    elif codigo == "152" and concepto == "nacionalidad":
        variable, categoria = "p27_nacionalidad_rec", "1"
    else:
        variables = {
            "nacimiento": "p25_lug_nacimiento_esp",
            "nacionalidad": "p27_nacionalidad_esp",
            "residencia_2019": "p24_lug_resid5_esp",
            "trabajo": "p44_lug_trab_esp",
        }
        variable = variables[concepto]
        categoria = codigo

    categorias = VARIABLES["personas"]["variables"][variable]["categorias"]
    if str(categoria) not in {str(c) for c in categorias}:
        return None
    sustantivo = {
        "nacimiento": "personas nacidas en",
        "nacionalidad": "personas de nacionalidad de",
        "residencia_2019": "personas que residían en 2019 en",
        "trabajo": "personas cuyo lugar de trabajo está en",
    }[concepto]
    intencion = {
        "tabla": "personas",
        "variable": variable,
        "categoria_valor": str(categoria),
        "operacion": operacion,
        "indicador_descripcion": (
            ("Porcentaje de " if operacion == "porcentaje" else "Cantidad de ")
            + f"{sustantivo} {etiqueta}"
        ),
        "_origen_interpretacion": "territorio_especifico",
    }
    if operacion == "porcentaje":
        intencion["denominador_valores"] = categorias_validas("personas", variable)
    return intencion
