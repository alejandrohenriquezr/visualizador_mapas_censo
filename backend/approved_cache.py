# -*- coding: utf-8 -*-
"""Caché persistente de consultas aprobadas explícitamente por la persona."""
import json
import os
import re
import sqlite3
import unicodedata
import zlib
from copy import deepcopy
from pathlib import Path
from threading import RLock


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("CENSO_APROBADOS_DB", str(BASE_DIR / "datos" / "consultas_aprobadas.sqlite3")))
_LOCK = RLock()
# Cambiar esta versión cuando una actualización modifica la semántica del parser/SQL.
SEMANTIC_ENGINE_VERSION = "v30-od-regional-diagonal-ui-20260928"
def normalizar_pregunta(texto):
    """Normaliza mayúsculas, tildes, puntuación y espacios para reutilizarla."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"[^a-z0-9%]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _conexion():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS consultas_aprobadas (
            id INTEGER PRIMARY KEY,
            pregunta_limpia TEXT NOT NULL UNIQUE,
            pregunta_original TEXT NOT NULL,
            sql_texto TEXT NOT NULL,
            tabla TEXT,
            variable TEXT,
            operacion TEXT,
            motor_version TEXT,
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            usos INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS resultados_consulta (
            consulta_id INTEGER PRIMARY KEY,
            respuesta_comprimida BLOB NOT NULL,
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (consulta_id) REFERENCES consultas_aprobadas(id)
                ON DELETE CASCADE
        );
    """)
    # Migración compatible con bases creadas por versiones anteriores. Los
    # registros antiguos se conservan, pero al quedar motor_version=NULL no se
    # reutilizan con una semántica nueva.
    columnas = {fila[1] for fila in con.execute("PRAGMA table_info(consultas_aprobadas)")}
    if "motor_version" not in columnas:
        con.execute("ALTER TABLE consultas_aprobadas ADD COLUMN motor_version TEXT")
    return con


def buscar(pregunta):
    limpia = normalizar_pregunta(pregunta)
    if not limpia or not DB_PATH.exists():
        return None
    with _LOCK, _conexion() as con:
        fila = con.execute("""
            SELECT c.id, c.sql_texto, r.respuesta_comprimida
            FROM consultas_aprobadas c
            JOIN resultados_consulta r ON r.consulta_id = c.id
            WHERE c.pregunta_limpia = ? AND c.motor_version = ?
        """, (limpia, SEMANTIC_ENGINE_VERSION)).fetchone()
        if not fila:
            return None
        con.execute("UPDATE consultas_aprobadas SET usos = usos + 1 WHERE id = ?", (fila[0],))
    try:
        respuesta = json.loads(zlib.decompress(fila[2]).decode("utf-8"))
    except (ValueError, TypeError, zlib.error, UnicodeDecodeError):
        return None
    return {"pregunta_limpia": limpia, "sql": fila[1],
            "respuesta": deepcopy(respuesta)}


def guardar(pregunta, sql, respuesta):
    limpia = normalizar_pregunta(pregunta)
    if not limpia or not sql or not isinstance(respuesta, dict):
        raise ValueError("La consulta aprobada no contiene pregunta, SQL y resultado válidos.")
    interpretacion = respuesta.get("interpretacion") or {}
    copia = deepcopy(respuesta)
    copia.pop("feedback_id", None)
    contenido = zlib.compress(
        json.dumps(copia, ensure_ascii=False, separators=(",", ":"),
                   allow_nan=False).encode("utf-8"),
        level=6,
    )
    with _LOCK, _conexion() as con:
        con.execute("""
            INSERT INTO consultas_aprobadas
                (pregunta_limpia, pregunta_original, sql_texto, tabla, variable, operacion, motor_version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pregunta_limpia) DO UPDATE SET
                pregunta_original=excluded.pregunta_original,
                sql_texto=excluded.sql_texto,
                tabla=excluded.tabla,
                variable=excluded.variable,
                operacion=excluded.operacion,
                motor_version=excluded.motor_version,
                actualizado_en=CURRENT_TIMESTAMP
        """, (limpia, pregunta, sql, interpretacion.get("tabla"),
              interpretacion.get("variable"), interpretacion.get("operacion"),
              SEMANTIC_ENGINE_VERSION))
        consulta_id = con.execute(
            "SELECT id FROM consultas_aprobadas WHERE pregunta_limpia = ?", (limpia,)
        ).fetchone()[0]
        con.execute("""
            INSERT INTO resultados_consulta (consulta_id, respuesta_comprimida)
            VALUES (?, ?)
            ON CONFLICT(consulta_id) DO UPDATE SET
                respuesta_comprimida=excluded.respuesta_comprimida,
                actualizado_en=CURRENT_TIMESTAMP
        """, (consulta_id, contenido))
    return limpia

# BEGIN VISOR V31 POSTGRES STATE
import os as _v31_os
if _v31_os.getenv("DATABASE_URL", "").strip():
    from state_store import approved_get as _pg_approved_get, approved_save as _pg_approved_save

    def buscar(pregunta):
        return _pg_approved_get(pregunta, normalizar_pregunta, SEMANTIC_ENGINE_VERSION)

    def guardar(pregunta, sql, respuesta):
        return _pg_approved_save(pregunta, sql, respuesta, normalizar_pregunta, SEMANTIC_ENGINE_VERSION)
# END VISOR V31 POSTGRES STATE
