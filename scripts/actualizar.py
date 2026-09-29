# -*- coding: utf-8 -*-
import json, sys, urllib.request
from backup_postgres import crear_backup
from ops_common import base_url, compose, ensure_external_volumes, git, python_executable, run, wait_services
from restore_postgres import restaurar

def salud_detallada():
    with urllib.request.urlopen(base_url().rstrip("/")+"/api/salud/detallada",timeout=30) as r:
        data=json.loads(r.read().decode("utf-8"))
    if data.get("estado")!="ok": raise RuntimeError(f"Salud degradada: {data}")
    print("[salud]",json.dumps(data,ensure_ascii=False))

def main():
    if git("status","--porcelain"): raise RuntimeError("El árbol Git no está limpio. Commit/stash antes de actualizar.")
    if git("branch","--show-current")!="main": raise RuntimeError("ACTUALIZAR.cmd solo despliega desde main.")
    ensure_external_volumes()
    anterior=git("rev-parse","HEAD"); run(("git","fetch","origin","main")); objetivo=git("rev-parse","origin/main")
    if objetivo==anterior:
        print("Ya está actualizado."); wait_services(120); run((python_executable(),"scripts/smoke_test.py",base_url())); salud_detallada(); return
    backup=crear_backup()
    try:
        run(("git","pull","--ff-only","origin","main"))
        run((python_executable(),"scripts/validate_repo.py","."))
        run((python_executable(),"-m","compileall","-q","backend","cartography","scripts","tests"))
        compose("build","frontend","backend","cartography")
        compose("up","-d","db","llm","cartography"); compose("up","-d","backend","frontend")
        wait_services(300); run((python_executable(),"scripts/smoke_test.py",base_url())); salud_detallada()
        print("ACTUALIZACION_OK")
    except Exception as exc:
        print("ERROR:",exc,file=sys.stderr); print("[rollback] restaurando",file=sys.stderr)
        compose("stop","frontend","backend",check=False); run(("git","reset","--hard",anterior))
        compose("build","frontend","backend","cartography"); compose("up","-d","db","llm","cartography")
        restaurar(backup,confirmar=False,validar=False); wait_services(300)
        run((python_executable(),"scripts/smoke_test.py",base_url()))
        print("ROLLBACK_OK",file=sys.stderr); raise
if __name__=="__main__": main()
