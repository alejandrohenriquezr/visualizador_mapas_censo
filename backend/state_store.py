# -*- coding: utf-8 -*-
"""Persistencia PostgreSQL para pendientes, feedback y cache aprobada."""
from copy import deepcopy
from uuid import uuid4
import os

import psycopg
from psycopg.types.json import Jsonb

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TTL_MINUTES = int(os.getenv("PENDING_TTL_MINUTES", "30"))


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurada")
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def pending_save(pregunta, sql, respuesta):
    identificador = uuid4().hex
    copia = deepcopy(respuesta)
    copia.pop("feedback_id", None)
    with _connect() as con:
        con.execute(
            "DELETE FROM resultados_pendientes WHERE creado_en < NOW() - (%s * INTERVAL '1 minute')",
            (TTL_MINUTES,),
        )
        con.execute(
            "INSERT INTO resultados_pendientes(id,pregunta,sql_texto,respuesta) VALUES(%s,%s,%s,%s)",
            (identificador, pregunta, sql, Jsonb(copia)),
        )
    return identificador


def pending_get(identificador):
    with _connect() as con:
        fila = con.execute(
            """
            SELECT pregunta,sql_texto,respuesta FROM resultados_pendientes
            WHERE id=%s AND creado_en >= NOW() - (%s * INTERVAL '1 minute')
            """,
            (identificador, TTL_MINUTES),
        ).fetchone()
        if not fila:
            con.execute("DELETE FROM resultados_pendientes WHERE id=%s", (identificador,))
            return None
        con.execute(
            "UPDATE resultados_pendientes SET ultimo_acceso=NOW() WHERE id=%s",
            (identificador,),
        )
    return {"pregunta": fila[0], "sql": fila[1], "respuesta": deepcopy(fila[2])}


def feedback_save(feedback_id, valor):
    with _connect() as con:
        con.execute(
            "INSERT INTO feedback(feedback_id,valor) VALUES(%s,%s)",
            (feedback_id, valor),
        )


def approved_get(pregunta, normalizar, engine_version):
    limpia = normalizar(pregunta)
    if not limpia:
        return None
    with _connect() as con:
        fila = con.execute(
            """
            SELECT c.id,c.sql_texto,r.respuesta
            FROM consultas_aprobadas c
            JOIN resultados_consulta r ON r.consulta_id=c.id
            WHERE c.pregunta_limpia=%s AND c.motor_version=%s
            """,
            (limpia, engine_version),
        ).fetchone()
        if not fila:
            return None
        con.execute(
            "UPDATE consultas_aprobadas SET usos=usos+1 WHERE id=%s", (fila[0],)
        )
    return {
        "pregunta_limpia": limpia,
        "sql": fila[1],
        "respuesta": deepcopy(fila[2]),
    }


def approved_save(pregunta, sql, respuesta, normalizar, engine_version):
    limpia = normalizar(pregunta)
    if not limpia or not sql or not isinstance(respuesta, dict):
        raise ValueError("Consulta aprobada invalida")
    interpretacion = respuesta.get("interpretacion") or {}
    copia = deepcopy(respuesta)
    copia.pop("feedback_id", None)
    with _connect() as con:
        fila = con.execute(
            """
            INSERT INTO consultas_aprobadas
              (pregunta_limpia,pregunta_original,sql_texto,tabla,variable,operacion,motor_version)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(pregunta_limpia) DO UPDATE SET
              pregunta_original=EXCLUDED.pregunta_original,
              sql_texto=EXCLUDED.sql_texto,
              tabla=EXCLUDED.tabla,
              variable=EXCLUDED.variable,
              operacion=EXCLUDED.operacion,
              motor_version=EXCLUDED.motor_version,
              actualizado_en=NOW()
            RETURNING id
            """,
            (
                limpia,
                pregunta,
                sql,
                interpretacion.get("tabla"),
                interpretacion.get("variable"),
                interpretacion.get("operacion"),
                engine_version,
            ),
        ).fetchone()
        con.execute(
            """
            INSERT INTO resultados_consulta(consulta_id,respuesta) VALUES(%s,%s)
            ON CONFLICT(consulta_id) DO UPDATE SET
              respuesta=EXCLUDED.respuesta,actualizado_en=NOW()
            """,
            (fila[0], Jsonb(copia)),
        )
    return limpia
