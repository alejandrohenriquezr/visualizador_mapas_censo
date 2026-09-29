# -*- coding: utf-8 -*-
"""
Ejecuta: python diagnostico.py
Revisa que las carpetas 'datos/' y 'cartografia/' estén donde se espera,
que los parquet tengan las columnas necesarias y lista las capas reales
del .gdb (útil si sus nombres no calzan exactamente con el diccionario).
"""
from pathlib import Path
import duckdb
import geopandas as gpd

BASE_DIR = Path(__file__).resolve().parent.parent
DATOS_DIR = BASE_DIR / "datos"
GDB_PATH = BASE_DIR / "cartografia" / "Cartografia_censo2024_Pais.gdb"

print("=== Verificando carpeta de datos ===")
for nombre in ["personas_censo2024.parquet", "hogares_censo2024.parquet", "viviendas_censo2024.parquet"]:
    ruta = DATOS_DIR / nombre
    if ruta.exists():
        cols = duckdb.sql(f"SELECT * FROM read_parquet('{ruta.as_posix()}') LIMIT 0").columns
        print(f"[OK] {nombre} -> {len(cols)} columnas. ¿tiene region/provincia/comuna? "
              f"{'region' in cols and 'provincia' in cols and 'comuna' in cols}")
    else:
        print(f"[FALTA] No se encontró {ruta}")

print("\n=== Verificando geodatabase ===")
if GDB_PATH.exists():
    capas = gpd.list_layers(GDB_PATH)["name"].tolist()
    print(f"[OK] Geodatabase encontrada en {GDB_PATH}")
    print("Capas disponibles:")
    for c in capas:
        print(" -", c)
else:
    print(f"[FALTA] No se encontró la geodatabase en {GDB_PATH}")

print("\n=== Verificando Ollama (LLM local) ===")
try:
    import requests
    r = requests.get("http://localhost:11434/api/tags", timeout=3)
    modelos = [m["name"] for m in r.json().get("models", [])]
    print(f"[OK] Ollama está corriendo. Modelos instalados: {modelos}")
except Exception as e:
    print(f"[AVISO] No se pudo contactar a Ollama en localhost:11434 ({e}).")
    print("        La app funcionará igual, pero usando el modo de respaldo sin LLM.")
