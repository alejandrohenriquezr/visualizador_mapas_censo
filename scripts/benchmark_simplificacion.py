# -*- coding: utf-8 -*-
"""Ejecuta el benchmark de simplificacion dentro del contenedor cartography."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--niveles", default="region,provincia,comuna")
    p.add_argument(
        "--tolerancias",
        default="0.0005,0.00075,0.001,0.0015,0.002,0.003,0.005,0.01",
    )
    args = p.parse_args()
    cmd = [
        "docker","compose","exec","-T","cartography",
        "python","/app/cartography/benchmark_simplificacion.py",
        "--niveles",args.niveles,
        "--tolerancias",args.tolerancias,
    ]
    print("+"," ".join(cmd))
    raise SystemExit(subprocess.call(cmd, cwd=ROOT))

if __name__ == "__main__":
    main()
