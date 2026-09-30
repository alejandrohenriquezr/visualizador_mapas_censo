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

# BEGIN V34 APRENDIZAJE SILENCIOSO
# Estas funciones solo observan. Ninguna participa en la interpretación o cálculo.
def _learning_normalize(texto):
    import re, unicodedata
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def learning_start(query_id, session_id, pregunta, contexto=None):
    """Registra el inicio y marca una reformulación probable de forma heurística."""
    from difflib import SequenceMatcher
    limpia = _learning_normalize(pregunta)
    contexto = contexto or {}
    with _connect() as con:
        if session_id:
            previa = con.execute(
                """
                SELECT id,pregunta,pregunta_normalizada,feedback_valor
                FROM aprendizaje_consultas
                WHERE session_id=%s AND resultado IN ('exito','ambiguedad')
                  AND iniciado_en >= NOW() - INTERVAL '3 minutes'
                ORDER BY iniciado_en DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if previa and previa[0] != query_id:
                anterior = previa[2] or _learning_normalize(previa[1])
                similitud = SequenceMatcher(None, anterior, limpia).ratio() if anterior and limpia else 0.0
                # Señal débil: se guarda como "probable", nunca como verdad ni decisión.
                probable = bool(
                    limpia and anterior and limpia != anterior
                    and (similitud >= 0.45 or previa[3] == 'negativo')
                )
                if probable:
                    con.execute(
                        """
                        UPDATE aprendizaje_consultas
                        SET reformulacion_probable=TRUE,reformulacion_similitud=%s,
                            reformulada_por=%s,actualizado_en=NOW()
                        WHERE id=%s
                        """,
                        (float(similitud), query_id, previa[0]),
                    )
        con.execute(
            """
            INSERT INTO aprendizaje_consultas
              (id,session_id,pregunta,pregunta_normalizada,contexto)
            VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO NOTHING
            """,
            (query_id, session_id, pregunta, limpia, Jsonb(contexto)),
        )


def learning_success(query_id, feedback_id, interpretacion, senales, riesgo, cache_aprobada=False):
    with _connect() as con:
        con.execute(
            """
            UPDATE aprendizaje_consultas SET
              resultado='exito',feedback_id=%s,interpretacion=%s,senales=%s,
              riesgo_sombra=%s,cache_aprobada=%s,finalizado_en=NOW(),actualizado_en=NOW()
            WHERE id=%s
            """,
            (feedback_id, Jsonb(interpretacion or {}), Jsonb(senales or {}),
             float(riesgo), bool(cache_aprobada), query_id),
        )


def learning_ambiguity(query_id, tipo, opciones, detalle=None):
    with _connect() as con:
        con.execute(
            """
            UPDATE aprendizaje_consultas SET
              resultado='ambiguedad',tipo_ambiguedad=%s,opciones_ambiguedad=%s,
              error_detalle=%s,finalizado_en=NOW(),actualizado_en=NOW()
            WHERE id=%s
            """,
            (tipo, int(opciones or 0), str(detalle or '')[:1000], query_id),
        )


def learning_error(query_id, codigo, detalle):
    with _connect() as con:
        con.execute(
            """
            UPDATE aprendizaje_consultas SET
              resultado='error',error_codigo=%s,error_detalle=%s,
              finalizado_en=NOW(),actualizado_en=NOW()
            WHERE id=%s
            """,
            (int(codigo), str(detalle or '')[:1500], query_id),
        )


def learning_feedback(feedback_id, valor):
    with _connect() as con:
        con.execute(
            """UPDATE aprendizaje_consultas SET feedback_valor=%s,actualizado_en=NOW()
               WHERE feedback_id=%s""",
            (valor, feedback_id),
        )


def learning_excel(feedback_id):
    with _connect() as con:
        con.execute(
            """UPDATE aprendizaje_consultas SET excel_descargado=TRUE,actualizado_en=NOW()
               WHERE feedback_id=%s""",
            (feedback_id,),
        )


def learning_summary(days=30):
    days = max(1, min(int(days), 3650))
    with _connect() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM aprendizaje_consultas WHERE iniciado_en >= NOW() - (%s * INTERVAL '1 day')",
            (days,),
        ).fetchone()[0]
        outcomes = dict(con.execute(
            """SELECT resultado,COUNT(*) FROM aprendizaje_consultas
               WHERE iniciado_en >= NOW() - (%s * INTERVAL '1 day') GROUP BY resultado""",
            (days,),
        ).fetchall())
        feedback = dict(con.execute(
            """SELECT feedback_valor,COUNT(*) FROM aprendizaje_consultas
               WHERE iniciado_en >= NOW() - (%s * INTERVAL '1 day') AND feedback_valor IS NOT NULL
               GROUP BY feedback_valor""",
            (days,),
        ).fetchall())
        ambiguities = dict(con.execute(
            """SELECT tipo_ambiguedad,COUNT(*) FROM aprendizaje_consultas
               WHERE iniciado_en >= NOW() - (%s * INTERVAL '1 day') AND tipo_ambiguedad IS NOT NULL
               GROUP BY tipo_ambiguedad ORDER BY COUNT(*) DESC""",
            (days,),
        ).fetchall())
        extras = con.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE reformulacion_probable),
              COUNT(*) FILTER (WHERE excel_descargado),
              COUNT(*) FILTER (WHERE riesgo_sombra < 0.25),
              COUNT(*) FILTER (WHERE riesgo_sombra >= 0.25 AND riesgo_sombra < 0.65),
              COUNT(*) FILTER (WHERE riesgo_sombra >= 0.65),
              AVG(riesgo_sombra) FILTER (WHERE riesgo_sombra IS NOT NULL)
            FROM aprendizaje_consultas
            WHERE iniciado_en >= NOW() - (%s * INTERVAL '1 day')
            """,
            (days,),
        ).fetchone()
    return {
        "periodo_dias": days,
        "consultas": int(total),
        "resultados": outcomes,
        "feedback": feedback,
        "ambiguedades": ambiguities,
        "reformulaciones_probables": int(extras[0] or 0),
        "descargas_excel": int(extras[1] or 0),
        "riesgo_sombra": {
            "bajo_menor_0_25": int(extras[2] or 0),
            "medio_0_25_a_0_65": int(extras[3] or 0),
            "alto_0_65_o_mas": int(extras[4] or 0),
            "promedio": None if extras[5] is None else round(float(extras[5]), 4),
        },
    }


def learning_recent(days=30, limit=50):
    days = max(1, min(int(days), 3650)); limit = max(1, min(int(limit), 200))
    with _connect() as con:
        rows = con.execute(
            """
            SELECT id,pregunta,resultado,tipo_ambiguedad,riesgo_sombra,
                   feedback_valor,excel_descargado,reformulacion_probable,
                   iniciado_en,finalizado_en
            FROM aprendizaje_consultas
            WHERE iniciado_en >= NOW() - (%s * INTERVAL '1 day')
            ORDER BY iniciado_en DESC LIMIT %s
            """,
            (days, limit),
        ).fetchall()
    return [
        {"id":r[0],"pregunta":r[1],"resultado":r[2],"tipo_ambiguedad":r[3],
         "riesgo_sombra":r[4],"feedback":r[5],"excel_descargado":r[6],
         "reformulacion_probable":r[7],"iniciado_en":r[8].isoformat() if r[8] else None,
         "finalizado_en":r[9].isoformat() if r[9] else None}
        for r in rows
    ]
# END V34 APRENDIZAJE SILENCIOSO
