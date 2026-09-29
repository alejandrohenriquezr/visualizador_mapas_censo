# -*- coding: utf-8 -*-
"""Mide transferencia cartografica cruda vs gzip a traves del frontend."""
from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.request


def descargar(base: str, nivel: str, encoding: str):
    url = f"{base.rstrip('/')}/api/geometrias/{nivel}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/geo+json",
            "Accept-Encoding": encoding,
        },
    )
    inicio = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        cuerpo = r.read()
        headers = {str(k).lower(): str(v) for k, v in r.headers.items()}
    duracion = time.perf_counter() - inicio
    return cuerpo, headers, duracion


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8010")
    p.add_argument(
        "--niveles",
        default="region,provincia,comuna",
        help="Lista separada por comas",
    )
    args = p.parse_args()

    print("nivel\traw_bytes\tgzip_bytes\treduccion_pct\traw_s\tgzip_s")
    for nivel in [x.strip() for x in args.niveles.split(",") if x.strip()]:
        raw, h_raw, t_raw = descargar(args.base, nivel, "identity")
        gz, h_gz, t_gz = descargar(args.base, nivel, "gzip")
        if h_gz.get("content-encoding", "").lower() == "gzip":
            descomprimido = gzip.decompress(gz)
        else:
            descomprimido = gz
        if descomprimido != raw:
            raise RuntimeError(f"El contenido gzip de {nivel} no coincide con el original")
        reduccion = 100.0 * (1.0 - len(gz) / max(len(raw), 1))
        print(
            f"{nivel}\t{len(raw)}\t{len(gz)}\t{reduccion:.2f}\t"
            f"{t_raw:.3f}\t{t_gz:.3f}"
        )


if __name__ == "__main__":
    main()
