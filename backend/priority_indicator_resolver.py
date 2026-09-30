# -*- coding: utf-8 -*-
"""Resolutores prioritarios v24 para categorías específicas e indicadores derivados.

Se ejecutan antes de los planificadores genéricos para impedir que una categoría
solicitada explícitamente (p.ej. Mapuzugún) sea interpretada como distribución y
para registrar fórmulas verificadas de indicadores demográficos/laborales.
"""
import re

from dictionary import VARIABLES, _norm, categorias_validas


def _variable_lengua_indigena():
    halladas = []
    for variable, info in VARIABLES["personas"]["variables"].items():
        desc = _norm(info.get("descripcion", ""))
        cats = info.get("categorias") or {}
        tiene_lenguas = any("mapuzugun" in _norm(et) for et in cats.values())
        if tiene_lenguas and "habla o entiende" in desc:
            halladas.append(variable)
    if len(halladas) != 1:
        raise ValueError("No se identificó de forma única la variable de lengua indígena.")
    return halladas[0]


def _categoria_lengua_solicitada(q, variable):
    """Devuelve código/etiqueta solo si la consulta nombra una lengua específica."""
    categorias = VARIABLES["personas"]["variables"][variable]["categorias"]
    contexto_lengua = bool(re.search(r"\b(?:habl\w*|entiend\w*|lengua)\b", q))
    if not contexto_lengua:
        return None
    for codigo, etiqueta in categorias.items():
        if str(codigo).startswith("-") or str(codigo).upper() == "NA":
            continue
        et = _norm(etiqueta)
        principal = re.split(r"\s*\(", et, maxsplit=1)[0].strip()
        candidatos = [principal]
        if "mapuzugun" in et:
            candidatos.append("mapuche")
        if any(c and re.search(r"\b" + re.escape(c) + r"\b", q) for c in candidatos):
            return str(codigo), str(etiqueta)
    return None


def resolver_lengua_indigena_especifica(consulta: str):
    q = _norm(consulta)
    if not re.search(r"\bpersonas?\b", q):
        return None
    variable = _variable_lengua_indigena()
    categoria = _categoria_lengua_solicitada(q, variable)
    if categoria is None:
        return None
    codigo, etiqueta = categoria
    porcentaje = bool(re.search(r"\b(?:porcentaje|proporcion)\b|%", q))
    salida = {
        "tabla": "personas",
        "variable": variable,
        "categoria_valor": codigo,
        "operacion": "porcentaje" if porcentaje else "conteo",
        "tipo_consulta": "lengua_indigena_especifica",
        "lengua_etiqueta": etiqueta,
        "indicador_descripcion": (
            f"Porcentaje de personas que hablan o entienden {etiqueta}"
            if porcentaje else f"Cantidad de personas que hablan o entienden {etiqueta}"
        ),
        "_origen_interpretacion": "regla_prioritaria_v24",
    }
    if porcentaje:
        salida["denominador_valores"] = categorias_validas("personas", variable)
    return salida


_INDICADORES = {
    "envejecimiento": {
        "patrones": (r"\bindice\s+(?:de\s+)?envejecimiento\b", r"\brazon\s+(?:de\s+)?envejecimiento\b"),
        "variable": "edad",
        "descripcion": "Índice de envejecimiento",
        "nota": "100 × población de 60 años o más / población de 0 a 14 años.",
        "universo": "Población con edad válida.",
        "formula": "Índice de envejecimiento = (población de 60 años o más / población de 0 a 14 años) × 100",
    },
    "dependencia_total": {
        "patrones": (
            r"\bindice\s+(?:de\s+)?dependencia\s+(?:total|laboral)\b",
            r"\bdependencia\s+total\b",
            r"\bdependencia\s+laboral\b",
            r"\bidd\b",
        ),
        "variable": "edad",
        "descripcion": "Índice de dependencia total (IDD)",
        "nota": "100 × (población de 0 a 14 años + población de 60 años o más) / población de 15 a 59 años.",
        "universo": "Población con edad válida.",
        "formula": "Índice de dependencia total = ((población de 0 a 14 años + población de 60 años o más) / población de 15 a 59 años) × 100",
    },
    "dependencia_juvenil": {
        "patrones": (r"\bindice\s+(?:de\s+)?dependencia\s+juvenil\b", r"\bdependencia\s+juvenil\b"),
        "variable": "edad",
        "descripcion": "Índice de dependencia juvenil",
        "nota": "100 × población de 0 a 14 años / población de 15 a 59 años.",
        "universo": "Población con edad válida.",
        "formula": "Índice de dependencia juvenil = (población de 0 a 14 años / población de 15 a 59 años) × 100",
    },
    "dependencia_mayores": {
        "patrones": (
            r"\bindice\s+(?:de\s+)?dependencia\s+(?:de\s+)?mayores\b",
            r"\bdependencia\s+(?:de\s+)?mayores\b",
            r"\bdependencia\s+(?:de\s+)?adultos?\s+mayores\b",
        ),
        "variable": "edad",
        "descripcion": "Índice de dependencia de mayores",
        "nota": "100 × población de 60 años o más / población de 15 a 59 años.",
        "universo": "Población con edad válida.",
        "formula": "Índice de dependencia de mayores = (población de 60 años o más / población de 15 a 59 años) × 100",
    },
    "tasa_ocupacion": {
        "patrones": (r"\btasa\s+(?:de\s+)?ocupacion\b",),
        "variable": "sit_fuerza_trabajo",
        "descripcion": "Tasa de ocupación",
        "nota": "100 × personas ocupadas / población de 15 años o más con situación laboral válida.",
        "universo": "Personas de 15 años o más con situación en la fuerza de trabajo válida.",
        "formula": "Tasa de ocupación = (personas ocupadas / (ocupadas + desocupadas + fuera de la fuerza de trabajo)) × 100",
    },
    "tasa_desocupacion": {
        "patrones": (
            r"\btasa\s+(?:de\s+)?desocupacion\b", r"\btasa\s+(?:de\s+)?desempleo\b",
            r"\b(?:porcentaje|proporcion)\s+(?:de\s+)?desocupacion\b",
        ),
        "variable": "sit_fuerza_trabajo",
        "descripcion": "Tasa de desocupación",
        "nota": "100 × personas desocupadas / (personas ocupadas + personas desocupadas).",
        "universo": "Personas de 15 años o más en la fuerza de trabajo, con situación laboral válida.",
        "formula": "Tasa de desocupación = (personas desocupadas / (personas ocupadas + personas desocupadas)) × 100",
    },
}


def resolver_indicador_derivado_v24(consulta: str):
    q = _norm(consulta)
    for indicador_id, meta in _INDICADORES.items():
        if any(re.search(p, q) for p in meta["patrones"]):
            variable = meta["variable"]
            if variable not in VARIABLES["personas"]["variables"]:
                raise ValueError(f"La variable requerida por {indicador_id} no existe en el diccionario.")
            return {
                "tabla": "personas",
                "variable": variable,
                "categoria_valor": None,
                "operacion": "razon",
                "tipo_consulta": "indicador_derivado_v24",
                "indicador_id": indicador_id,
                "indicador_descripcion": meta["descripcion"],
                "nota_interpretacion": meta["nota"],
                "universo": meta.get("universo"),
                "formula": meta.get("formula"),
                "_origen_interpretacion": "catalogo_indicadores_v24",
            }
    return None


def resolver_prioritario_v24(consulta: str):
    return resolver_lengua_indigena_especifica(consulta) or resolver_indicador_derivado_v24(consulta)
