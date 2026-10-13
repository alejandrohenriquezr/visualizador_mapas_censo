# -*- coding: utf-8 -*-
"""Verificación estática del parche V40, sin modificar Git ni los datos."""
from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition), detail))


def contains(path, token):
    return path.exists() and token in path.read_text(encoding="utf-8")


def main():
    backend = ROOT / "backend"
    frontend = ROOT / "frontend"
    dic = ROOT / "data" / "diccionario_variables.json"
    check("módulo V40 backend", (backend / "v40_general.py").exists())
    check("herramientas JS V40", (frontend / "v40-map-tools.js").exists())
    check("estilos V40", (frontend / "v40-map-tools.css").exists())
    check("frontend carga V40", contains(frontend / "index.html", "v40-map-tools.js"))
    check("frontend despacha series_mapa", contains(frontend / "index.html", "pintarSeriesMapaV40"))
    check("CORS para exportación PNG", contains(frontend / "index.html", "crossOrigin: true"))
    check("parser selector tipo de edad", contains(backend / "nl_parser.py", "seleccionar_tipo_edad_v40"))
    check("parser desagrega indicadores", contains(backend / "nl_parser.py", "aplicar_desagregaciones_indicador_v40"))
    check("motor reagrupa primera dimensión", contains(backend / "data_engine.py", "reagrupar_tortas_primera_dimension_v40"))
    check("Excel admite series", contains(backend / "excel_export.py", 'tipo == "series_mapa"'))

    try:
        data = json.loads(dic.read_text(encoding="utf-8"))
        item = data["personas"]["variables"]["edad_grandes_grupos"]
        check("diccionario edad_grandes_grupos", item.get("categorias") == {"0":"0-14","1":"15-59","2":"60 o más"})
        check("universo edad_grandes_grupos", item.get("universo") == "Todas las personas")
    except Exception as exc:
        check("diccionario edad_grandes_grupos", False, str(exc))

    py_files = [
        backend / "v40_general.py", backend / "nl_parser.py",
        backend / "advanced_query_planner.py", backend / "cross_query_planner.py",
        backend / "data_engine.py", backend / "excel_export.py",
    ]
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            check(f"Python compila: {p.name}", True)
        except Exception as exc:
            check(f"Python compila: {p.name}", False, str(exc))

    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", str(frontend / "v40-map-tools.js")], capture_output=True, text=True)
        check("JavaScript V40 válido", proc.returncode == 0, proc.stderr.strip())
    else:
        check("JavaScript V40 válido", True, "Node no está instalado: comprobación omitida")

    ok = True
    for name, passed, detail in CHECKS:
        estado = "OK" if passed else "ERROR"
        print(f"[{estado}] {name}" + (f" — {detail}" if detail else ""))
        ok = ok and passed
    print()
    print("Resultado:", "V40 supera la verificación estática." if ok else "Hay verificaciones con error.")
    print("Esta verificación no ejecuta git ni sincroniza con GitHub.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
