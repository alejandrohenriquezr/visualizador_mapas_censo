# -*- coding: utf-8 -*-
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
SERVICES = ("db", "llm", "cartography", "backend", "frontend")

def load_env():
    data={}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line=raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1); data[k.strip()]=v.strip().strip('"').strip("'")
    return data

def run(args, *, check=True, capture=False):
    print("+", " ".join(str(x) for x in args))
    return subprocess.run([str(x) for x in args], cwd=ROOT, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None)

def output(args):
    return run(args, capture=True).stdout.decode("utf-8", errors="replace").strip()

def compose(*args, **kwargs):
    return run(("docker","compose",*args), **kwargs)

def git(*args):
    return output(("git",*args))

def service_health(service):
    cid=output(("docker","compose","ps","-q",service))
    if not cid: return "missing"
    return output(("docker","inspect","--format","{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",cid))

def wait_services(timeout=300, services=SERVICES):
    deadline=time.time()+timeout; ultimo={}
    while time.time()<deadline:
        estados={s:service_health(s) for s in services}
        if estados!=ultimo: print("[health]",estados); ultimo=estados
        if all(v in {"healthy","running"} for v in estados.values()): return estados
        if any(v in {"unhealthy","exited","dead"} for v in estados.values()):
            raise RuntimeError(f"Servicio no saludable: {estados}")
        time.sleep(3)
    raise TimeoutError(f"Timeout esperando servicios: {ultimo}")

def python_executable(): return sys.executable
def base_url(): return "http://localhost:"+load_env().get("VISOR_PORT","8010")
def postgres_credentials():
    env=load_env(); return env.get("POSTGRES_USER","visor"), env.get("POSTGRES_DB","visor_censo")

def ensure_external_volumes():
    for name in ("visor_censo_postgres","visor_censo_ollama","visor_censo_cartography_cache"):
        r=subprocess.run(["docker","volume","inspect",name],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if r.returncode!=0:
            run(("docker","volume","create",name)); print("[volume] creado",name)
        else: print("[volume] existe",name)
