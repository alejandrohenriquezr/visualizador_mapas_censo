# -*- coding: utf-8 -*-
"""
Ejecuta la intención estructurada (ver nl_parser.py) contra:
  - los archivos parquet del Censo 2024 (datos/*.parquet), usando DuckDB
  - la cartografía CPV24 (cartografia/Cartografia_censo2024_Pais.gdb),
    usando GeoPandas/Fiona

y devuelve un GeoJSON listo para pintar en el mapa (Leaflet).
"""
import difflib
from pathlib import Path

import duckdb
import geopandas as gpd

from dictionary import VARIABLES, TABLAS_PARQUET

BASE_DIR = Path(__file__).resolve().parent.parent
DATOS_DIR = BASE_DIR / "datos"
GDB_PATH = BASE_DIR / "cartografia" / "Cartografia_censo2024_Pais.gdb"

# Nivel geográfico -> (columna en el parquet, capa "ideal" del gdb, campo llave en el gdb)
NIVELES = {
    "region": {"col_parquet": "region", "capa_gdb": "Regional_CPV24", "campo_gdb": "COD_REGION", "campo_nombre": "REGION"},
    "provincia": {"col_parquet": "provincia", "capa_gdb": "Provincial_CPV24", "campo_gdb": "COD_PROVINCIA", "campo_nombre": "PROVINCIA"},
    "comuna": {"col_parquet": "comuna", "capa_gdb": "Comunal_CPV24", "campo_gdb": "CUT", "campo_nombre": "COMUNA"},
}

_capas_cache = None


def _listar_capas():
    global _capas_cache
    if _capas_cache is None:
        _capas_cache = gpd.list_layers(GDB_PATH)["name"].tolist() if GDB_PATH.exists() else []
    return _capas_cache


def _resolver_capa(nombre_ideal: str) -> str:
    """Encuentra el nombre real de la capa dentro del .gdb, por si difiere
    levemente del nombre del diccionario (mayúsculas, sufijos, etc.)."""
    capas = _listar_capas()
    if not capas:
        raise FileNotFoundError(
            f"No se encontró la geodatabase en '{GDB_PATH}'. Verifica la carpeta 'cartografia/'."
        )
    if nombre_ideal in capas:
        return nombre_ideal
    coincidencia = difflib.get_close_matches(nombre_ideal, capas, n=1, cutoff=0.4)
    if coincidencia:
        return coincidencia[0]
    raise ValueError(f"No se encontró una capa similar a '{nombre_ideal}'. Capas disponibles: {capas}")


def _ruta_parquet(tabla: str) -> Path:
    ruta = DATOS_DIR / TABLAS_PARQUET[tabla]
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró '{ruta}'. Verifica la carpeta 'datos/'.")
    return ruta


def _construir_sql(intencion: dict, nivel_info: dict, ruta_parquet: Path) -> str:
    tabla = intencion["tabla"]
    variable = intencion["variable"]
    valor = intencion.get("categoria_valor")
    operacion = intencion.get("operacion", "conteo")
    col_geo = nivel_info["col_parquet"]

    filtros = []
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if f_nivel and f_codigo is not None and f_nivel in NIVELES:
        col_filtro = NIVELES[f_nivel]["col_parquet"]
        filtros.append(f"{col_filtro} = {int(f_codigo)}")

    origen = f"read_parquet('{ruta_parquet.as_posix()}')"

    if operacion == "promedio":
        # se descartan códigos negativos típicos de "no aplica"/"no responde"
        filtros.append(f"TRY_CAST({variable} AS DOUBLE) IS NOT NULL")
        filtros.append(f"{variable} >= 0")
        where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        sql = f"""
            SELECT {col_geo} AS codigo, AVG(TRY_CAST({variable} AS DOUBLE)) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """
        return sql

    if operacion == "porcentaje":
        where_total = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        filtros_num = list(filtros)
        if valor is not None:
            filtros_num.append(f"CAST({variable} AS VARCHAR) = '{valor}'")
        where_num = ("WHERE " + " AND ".join(filtros_num)) if filtros_num else ""
        sql = f"""
            WITH total AS (
                SELECT {col_geo} AS codigo, COUNT(*) AS n_total
                FROM {origen}
                {where_total}
                GROUP BY {col_geo}
            ),
            numerador AS (
                SELECT {col_geo} AS codigo, COUNT(*) AS n_num
                FROM {origen}
                {where_num}
                GROUP BY {col_geo}
            )
            SELECT total.codigo AS codigo,
                   100.0 * COALESCE(numerador.n_num, 0) / total.n_total AS valor
            FROM total
            LEFT JOIN numerador ON total.codigo = numerador.codigo
        """
        return sql

    # operacion == "conteo"
    if valor is not None:
        filtros.append(f"CAST({variable} AS VARCHAR) = '{valor}'")
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    sql = f"""
        SELECT {col_geo} AS codigo, COUNT(*) AS valor
        FROM {origen}
        {where}
        GROUP BY {col_geo}
    """
    return sql


def ejecutar_consulta(intencion: dict) -> dict:
    nivel = intencion.get("nivel_geografico", "comuna")
    if nivel not in NIVELES:
        nivel = "comuna"
    nivel_info = NIVELES[nivel]

    ruta_parquet = _ruta_parquet(intencion["tabla"])
    sql = _construir_sql(intencion, nivel_info, ruta_parquet)
    df = duckdb.sql(sql).df()
    df["codigo"] = df["codigo"].astype("Int64")

    capa_real = _resolver_capa(nivel_info["capa_gdb"])
    gdf = gpd.read_file(GDB_PATH, layer=capa_real)
    gdf[nivel_info["campo_gdb"]] = gdf[nivel_info["campo_gdb"]].astype("Int64")

    gdf = gdf.merge(df, left_on=nivel_info["campo_gdb"], right_on="codigo", how="left")
    gdf["valor"] = gdf["valor"].fillna(0)

    # Reproyectar a WGS84 (lat/lon) para Leaflet, y simplificar geometría
    # para que el mapa cargue rápido en el navegador.
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf["geometry"].simplify(0.0005, preserve_topology=True)

    columnas_salida = ["geometry", "valor", nivel_info["campo_nombre"], nivel_info["campo_gdb"]]
    columnas_salida = [c for c in columnas_salida if c in gdf.columns]
    gdf_salida = gdf[columnas_salida].rename(columns={
        nivel_info["campo_nombre"]: "nombre",
        nivel_info["campo_gdb"]: "codigo",
    })

    return {
        "geojson": gdf_salida.__geo_interface__,
        "nivel_geografico": nivel,
        "valores": {
            "min": float(gdf_salida["valor"].min()),
            "max": float(gdf_salida["valor"].max()),
        },
    }
