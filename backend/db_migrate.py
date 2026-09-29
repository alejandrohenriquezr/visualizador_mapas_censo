# -*- coding: utf-8 -*-
"""Aplica migraciones SQL versionadas antes de iniciar el backend."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MIGRATIONS_DIR = Path(os.getenv("DB_MIGRATIONS_DIR", "/app/database/migrations"))

def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def migrate() -> None:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurada")
    if not MIGRATIONS_DIR.exists():
        raise RuntimeError(f"No existe el directorio de migraciones: {MIGRATIONS_DIR}")
    migraciones = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migraciones:
        raise RuntimeError(f"No hay migraciones SQL en {MIGRATIONS_DIR}")
    with psycopg.connect(DATABASE_URL, connect_timeout=10, autocommit=True) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        aplicadas = dict(con.execute("SELECT version, checksum FROM schema_migrations").fetchall())
        for path in migraciones:
            version = path.stem
            checksum = _checksum(path)
            if version in aplicadas:
                if aplicadas[version] != checksum:
                    raise RuntimeError(f"La migración aplicada {version} cambió de contenido")
                print(f"[db] {version}: ya aplicada")
                continue
            print(f"[db] {version}: aplicando")
            with con.transaction():
                con.execute(path.read_text(encoding="utf-8"))
                con.execute("INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)", (version, checksum))
            print(f"[db] {version}: OK")

if __name__ == "__main__":
    migrate()
