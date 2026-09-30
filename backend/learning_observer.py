# -*- coding: utf-8 -*-
"""Señales de aprendizaje silencioso del Visor Censo.

Este módulo NO decide, NO bloquea y NO modifica la interpretación ni la respuesta.
Solo transforma metadatos ya generados por el visor en señales de diagnóstico y
un puntaje de riesgo "sombra" para evaluación posterior.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(texto: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9áéíóúüñ%]+", " ", s)).strip()


def _hojas_ast(nodo: Any) -> list[dict]:
    if not isinstance(nodo, dict):
        return []
    if nodo.get("op") in {"and", "or"}:
        out: list[dict] = []
        for item in nodo.get("args") or []:
            out.extend(_hojas_ast(item))
        return out
    if nodo.get("op") == "not":
        return _hojas_ast(nodo.get("arg"))
    return [nodo]


def _tablas_plan(plan: dict) -> set[str]:
    tablas: set[str] = set()
    if plan.get("entidad_objetivo"):
        tablas.add(str(plan["entidad_objetivo"]))
    for d in plan.get("dimensiones") or []:
        if d.get("tabla"):
            tablas.add(str(d["tabla"]))
    medida = plan.get("medida") or {}
    if medida.get("tabla"):
        tablas.add(str(medida["tabla"]))
    for nodo in (plan.get("filtro_ast"), plan.get("universo_ast")):
        for hoja in _hojas_ast(nodo):
            if hoja.get("tabla"):
                tablas.add(str(hoja["tabla"]))
            for sf in hoja.get("subfiltros") or []:
                if sf.get("tabla"):
                    tablas.add(str(sf["tabla"]))
    for f in plan.get("filtros") or []:
        if isinstance(f, dict) and f.get("tabla"):
            tablas.add(str(f["tabla"]))
    return tablas


def construir_senales(
    pregunta: str,
    interpretacion: dict | None,
    respuesta: dict | None = None,
    seleccion: dict | None = None,
) -> dict:
    """Extrae señales estructuradas sin consultar microdatos ni llamar al LLM."""
    interp = interpretacion or {}
    resp = respuesta or {}
    seleccion = seleccion or {}
    plan = interp.get("plan_cruce") or {}
    filtros = (_hojas_ast(plan.get("filtro_ast")) if plan.get("filtro_ast")
               else [f for f in (plan.get("filtros") or []) if isinstance(f, dict)])
    dimensiones = plan.get("dimensiones") or []
    tablas = _tablas_plan(plan)

    q = _norm(pregunta)
    tokens = [t for t in q.split() if t]
    terminos_ambiguos = interp.get("terminos_ambiguos") or []
    aliases = interp.get("aliases_aplicados") or []
    correcciones = interp.get("correcciones_ortograficas") or []
    selecciones_usuario = sum(bool(seleccion.get(k)) for k in (
        "tabla_seleccionada", "variable_seleccionada",
        "operacion_seleccionada", "denominador_seleccionado",
    ))

    return {
        "longitud_caracteres": len(str(pregunta or "")),
        "n_tokens": len(tokens),
        "tiene_porcentaje": bool(re.search(r"\b(?:porcentaje|proporcion|tasa|indice|razon)\b|%", q)),
        "tiene_negacion": bool(re.search(r"\b(?:no|sin|excepto|excluye|excluir)\b", q)),
        "tiene_or": bool(re.search(r"\bo\b", q)),
        "tiene_rango_numerico": bool(re.search(r"\d+\s*(?:-|a|y)\s*\d+|(?:>=|<=|>|<)\s*\d+", str(pregunta or ""))),
        "tabla": interp.get("tabla"),
        "variable": interp.get("variable"),
        "operacion": interp.get("operacion"),
        "nivel_geografico": interp.get("nivel_geografico"),
        "tipo_consulta": interp.get("tipo_consulta"),
        "origen_interpretacion": interp.get("origen"),
        "n_dimensiones": len(dimensiones),
        "n_filtros": len(filtros),
        "n_tablas_plan": len(tablas),
        "tablas_plan": sorted(tablas),
        "n_terminos_ambiguos": len(terminos_ambiguos),
        "n_aliases": len(aliases),
        "n_correcciones": len(correcciones),
        "denominador_requirio_confirmacion": bool(interp.get("denominador_requirio_confirmacion")),
        "n_selecciones_usuario": selecciones_usuario,
        "cache_aprobada": bool(resp.get("cache_aprobada")),
        "tipo_visualizacion": resp.get("tipo_visualizacion"),
        "piramide_disponible": bool((resp.get("piramide") or {}).get("disponible")),
    }


def riesgo_sombra(senales: dict) -> float:
    """Heurística inicial solo para medir; no interviene en producción."""
    r = 0.04
    if senales.get("denominador_requirio_confirmacion"):
        r += 0.35
    r += min(int(senales.get("n_terminos_ambiguos") or 0) * 0.08, 0.24)
    if int(senales.get("n_tablas_plan") or 0) >= 2:
        r += 0.12
    if int(senales.get("n_dimensiones") or 0) >= 2:
        r += 0.08
    if int(senales.get("n_filtros") or 0) >= 3:
        r += 0.06
    if int(senales.get("n_selecciones_usuario") or 0) > 0:
        r += 0.10
    if senales.get("tiene_porcentaje") and not senales.get("operacion"):
        r += 0.16
    if not senales.get("variable") and not senales.get("tipo_consulta"):
        r += 0.18
    if senales.get("tiene_or"):
        r += 0.05
    if senales.get("tiene_negacion"):
        r += 0.04
    if senales.get("cache_aprobada"):
        r -= 0.12
    return round(max(0.0, min(1.0, r)), 4)
