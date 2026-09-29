# -*- coding: utf-8 -*-
"""Benchmark offline de simplificacion cartografica sobre la FileGDB real."""
from __future__ import annotations

import argparse
import gzip
import math
from time import perf_counter

import geopandas as gpd
import pandas as pd
import shapely

from main import GDB_PATH, NIVELES, _resolver_capa


def _coordenadas(serie):
    return int(sum(shapely.get_num_coordinates(geom) for geom in serie if geom is not None))


def _serializar(gdf, nivel):
    info = NIVELES[nivel]
    centros = gdf.geometry.representative_point()
    salida = gdf[["geometry", info["campo_nombre"], info["campo_gdb"]]].copy()
    salida["centro_lon"] = centros.x
    salida["centro_lat"] = centros.y
    salida = salida.rename(
        columns={info["campo_nombre"]: "nombre", info["campo_gdb"]: "codigo"}
    )
    raw = salida.to_json(drop_id=True, ensure_ascii=False).encode("utf-8")
    gz = gzip.compress(raw, compresslevel=5, mtime=0)
    return len(raw), len(gz)


def _leer(nivel):
    info = NIVELES[nivel]
    capa = _resolver_capa(info["capa_gdb"])
    gdf = gpd.read_file(GDB_PATH, layer=capa)
    if gdf.crs is None:
        raise RuntimeError(f"La capa {capa} no tiene CRS")
    campos = {"geometry", info["campo_gdb"], info["campo_nombre"]}
    campos.update(v["campo_gdb"] for v in NIVELES.values())
    return gdf[[c for c in gdf.columns if c in campos]].to_crs(4326)


def medir(nivel, tolerancias):
    gdf = _leer(nivel)
    base_area = gdf.to_crs(6933).geometry.area
    base_coords = _coordenadas(gdf.geometry)
    filas = []

    for tolerancia in tolerancias:
        inicio = perf_counter()
        simplificada = gdf.copy()
        simplificada["geometry"] = gdf.geometry.simplify(
            tolerancia, preserve_topology=True
        )
        coords = _coordenadas(simplificada.geometry)
        area = simplificada.to_crs(6933).geometry.area
        denom_total = float(base_area.sum()) or 1.0
        error_area_total = float((area - base_area).abs().sum() / denom_total * 100.0)

        base_segura = base_area.where(base_area > 0)
        errores_rel = ((area - base_area).abs() / base_segura * 100.0).replace(
            [math.inf, -math.inf], pd.NA
        ).dropna()
        error_area_max = float(errores_rel.max()) if len(errores_rel) else 0.0

        raw, gz = _serializar(simplificada, nivel)
        filas.append(
            {
                "nivel": nivel,
                "tolerancia": tolerancia,
                "features": len(simplificada),
                "coords": coords,
                "reduccion_coords_pct": 100.0 * (1.0 - coords / max(base_coords, 1)),
                "raw_bytes": raw,
                "gzip_bytes": gz,
                "reduccion_gzip_vs_raw_pct": 100.0 * (1.0 - gz / max(raw, 1)),
                "error_area_total_pct": error_area_total,
                "error_area_max_pct": error_area_max,
                "invalidas": int((~simplificada.geometry.is_valid).sum()),
                "vacias": int(simplificada.geometry.is_empty.sum()),
                "segundos": perf_counter() - inicio,
            }
        )
    return filas


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--niveles", default="region,provincia,comuna")
    p.add_argument(
        "--tolerancias",
        default="0.0005,0.00075,0.001,0.0015,0.002,0.003,0.005,0.01",
    )
    args = p.parse_args()

    niveles = [x.strip() for x in args.niveles.split(",") if x.strip()]
    tolerancias = [float(x.strip()) for x in args.tolerancias.split(",") if x.strip()]
    print(
        "nivel\ttolerancia\tfeatures\tcoords\treduccion_coords_pct\t"
        "raw_bytes\tgzip_bytes\treduccion_gzip_vs_raw_pct\t"
        "error_area_total_pct\terror_area_max_pct\tinvalidas\tvacias\tsegundos"
    )
    for nivel in niveles:
        if nivel not in NIVELES:
            raise SystemExit(f"Nivel no valido: {nivel}")
        for fila in medir(nivel, tolerancias):
            print(
                f"{fila['nivel']}\t{fila['tolerancia']:.6f}\t{fila['features']}\t"
                f"{fila['coords']}\t{fila['reduccion_coords_pct']:.2f}\t"
                f"{fila['raw_bytes']}\t{fila['gzip_bytes']}\t"
                f"{fila['reduccion_gzip_vs_raw_pct']:.2f}\t"
                f"{fila['error_area_total_pct']:.4f}\t{fila['error_area_max_pct']:.4f}\t"
                f"{fila['invalidas']}\t{fila['vacias']}\t{fila['segundos']:.3f}"
            )


if __name__ == "__main__":
    main()
