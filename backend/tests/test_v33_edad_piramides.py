# -*- coding: utf-8 -*-
"""Pruebas estáticas mínimas del parche V33, sin requerir los parquet."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).parent.name == "tests" else Path(__file__).resolve().parent.parent
if not (ROOT / "backend").exists():
    ROOT = Path.cwd()

def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")

data = read("backend/data_engine.py")
priority = read("backend/priority_indicator_resolver.py")
pres = read("backend/presentation.py")
planner = read("backend/advanced_query_planner.py")
main = read("backend/main.py")
excel = read("backend/excel_export.py")
front = read("frontend/index.html")

# Umbral demográfico coherente 60+ / 15-59.
assert ">= 65 THEN 1 ELSE 0" not in data
assert "BETWEEN 65 AND 120 THEN 1 ELSE 0" not in data
assert "BETWEEN 15 AND 64 THEN 1 ELSE 0" not in data
assert "60 años o más" in priority and "15 a 59 años" in priority
assert "60 años o más" in pres and "15 a 59 años" in pres

# Pirámides y edad simple.
assert 'dimension.get("tipo") == "edad_simple"' in data
assert "def _config_piramide_cruce" in data
assert '"piramide": piramide' in data
assert "edad_simple = bool" in planner
assert "edad_grupo = bool" in planner
assert 'id="btn-piramide"' in front
assert 'id="piramide-edad"' in front
assert "region_default" in data
assert "actualizarPiramideEdadV33" in front
assert '"piramide": resultado.get("piramide")' in main

# Excel: todas las categorías y todas las pirámides.
assert "distribucion_completa" in data
assert "distribucion_completa" in excel
assert "def _agregar_hoja_piramides" in excel
assert 'nombre = "Piramides_edad"' in excel
assert "universo_formula_explicitos" in excel

# Cachés anteriores no deben congelar semántica obsoleta.
assert "_cache_requiere_recalculo_v33" in main
print("TEST_V33_OK")
