# -*- coding: utf-8 -*-
"""Verificación estática del parche V41. No modifica archivos."""
from pathlib import Path
import sys

ROOT = Path.cwd()

CHECKS = [
    (ROOT / "backend" / "v40_general.py", r"\bgrupos?\s+de\s+edad\s+quinquenal(?:es)?\b", "frase 'grupo de edad quinquenal'"),
    (ROOT / "backend" / "data_engine.py", "usar_completa=False", "resumen basado en la primera dimensión"),
    (ROOT / "backend" / "data_engine.py", '"torta_primera_dimension": True', "marca de torta por primera dimensión"),
    (ROOT / "frontend" / "index.html", "yaAgrupadaPrimeraDimension", "V36 no deshace el reagrupamiento V40"),
    (ROOT / "frontend" / "index.html", r"(?:\s*anos?)?", "pirámide acepta rangos sin la palabra años"),
    (ROOT / "frontend" / "index.html", "/v41-fixes.css", "CSS V41 enlazado"),
    (ROOT / "frontend" / "index.html", "/v41-fixes.js", "JS V41 enlazado"),
    (ROOT / "frontend" / "v41-fixes.js", "renderResumenTextualV41", "resumen textual"),
    (ROOT / "frontend" / "v41-fixes.js", "ajustarMapaResultadoV41", "reajuste territorial fullscreen/PNG"),
    (ROOT / "frontend" / "v41-fixes.css", "v41-piramide-activa", "aislamiento visual de pirámide"),
]

fallos = []
for path, needle, label in CHECKS:
    if not path.exists():
        fallos.append(f"FALTA {path}")
        continue
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        fallos.append(f"NO OK: {label} ({path})")
    else:
        print(f"OK  {label}")

if fallos:
    print("\nVERIFICACIÓN V41 CON ERRORES:")
    for f in fallos:
        print(" -", f)
    sys.exit(1)

print("\nVERIFICACIÓN V41: OK")
print("No se ejecutó ninguna operación Git/GitHub.")
