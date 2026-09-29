# -*- coding: utf-8 -*-
"""Microservicio de cartografia del Visor Censo 2024."""
from pathlib import Path
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import lru_cache
from threading import RLock, Thread
from time import perf_counter
from uuid import uuid4
import difflib
import hashlib
import json
import logging
import os

import pandas as pd
import geopandas as gpd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

LOG = logging.getLogger("uvicorn.error")
GDB_PATH = Path(os.getenv("CENSO_CARTOGRAFIA_GDB", "/app/cartografia/Cartografia_censo2024_Pais.gdb"))
CACHE_DIR = Path(os.getenv("CENSO_CACHE_DIR", "/app/runtime/cache"))
SIMPLIFICACION = float(os.getenv("CENSO_SIMPLIFICACION", "0.0005"))
if not 0 < SIMPLIFICACION < 1:
    raise ValueError("CENSO_SIMPLIFICACION debe estar entre 0 y 1 grado.")

NIVELES = {
    "region": {"capa_gdb": "Regional_CPV24", "campo_gdb": "COD_REGION", "campo_nombre": "REGION"},
    "provincia": {"capa_gdb": "Provincial_CPV24", "campo_gdb": "COD_PROVINCIA", "campo_nombre": "PROVINCIA"},
    "comuna": {"capa_gdb": "Comunal_CPV24", "campo_gdb": "CUT", "campo_nombre": "COMUNA"},
}
_LOCK = RLock()
_PREWARM_LOCK = RLock()
_CAPAS = None
_GDFS = {}
_JSON = {}
_FIRMAS = {}
_ESTADO = {"estado": "pendiente", "niveles_listos": [], "errores": {}}


def _listar_capas():
    global _CAPAS
    with _LOCK:
        if _CAPAS is None:
            if not GDB_PATH.exists():
                return []
            _CAPAS = gpd.list_layers(GDB_PATH)["name"].tolist()
        return list(_CAPAS)


def _resolver_capa(ideal):
    capas = _listar_capas()
    if not capas:
        raise FileNotFoundError(f"No se encontro la geodatabase: {GDB_PATH}")
    if ideal in capas:
        return ideal
    coincidencia = difflib.get_close_matches(ideal, capas, n=1, cutoff=0.4)
    if coincidencia:
        return coincidencia[0]
    raise ValueError(f"No se encontro capa similar a {ideal}. Disponibles: {capas}")


@lru_cache(maxsize=8)
def _firma(nivel):
    archivos = []
    if GDB_PATH.exists():
        entradas = GDB_PATH.rglob("*") if GDB_PATH.is_dir() else [GDB_PATH]
        for ruta in entradas:
            if ruta.is_file() and not ruta.name.lower().endswith(".lock"):
                st = ruta.stat()
                archivos.append((str(ruta.relative_to(GDB_PATH.parent)), st.st_size, st.st_mtime_ns))
    config = [
        "cartography-v31",
        str(GDB_PATH.resolve()),
        sorted(archivos),
        nivel,
        NIVELES[nivel],
        SIMPLIFICACION,
        gpd.__version__,
    ]
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:24]


def _guardar(gdf, ruta):
    temporal = ruta.with_name(f"{ruta.stem}-{uuid4().hex}.tmp.gpkg")
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(temporal, layer="capa", driver="GPKG", index=False)
        os.replace(temporal, ruta)
    finally:
        if temporal.exists():
            try:
                temporal.unlink()
            except OSError:
                pass


def _cargar(nivel):
    if nivel not in NIVELES:
        raise ValueError("Nivel geografico no valido.")
    inicio = perf_counter()
    firma = _firma(nivel)
    info = NIVELES[nivel]
    with _LOCK:
        if nivel in _GDFS and _FIRMAS.get(nivel) == firma:
            return _GDFS[nivel].copy()
        ruta = CACHE_DIR / f"{nivel}-{firma}.gpkg"
        gdf = None
        origen = "gdb"
        if ruta.exists():
            try:
                gdf = gpd.read_file(ruta, layer="capa")
                origen = "disco"
            except Exception as exc:
                LOG.warning("Cache cartografica ilegible: %s", exc)
                gdf = None
        if gdf is None:
            capa = _resolver_capa(info["capa_gdb"])
            paso = perf_counter()
            gdf = gpd.read_file(GDB_PATH, layer=capa)
            LOG.info("[cartografia] lectura_gdb[%s]=%.3fs", nivel, perf_counter() - paso)
            for campo in (info["campo_gdb"], info["campo_nombre"]):
                if campo not in gdf:
                    raise ValueError(f"La capa {capa} no contiene {campo}")
            if gdf.crs is None:
                raise ValueError(f"La capa {capa} no tiene CRS")
            campos = {"geometry", info["campo_gdb"], info["campo_nombre"]}
            campos.update(v["campo_gdb"] for v in NIVELES.values())
            gdf = gdf[[c for c in gdf.columns if c in campos]].to_crs(4326)
            gdf["geometry"] = gdf.geometry.simplify(SIMPLIFICACION, preserve_topology=True)
            _guardar(gdf, ruta)
        _GDFS[nivel] = gdf
        _FIRMAS[nivel] = firma
        LOG.info("[cartografia] geometria[%s]=%.3fs origen=%s", nivel, perf_counter() - inicio, origen)
        return gdf.copy()


def _filtrar(gdf, nivel, filtro_nivel, filtro_codigo):
    if not filtro_nivel and filtro_codigo is None:
        return gdf
    if bool(filtro_nivel) != (filtro_codigo is not None):
        raise ValueError("Filtro territorial incompleto.")
    if filtro_nivel not in NIVELES:
        raise ValueError("Nivel del filtro no valido.")
    codigo = int(filtro_codigo)
    campo = NIVELES[filtro_nivel]["campo_gdb"]
    if campo in gdf.columns:
        return gdf.loc[pd.to_numeric(gdf[campo], errors="coerce") == codigo].copy()
    orden = {"region": 0, "provincia": 1, "comuna": 2}
    if orden[filtro_nivel] > orden[nivel]:
        raise ValueError("El filtro es mas especifico que el nivel del mapa.")
    limite = _cargar(filtro_nivel)
    limite = limite.loc[pd.to_numeric(limite[campo], errors="coerce") == codigo]
    if limite.empty:
        raise ValueError("El territorio solicitado no existe en cartografia.")
    mascara = gdf.geometry.representative_point().apply(
        lambda punto: any(poligono.covers(punto) for poligono in limite.geometry)
    )
    return gdf.loc[mascara].copy()


def referencia(nivel, filtro_nivel=None, filtro_codigo=None):
    if nivel not in NIVELES:
        raise ValueError("Nivel geografico no valido.")
    if bool(filtro_nivel) != (filtro_codigo is not None):
        raise ValueError("Filtro territorial incompleto.")
    return {
        "nivel": nivel,
        "filtro_nivel": filtro_nivel,
        "filtro_codigo": int(filtro_codigo) if filtro_codigo is not None else None,
        "version": _firma(nivel),
    }


def serializar(nivel, filtro_nivel=None, filtro_codigo=None):
    ref = referencia(nivel, filtro_nivel, filtro_codigo)
    clave = (nivel, filtro_nivel, ref["filtro_codigo"], ref["version"])
    with _LOCK:
        if clave in _JSON:
            return _JSON[clave], ref["version"]
    gdf = _filtrar(_cargar(nivel), nivel, filtro_nivel, filtro_codigo)
    if gdf.empty:
        raise ValueError("No hay geometrias para el filtro solicitado.")
    info = NIVELES[nivel]
    centros = gdf.geometry.representative_point()
    salida = gdf[["geometry", info["campo_nombre"], info["campo_gdb"]]].copy()
    salida["centro_lon"] = centros.x
    salida["centro_lat"] = centros.y
    salida = salida.rename(columns={info["campo_nombre"]: "nombre", info["campo_gdb"]: "codigo"})
    contenido = salida.to_json(drop_id=True, ensure_ascii=False).encode("utf-8")
    with _LOCK:
        _JSON[clave] = contenido
    return contenido, ref["version"]


def precalentar(niveles):
    inicio = perf_counter()
    with _PREWARM_LOCK:
        _ESTADO.update(estado="en_curso", niveles_listos=[], errores={})
    for nivel in niveles:
        try:
            serializar(nivel)
            with _PREWARM_LOCK:
                _ESTADO["niveles_listos"].append(nivel)
        except Exception as exc:
            with _PREWARM_LOCK:
                _ESTADO["errores"][nivel] = str(exc)
            LOG.exception("[cartografia] precalentamiento %s", nivel)
    with _PREWARM_LOCK:
        errores = bool(_ESTADO["errores"])
        listos = bool(_ESTADO["niveles_listos"])
        _ESTADO["estado"] = "parcial" if errores and listos else "error" if errores else "listo"
        _ESTADO["duracion_segundos"] = round(perf_counter() - inicio, 3)


@asynccontextmanager
async def lifespan(app):
    niveles = [
        x.strip().lower()
        for x in os.getenv("CENSO_PRECALENTAR_GEOMETRIAS", "region,comuna,provincia").split(",")
        if x.strip()
    ]
    if niveles:
        Thread(target=precalentar, args=(niveles,), daemon=True).start()
    yield


app = FastAPI(title="Visor Censo 2024 - Cartografia", lifespan=lifespan)


@app.get("/api/salud")
def salud():
    with _PREWARM_LOCK:
        estado = deepcopy(_ESTADO)
    return {
        "estado": "ok",
        "gdb_existe": GDB_PATH.exists(),
        "gdb": str(GDB_PATH),
        "geometrias": estado,
    }


@app.get("/api/referencia/{nivel}")
def referencia_api(nivel: str, filtro_nivel: str | None = None, filtro_codigo: int | None = None):
    try:
        return referencia(nivel, filtro_nivel, filtro_codigo)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/geometrias/{nivel}")
def geometria(
    nivel: str,
    request: Request,
    filtro_nivel: str | None = None,
    filtro_codigo: int | None = None,
):
    try:
        contenido, version = serializar(nivel, filtro_nivel, filtro_codigo)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    etag = f'"{version}-{filtro_nivel or "pais"}-{filtro_codigo or "todos"}"'
    version_solicitada = request.query_params.get("v")
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=31536000, immutable"
        if version_solicitada == version
        else "no-cache",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=contenido, media_type="application/geo+json", headers=headers)
