from pathlib import Path
import os, sys
root = Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()
required = [
    "docker-compose.yml", ".env", "frontend/index.html", "frontend/Dockerfile",
    "backend/main.py", "backend/Dockerfile", "backend/state_store.py", "backend/geometry_remote.py",
    "cartography/main.py", "cartography/Dockerfile", "database/init/001_schema.sql",
    "data/diccionario_variables.json", "data/diccionario_geografico.json",
]
missing=[x for x in required if not (root/x).exists()]
if missing:
    print("ERROR: faltan archivos:")
    for x in missing: print(" -",x)
    raise SystemExit(1)
for folder in ["datos","cartografia"]:
    if not (root/folder).exists(): print(f"ADVERTENCIA: falta {folder}/")
print("OK estructura de repositorio")
