from pathlib import Path
import re, sys
root=Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()
errors=[]
for p in root.rglob("*"):
    if not p.is_file() or ".git" in p.parts: continue
    rel=p.relative_to(root)
    low=str(rel).lower().replace("\\","/")
    if low.startswith("backup_") or "/backup_" in low:
        errors.append(f"archivo local prohibido: {rel}")
    parts={part.lower() for part in rel.parts}
    if parts & {"venv",".venv","site-packages","dist-packages","node_modules"}:
        errors.append(f"dependencia/entorno local prohibido: {rel}")
    if p.suffix.lower() in {".parquet",".gdb",".sqlite",".sqlite3"}:
        errors.append(f"dato/estado prohibido: {rel}")
    if p.stat().st_size > 50*1024*1024:
        errors.append(f"archivo >50 MB: {rel} ({p.stat().st_size})")
gitignore=(root/".gitignore").read_text(encoding="utf-8") if (root/".gitignore").exists() else ""
if ".env" not in gitignore: errors.append(".gitignore no excluye .env")
for required in ["README.md","docker-compose.yml",".env.example","frontend/Dockerfile","backend/Dockerfile","cartography/Dockerfile","database/init/001_schema.sql"]:
    if not (root/required).exists(): errors.append(f"falta {required}")
compose=(root/"docker-compose.yml").read_text(encoding="utf-8")
for svc in ["frontend","backend","db","llm","cartography"]:
    if not re.search(rf"^  {svc}:\s*$",compose,re.M): errors.append(f"falta servicio {svc}")
if errors:
    print("REPOSITORIO NO APTO:")
    for e in errors: print(" -",e)
    raise SystemExit(1)
print("REPOSITORIO APTO PARA GIT")
