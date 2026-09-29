# -*- coding: utf-8 -*-
import json, subprocess
from datetime import datetime
from pathlib import Path
from ops_common import ROOT, compose, git, postgres_credentials, service_health

def crear_backup():
    backups=ROOT/"backups"; backups.mkdir(exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    destino=backups/f"visor_censo_{stamp}.dump"
    if service_health("db") not in {"healthy","running"}: compose("up","-d","db")
    user,db=postgres_credentials()
    cmd=["docker","compose","exec","-T","db","pg_dump","-U",user,"-d",db,"-Fc","--no-owner","--no-privileges"]
    print("+"," ".join(cmd),">",destino)
    with destino.open("wb") as fh: subprocess.run(cmd,cwd=ROOT,check=True,stdout=fh)
    try: commit=git("rev-parse","HEAD")
    except Exception: commit=None
    destino.with_suffix(".json").write_text(json.dumps({
        "creado_en":datetime.now().isoformat(timespec="seconds"),"archivo":destino.name,
        "git_commit":commit,"postgres_db":db,"postgres_user":user
    },ensure_ascii=False,indent=2),encoding="utf-8")
    print("BACKUP_OK",destino); return destino

if __name__=="__main__": crear_backup()
