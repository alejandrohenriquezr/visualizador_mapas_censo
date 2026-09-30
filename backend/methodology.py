# -*- coding: utf-8 -*-
"""Metadatos metodológicos explícitos para Universo y Fórmula de exportaciones.

Las reglas base provienen del Manual Censal CPV 2024 y se complementan con
los códigos especiales definidos en ``data/diccionario_variables.json``.
No reconstruye ni altera el cálculo: describe en lenguaje legible el plan de
consulta que ya ejecutó el visor.
"""
from __future__ import annotations

from pathlib import Path
import json
import re

from dictionary import VARIABLES, es_categoria_invalida

_BASE = Path(__file__).resolve().parent.parent
_CATALOGO_PATH = _BASE / "data" / "universos_variables.json"
try:
    CATALOGO = json.loads(_CATALOGO_PATH.read_text(encoding="utf-8"))
except Exception:
    CATALOGO = {}


def _meta(tabla, variable):
    return (CATALOGO.get(str(tabla), {}) or {}).get(str(variable), {}) or {}


def _descripcion(tabla, variable):
    info = VARIABLES.get(tabla, {}).get("variables", {}).get(variable, {})
    return str(info.get("descripcion") or variable or "").strip()


def _etiqueta_categoria(tabla, variable, valores, etiqueta=None):
    # Para la documentación metodológica se prefieren las etiquetas oficiales
    # del diccionario (p. ej. código 2 = «No») por sobre aliases coloquiales
    # usados internamente por el planificador (p. ej. «Sin internet fija»).
    cats = VARIABLES.get(tabla, {}).get("variables", {}).get(variable, {}).get("categorias", {})
    valores = list(valores or [])
    if valores and all(str(v) in cats for v in valores):
        return " / ".join(str(cats[str(v)]) for v in valores)
    if etiqueta:
        return str(etiqueta)
    return " / ".join(str(cats.get(str(v), v)) for v in valores)


def _nombre_territorio(nivel, codigo):
    if codigo in (None, ""):
        return ""
    geo = VARIABLES.get("geografia", {}).get(nivel, {})
    for clave, nombre in geo.items():
        try:
            if str(clave).isdigit() and str(codigo).isdigit() and int(clave) == int(codigo):
                return str(nombre)
        except Exception:
            pass
    return str(codigo)


def _simbolo_rango(nodo):
    minimo, maximo = nodo.get("minimo"), nodo.get("maximo")
    inc_min = nodo.get("incluir_minimo", True)
    inc_max = nodo.get("incluir_maximo", True)
    if minimo is not None and maximo is not None:
        if inc_min and inc_max:
            return f"entre {minimo} y {maximo}, ambos incluidos"
        izq = ">=" if inc_min else ">"
        der = "<=" if inc_max else "<"
        return f"{izq} {minimo} y {der} {maximo}"
    if minimo is not None:
        return f"{'>=' if inc_min else '>'} {minimo}"
    if maximo is not None:
        return f"{'<=' if inc_max else '<'} {maximo}"
    return "con valor válido"


def _render_hoja(nodo):
    tipo = nodo.get("tipo")
    tabla, variable = nodo.get("tabla"), nodo.get("variable")
    desc = _descripcion(tabla, variable)
    if tipo == "categoria":
        etiqueta = _etiqueta_categoria(tabla, variable, nodo.get("valores"), nodo.get("etiqueta"))
        neg = nodo.get("modo") == "not_in" or nodo.get("_negado")
        return f"{desc} {'!=' if neg else '='} {etiqueta}"
    if tipo == "rango":
        return f"{desc} {_simbolo_rango(nodo)}"
    if tipo == "comparacion":
        op = nodo.get("operador") or "="
        valor = nodo.get("valor")
        cats = VARIABLES.get(tabla, {}).get("variables", {}).get(variable, {}).get("categorias", {})
        etiqueta = cats.get(str(valor), valor)
        return f"{desc} {op} {etiqueta}"
    if tipo in {"existe_en_hogar", "todos_en_hogar", "conteo_en_hogar"}:
        pref = {
            "existe_en_hogar": "Existe al menos una persona del hogar que cumple",
            "todos_en_hogar": "Todas las personas del hogar cumplen",
            "conteo_en_hogar": "Conteo de personas del hogar que cumplen",
        }[tipo]
        sub = nodo.get("subfiltros") or []
        partes = [_render_ast(x) for x in sub]
        partes = [p for p in partes if p]
        return pref + (": " + " Y ".join(partes) if partes else "")
    return desc or str(nodo)


def _render_ast(nodo):
    if not isinstance(nodo, dict):
        return ""
    op = nodo.get("op")
    if op in {"and", "or"}:
        partes = [_render_ast(x) for x in (nodo.get("args") or [])]
        partes = [p for p in partes if p]
        if not partes:
            return ""
        conector = " Y " if op == "and" else " O "
        if len(partes) == 1:
            return partes[0]
        return "(" + conector.join(partes) + ")"
    if op == "not":
        parte = _render_ast(nodo.get("arg"))
        return f"NO ({parte})" if parte else ""
    return _render_hoja(nodo)


def _filtros_plan(interp):
    plan = interp.get("plan_cruce") or {}
    if not plan:
        if interp.get("categoria_valor") is None and not interp.get("categoria_valores"):
            return ""
        tabla, variable = interp.get("tabla"), interp.get("variable")
        valores = interp.get("categoria_valores") or [interp.get("categoria_valor")]
        etiqueta = _etiqueta_categoria(tabla, variable, valores)
        return f"{_descripcion(tabla, variable)} = {etiqueta}"
    if plan.get("filtro_ast"):
        return _render_ast(plan.get("filtro_ast"))
    partes = [_render_hoja(x) for x in (plan.get("filtros") or [])]
    return " Y ".join(p for p in partes if p)


def _universo_tecnico_plan(interp):
    plan = interp.get("plan_cruce") or {}
    return _render_ast(plan.get("universo_ast")) if plan.get("universo_ast") else ""


def _variables_involucradas(interp):
    items = []
    plan = interp.get("plan_cruce") or {}

    def agregar(tabla, variable):
        par = (tabla, variable)
        if tabla and variable and par not in items:
            items.append(par)

    def recorrer(nodo):
        if not isinstance(nodo, dict):
            return
        if nodo.get("op") in {"and", "or"}:
            for x in nodo.get("args") or []:
                recorrer(x)
            return
        if nodo.get("op") == "not":
            recorrer(nodo.get("arg")); return
        agregar(nodo.get("tabla"), nodo.get("variable"))
        for x in nodo.get("subfiltros") or []:
            recorrer(x)

    if plan:
        for d in plan.get("dimensiones") or []:
            agregar(d.get("tabla"), d.get("variable"))
        if plan.get("filtro_ast"):
            recorrer(plan.get("filtro_ast"))
        else:
            for f in plan.get("filtros") or []:
                recorrer(f)
        recorrer(plan.get("universo_ast"))
        med = plan.get("medida") or {}
        agregar(med.get("tabla"), med.get("variable"))
    else:
        agregar(interp.get("tabla"), interp.get("variable"))
    return items


def _exclusiones(tabla, variable):
    cats = VARIABLES.get(tabla, {}).get("variables", {}).get(variable, {}).get("categorias", {})
    salida = []
    for codigo, etiqueta in cats.items():
        if es_categoria_invalida(codigo, etiqueta):
            salida.append(f"{codigo} ({etiqueta})")
    return salida


def _ambito_geografico(interp):
    nivel = interp.get("filtro_geografico_nivel")
    codigo = interp.get("filtro_geografico_codigo")
    if nivel and codigo not in (None, ""):
        nombre = _nombre_territorio(nivel, codigo)
        return f"Ámbito territorial: {nivel} {nombre}."
    return ""


def _universos_base(interp):
    frases = []
    for tabla, variable in _variables_involucradas(interp):
        meta = _meta(tabla, variable)
        universo = str(meta.get("universo") or "").strip()
        if universo and universo not in frases:
            frases.append(universo)
    return frases


def _exclusiones_texto(interp):
    por_var = []
    for tabla, variable in _variables_involucradas(interp):
        ex = _exclusiones(tabla, variable)
        if ex:
            por_var.append(f"{_descripcion(tabla, variable)}: " + ", ".join(ex))
    if not por_var:
        return ""
    return "Se excluyen como valores no válidos/no aplicables: " + "; ".join(por_var) + "."


def construir_universo(interp):
    """Describe el universo efectivo: aplicabilidad + validez + filtros + territorio."""
    partes = _universos_base(interp)
    universo_tecnico = _universo_tecnico_plan(interp)
    if universo_tecnico:
        partes.append("Condición de validez de la medida: " + universo_tecnico + ".")
    filtros = _filtros_plan(interp)
    if filtros:
        partes.append("Filtros efectivos de la consulta: " + filtros + ".")
    geo = _ambito_geografico(interp)
    if geo:
        partes.append(geo)
    excl = _exclusiones_texto(interp)
    if excl:
        partes.append(excl)
    # de-dup textual fragments while preserving order
    out=[]
    for p in partes:
        p=str(p).strip()
        if p and p not in out:
            out.append(p)
    return " ".join(out)


def _medida(interp):
    plan = interp.get("plan_cruce") or {}
    medida = plan.get("medida") or {}
    operacion = str(medida.get("operacion") or interp.get("operacion") or "conteo").lower()
    tabla = medida.get("tabla") or interp.get("tabla")
    variable = medida.get("variable") or interp.get("variable")
    entidad = medida.get("entidad") or plan.get("entidad_objetivo") or interp.get("entidad_objetivo") or tabla or "casos"
    return operacion, tabla, variable, entidad


def _agrupacion_texto(interp):
    nivel = str(interp.get("nivel_geografico") or "").strip().lower()
    if not nivel or nivel in {"pais", "nacional"}:
        return ""
    filtro_nivel = interp.get("filtro_geografico_nivel")
    filtro_codigo = interp.get("filtro_geografico_codigo")
    if filtro_nivel and filtro_codigo not in (None, ""):
        nombre = _nombre_territorio(filtro_nivel, filtro_codigo)
        return f" El cálculo se realiza separadamente para cada {nivel} dentro de {filtro_nivel} {nombre}."
    return f" El cálculo se realiza separadamente para cada {nivel}."


def construir_formula(interp):
    """Explica la operación con las condiciones concretas del plan ejecutado."""
    operacion, tabla, variable, entidad = _medida(interp)
    filtros = _filtros_plan(interp)
    tecnico = _universo_tecnico_plan(interp)
    condicion = filtros or tecnico
    desc = _descripcion(tabla, variable) if variable else ""
    agrupacion = _agrupacion_texto(interp)

    if operacion in {"conteo", "conteo_distinto", "count", "count_distinct"}:
        base = f"Cantidad de {entidad} = conteo distinto de {entidad}"
        if condicion:
            base += f" que cumplen simultáneamente las condiciones: {condicion}"
        return base + "." + agrupacion
    if operacion in {"promedio", "avg", "mean"}:
        nombre = desc or variable or "variable"
        return (f"Promedio de {nombre} = suma de los valores válidos de {nombre} / número de {entidad} "
                f"con valor válido de {nombre}" + (f" y que cumplen: {filtros}" if filtros else "") + "." + agrupacion)
    if operacion in {"suma", "sum"}:
        return f"Suma de {desc or variable} = suma de los valores válidos" + (f" de los casos que cumplen: {filtros}" if filtros else "") + "."
    if operacion in {"mediana", "median"}:
        return f"Mediana de {desc or variable} = mediana de los valores válidos" + (f" de los casos que cumplen: {filtros}" if filtros else "") + "."
    if operacion in {"minimo", "min"}:
        return f"Mínimo de {desc or variable} = menor valor válido" + (f" entre los casos que cumplen: {filtros}" if filtros else "") + "."
    if operacion in {"maximo", "max"}:
        return f"Máximo de {desc or variable} = mayor valor válido" + (f" entre los casos que cumplen: {filtros}" if filtros else "") + "."
    if operacion in {"porcentaje", "porcentaje_rango", "distribucion"}:
        if operacion == "distribucion":
            return ("Porcentaje de cada categoría = (número de casos válidos de la categoría / número total de casos válidos del universo efectivo) × 100"
                    + (f", aplicando además: {filtros}" if filtros else "") + ".")
        return ("Porcentaje = (número de casos que cumplen la condición / número de casos válidos del universo efectivo) × 100"
                + (f"; condición: {filtros}" if filtros else "") + ".")
    if operacion in {"razon", "ratio"}:
        factor = interp.get("factor")
        fac = f" × {factor}" if factor not in (None, 1, 1.0) else ""
        return f"Indicador = numerador / denominador{fac}, usando el universo y filtros explicitados anteriormente."
    return "Cálculo según la operación ejecutada, usando exclusivamente los casos válidos del universo y filtros explicitados."


def universo_formula_explicitos(respuesta):
    """Devuelve (universo, formula) sin reemplazar metadatos explícitos de indicadores."""
    interp = respuesta.get("interpretacion") or {}
    universo = construir_universo(interp)
    formula = construir_formula(interp)
    return universo, formula
