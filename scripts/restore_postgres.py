# -*- coding: utf-8 -*-
import argparse, subprocess
from pathlib import Path
from ops_common import ROOT, base_url, compose, postgres_credentials, python_executable, run, wait_services

def restaurar(path, *, confirmar=True, validar=True):
    path=Path(path).resolve()
    if not path.is_file(): raise FileNotFoundError(path)
    if confirmar and input(f"Se reemplazará PostgreSQL con {path.name}. Escriba RESTAURAR: ").strip()!="RESTAURAR":
        raise SystemExit("Restauración cancelada.")
    user,db=postgres_credentials()
    compose("stop","frontend","backend",check=False); compose("up","-d","db")
    cmd=["docker","compose","exec","-T","db","pg_restore","-U",user,"-d",db,"--clean","--if-exists","--no-owner","--no-privileges"]
    print("+"," ".join(cmd),"<",path)
    with path.open("rb") as fh: subprocess.run(cmd,cwd=ROOT,check=True,stdin=fh)
    compose("up","-d","backend","frontend"); wait_services(300)
    if validar: run((python_executable(),"scripts/smoke_test.py",base_url()))
    print("RESTAURACION_OK")

def main():
    p=argparse.ArgumentParser(); p.add_argument("backup"); p.add_argument("--yes",action="store_true"); p.add_argument("--no-smoke",action="store_true")
    a=p.parse_args(); restaurar(a.backup,confirmar=not a.yes,validar=not a.no_smoke)
if __name__=="__main__": main()
