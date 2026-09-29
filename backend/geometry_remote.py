# -*- coding: utf-8 -*-
"""Adaptador de cartografia remota para la arquitectura 5svc."""
from functools import lru_cache
from urllib.parse import urlencode
import json
import os
import urllib.request

BASE_URL = os.getenv("CARTOGRAPHY_URL", "http://cartography:8090").rstrip("/")


def _get_json(path, timeout=30):
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _query(filtro_nivel=None, filtro_codigo=None):
    query = {}
    if filtro_nivel:
        query["filtro_nivel"] = filtro_nivel
    if filtro_codigo is not None:
        query["filtro_codigo"] = int(filtro_codigo)
    return "?" + urlencode(query) if query else ""


@lru_cache(maxsize=128)
def referencia_geometria_remota(nivel, filtro_nivel=None, filtro_codigo=None):
    return _get_json(
        f"/api/referencia/{nivel}" + _query(filtro_nivel, filtro_codigo), timeout=15
    )


def obtener_geometria_serializada_remota(nivel, filtro_nivel=None, filtro_codigo=None):
    ref = referencia_geometria_remota(nivel, filtro_nivel, filtro_codigo)
    path = f"/api/geometrias/{nivel}" + _query(filtro_nivel, filtro_codigo)
    request = urllib.request.Request(
        BASE_URL + path, headers={"Accept": "application/geo+json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read(), ref["version"]


def precalentar_geometrias_remoto(niveles=None):
    for nivel in niveles or ("region", "comuna", "provincia"):
        obtener_geometria_serializada_remota(nivel)


def estado_precalentamiento_remoto():
    try:
        return _get_json("/api/salud", timeout=5).get("geometrias", {})
    except Exception as exc:
        return {
            "estado": "no_disponible",
            "niveles_listos": [],
            "errores": {"cartography": str(exc)},
        }
