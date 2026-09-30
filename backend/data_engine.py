# -*- coding: utf-8 -*-
"""
Ejecuta la intención estructurada (ver nl_parser.py) contra:
  - los archivos parquet del Censo 2024 (datos/*.parquet), usando DuckDB
  - la cartografía CPV24 (cartografia/Cartografia_censo2024_Pais.gdb),
    usando GeoPandas/Fiona

y devuelve un GeoJSON listo para pintar en el mapa (Leaflet).
"""
import difflib
import hashlib
import json
import math
import os
from copy import deepcopy
from uuid import uuid4
import logging
from time import perf_counter
from functools import lru_cache
from threading import RLock
import pandas as pd
from pathlib import Path

import duckdb
# VISOR_V31_OPTIONAL_GEOPANDAS: backend 5svc no necesita GDAL/GeoPandas.
try:
    import geopandas as gpd
except ImportError:  # pragma: no cover - solo arquitectura desacoplada
    gpd = None

from dictionary import VARIABLES, TABLAS_PARQUET, categorias_validas

BASE_DIR = Path(__file__).resolve().parent.parent
DATOS_DIR = Path(os.getenv("CENSO_DATOS_DIR", str(BASE_DIR / "datos")))
GDB_PATH = Path(os.getenv("CENSO_CARTOGRAFIA_GDB", str(BASE_DIR / "cartografia" / "Cartografia_censo2024_Pais.gdb")))

# Nivel geográfico -> (columna en el parquet, capa "ideal" del gdb, campo llave en el gdb)
NIVELES = {
    "region": {"col_parquet": "region", "capa_gdb": "Regional_CPV24", "campo_gdb": "COD_REGION", "campo_nombre": "REGION"},
    "provincia": {"col_parquet": "provincia", "capa_gdb": "Provincial_CPV24", "campo_gdb": "COD_PROVINCIA", "campo_nombre": "PROVINCIA"},
    "comuna": {"col_parquet": "comuna", "capa_gdb": "Comunal_CPV24", "campo_gdb": "CUT", "campo_nombre": "COMUNA"},
}

_capas_cache = None
_GEOMETRIAS = {}
# La caché persistente contiene solo cartografía preparada, nunca microdatos.
CACHE_DIR = Path(os.getenv("CENSO_CACHE_DIR", str(BASE_DIR / ".cache_visor")))
SIMPLIFICACION = float(os.getenv("CENSO_SIMPLIFICACION", "0.0005"))
if not 0 < SIMPLIFICACION < 1:
    raise ValueError("CENSO_SIMPLIFICACION debe ser mayor que cero y menor que 1 grado.")
_FIRMAS_GEOMETRIA = {}
_GEOMETRIAS_JSON = {}
_GEOMETRY_LOCK = RLock()
_SQL_CACHE_LOCK = RLock()
_PREWARM_LOCK = RLock()
LOG = logging.getLogger("uvicorn.error")
_ESTADO_PRECALENTAMIENTO = {
    "estado": "pendiente", "niveles_listos": [], "errores": {},
}


def _numero_sql(valor, nombre):
    """Valida un límite numérico antes de incorporarlo al SQL."""
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{nombre} no es numérico.") from exc
    if not math.isfinite(numero):
        raise ValueError(f"{nombre} no es finito.")
    return str(int(numero)) if numero.is_integer() else repr(numero)


def _condiciones_rango(tabla, filtro, incluir_solicitado=True):
    """Construye condiciones validadas para el dominio y el rango solicitado."""
    variable = filtro.get("variable")
    if variable not in VARIABLES.get(tabla, {}).get("variables", {}):
        raise ValueError("La variable del filtro numérico no existe en el diccionario.")
    variable_sql = '"' + variable.replace('"', '""') + '"'
    expresion = f"TRY_CAST({variable_sql} AS DOUBLE)"
    condiciones = [f"{expresion} IS NOT NULL"]
    if filtro.get("dominio_minimo") is not None:
        condiciones.append(f"{expresion} >= {_numero_sql(filtro['dominio_minimo'], 'dominio_minimo')}")
    if filtro.get("dominio_maximo") is not None:
        condiciones.append(f"{expresion} <= {_numero_sql(filtro['dominio_maximo'], 'dominio_maximo')}")
    if incluir_solicitado and filtro.get("minimo") is not None:
        operador = ">=" if filtro.get("incluir_minimo", True) else ">"
        condiciones.append(f"{expresion} {operador} {_numero_sql(filtro['minimo'], 'mínimo')}")
    if incluir_solicitado and filtro.get("maximo") is not None:
        operador = "<=" if filtro.get("incluir_maximo", True) else "<"
        condiciones.append(f"{expresion} {operador} {_numero_sql(filtro['maximo'], 'máximo')}")
    minimo, maximo = filtro.get("minimo"), filtro.get("maximo")
    if minimo is not None and maximo is not None and float(minimo) > float(maximo):
        raise ValueError("El límite mínimo del rango es mayor que el máximo.")
    return condiciones


def _listar_capas():
    global _capas_cache
    if _capas_cache is None:
        _capas_cache = gpd.list_layers(GDB_PATH)["name"].tolist() if GDB_PATH.exists() else []
    return _capas_cache


def _resolver_capa(nombre_ideal: str) -> str:
    """Encuentra el nombre real de la capa dentro del .gdb, por si difiere
    levemente del nombre del diccionario (mayúsculas, sufijos, etc.)."""
    capas = _listar_capas()
    if not capas:
        raise FileNotFoundError(
            f"No se encontró la geodatabase en '{GDB_PATH}'. Verifica la carpeta 'cartografia/'."
        )
    if nombre_ideal in capas:
        return nombre_ideal
    coincidencia = difflib.get_close_matches(nombre_ideal, capas, n=1, cutoff=0.4)
    if coincidencia:
        return coincidencia[0]
    raise ValueError(f"No se encontró una capa similar a '{nombre_ideal}'. Capas disponibles: {capas}")


def _ruta_parquet(tabla: str) -> Path:
    ruta = DATOS_DIR / TABLAS_PARQUET[tabla]
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró '{ruta}'. Verifica la carpeta 'datos/'.")
    return ruta


def _construir_sql(intencion: dict, nivel_info: dict, ruta_parquet: Path) -> str:
    tabla = intencion["tabla"]
    variable_nombre = intencion["variable"]
    variable = variable_nombre
    valor = intencion.get("categoria_valor")
    valores_objetivo = [str(v) for v in (intencion.get("categoria_valores") or [])]
    operacion = intencion.get("operacion", "conteo")
    col_geo = nivel_info["col_parquet"]

    # Valida y cita los identificadores; las categorías se escapan como literales.
    if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError("Tabla o variable desconocida.")
    es_lengua_indigena_especifica = (
        intencion.get("tipo_consulta") == "lengua_indigena_especifica"
        and tabla == "personas" and variable_nombre == "p30_lengua_indigena"
    )
    variable = '"' + variable.replace('"', '""') + '"'
    if valor is not None:
        valor = str(valor).replace("'", "''")
    if operacion not in ("conteo", "porcentaje", "porcentaje_rango", "promedio", "razon"):
        raise ValueError("Operación no admitida.")
    filtros = []
    if intencion.get("edad_minima") is not None:
        edad = intencion.get("variable_edad")
        if tabla != "personas" or edad not in VARIABLES[tabla]["variables"]:
            raise ValueError("Variable de edad no válida.")
        edad = '"' + edad.replace('"', '""') + '"'
        filtros.append(f"TRY_CAST({edad} AS DOUBLE) >= {int(intencion['edad_minima'])}")
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if f_nivel and f_codigo is not None and f_nivel in NIVELES:
        col_filtro = NIVELES[f_nivel]["col_parquet"]
        filtros.append(f"{col_filtro} = {int(f_codigo)}")

    # Los filtros numéricos adicionales restringen el universo completo. El
    # rango objetivo de un porcentaje se procesa aparte para no producir 100 %.
    for filtro_numerico in intencion.get("filtros_numericos") or []:
        filtros.extend(_condiciones_rango(tabla, filtro_numerico, incluir_solicitado=True))

    ruta_sql = ruta_parquet.as_posix().replace("'", "''")
    origen = f"read_parquet('{ruta_sql}')"

    if operacion == "promedio":
        # se descartan códigos negativos típicos de "no aplica"/"no responde"
        filtros.append(f"TRY_CAST({variable} AS DOUBLE) IS NOT NULL")
        filtros.append(f"TRY_CAST({variable} AS DOUBLE) >= 0")
        where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        sql = f"""
            SELECT {col_geo} AS codigo, AVG(TRY_CAST({variable} AS DOUBLE)) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """
        return sql

    if operacion == "porcentaje_rango":
        rango = intencion.get("rango_objetivo")
        if not isinstance(rango, dict):
            raise ValueError("El porcentaje por rango requiere límites numéricos.")
        condicion_num = " AND ".join(_condiciones_rango(tabla, rango, incluir_solicitado=True))
        condicion_den = " AND ".join(_condiciones_rango(tabla, rango, incluir_solicitado=False))
        where_total = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        LOG.info("[rango] tabla=%s variable=%s minimo=%s maximo=%s",
                 tabla, rango.get("variable"), rango.get("minimo"), rango.get("maximo"))
        return f"""
            SELECT {col_geo} AS codigo,
                   100.0 * SUM(CASE WHEN {condicion_num} THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN {condicion_den} THEN 1 ELSE 0 END), 0) AS valor
            FROM {origen}
            {where_total}
            GROUP BY {col_geo}
        """

    if operacion == "porcentaje":
        where_total = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        if valor is None and not valores_objetivo:
            raise ValueError("Un porcentaje requiere una categoría objetivo.")
        denominador = intencion.get("denominador_valores") or categorias_validas(
            tabla, intencion["variable"]
        )
        denominador = list(dict.fromkeys(str(v) for v in denominador))
        if len(denominador) < 2:
            raise ValueError(
                "El porcentaje requiere al menos dos categorías válidas en el denominador."
            )
        objetivos = valores_objetivo or [str(intencion.get("categoria_valor"))]
        if any(v not in denominador for v in objetivos):
            raise ValueError(
                "Alguna categoría objetivo no pertenece al denominador válido de la variable."
            )
        LOG.info("[porcentaje] tabla=%s variable=%s objetivos=%s denominador=%s",
                 tabla, intencion["variable"], objetivos, denominador)
        # P30 puede venir físicamente como entero, decimal o texto según la
        # conversión del archivo fuente. Para una lengua específica se compara
        # por código numérico y se evita que 1.0 deje el mapa sin resultados.
        if es_lengua_indigena_especifica:
            try:
                objetivos_int = [int(float(v)) for v in objetivos]
                denominador_int = [int(float(v)) for v in denominador]
            except (TypeError, ValueError):
                raise ValueError("Los códigos de lengua indígena no son numéricos.")
            valores_num = ", ".join(str(v) for v in objetivos_int)
            valores_den = ", ".join(str(v) for v in denominador_int)
            condicion = f"TRY_CAST({variable} AS INTEGER) IN ({valores_num})"
            condicion_den = f"TRY_CAST({variable} AS INTEGER) IN ({valores_den})"
        else:
            valores_den = ", ".join("'" + str(v).replace("'", "''") + "'" for v in denominador)
            # Excluye No aplica, No respuesta y códigos especiales del universo.
            if valores_objetivo:
                valores_num = ", ".join("'" + v.replace("'", "''") + "'" for v in valores_objetivo)
                condicion = f"CAST({variable} AS VARCHAR) IN ({valores_num})"
            else:
                condicion = f"CAST({variable} AS VARCHAR) = '{valor}'"
            condicion_den = ("TRUE" if intencion.get("denominador_entidad_total")
                             else f"CAST({variable} AS VARCHAR) IN ({valores_den})")
        return f"""
            SELECT {col_geo} AS codigo,
                   100.0 * SUM(CASE WHEN {condicion} THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN {condicion_den} THEN 1 ELSE 0 END), 0) AS valor
            FROM {origen} {where_total}
            GROUP BY {col_geo}
        """

    if operacion == "razon":
        numerador = intencion.get("numerador_valores") or []
        denominador = intencion.get("denominador_valores") or []
        if not numerador or not denominador:
            raise ValueError("Una razón requiere categorías de numerador y denominador.")
        lista_num = ", ".join("'" + str(v).replace("'", "''") + "'" for v in numerador)
        lista_den = ", ".join("'" + str(v).replace("'", "''") + "'" for v in denominador)
        factor = float(intencion.get("factor", 1.0))
        where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        return f"""
            SELECT {col_geo} AS codigo,
                   {factor} * SUM(CASE WHEN CAST({variable} AS VARCHAR) IN ({lista_num}) THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN CAST({variable} AS VARCHAR) IN ({lista_den}) THEN 1 ELSE 0 END), 0) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    # Cuenta la categoría dentro de cada grupo para conservar ceros reales
    # cuando existen personas en la comuna, pero ninguna cumple la categoría.
    if es_lengua_indigena_especifica and valor is not None:
        try:
            codigo_lengua = int(float(valor))
        except (TypeError, ValueError):
            raise ValueError("El código de lengua indígena no es numérico.")
        agregado = (
            f"SUM(CASE WHEN TRY_CAST({variable} AS INTEGER) = {codigo_lengua} "
            "THEN 1 ELSE 0 END)"
        )
    elif valores_objetivo:
        valores_num = ", ".join("'" + v.replace("'", "''") + "'" for v in valores_objetivo)
        agregado = f"SUM(CASE WHEN CAST({variable} AS VARCHAR) IN ({valores_num}) THEN 1 ELSE 0 END)"
    else:
        agregado = (f"SUM(CASE WHEN CAST({variable} AS VARCHAR) = '{valor}' THEN 1 ELSE 0 END)"
                    if valor is not None else "COUNT(*)")
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""

    print(f"""
        SELECT {col_geo} AS codigo, {agregado} AS valor
        FROM {origen}
        {where}
        GROUP BY {col_geo}
    """)
    return f"""
        SELECT {col_geo} AS codigo, {agregado} AS valor
        FROM {origen}
        {where}
        GROUP BY {col_geo}
    """



def _construir_sql_indicador_derivado_v24(intencion: dict, nivel_info: dict, ruta_parquet: Path) -> str:
    """SQL de indicadores demográficos/laborales verificados en v24."""
    indicador = intencion.get("indicador_id")
    permitidos = {
        "envejecimiento", "dependencia_total", "dependencia_juvenil",
        "dependencia_mayores", "tasa_ocupacion", "tasa_desocupacion",
    }
    if indicador not in permitidos:
        raise ValueError("Indicador derivado v24 desconocido.")
    col_geo = nivel_info["col_parquet"]
    filtros = []
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if f_nivel and f_codigo is not None:
        filtros.append(f"{NIVELES[f_nivel]['col_parquet']} = {int(f_codigo)}")
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    ruta_sql = ruta_parquet.as_posix().replace("'", "''")
    origen = f"read_parquet('{ruta_sql}')"
    edad = 'TRY_CAST("edad" AS DOUBLE)'
    sit = 'CAST("sit_fuerza_trabajo" AS VARCHAR)'

    formulas = {
        "envejecimiento": (
            f"SUM(CASE WHEN {edad} >= 60 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 0 AND 14 THEN 1 ELSE 0 END)",
        ),
        "dependencia_total": (
            f"SUM(CASE WHEN ({edad} BETWEEN 0 AND 14) OR {edad} >= 60 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 15 AND 59 THEN 1 ELSE 0 END)",
        ),
        "dependencia_juvenil": (
            f"SUM(CASE WHEN {edad} BETWEEN 0 AND 14 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 15 AND 59 THEN 1 ELSE 0 END)",
        ),
        "dependencia_mayores": (
            f"SUM(CASE WHEN {edad} >= 60 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 15 AND 59 THEN 1 ELSE 0 END)",
        ),
        "tasa_ocupacion": (
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} = '1' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} IN ('1','2','3') THEN 1 ELSE 0 END)",
        ),
        "tasa_desocupacion": (
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} = '2' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} IN ('1','2') THEN 1 ELSE 0 END)",
        ),
    }
    numerador, denominador = formulas[indicador]
    return f"""
        SELECT {col_geo} AS codigo,
               100.0 * ({numerador}) / NULLIF(({denominador}), 0) AS valor
        FROM {origen}
        {where}
        GROUP BY {col_geo}
    """




def _filtros_geograficos_indicador_v27(intencion: dict, nivel: str) -> list[str]:
    """Construye filtros territoriales sobre la geografía actual del parquet."""
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if not f_nivel:
        return []
    if f_nivel not in NIVELES:
        raise ValueError("Filtro territorial no válido.")
    return [f"{NIVELES[f_nivel]['col_parquet']} = {int(f_codigo)}"]


def _construir_sql_indicador_censal_v27(intencion: dict, nivel_info: dict, ruta_parquet: Path) -> str:
    """SQL auditable para tasas e indicadores del catálogo censal v27."""
    indicador = intencion.get("indicador_id")
    permitidos = {
        "tasa_desocupacion", "tasa_participacion_economica", "tasa_ocupacion",
        "envejecimiento", "dependencia_total", "dependencia_juvenil", "dependencia_mayores",
        "tasa_alfabetismo", "tasa_analfabetismo",
        "porcentaje_poblacion_indigena", "porcentaje_poblacion_afrodescendiente",
        "porcentaje_poblacion_indigena_o_afro", "porcentaje_inmigrante_internacional",
        "tasa_migracion_reciente", "tasa_migracion_interna",
        "tasa_migracion_neta_interna", "tgf_aproximada_censal",
        "porcentaje_personas_mayores_jefatura",
    }
    if indicador not in permitidos:
        raise ValueError("Indicador censal v27 desconocido.")

    nivel = intencion.get("nivel_geografico", "region")
    col_geo = nivel_info["col_parquet"]
    ruta_sql = ruta_parquet.as_posix().replace("'", "''")
    origen = f"read_parquet('{ruta_sql}')"
    filtros = _filtros_geograficos_indicador_v27(intencion, nivel)
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""

    edad = 'TRY_CAST("edad" AS DOUBLE)'
    sexo = 'CAST("sexo" AS VARCHAR)'
    sit = 'CAST("sit_fuerza_trabajo" AS VARCHAR)'
    p37 = 'CAST("p37_alfabet" AS VARCHAR)'
    p28 = 'CAST("p28_autoid_pueblo" AS VARCHAR)'
    p29 = 'CAST("p29_afrodescendencia_rec" AS VARCHAR)'
    p25 = 'CAST("p25_lug_nacimiento" AS VARCHAR)'
    p24 = 'CAST("p24_lug_resid5" AS VARCHAR)'
    parentesco = 'CAST("parentesco" AS VARCHAR)'
    tipo_operativo = 'CAST("tipo_operativo" AS VARCHAR)'

    # Umbral dinámico únicamente para el indicador de jefatura en personas
    # mayores. Se valida para impedir que texto libre llegue al SQL.
    edad_umbral = int(intencion.get("edad_umbral", 60))
    if not 0 <= edad_umbral <= 120:
        raise ValueError("El umbral de edad del indicador de jefatura no es válido.")
    edad_op = ">=" if bool(intencion.get("edad_inclusiva", True)) else ">"
    condicion_mayor = f"{edad} {edad_op} {edad_umbral} AND {edad} <= 120"

    formulas = {
        "tasa_desocupacion": (
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} = '2' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} IN ('1','2') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "tasa_participacion_economica": (
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} IN ('1','2') THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} IN ('1','2','3') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "tasa_ocupacion": (
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} = '1' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 15 AND {sit} IN ('1','2','3') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "envejecimiento": (
            f"SUM(CASE WHEN {edad} BETWEEN 60 AND 120 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 0 AND 14 THEN 1 ELSE 0 END)",
            100.0,
        ),
        "dependencia_total": (
            f"SUM(CASE WHEN ({edad} BETWEEN 0 AND 14) OR ({edad} BETWEEN 60 AND 120) THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 15 AND 59 THEN 1 ELSE 0 END)",
            100.0,
        ),
        "dependencia_juvenil": (
            f"SUM(CASE WHEN {edad} BETWEEN 0 AND 14 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 15 AND 59 THEN 1 ELSE 0 END)",
            100.0,
        ),
        "dependencia_mayores": (
            f"SUM(CASE WHEN {edad} BETWEEN 60 AND 120 THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} BETWEEN 15 AND 59 THEN 1 ELSE 0 END)",
            100.0,
        ),
        "tasa_alfabetismo": (
            f"SUM(CASE WHEN {edad} >= 5 AND {p37} = '1' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 5 AND {p37} IN ('1','2') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "tasa_analfabetismo": (
            f"SUM(CASE WHEN {edad} >= 5 AND {p37} = '2' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {edad} >= 5 AND {p37} IN ('1','2') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "porcentaje_poblacion_indigena": (
            f"SUM(CASE WHEN {p28} = '1' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {p28} IN ('1','2') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "porcentaje_poblacion_afrodescendiente": (
            f"SUM(CASE WHEN {p29} = '1' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {p29} IN ('1','2') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "porcentaje_poblacion_indigena_o_afro": (
            f"SUM(CASE WHEN {p28} IN ('1','2') AND {p29} IN ('1','2') AND ({p28} = '1' OR {p29} = '1') THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {p28} IN ('1','2') AND {p29} IN ('1','2') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "porcentaje_inmigrante_internacional": (
            f"SUM(CASE WHEN {p25} = '3' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {p25} IN ('1','2','3') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "tasa_migracion_reciente": (
            f"SUM(CASE WHEN {p24} IN ('3','4') THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {p24} IN ('2','3','4') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "tasa_migracion_interna": (
            f"SUM(CASE WHEN {p24} = '3' THEN 1 ELSE 0 END)",
            f"SUM(CASE WHEN {p24} IN ('2','3') THEN 1 ELSE 0 END)",
            100.0,
        ),
        "porcentaje_personas_mayores_jefatura": (
            f"SUM(CASE WHEN {condicion_mayor} AND {tipo_operativo} = '2' AND {parentesco} = '1' THEN 1 ELSE 0 END)",
            (
                "COUNT(*)" if intencion.get("denominador_id") == "total_personas"
                else f"SUM(CASE WHEN {condicion_mayor} THEN 1 ELSE 0 END)"
                if intencion.get("denominador_id") == "total_personas_mayores"
                else f"SUM(CASE WHEN {condicion_mayor} AND {tipo_operativo} = '2' THEN 1 ELSE 0 END)"
            ),
            100.0,
        ),
    }
    if indicador in formulas:
        numerador, denominador, factor = formulas[indicador]
        return f"""
            SELECT {col_geo} AS codigo,
                   {factor} * ({numerador}) / NULLIF(({denominador}), 0) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    if indicador == "tgf_aproximada_censal":
        anio = 'TRY_CAST("p48_anio_nac_uh" AS INTEGER)'
        terminos = []
        for a, b in ((15,19),(20,24),(25,29),(30,34),(35,39),(40,44),(45,49)):
            nac = f"SUM(CASE WHEN {sexo} = '2' AND {edad} BETWEEN {a} AND {b} AND {anio} = 2023 THEN 1 ELSE 0 END)"
            muj = f"SUM(CASE WHEN {sexo} = '2' AND {edad} BETWEEN {a} AND {b} THEN 1 ELSE 0 END)"
            terminos.append(f"(({nac}) / NULLIF(({muj}), 0))")
        suma = " + ".join(terminos)
        return f"""
            SELECT {col_geo} AS codigo,
                   5.0 * ({suma}) AS valor
            FROM {origen}
            {where}
            GROUP BY {col_geo}
        """

    # Tasa neta interna: reconstruye las poblaciones comparables de 2019 y
    # 2024 sobre las mismas personas con origen/destino interno identificable.
    if indicador == "tasa_migracion_neta_interna":
        _, lista_comunas = _codigos_comuna_validos_sql()
        actual = 'TRY_CAST(p."comuna" AS BIGINT)'
        p24s = 'CAST(p."p24_lug_resid5" AS VARCHAR)'
        p24esp = 'TRY_CAST(p."p24_lug_resid5_esp" AS BIGINT)'
        origen_comuna = (
            f"CASE WHEN {p24s} = '2' THEN {actual} "
            f"WHEN {p24s} = '3' AND {p24esp} IN ({lista_comunas}) THEN {p24esp} END"
        )
        if nivel == "region":
            origen_geo = f"CAST(FLOOR(({origen_comuna}) / 1000) AS INTEGER)"
            destino_geo = f"CAST(FLOOR(({actual}) / 1000) AS INTEGER)"
        elif nivel == "comuna":
            origen_geo = origen_comuna
            destino_geo = actual
        else:
            raise ValueError("La tasa neta de migración interna está disponible por región o comuna.")
        condiciones = [
            f"{actual} IN ({lista_comunas})",
            f"({p24s} = '2' OR ({p24s} = '3' AND {p24esp} IN ({lista_comunas})))",
        ]
        # El ámbito regional/comunal solicitado se aplica al resultado, no a la
        # base, porque emigrantes de un territorio pueden residir hoy fuera de él.
        f_nivel = intencion.get("filtro_geografico_nivel")
        f_codigo = intencion.get("filtro_geografico_codigo")
        if bool(f_nivel) != (f_codigo is not None):
            raise ValueError("Filtro territorial incompleto o no válido.")
        filtro_final = ""
        if f_nivel:
            if f_nivel == nivel:
                filtro_final = f"WHERE codigo = {int(f_codigo)}"
            elif nivel == "comuna" and f_nivel == "region":
                filtro_final = f"WHERE CAST(FLOOR(codigo / 1000) AS INTEGER) = {int(f_codigo)}"
            else:
                raise ValueError("El filtro territorial no es compatible con la tasa neta de migración interna.")
        base_where = " AND ".join(f"({c})" for c in condiciones)
        return f"""
            WITH base AS (
                SELECT {origen_geo} AS origen, {destino_geo} AS destino
                FROM {origen} p
                WHERE {base_where}
            ), territorios AS (
                SELECT origen AS codigo FROM base WHERE origen IS NOT NULL
                UNION
                SELECT destino AS codigo FROM base WHERE destino IS NOT NULL
            ), resumen AS (
                SELECT t.codigo,
                       SUM(CASE WHEN b.destino = t.codigo AND b.origen <> t.codigo THEN 1 ELSE 0 END) AS inmigrantes,
                       SUM(CASE WHEN b.origen = t.codigo AND b.destino <> t.codigo THEN 1 ELSE 0 END) AS emigrantes,
                       SUM(CASE WHEN b.origen = t.codigo THEN 1 ELSE 0 END) AS poblacion_2019,
                       SUM(CASE WHEN b.destino = t.codigo THEN 1 ELSE 0 END) AS poblacion_2024
                FROM territorios t CROSS JOIN base b
                GROUP BY t.codigo
            )
            SELECT codigo,
                   1000.0 * (inmigrantes - emigrantes)
                   / NULLIF(5.0 * ((poblacion_2019 + poblacion_2024) / 2.0), 0) AS valor
            FROM resumen
            {filtro_final}
            ORDER BY codigo
        """

    raise ValueError("Indicador censal v27 sin fórmula SQL registrada.")


def _ejecutar_indicador_censal_v27(intencion, avisar, inicio):
    nivel = intencion.get("nivel_geografico", "region")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    ruta = _ruta_parquet("personas")
    sql = _construir_sql_indicador_censal_v27(intencion, NIVELES[nivel], ruta)
    stat = ruta.stat()
    with _SQL_CACHE_LOCK:
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
    avisar(2, True); avisar(3, False)
    geometria = referencia_geometria(
        nivel, intencion.get("filtro_geografico_nivel"),
        intencion.get("filtro_geografico_codigo"),
    )
    avisar(3, True); avisar(4, False)
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    datos = []
    if "codigo" in df:
        df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    for fila in df.itertuples(index=False):
        if pd.isna(fila.codigo):
            continue
        codigo = int(fila.codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and int(k) == codigo), str(codigo))
        datos.append({"codigo": codigo, "nombre": nombre,
                      "valor": None if pd.isna(fila.valor) else float(fila.valor)})
    validos = df["valor"].dropna() if "valor" in df else pd.Series(dtype=float)
    avisar(4, True)
    return {
        "tipo_visualizacion": "mapa", "datos": datos, "geometria": geometria,
        "nivel_geografico": nivel, "_sql_ejecutada": sql,
        "nota": intencion.get("nota_interpretacion"),
        "valores": {"min": float(validos.min()) if len(validos) else None,
                    "max": float(validos.max()) if len(validos) else None},
    }

def _ejecutar_indicador_derivado_v24(intencion, avisar, inicio):
    """Ejecuta un índice/tasa derivada y devuelve un mapa estándar."""
    nivel = intencion.get("nivel_geografico", "region")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    ruta = _ruta_parquet("personas")
    sql = _construir_sql_indicador_derivado_v24(intencion, NIVELES[nivel], ruta)
    stat = ruta.stat()
    with _SQL_CACHE_LOCK:
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
    avisar(2, True); avisar(3, False)
    geometria = referencia_geometria(
        nivel, intencion.get("filtro_geografico_nivel"),
        intencion.get("filtro_geografico_codigo"),
    )
    avisar(3, True); avisar(4, False)
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    datos = []
    if "codigo" in df:
        df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    for fila in df.itertuples(index=False):
        if pd.isna(fila.codigo):
            continue
        codigo = int(fila.codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and int(k) == codigo), str(codigo))
        datos.append({"codigo": codigo, "nombre": nombre,
                      "valor": None if pd.isna(fila.valor) else float(fila.valor)})
    validos = df["valor"].dropna() if "valor" in df else pd.Series(dtype=float)
    avisar(4, True)
    return {
        "datos": datos,
        "geometria": geometria,
        "nivel_geografico": nivel,
        "_sql_ejecutada": sql,
        "nota": intencion.get("nota_interpretacion"),
        "valores": {
            "min": float(validos.min()) if len(validos) else None,
            "max": float(validos.max()) if len(validos) else None,
        },
    }

def _firma_geometria(nivel):
    """Invalida por ruta, tamaño/fecha de los archivos, configuración y versión."""
    archivos = []
    if GDB_PATH.exists():
        entradas = GDB_PATH.rglob("*") if GDB_PATH.is_dir() else [GDB_PATH]
        for ruta in entradas:
            # Los locks de GDAL pueden cambiar al leer y no modifican los datos.
            if ruta.is_file() and not ruta.name.lower().endswith(".lock"):
                st = ruta.stat()
                archivos.append((str(ruta.relative_to(GDB_PATH.parent)), st.st_size, st.st_mtime_ns))
    config = ["capas-v2", str(GDB_PATH.resolve()), sorted(archivos),
              nivel, NIVELES[nivel], SIMPLIFICACION, gpd.__version__]
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:24]


def _guardar_capa(gdf, ruta):
    """Escritura atómica; si el disco no permite guardar, conserva la caché RAM."""
    temporal = ruta.with_name(f"{ruta.stem}-{uuid4().hex}.tmp.gpkg")
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(temporal, layer="capa", driver="GPKG", index=False)
        os.replace(temporal, ruta)
    except Exception as exc:
        LOG.warning("No se pudo guardar la caché de cartografía: %s", exc)
    finally:
        if temporal.exists():
            try:
                temporal.unlink()
            except OSError:
                pass


def _cargar_geometria(nivel):
    """RAM -> cartografía preparada en disco -> geodatabase original."""
    inicio = perf_counter()
    with _GEOMETRY_LOCK:
        firma = _firma_geometria(nivel)
        info = NIVELES[nivel]
        origen = "memoria"
        hit = nivel in _GEOMETRIAS and _FIRMAS_GEOMETRIA.get(nivel) == firma
        if not hit:
            ruta_cache = CACHE_DIR / f"{nivel}-{firma}.gpkg"
            gdf = None
            if ruta_cache.exists():
                try:
                    paso = perf_counter()
                    gdf = gpd.read_file(ruta_cache, layer="capa")
                    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                        raise ValueError("CRS de caché incorrecto")
                    for campo in (info["campo_gdb"], info["campo_nombre"]):
                        if campo not in gdf:
                            raise ValueError(f"La caché no contiene {campo}")
                    origen = "disco"
                    LOG.info("[tiempo] lectura_cache_disco[%s]=%.3fs", nivel, perf_counter() - paso)
                except Exception as exc:
                    LOG.warning("Caché de cartografía ilegible; se regenerará: %s", exc)
                    gdf = None
            if gdf is None:
                origen = "gdb"
                # Refresca la lista por si la geodatabase cambió en este proceso.
                global _capas_cache
                _capas_cache = None
                capa = _resolver_capa(info["capa_gdb"])
                paso = perf_counter()
                gdf = gpd.read_file(GDB_PATH, layer=capa)
                LOG.info("[tiempo] lectura_gdb[%s]=%.3fs", nivel, perf_counter() - paso)
                for campo in (info["campo_gdb"], info["campo_nombre"]):
                    if campo not in gdf:
                        raise ValueError(f"La capa {capa} no contiene {campo}.")
                paso = perf_counter()
                if gdf.crs is None:
                    raise ValueError(f"La capa {capa} no tiene sistema de coordenadas definido.")
                # Guarda solo campos necesarios para nombres, llaves y filtros.
                campos = {"geometry", info["campo_gdb"], info["campo_nombre"]}
                campos.update(v["campo_gdb"] for v in NIVELES.values())
                gdf = gdf[[c for c in gdf.columns if c in campos]].to_crs(4326)
                gdf["geometry"] = gdf.geometry.simplify(SIMPLIFICACION, preserve_topology=True)
                LOG.info("[tiempo] reproyeccion_simplificacion[%s]=%.3fs", nivel, perf_counter() - paso)
                paso = perf_counter()
                _guardar_capa(gdf, ruta_cache)
                LOG.info("[tiempo] guardar_cache_disco[%s]=%.3fs", nivel, perf_counter() - paso)
            gdf[info["campo_gdb"]] = pd.to_numeric(gdf[info["campo_gdb"]], errors="raise").astype("Int64")
            _GEOMETRIAS[nivel] = gdf
            _FIRMAS_GEOMETRIA[nivel] = firma
        # Cada solicitud trabaja sobre una copia para no alterar la caché.
        resultado = _GEOMETRIAS[nivel].copy()
    LOG.info("[tiempo] geometria[%s]=%.3fs cache=%s origen=%s pid=%s",
             nivel, perf_counter() - inicio, origen != "gdb", origen, os.getpid())
    return resultado


def _codigo_json(valor):
    """Convierte códigos pandas/numpy a enteros JSON cuando corresponde."""
    if pd.isna(valor):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return str(valor)


def _valor_json(valor):
    """Evita NaN y tipos numpy en las respuestas del API."""
    if pd.isna(valor):
        return None
    if hasattr(valor, "item"):
        valor = valor.item()
    return valor


def referencia_geometria(nivel, filtro_nivel=None, filtro_codigo=None):
    """Describe una capa reutilizable sin incluir sus polígonos en la consulta."""
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    if bool(filtro_nivel) != (filtro_codigo is not None):
        raise ValueError("Filtro territorial incompleto.")
    if filtro_nivel and filtro_nivel not in NIVELES:
        raise ValueError("Nivel del filtro territorial no válido.")
    # La precarga registra la firma. Si aún no terminó, calcularla no obliga a
    # leer la capa y permite que la consulta entregue la referencia enseguida.
    firma = _FIRMAS_GEOMETRIA.get(nivel) or _firma_geometria(nivel)
    return {
        "nivel": nivel,
        "filtro_nivel": filtro_nivel,
        "filtro_codigo": int(filtro_codigo) if filtro_codigo is not None else None,
        "version": firma,
    }


def obtener_geometria_serializada(nivel, filtro_nivel=None, filtro_codigo=None):
    """Devuelve GeoJSON sin valores censales y lo conserva serializado en RAM."""
    inicio = perf_counter()
    referencia = referencia_geometria(nivel, filtro_nivel, filtro_codigo)
    clave = (nivel, filtro_nivel, referencia["filtro_codigo"], referencia["version"])
    with _GEOMETRY_LOCK:
        contenido = _GEOMETRIAS_JSON.get(clave)
    if contenido is not None:
        LOG.info("[tiempo] geometria_api[%s]=%.3fs cache=True bytes=%s",
                 nivel, perf_counter() - inicio, len(contenido))
        return contenido, referencia["version"]

    gdf = _cargar_geometria(nivel)
    intencion = {
        "filtro_geografico_nivel": filtro_nivel,
        "filtro_geografico_codigo": filtro_codigo,
    }
    gdf = _filtrar_geometrias(gdf, nivel, intencion)
    if gdf.empty:
        raise ValueError("No hay geometrías para el filtro solicitado.")
    info = NIVELES[nivel]
    centros = gdf.geometry.representative_point()
    salida = gdf[["geometry", info["campo_nombre"], info["campo_gdb"]]].copy()
    salida["centro_lon"] = centros.x
    salida["centro_lat"] = centros.y
    salida = salida.rename(columns={
        info["campo_nombre"]: "nombre", info["campo_gdb"]: "codigo",
    })
    # to_json normaliza los escalares numpy y omite el índice interno.
    contenido = salida.to_json(drop_id=True, ensure_ascii=False).encode("utf-8")
    with _GEOMETRY_LOCK:
        _GEOMETRIAS_JSON[clave] = contenido
    LOG.info("[tiempo] geometria_api[%s]=%.3fs cache=False poligonos=%s bytes=%s",
             nivel, perf_counter() - inicio, len(salida), len(contenido))
    return contenido, referencia["version"]


def precalentar_geometrias(niveles=None):
    """Carga y serializa las capas configuradas al iniciar el servidor."""
    niveles = list(niveles or NIVELES)
    inicio = perf_counter()
    with _PREWARM_LOCK:
        _ESTADO_PRECALENTAMIENTO.update(
            estado="en_curso", niveles_listos=[], errores={}, inicio_segundos=0.0
        )
    for nivel in niveles:
        if nivel not in NIVELES:
            with _PREWARM_LOCK:
                _ESTADO_PRECALENTAMIENTO["errores"][nivel] = "Nivel desconocido"
            continue
        paso = perf_counter()
        try:
            obtener_geometria_serializada(nivel)
            with _PREWARM_LOCK:
                _ESTADO_PRECALENTAMIENTO["niveles_listos"].append(nivel)
            LOG.info("[precalentamiento] nivel=%s listo tiempo=%.3fs",
                     nivel, perf_counter() - paso)
        except Exception as exc:
            with _PREWARM_LOCK:
                _ESTADO_PRECALENTAMIENTO["errores"][nivel] = str(exc)
            LOG.exception("[precalentamiento] nivel=%s error=%s", nivel, exc)
    with _PREWARM_LOCK:
        errores = bool(_ESTADO_PRECALENTAMIENTO["errores"])
        listos = bool(_ESTADO_PRECALENTAMIENTO["niveles_listos"])
        _ESTADO_PRECALENTAMIENTO["estado"] = (
            "parcial" if errores and listos else "error" if errores else "listo"
        )
        _ESTADO_PRECALENTAMIENTO["duracion_segundos"] = round(
            perf_counter() - inicio, 3
        )
    LOG.info("[precalentamiento] estado=%s tiempo_total=%.3fs",
             _ESTADO_PRECALENTAMIENTO["estado"], perf_counter() - inicio)


def estado_precalentamiento():
    """Copia segura para el endpoint de salud."""
    with _PREWARM_LOCK:
        return deepcopy(_ESTADO_PRECALENTAMIENTO)


@lru_cache(maxsize=64)
def _consultar_sql(sql, ruta, mtime_ns, size):
    """Cachea agregados pequeños; invalida al cambiar tamaño o fecha del parquet."""
    with duckdb.connect(database=":memory:") as conexion:
        return conexion.execute(sql).df()


def _filtrar_geometrias(gdf, nivel, intencion):
    """Selecciona polígonos del territorio solicitado, incluso sin observaciones."""
    filtro = intencion.get("filtro_geografico_nivel")
    codigo = intencion.get("filtro_geografico_codigo")
    if not filtro or codigo is None:
        return gdf
    codigo = int(codigo)
    campo = NIVELES[filtro]["campo_gdb"]
    if campo in gdf.columns:
        return gdf.loc[pd.to_numeric(gdf[campo], errors="coerce") == codigo].copy()
    # Para capas sin código de la unidad superior, selecciona por un punto
    # interior. No usa intersección de bordes (incluiría territorios vecinos).
    orden = {"region": 0, "provincia": 1, "comuna": 2}
    if orden[filtro] > orden[nivel]:
        raise ValueError("El filtro es más específico que el nivel del mapa; pedir ese nivel o uno inferior.")
    limite = _cargar_geometria(filtro)
    limite = limite.loc[limite[campo] == codigo]
    if limite.empty:
        raise ValueError("El territorio solicitado no existe en la cartografía.")
    mascara = gdf.geometry.representative_point().apply(
        lambda punto: any(poligono.covers(punto) for poligono in limite.geometry))
    return gdf.loc[mascara].copy()


def _ejecutar_distribucion(intencion, progreso, inicio):
    """Calcula una distribución categórica para cada polígono del mapa."""
    avisar = progreso or (lambda etapa, terminado: None)
    tabla = intencion["tabla"]
    nombre_variable = intencion["variable"]
    if tabla not in TABLAS_PARQUET or nombre_variable not in VARIABLES[tabla]["variables"]:
        raise ValueError("Tabla o variable desconocida para la distribución.")
    ruta = _ruta_parquet(tabla)
    variable = '"' + nombre_variable.replace('"', '""') + '"'
    nivel = intencion.get("nivel_geografico", "comuna")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    nivel_info = NIVELES[nivel]
    col_geo = nivel_info["col_parquet"]
    filtros = []
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if f_nivel:
        filtros.append(f"{NIVELES[f_nivel]['col_parquet']} = {int(f_codigo)}")
    for filtro_numerico in intencion.get("filtros_numericos") or []:
        filtros.extend(_condiciones_rango(tabla, filtro_numerico, incluir_solicitado=True))
    if intencion.get("edad_minima") is not None:
        edad = intencion.get("variable_edad")
        if tabla != "personas" or edad not in VARIABLES[tabla]["variables"]:
            raise ValueError("Variable de edad no válida.")
        edad_sql = '"' + edad.replace('"', '""') + '"'
        filtros.append(f"TRY_CAST({edad_sql} AS DOUBLE) >= {int(intencion['edad_minima'])}")
    validas = intencion.get("categorias_validas") or categorias_validas(tabla, nombre_variable)
    if len(validas) < 2:
        raise ValueError("La variable no tiene suficientes categorías válidas.")
    lista_validas = ", ".join("'" + str(v).replace("'", "''") + "'" for v in validas)
    filtros.append(f"CAST({variable} AS VARCHAR) IN ({lista_validas})")
    where = "WHERE " + " AND ".join(filtros)
    ruta_sql = ruta.as_posix().replace("'", "''")
    sql = f"""
        SELECT {col_geo} AS codigo,
               CAST({variable} AS VARCHAR) AS categoria,
               COUNT(*) AS valor
        FROM read_parquet('{ruta_sql}')
        {where}
        GROUP BY {col_geo}, categoria
        ORDER BY {col_geo}, valor DESC, categoria
    """
    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] distribucion_duckdb=%.3fs cache=%s filas=%s",
             perf_counter() - paso, hit, len(df))
    avisar(2, True)
    avisar(3, False)
    geometria = referencia_geometria(
        nivel, intencion.get("filtro_geografico_nivel"),
        intencion.get("filtro_geografico_codigo"),
    )
    avisar(3, True)
    avisar(4, False)
    df["codigo"] = df["codigo"].astype("Int64")
    df["categoria"] = df["categoria"].astype(str)
    etiquetas = VARIABLES[tabla]["variables"][nombre_variable]["categorias"]
    # Se usan las mismas cinco categorías principales en todos los polígonos,
    # calculadas sobre el territorio completo de la consulta.
    totales_categoria = (df.groupby("categoria", as_index=False)["valor"].sum()
                         .sort_values(["valor", "categoria"], ascending=[False, True]))
    codigos_ordenados = totales_categoria["categoria"].tolist()
    principales = codigos_ordenados[:5] if len(codigos_ordenados) > 5 else codigos_ordenados
    agrupar_otros = len(codigos_ordenados) > 5
    categorias_grafico = [
        {"codigo": codigo, "etiqueta": str(etiquetas.get(codigo, codigo))}
        for codigo in principales
    ]
    if agrupar_otros:
        categorias_grafico.append({"codigo": "otros", "etiqueta": "Otros"})

    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    datos = []
    for codigo, grupo in df.groupby("codigo"):
        conteos = {str(fila.categoria): int(fila.valor)
                   for fila in grupo.itertuples(index=False)}
        total = sum(conteos.values())
        # V33: la visualización conserva las cuatro principales + Otros,
        # pero la respuesta guarda además todas las categorías válidas para Excel.
        distribucion_completa = []
        for categoria in [str(v) for v in validas]:
            valor = conteos.get(categoria, 0)
            distribucion_completa.append({
                "codigo": categoria,
                "etiqueta": str(etiquetas.get(categoria, categoria)),
                "valor": valor,
                "porcentaje": 100.0 * valor / total if total else None,
            })

        distribucion_completa = []
        for categoria in codigos_ordenados:
            valor = conteos.get(categoria, 0)
            distribucion_completa.append({
                "codigo": categoria,
                "etiqueta": str(etiquetas.get(categoria, categoria)),
                "valor": valor,
                "porcentaje": 100.0 * valor / total if total else None,
            })

        distribucion = []
        for categoria in principales:
            valor = conteos.get(categoria, 0)
            distribucion.append({
                "codigo": categoria,
                "etiqueta": str(etiquetas.get(categoria, categoria)),
                "valor": valor,
                "porcentaje": 100.0 * valor / total if total else None,
            })
        if agrupar_otros:
            valor_otros = sum(valor for categoria, valor in conteos.items()
                              if categoria not in principales)
            distribucion.append({
                "codigo": "otros", "etiqueta": "Otros", "valor": valor_otros,
                "porcentaje": 100.0 * valor_otros / total if total else None,
            })
        codigo_json = _codigo_json(codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and str(codigo_json).isdigit()
                       and int(k) == int(codigo_json)), str(codigo_json))
        datos.append({"codigo": codigo_json, "nombre": nombre,
                      "distribucion": distribucion,
                      "distribucion_completa": distribucion_completa,
                      "total": total})
    resultado = {
        "tipo_visualizacion": "tortas_mapa",
        "datos": datos,
        "geometria": geometria,
        "nivel_geografico": nivel,
        "categorias_grafico": categorias_grafico,
        "_sql_ejecutada": sql,
    }
    avisar(4, True)
    LOG.info("[tiempo] distribucion_total=%.3fs filas_salida=%s",
             perf_counter() - inicio, len(datos))
    return resultado



def _ejecutar_dimensiones_funcionales(intencion, progreso, inicio):
    """Compara las seis dimensiones P32 dentro de cada zona geográfica.

    Cada zona recibe un mini gráfico de seis barras. Las dimensiones no son
    mutuamente excluyentes. Para porcentajes, cada dimensión usa como
    denominador sus respuestas válidas P32 (categorías 1-4).
    """
    avisar = progreso or (lambda etapa, terminado: None)
    tabla = intencion.get("tabla")
    if tabla != "personas":
        raise ValueError("Las dimensiones funcionales P32 pertenecen a la tabla personas.")
    variables = intencion.get("variables_dimensiones") or []
    etiquetas = intencion.get("etiquetas_dimensiones") or {}
    severidad = str(intencion.get("categoria_valor") or "")
    if severidad not in {"1", "2", "3", "4"}:
        raise ValueError("El grado de dificultad P32 no es válido.")
    for variable in variables:
        if variable not in VARIABLES["personas"]["variables"]:
            raise ValueError(f"La dimensión funcional '{variable}' no existe en el diccionario.")

    nivel = intencion.get("nivel_geografico", "region")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    col_geo = NIVELES[nivel]["col_parquet"]
    ruta = _ruta_parquet("personas")
    filtros = []
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if f_nivel:
        filtros.append(f"{NIVELES[f_nivel]['col_parquet']} = {int(f_codigo)}")

    if intencion.get("edad_minima") is not None:
        edad = intencion.get("variable_edad")
        if edad not in VARIABLES["personas"]["variables"]:
            raise ValueError("Variable de edad no válida.")
        edad_sql = '"' + edad.replace('"', '""') + '"'
        filtros.append(f"TRY_CAST({edad_sql} AS DOUBLE) >= {int(intencion['edad_minima'])}")

    for filtro_numerico in intencion.get("filtros_numericos") or []:
        filtros.extend(_condiciones_rango("personas", filtro_numerico, incluir_solicitado=True))

    expresiones = []
    for variable in variables:
        var_sql = '"' + variable.replace('"', '""') + '"'
        validas = categorias_validas("personas", variable)
        validas = [str(v) for v in validas if str(v) in {"1", "2", "3", "4"}]
        if len(validas) != 4:
            raise ValueError(
                f"La dimensión {variable} no contiene las cuatro categorías P32 esperadas."
            )
        valores_validos = ", ".join("'" + v.replace("'", "''") + "'" for v in validas)
        alias_n = variable.replace('"', '""') + "__n"
        alias_d = variable.replace('"', '""') + "__d"
        expresiones.append(
            f"SUM(CASE WHEN CAST({var_sql} AS VARCHAR) = '{severidad}' THEN 1 ELSE 0 END) AS \"{alias_n}\""
        )
        expresiones.append(
            f"SUM(CASE WHEN CAST({var_sql} AS VARCHAR) IN ({valores_validos}) THEN 1 ELSE 0 END) AS \"{alias_d}\""
        )

    ruta_sql = ruta.as_posix().replace("'", "''")
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    sql = f"""SELECT {col_geo} AS codigo, {', '.join(expresiones)}
              FROM read_parquet('{ruta_sql}') {where}
              GROUP BY {col_geo}
              ORDER BY {col_geo}"""

    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] dimensiones_p32_duckdb=%.3fs cache=%s filas=%s",
             perf_counter() - paso, hit, len(df))
    avisar(2, True)

    avisar(3, False)
    geometria = referencia_geometria(nivel, f_nivel, f_codigo)
    avisar(3, True)
    avisar(4, False)

    if len(df):
        df["codigo"] = df["codigo"].astype("Int64")
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    metrica = intencion.get("metrica_dimensiones", "conteo")
    datos = []
    for fila in df.itertuples(index=False):
        codigo = _codigo_json(fila.codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and str(codigo).isdigit()
                       and int(k) == int(codigo)), str(codigo))
        barras = []
        for variable in variables:
            conteo_raw = getattr(fila, f"{variable}__n")
            denominador_raw = getattr(fila, f"{variable}__d")
            conteo = int(conteo_raw) if pd.notna(conteo_raw) else 0
            denominador = int(denominador_raw) if pd.notna(denominador_raw) else 0
            porcentaje = 100.0 * conteo / denominador if denominador else None
            barras.append({
                "variable": variable,
                "etiqueta": etiquetas.get(variable, VARIABLES["personas"]["variables"][variable]["descripcion"]),
                "valor": porcentaje if metrica == "porcentaje" else conteo,
                "conteo": conteo,
                "porcentaje": porcentaje,
                "denominador": denominador,
            })
        datos.append({"codigo": codigo, "nombre": nombre, "barras": barras})

    avisar(4, True)
    return {
        "tipo_visualizacion": "barras_mapa",
        "datos": datos,
        "geometria": geometria,
        "metrica": metrica,
        "severidad_codigo": severidad,
        "severidad_etiqueta": VARIABLES["personas"]["variables"][variables[0]]["categorias"][severidad],
        "nivel_geografico": nivel,
        "filtro_geografico_nivel": f_nivel,
        "filtro_geografico_codigo": f_codigo,
        "dimensiones": [{"variable": v, "etiqueta": etiquetas.get(v, v)} for v in variables],
        "nota": intencion.get("nota_interpretacion"),
        "_sql_ejecutada": sql,
    }




# ---------------------------------------------------------------------------
# Cruces multientidad
# ---------------------------------------------------------------------------
_ALIAS_ENTIDAD = {"personas": "p", "hogares": "h", "viviendas": "v"}


def _col(alias, variable):
    return f'{alias}."{str(variable).replace(chr(34), chr(34) * 2)}"'


def _clave_distinta(entidad):
    a = _ALIAS_ENTIDAD[entidad]
    if entidad == "personas":
        return (f"concat_ws('|', CAST({a}.id_vivienda AS VARCHAR), "
                f"CAST({a}.id_hogar AS VARCHAR), CAST({a}.id_persona AS VARCHAR))")
    if entidad == "hogares":
        return (f"concat_ws('|', CAST({a}.id_vivienda AS VARCHAR), "
                f"CAST({a}.id_hogar AS VARCHAR))")
    return f"CAST({a}.id_vivienda AS VARCHAR)"


def _origenes_cruce(tablas):
    """FROM/JOIN canónico. Solo une de la entidad inferior hacia superiores."""
    tablas = set(tablas)
    rutas = {tabla: _ruta_parquet(tabla) for tabla in tablas}
    def src(tabla):
        ruta = rutas[tabla].as_posix().replace("'", "''")
        return f"read_parquet('{ruta}') {_ALIAS_ENTIDAD[tabla]}"

    if "personas" in tablas:
        sql = f"FROM {src('personas')}"
        if "hogares" in tablas:
            sql += (f" JOIN {src('hogares')} ON p.id_vivienda = h.id_vivienda "
                    f"AND p.id_hogar = h.id_hogar")
        if "viviendas" in tablas:
            if "hogares" in tablas:
                sql += f" JOIN {src('viviendas')} ON h.id_vivienda = v.id_vivienda"
            else:
                sql += f" JOIN {src('viviendas')} ON p.id_vivienda = v.id_vivienda"
        return sql, rutas
    if "hogares" in tablas:
        sql = f"FROM {src('hogares')}"
        if "viviendas" in tablas:
            sql += f" JOIN {src('viviendas')} ON h.id_vivienda = v.id_vivienda"
        return sql, rutas
    return f"FROM {src('viviendas')}", rutas


def _tablas_nodo_filtro(nodo):
    """Tablas que deben participar en el FROM principal.

    Los filtros jerárquicos (EXISTS/COUNT sobre miembros) se ejecutan en una
    subconsulta correlacionada y, por tanto, no fuerzan a incorporar personas
    al JOIN principal cuando la entidad objetivo es hogar/vivienda.
    """
    if not isinstance(nodo, dict):
        return set()
    if nodo.get("op") in {"and", "or"}:
        salida = set()
        for item in nodo.get("args") or []:
            salida.update(_tablas_nodo_filtro(item))
        return salida
    if nodo.get("op") == "not":
        return _tablas_nodo_filtro(nodo.get("arg"))
    if nodo.get("tipo") in {"existe_en_hogar", "no_existe_en_hogar", "conteo_relacionado"}:
        return set()
    tabla = nodo.get("tabla")
    return {tabla} if tabla in TABLAS_PARQUET else set()


def _condicion_filtro_cruce(filtro, objetivo=None, alias_overrides=None):
    """Compila un filtro o AST lógico a SQL seguro y validado."""
    alias_overrides = alias_overrides or {}
    if not isinstance(filtro, dict):
        raise ValueError("El filtro del plan no tiene un formato válido.")

    op_logico = filtro.get("op")
    if op_logico in {"and", "or"}:
        partes = [
            _condicion_filtro_cruce(x, objetivo=objetivo, alias_overrides=alias_overrides)
            for x in (filtro.get("args") or [])
        ]
        partes = [p for p in partes if p]
        if not partes:
            raise ValueError("El grupo lógico no contiene condiciones válidas.")
        conector = " AND " if op_logico == "and" else " OR "
        return "(" + conector.join(f"({p})" for p in partes) + ")"
    if op_logico == "not":
        interno = _condicion_filtro_cruce(
            filtro.get("arg"), objetivo=objetivo, alias_overrides=alias_overrides
        )
        return f"NOT ({interno})"

    tipo = filtro.get("tipo")
    if tipo in {"existe_en_hogar", "no_existe_en_hogar", "conteo_relacionado"}:
        if objetivo not in {"personas", "hogares", "viviendas"}:
            raise ValueError("El filtro jerárquico requiere una entidad objetivo válida.")
        subfiltros = filtro.get("subfiltros") or []
        if not subfiltros:
            raise ValueError("El filtro jerárquico no contiene condiciones internas.")
        alias_obj = _ALIAS_ENTIDAD[objetivo]
        ruta = _ruta_parquet("personas").as_posix().replace("'", "''")
        enlaces = [f"px.id_vivienda = {alias_obj}.id_vivienda"]
        if objetivo in {"personas", "hogares"}:
            enlaces.append(f"px.id_hogar = {alias_obj}.id_hogar")
        condiciones_sub = list(enlaces)
        for sub in subfiltros:
            condiciones_sub.append(_condicion_filtro_cruce(
                sub, objetivo="personas", alias_overrides={"personas": "px"}
            ))
        where_sub = " AND ".join(f"({x})" for x in condiciones_sub)
        if tipo == "conteo_relacionado":
            minimo = int(filtro.get("min_conteo", 1))
            maximo = filtro.get("max_conteo")
            clave_px = "concat_ws('|', CAST(px.id_vivienda AS VARCHAR), CAST(px.id_hogar AS VARCHAR), CAST(px.id_persona AS VARCHAR))"
            expr = f"(SELECT COUNT(DISTINCT {clave_px}) FROM read_parquet('{ruta}') px WHERE {where_sub})"
            condiciones = [f"{expr} >= {minimo}"]
            if maximo is not None:
                condiciones.append(f"{expr} <= {int(maximo)}")
            return " AND ".join(condiciones)
        exists = f"EXISTS (SELECT 1 FROM read_parquet('{ruta}') px WHERE {where_sub})"
        return f"NOT ({exists})" if tipo == "no_existe_en_hogar" else exists

    tabla = filtro.get("tabla")
    variable = filtro.get("variable")
    if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError("El plan de cruce contiene una variable de filtro desconocida.")
    alias = alias_overrides.get(tabla, _ALIAS_ENTIDAD[tabla])
    expr = _col(alias, variable)

    if tipo == "categoria":
        valores = [str(v) for v in (filtro.get("valores") or [])]
        codigos = {str(c) for c in VARIABLES[tabla]["variables"][variable]["categorias"]}
        if not valores or any(v not in codigos for v in valores):
            raise ValueError("El plan de cruce contiene una categoría que no existe en el diccionario.")
        lista = ", ".join("'" + v.replace("'", "''") + "'" for v in valores)
        modo = filtro.get("modo", "in")
        if modo not in {"in", "not_in"}:
            raise ValueError("Modo categórico no válido.")
        return f"CAST({expr} AS VARCHAR) {'NOT IN' if modo == 'not_in' else 'IN'} ({lista})"

    if tipo == "rango":
        partes = [f"TRY_CAST({expr} AS DOUBLE) IS NOT NULL"]
        if filtro.get("dominio_minimo") is not None:
            partes.append(f"TRY_CAST({expr} AS DOUBLE) >= {_numero_sql(filtro['dominio_minimo'], 'dominio_minimo')}")
        if filtro.get("dominio_maximo") is not None:
            partes.append(f"TRY_CAST({expr} AS DOUBLE) <= {_numero_sql(filtro['dominio_maximo'], 'dominio_maximo')}")
        if filtro.get("minimo") is not None:
            op = ">=" if filtro.get("incluir_minimo", True) else ">"
            partes.append(f"TRY_CAST({expr} AS DOUBLE) {op} {_numero_sql(filtro['minimo'], 'mínimo')}")
        if filtro.get("maximo") is not None:
            op = "<=" if filtro.get("incluir_maximo", True) else "<"
            partes.append(f"TRY_CAST({expr} AS DOUBLE) {op} {_numero_sql(filtro['maximo'], 'máximo')}")
        return " AND ".join(partes)

    if tipo == "comparacion":
        operador = filtro.get("operador")
        if operador not in {"=", "!=", "<>", ">", "<", ">=", "<="}:
            raise ValueError("Operador de comparación no permitido.")
        valor = _numero_sql(filtro.get("valor"), "valor de comparación")
        return f"TRY_CAST({expr} AS DOUBLE) {operador} {valor}"

    raise ValueError("Tipo de filtro de cruce no admitido.")


def _expresion_dimension(dimension, indice):
    tabla, variable = dimension.get("tabla"), dimension.get("variable")
    if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError("El plan de cruce contiene una dimensión desconocida.")
    expr = _col(_ALIAS_ENTIDAD[tabla], variable)
    # V33: edad simple se agrupa por año cumplido y excluye códigos especiales.
    if dimension.get("tipo") == "edad_simple":
        edad = f"TRY_CAST({expr} AS INTEGER)"
        return f"{edad} AS d{indice}", edad, f"{edad} BETWEEN 0 AND 120"
    if dimension.get("tipo") == "recode_rangos":
        grupos = dimension.get("grupos") or []
        if len(grupos) < 2:
            raise ValueError("La recodificación requiere al menos dos grupos.")
        partes = ["CASE"]
        for grupo in grupos:
            cond = [f"TRY_CAST({expr} AS DOUBLE) IS NOT NULL"]
            if grupo.get("minimo") is not None:
                cond.append(f"TRY_CAST({expr} AS DOUBLE) >= {_numero_sql(grupo['minimo'], 'mínimo de grupo')}")
            if grupo.get("maximo") is not None:
                cond.append(f"TRY_CAST({expr} AS DOUBLE) <= {_numero_sql(grupo['maximo'], 'máximo de grupo')}")
            etiqueta = str(grupo.get("etiqueta") or "").replace("'", "''")
            partes.append(" WHEN " + " AND ".join(cond) + f" THEN '{etiqueta}'")
        partes.append(" ELSE NULL END")
        case = "".join(partes)
        return f"{case} AS d{indice}", case, f"({case}) IS NOT NULL"

    validas = [str(v) for v in (dimension.get("categorias_validas") or categorias_validas(tabla, variable))]
    if len(validas) < 2:
        raise ValueError("Una dimensión del cruce no tiene suficientes categorías válidas.")
    lista = ", ".join("'" + v.replace("'", "''") + "'" for v in validas)
    return f"CAST({expr} AS VARCHAR) AS d{indice}", f"CAST({expr} AS VARCHAR)", f"CAST({expr} AS VARCHAR) IN ({lista})"


def _expresion_medida(plan, objetivo):
    medida = plan.get("medida") or {"operacion": "conteo_distinto", "entidad": objetivo}
    operacion = medida.get("operacion", "conteo_distinto")
    if operacion == "conteo_distinto":
        return f"COUNT(DISTINCT {_clave_distinta(objetivo)})", operacion
    tabla, variable = medida.get("tabla"), medida.get("variable")
    if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError("La medida numérica no existe en el diccionario.")
    expr = f"TRY_CAST({_col(_ALIAS_ENTIDAD[tabla], variable)} AS DOUBLE)"
    agregadores = {
        "promedio": f"AVG({expr})",
        "mediana": f"MEDIAN({expr})",
        "suma": f"SUM({expr})",
        "minimo": f"MIN({expr})",
        "maximo": f"MAX({expr})",
    }
    if operacion not in agregadores:
        raise ValueError("Operación de medida avanzada no admitida.")
    return agregadores[operacion], operacion


def _construir_sql_cruce(intencion):
    plan = intencion.get("plan_cruce") or {}
    objetivo = plan.get("entidad_objetivo")
    if objetivo not in TABLAS_PARQUET:
        raise ValueError("El plan de cruce no define una entidad objetivo válida.")
    dimensiones = plan.get("dimensiones") or []
    version = int(plan.get("version", 1) or 1)
    if len(dimensiones) > (3 if version >= 2 else 2):
        raise ValueError("El motor admite hasta tres dimensiones simultáneas en QueryPlan v2.")

    tablas = {objetivo}
    for d in dimensiones:
        if d.get("tabla") in TABLAS_PARQUET:
            tablas.add(d["tabla"])
    medida = plan.get("medida") or {}
    if medida.get("tabla") in TABLAS_PARQUET:
        tablas.add(medida["tabla"])
    if version >= 2:
        tablas.update(_tablas_nodo_filtro(plan.get("filtro_ast")))
        tablas.update(_tablas_nodo_filtro(plan.get("universo_ast")))
    else:
        tablas.update(f["tabla"] for f in (plan.get("filtros") or []) if f.get("tabla") in TABLAS_PARQUET)

    origen, rutas = _origenes_cruce(tablas)
    alias_obj = _ALIAS_ENTIDAD[objetivo]
    nivel = intencion.get("nivel_geografico", "region")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    geo = _col(alias_obj, NIVELES[nivel]["col_parquet"])

    select_dims = []
    group_dims = []
    condiciones = []
    for i, d in enumerate(dimensiones):
        select_sql, group_sql, condicion = _expresion_dimension(d, i)
        select_dims.append(select_sql)
        group_dims.append(group_sql)
        if condicion:
            condiciones.append(condicion)

    if version >= 2:
        if plan.get("universo_ast"):
            condiciones.append(_condicion_filtro_cruce(plan["universo_ast"], objetivo=objetivo))
        if plan.get("filtro_ast"):
            condiciones.append(_condicion_filtro_cruce(plan["filtro_ast"], objetivo=objetivo))
        for sel in plan.get("selecciones_geograficas") or []:
            nivel_sel = sel.get("nivel")
            codigos = [int(c) for c in (sel.get("codigos") or [])]
            if nivel_sel not in NIVELES or not codigos:
                continue
            lista = ", ".join(str(c) for c in codigos)
            condiciones.append(f"{_col(alias_obj, NIVELES[nivel_sel]['col_parquet'])} IN ({lista})")
    else:
        for filtro in plan.get("filtros") or []:
            condiciones.append(_condicion_filtro_cruce(filtro, objetivo=objetivo))

    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if f_nivel:
        condiciones.append(f"{_col(alias_obj, NIVELES[f_nivel]['col_parquet'])} = {int(f_codigo)}")

    medida_sql, medida_op = _expresion_medida(plan, objetivo)
    select_extra = (", " + ", ".join(select_dims)) if select_dims else ""
    group_extra_select = ", ".join(f"d{i}" for i in range(len(dimensiones)))
    group_by = ", " + ", ".join(group_dims) if group_dims else ""
    order_by = ", " + group_extra_select if group_extra_select else ""
    where = "WHERE " + " AND ".join(f"({c})" for c in condiciones if c) if condiciones else ""
    sql = f"""
        SELECT {geo} AS codigo{select_extra}, {medida_sql} AS valor
        {origen}
        {where}
        GROUP BY {geo}{group_by}
        ORDER BY {geo}{order_by}
    """
    return sql, rutas


def _construir_sql_denominador_cruce(intencion):
    """SQL independiente para un denominador elegido por el usuario.

    El numerador conserva todos los filtros del QueryPlan. El denominador usa
    exclusivamente el AST seleccionado (o ninguna condición para el total de
    la entidad), además de las restricciones geográficas de la consulta.
    """
    plan = intencion.get("plan_cruce") or {}
    pct = plan.get("porcentaje") or {}
    if not pct.get("denominador_personalizado"):
        return None, {}
    objetivo = plan.get("entidad_objetivo")
    if objetivo not in TABLAS_PARQUET:
        raise ValueError("El denominador no define una entidad objetivo válida.")
    den_ast = pct.get("denominador_ast")
    tablas = {objetivo}
    tablas.update(_tablas_nodo_filtro(den_ast))
    origen, rutas = _origenes_cruce(tablas)
    alias_obj = _ALIAS_ENTIDAD[objetivo]
    nivel = intencion.get("nivel_geografico", "region")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    geo = _col(alias_obj, NIVELES[nivel]["col_parquet"])
    condiciones = []
    if den_ast:
        condiciones.append(_condicion_filtro_cruce(den_ast, objetivo=objetivo))
    for sel in plan.get("selecciones_geograficas") or []:
        nivel_sel = sel.get("nivel")
        codigos = [int(c) for c in (sel.get("codigos") or [])]
        if nivel_sel not in NIVELES or not codigos:
            continue
        lista = ", ".join(str(c) for c in codigos)
        condiciones.append(f"{_col(alias_obj, NIVELES[nivel_sel]['col_parquet'])} IN ({lista})")
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None) or (f_nivel and f_nivel not in NIVELES):
        raise ValueError("Filtro territorial incompleto o no válido.")
    if f_nivel:
        condiciones.append(f"{_col(alias_obj, NIVELES[f_nivel]['col_parquet'])} = {int(f_codigo)}")
    where = "WHERE " + " AND ".join(f"({c})" for c in condiciones if c) if condiciones else ""
    sql = f"""
        SELECT {geo} AS codigo, COUNT(DISTINCT {_clave_distinta(objetivo)}) AS denominador
        {origen}
        {where}
        GROUP BY {geo}
        ORDER BY {geo}
    """
    return sql, rutas


def _consultar_denominador_cruce(intencion):
    """Ejecuta y devuelve {codigo: denominador} para un porcentaje personalizado."""
    sql, rutas = _construir_sql_denominador_cruce(intencion)
    if not sql:
        return None, None
    firma = "|".join(
        f"{tabla}:{ruta.stat().st_mtime_ns}:{ruta.stat().st_size}"
        for tabla, ruta in sorted(rutas.items())
    )
    df = _consultar_sql(sql, firma, hash(firma), sum(r.stat().st_size for r in rutas.values())).copy()
    salida = {}
    for fila in df.itertuples(index=False):
        codigo = _codigo_json(fila.codigo)
        valor = getattr(fila, "denominador", None)
        salida[codigo] = 0.0 if pd.isna(valor) else float(valor)
    return salida, sql


def _etiqueta_categoria_cruce(dimension, codigo):
    if dimension.get("tipo") == "edad_simple":
        try:
            return f"{int(float(codigo))} años"
        except (TypeError, ValueError):
            return str(codigo)
    if dimension.get("tipo") == "recode_rangos":
        return str(codigo)
    tabla, variable = dimension["tabla"], dimension["variable"]
    info = VARIABLES[tabla]["variables"][variable]
    return str(info["categorias"].get(str(codigo), codigo))


def _config_piramide_cruce(plan, intencion):
    """Describe cómo convertir una distribución edad×sexo en pirámides.

    No filtra ni duplica datos: la interfaz selecciona qué territorio mostrar,
    mientras la respuesta y el Excel conservan todos los territorios.
    """
    dimensiones = plan.get("dimensiones") or []
    if plan.get("entidad_objetivo") != "personas" or len(dimensiones) != 2:
        return None
    if (plan.get("medida") or {}).get("operacion", "conteo_distinto") != "conteo_distinto":
        return None
    if plan.get("porcentaje"):
        return None

    indice_sexo = next((i for i, d in enumerate(dimensiones)
                        if d.get("tabla") == "personas" and d.get("variable") == "sexo"), None)
    indice_edad = next((i for i, d in enumerate(dimensiones)
                        if d.get("tabla") == "personas" and d.get("variable") in {"edad", "edad_quinquenal"}), None)
    if indice_sexo is None or indice_edad is None:
        return None
    edad_dim = dimensiones[indice_edad]
    if edad_dim.get("variable") == "edad" and edad_dim.get("tipo") not in {"edad_simple", "recode_rangos"}:
        return None

    etiquetas_edad = {}
    orden_edad = []
    if edad_dim.get("tipo") == "recode_rangos":
        for grupo in edad_dim.get("grupos") or []:
            etiqueta = str(grupo.get("etiqueta") or "")
            if etiqueta:
                etiquetas_edad[etiqueta] = etiqueta
                orden_edad.append(etiqueta)
    elif edad_dim.get("variable") == "edad_quinquenal":
        cats = VARIABLES["personas"]["variables"]["edad_quinquenal"].get("categorias", {})
        for codigo in categorias_validas("personas", "edad_quinquenal"):
            codigo = str(codigo)
            etiquetas_edad[codigo] = str(cats.get(codigo, codigo))
            orden_edad.append(codigo)

    nivel = intencion.get("nivel_geografico", "region")
    filtro_region_unico = intencion.get("filtro_geografico_nivel") == "region"
    selecciones_region = [s for s in (plan.get("selecciones_geograficas") or [])
                          if s.get("nivel") == "region" and s.get("codigos")]
    if len(selecciones_region) == 1 and len(selecciones_region[0].get("codigos") or []) == 1:
        filtro_region_unico = True
    selector_region = nivel == "comuna" and not filtro_region_unico

    regiones = []
    for codigo, nombre in VARIABLES.get("geografia", {}).get("region", {}).items():
        if str(codigo).isdigit():
            regiones.append({"codigo": int(codigo), "nombre": str(nombre)})
    regiones.sort(key=lambda x: x["codigo"])

    return {
        "disponible": True,
        "indice_edad": indice_edad,
        "indice_sexo": indice_sexo,
        "tipo_edad": edad_dim.get("tipo") or "categoria",
        "variable_edad": edad_dim.get("variable"),
        "etiquetas_edad": etiquetas_edad,
        "orden_edad": orden_edad,
        "sexo_hombre_codigo": "1",
        "sexo_mujer_codigo": "2",
        "nivel_geografico": nivel,
        "selector_region": selector_region,
        "region_default": 13,
        "regiones": regiones,
    }


def _denominadores_porcentaje(combinaciones, base, n_dims):
    denominadores = {}
    if base == "total" or n_dims <= 1:
        for item in combinaciones:
            clave = (item["codigo_geo"],)
            denominadores[clave] = denominadores.get(clave, 0.0) + float(item["valor"] or 0)
        return denominadores, lambda item: (item["codigo_geo"],)
    indice = 0 if base == "fila" else 1
    if indice >= n_dims:
        indice = 0
    for item in combinaciones:
        clave = (item["codigo_geo"], item["codigos"][indice])
        denominadores[clave] = denominadores.get(clave, 0.0) + float(item["valor"] or 0)
    return denominadores, lambda item: (item["codigo_geo"], item["codigos"][indice])


def _ejecutar_cruce(intencion, progreso, inicio):
    """Ejecuta QueryPlan v1/v2 sin exponer microdatos."""
    avisar = progreso or (lambda etapa, terminado: None)
    plan = intencion.get("plan_cruce") or {}
    dimensiones = plan.get("dimensiones") or []
    objetivo = plan.get("entidad_objetivo")
    sql, rutas = _construir_sql_cruce(intencion)

    firma = "|".join(
        f"{tabla}:{ruta.stat().st_mtime_ns}:{ruta.stat().st_size}"
        for tabla, ruta in sorted(rutas.items())
    )
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, firma, hash(firma), sum(r.stat().st_size for r in rutas.values())).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] cruce_duckdb=%.3fs cache=%s filas=%s entidad=%s version=%s",
             perf_counter() - paso, hit, len(df), objetivo, plan.get("version", 1))
    avisar(2, True)

    nivel = intencion.get("nivel_geografico", "region")
    avisar(3, False)
    geometria = referencia_geometria(
        nivel, intencion.get("filtro_geografico_nivel"),
        intencion.get("filtro_geografico_codigo"),
    )
    avisar(3, True)
    avisar(4, False)
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    if "codigo" in df:
        df["codigo"] = df["codigo"].astype("Int64")

    medida_op = (plan.get("medida") or {}).get("operacion", "conteo_distinto")
    porcentaje_plan = plan.get("porcentaje") or None
    piramide = _config_piramide_cruce(plan, intencion)

    # Sin dimensiones: coroplético de conteo/medida o porcentaje con un
    # denominador independiente confirmado por la persona usuaria.
    if not dimensiones:
        denominadores_geo = sql_den = None
        if porcentaje_plan and porcentaje_plan.get("denominador_personalizado"):
            denominadores_geo, sql_den = _consultar_denominador_cruce(intencion)
        datos = []
        valores_salida = []
        for fila in df.itertuples(index=False):
            codigo = _codigo_json(fila.codigo)
            nombre = next((v for k, v in nombres.items()
                           if str(k).isdigit() and str(codigo).isdigit()
                           and int(k) == int(codigo)), str(codigo))
            bruto = None if pd.isna(fila.valor) else float(fila.valor)
            if porcentaje_plan:
                if denominadores_geo is None:
                    raise ValueError(
                        "El porcentaje compuesto no tiene un denominador independiente. "
                        "Selecciona el universo denominador antes de calcular."
                    )
                den = float(denominadores_geo.get(codigo, 0.0))
                valor = 100.0 * float(bruto or 0) / den if den else None
            else:
                valor = None if bruto is None else (int(bruto) if medida_op == "conteo_distinto" else bruto)
            if valor is not None:
                valores_salida.append(float(valor))
            item = {"codigo": codigo, "nombre": nombre, "valor": valor}
            if porcentaje_plan:
                item["conteo"] = None if bruto is None else int(bruto)
                item["denominador"] = float(denominadores_geo.get(codigo, 0.0))
            datos.append(item)
        avisar(4, True)
        sql_final = sql if not sql_den else sql + "\n-- DENOMINADOR SELECCIONADO --\n" + sql_den
        return {
            "tipo_visualizacion": "mapa", "datos": datos, "geometria": geometria,
            "nivel_geografico": nivel, "_sql_ejecutada": sql_final,
            "valores": {"min": min(valores_salida) if valores_salida else None,
                        "max": max(valores_salida) if valores_salida else None},
        }

    combinaciones = []
    for fila in df.itertuples(index=False):
        codigos = [str(getattr(fila, f"d{i}")) for i in range(len(dimensiones))]
        partes = [
            f"{dimensiones[i].get('etiqueta', dimensiones[i]['variable'])}: "
            f"{_etiqueta_categoria_cruce(dimensiones[i], codigos[i])}"
            for i in range(len(dimensiones))
        ]
        valor = None if pd.isna(fila.valor) else float(fila.valor)
        combinaciones.append({
            "codigo_geo": _codigo_json(fila.codigo), "codigos": codigos,
            "clave": "|".join(codigos), "etiqueta": " · ".join(partes),
            "valor": valor,
        })

    # Porcentajes cruzados o medidas numéricas por dimensión se representan con
    # barras: una torta sugeriría erróneamente que los valores son partes de un
    # único total cuando la base puede ser fila/columna o la medida puede ser AVG.
    if porcentaje_plan or medida_op != "conteo_distinto":
        base_pct = (porcentaje_plan or {}).get("base")
        denoms = selector = None
        denoms_geo = sql_den = None
        if porcentaje_plan:
            if porcentaje_plan.get("denominador_personalizado"):
                denoms_geo, sql_den = _consultar_denominador_cruce(intencion)
            else:
                denoms, selector = _denominadores_porcentaje(combinaciones, base_pct, len(dimensiones))
        claves = []
        etiquetas = {}
        for item in combinaciones:
            if item["clave"] not in etiquetas:
                claves.append(item["clave"]); etiquetas[item["clave"]] = item["etiqueta"]
        por_geo = {}
        for item in combinaciones:
            por_geo.setdefault(item["codigo_geo"], {})[item["clave"]] = item
        datos = []
        for codigo, items in por_geo.items():
            nombre = next((v for k, v in nombres.items()
                           if str(k).isdigit() and str(codigo).isdigit() and int(k) == int(codigo)), str(codigo))
            barras = []
            for clave in claves:
                item = items.get(clave)
                bruto = item["valor"] if item else None
                porcentaje = None
                denominador = None
                valor = bruto
                if porcentaje_plan and item:
                    if denoms_geo is not None:
                        denominador = float(denoms_geo.get(item["codigo_geo"], 0.0))
                    else:
                        denominador = denoms.get(selector(item), 0.0)
                    porcentaje = 100.0 * float(bruto or 0) / denominador if denominador else None
                    valor = porcentaje
                barras.append({
                    "variable": clave, "etiqueta": etiquetas[clave], "valor": valor,
                    "conteo": bruto if medida_op == "conteo_distinto" else None,
                    "porcentaje": porcentaje, "denominador": denominador,
                })
            datos.append({"codigo": codigo, "nombre": nombre, "barras": barras})
        avisar(4, True)
        return {
            "tipo_visualizacion": "barras_mapa", "datos": datos,
            "geometria": geometria,
            "metrica": "porcentaje" if porcentaje_plan else medida_op,
            "severidad_codigo": None, "severidad_etiqueta": None,
            "dimensiones": [{"variable": d.get("variable"), "etiqueta": d.get("etiqueta")} for d in dimensiones],
            "nivel_geografico": nivel,
            "nota": (f"Porcentaje base {base_pct}." if porcentaje_plan else None),
            "_sql_ejecutada": (sql if not sql_den else sql + "\n-- DENOMINADOR SELECCIONADO --\n" + sql_den),
        }

    # Conteos con dimensiones: combinaciones mutuamente excluyentes -> torta.
    totales = {}
    etiquetas = {}
    for item in combinaciones:
        valor = int(item["valor"] or 0)
        totales[item["clave"]] = totales.get(item["clave"], 0) + valor
        etiquetas[item["clave"]] = item["etiqueta"]
    claves_completas = sorted(totales, key=lambda k: (-totales[k], etiquetas[k]))
    principales = claves_completas[:5] if len(claves_completas) > 5 else claves_completas
    agrupar_otros = len(claves_completas) > 5
    categorias_grafico = [{"codigo": k, "etiqueta": etiquetas[k]} for k in principales]
    if agrupar_otros:
        categorias_grafico.append({"codigo": "otros", "etiqueta": "Otros"})
    # v35-top5-cruce
    por_geo = {}
    for item in combinaciones:
        por_geo.setdefault(item["codigo_geo"], {})[item["clave"]] = int(item["valor"] or 0)
    datos = []
    for codigo, conteos in por_geo.items():
        total = sum(conteos.values())
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and str(codigo).isdigit()
                       and int(k) == int(codigo)), str(codigo))
        # Detalle íntegro para Excel y pirámides.
        distribucion_completa = []
        for clave in claves_completas:
            valor = int(conteos.get(clave, 0))
            distribucion_completa.append({
                "codigo": clave, "etiqueta": etiquetas[clave], "valor": valor,
                "porcentaje": 100.0 * valor / total if total else None,
            })

        # Vista de mapa: cinco categorías principales y el resto agrupado.
        distribucion = []
        for clave in principales:
            valor = int(conteos.get(clave, 0))
            distribucion.append({
                "codigo": clave, "etiqueta": etiquetas[clave], "valor": valor,
                "porcentaje": 100.0 * valor / total if total else None,
            })
        if agrupar_otros:
            valor_otros = sum(
                int(valor)
                for clave, valor in conteos.items()
                if clave not in principales
            )
            distribucion.append({
                "codigo": "otros",
                "etiqueta": "Otros",
                "valor": valor_otros,
                "porcentaje": 100.0 * valor_otros / total if total else None,
            })

        datos.append({
            "codigo": codigo,
            "nombre": nombre,
            "distribucion": distribucion,
            "distribucion_completa": distribucion_completa,
            "total": total,
        })
    avisar(4, True)
    LOG.info("[tiempo] cruce_total=%.3fs filas_salida=%s dimensiones=%s",
             perf_counter() - inicio, len(datos), len(dimensiones))
    return {
        "tipo_visualizacion": "tortas_mapa", "datos": datos,
        "geometria": geometria, "nivel_geografico": nivel,
        "categorias_grafico": categorias_grafico, "_sql_ejecutada": sql,
        "entidad_objetivo": objetivo,
        "piramide": piramide,
    }



# ---------------------------------------------------------------------------
# Movilidad laboral comunal — Fase 1
# ---------------------------------------------------------------------------
def _construir_sql_movilidad_laboral_fase1(intencion):
    """Construye los cinco indicadores comunales de movilidad laboral.

    Universo base: personas ocupadas. En porcentajes se restringe además a
    quienes tienen un único lugar de trabajo identificable en Chile (P44=1,2,3).
    """
    indicador = intencion.get("movilidad_indicador")
    permitidos = {
        "salientes_cantidad", "misma_comuna_cantidad",
        "salientes_porcentaje", "misma_comuna_porcentaje",
        "entrantes_cantidad",
    }
    if indicador not in permitidos:
        raise ValueError("Indicador de movilidad laboral comunal no válido.")

    ruta = _ruta_parquet("personas")
    src = ruta.as_posix().replace("'", "''")
    clave = _clave_distinta("personas")
    ocupada = 'CAST(p."sit_fuerza_trabajo" AS VARCHAR) = \'1\''
    p44 = 'CAST(p."p44_lug_trab" AS VARCHAR)'
    condiciones = [ocupada]

    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")

    if indicador == "entrantes_cantidad":
        # La geografía de salida corresponde al lugar de trabajo, no a la
        # residencia. Se aceptan exclusivamente códigos comunales chilenos.
        codigos_comuna = sorted(
            int(c) for c in VARIABLES.get("geografia", {}).get("comuna", {})
            if str(c).isdigit()
        )
        lista_comunas = ", ".join(str(c) for c in codigos_comuna)
        geo_expr = 'TRY_CAST(p."p44_lug_trab_esp" AS BIGINT)'
        condiciones.extend([
            f"{p44} = '3'",
            f"{geo_expr} IN ({lista_comunas})",
        ])
        if f_nivel == "region" and f_codigo is not None:
            condiciones.append(f"CAST(FLOOR({geo_expr} / 1000) AS INTEGER) = {int(f_codigo)}")
        elif f_nivel == "comuna" and f_codigo is not None:
            condiciones.append(f"{geo_expr} = {int(f_codigo)}")
        elif f_nivel not in (None, "region", "comuna"):
            raise ValueError("La Fase 1 de movilidad laboral por comuna admite filtros de región o comuna.")
        medida = f"COUNT(DISTINCT {clave})"
        codigo = geo_expr
    else:
        # Salidas y permanencia se atribuyen a la comuna de residencia.
        codigo = 'p."comuna"'
        if f_nivel and f_codigo is not None:
            if f_nivel not in NIVELES:
                raise ValueError("Filtro territorial no válido.")
            condiciones.append(f'{_col("p", NIVELES[f_nivel]["col_parquet"])} = {int(f_codigo)}')

        if indicador == "salientes_cantidad":
            condiciones.append(f"{p44} = '3'")
            medida = f"COUNT(DISTINCT {clave})"
        elif indicador == "misma_comuna_cantidad":
            condiciones.append(f"{p44} IN ('1', '2')")
            medida = f"COUNT(DISTINCT {clave})"
        else:
            # Denominador: personas ocupadas con un único lugar de trabajo
            # identificable en Chile. P44=4/5, NR y NA quedan fuera.
            numerador_cond = (f"{p44} = '3'" if indicador == "salientes_porcentaje"
                              else f"{p44} IN ('1', '2')")
            denominador_cond = f"{p44} IN ('1', '2', '3')"
            medida = (
                "100.0 * COUNT(DISTINCT CASE WHEN " + numerador_cond + " THEN " + clave + " END) "
                "/ NULLIF(COUNT(DISTINCT CASE WHEN " + denominador_cond + " THEN " + clave + " END), 0)"
            )

    where = "WHERE " + " AND ".join(f"({c})" for c in condiciones)
    sql = f"""
        SELECT {codigo} AS codigo, {medida} AS valor
        FROM read_parquet('{src}') p
        {where}
        GROUP BY {codigo}
        ORDER BY {codigo}
    """
    return sql, ruta


def _ejecutar_movilidad_laboral_fase1(intencion, progreso, inicio):
    avisar = progreso or (lambda etapa, terminado: None)
    sql, ruta = _construir_sql_movilidad_laboral_fase1(intencion)
    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] movilidad_laboral_fase1=%.3fs cache=%s filas=%s indicador=%s",
             perf_counter() - paso, hit, len(df), intencion.get("movilidad_indicador"))
    avisar(2, True)

    nivel = "comuna"
    avisar(3, False)
    geometria = referencia_geometria(
        nivel, intencion.get("filtro_geografico_nivel"),
        intencion.get("filtro_geografico_codigo"),
    )
    avisar(3, True)
    avisar(4, False)

    nombres = VARIABLES.get("geografia", {}).get("comuna", {})
    datos = []
    if "codigo" in df:
        df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    for fila in df.itertuples(index=False):
        if pd.isna(fila.codigo):
            continue
        codigo = _codigo_json(fila.codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and int(k) == int(codigo)), str(codigo))
        valor = None if pd.isna(fila.valor) else float(fila.valor)
        if intencion.get("operacion") != "porcentaje" and valor is not None:
            valor = int(valor)
        datos.append({"codigo": codigo, "nombre": nombre, "valor": valor})

    validos = df["valor"].dropna() if "valor" in df else pd.Series(dtype=float)
    avisar(4, True)
    return {
        "tipo_visualizacion": "mapa", "datos": datos, "geometria": geometria,
        "nivel_geografico": nivel, "_sql_ejecutada": sql,
        "nota": intencion.get("nota_interpretacion"),
        "valores": {"min": float(validos.min()) if len(validos) else None,
                    "max": float(validos.max()) if len(validos) else None},
    }



# ---------------------------------------------------------------------------
# Movilidad laboral comunal — Fase 2: origen-destino dirigido
# ---------------------------------------------------------------------------
def _codigos_comuna_validos_sql():
    codigos = sorted(
        int(c) for c in VARIABLES.get("geografia", {}).get("comuna", {})
        if str(c).isdigit()
    )
    return codigos, ", ".join(str(c) for c in codigos)


def _construir_sql_movilidad_laboral_fase2(intencion):
    """SQL para flujos dirigidos, Top destinos/orígenes y saldo comunal."""
    indicador = intencion.get("movilidad_indicador")
    permitidos = {
        "flujo_comunal_cantidad", "destinos_principales",
        "origenes_principales", "saldo_comunal",
    }
    if indicador not in permitidos:
        raise ValueError("Indicador de movilidad laboral Fase 2 no válido.")

    ruta = _ruta_parquet("personas")
    src = ruta.as_posix().replace("'", "''")
    clave = _clave_distinta("personas")
    ocupada = 'CAST(p."sit_fuerza_trabajo" AS VARCHAR) = \'1\''
    p44 = 'CAST(p."p44_lug_trab" AS VARCHAR)'
    destino_esp = 'TRY_CAST(p."p44_lug_trab_esp" AS BIGINT)'
    _, lista_comunas = _codigos_comuna_validos_sql()
    destino_valido = f"{destino_esp} IN ({lista_comunas})"

    origen = intencion.get("movilidad_origen_codigo")
    destino = intencion.get("movilidad_destino_codigo")
    top_n = max(1, min(50, int(intencion.get("movilidad_top_n") or 10)))
    solo_externos = bool(intencion.get("movilidad_solo_externos"))

    if indicador == "flujo_comunal_cantidad":
        if origen is None or destino is None:
            raise ValueError("El flujo dirigido necesita comuna de residencia y comuna de trabajo.")
        origen = int(origen); destino = int(destino)
        condiciones = [ocupada, f'p."comuna" = {origen}']
        if origen == destino:
            condiciones.append(f"{p44} IN ('1', '2')")
        else:
            condiciones.extend([f"{p44} = '3'", f"{destino_esp} = {destino}"])
        where = "WHERE " + " AND ".join(f"({c})" for c in condiciones)
        sql = f"""
            SELECT {destino} AS codigo, COUNT(DISTINCT {clave}) AS valor
            FROM read_parquet('{src}') p
            {where}
        """
        return sql, ruta

    if indicador == "destinos_principales":
        if origen is None:
            raise ValueError("Los destinos principales requieren una comuna de residencia.")
        origen = int(origen)
        destino_expr = (
            f"CASE WHEN {p44} IN ('1', '2') THEN TRY_CAST(p.\"comuna\" AS BIGINT) "
            f"WHEN {p44} = '3' AND {destino_valido} THEN {destino_esp} END"
        )
        condiciones = [ocupada, f'p."comuna" = {origen}', f"{p44} IN ('1', '2', '3')"]
        if solo_externos:
            condiciones = [ocupada, f'p."comuna" = {origen}', f"{p44} = '3'", destino_valido]
        else:
            condiciones.append(f"({p44} IN ('1', '2') OR ({p44} = '3' AND {destino_valido}))")
        where = "WHERE " + " AND ".join(f"({c})" for c in condiciones)
        sql = f"""
            SELECT {destino_expr} AS codigo, COUNT(DISTINCT {clave}) AS valor
            FROM read_parquet('{src}') p
            {where}
            GROUP BY {destino_expr}
            HAVING {destino_expr} IS NOT NULL
            ORDER BY valor DESC, codigo
            LIMIT {top_n}
        """
        return sql, ruta

    if indicador == "origenes_principales":
        if destino is None:
            raise ValueError("Los orígenes principales requieren una comuna de trabajo.")
        destino = int(destino)
        misma = f'(p."comuna" = {destino} AND {p44} IN (\'1\', \'2\'))'
        externa = f'({p44} = \'3\' AND {destino_esp} = {destino})'
        condicion_destino = externa if solo_externos else f"({misma} OR {externa})"
        where = f"WHERE ({ocupada}) AND ({condicion_destino})"
        sql = f"""
            SELECT TRY_CAST(p."comuna" AS BIGINT) AS codigo, COUNT(DISTINCT {clave}) AS valor
            FROM read_parquet('{src}') p
            {where}
            GROUP BY TRY_CAST(p."comuna" AS BIGINT)
            ORDER BY valor DESC, codigo
            LIMIT {top_n}
        """
        return sql, ruta

    # Saldo = entradas desde otras comunas - salidas hacia otras comunas.
    filtro_nivel = intencion.get("filtro_geografico_nivel")
    filtro_codigo = intencion.get("filtro_geografico_codigo")
    filtro_final = ""
    if filtro_nivel == "region" and filtro_codigo is not None:
        filtro_final = f"WHERE CAST(FLOOR(codigo / 1000) AS INTEGER) = {int(filtro_codigo)}"
    elif filtro_nivel == "comuna" and filtro_codigo is not None:
        filtro_final = f"WHERE codigo = {int(filtro_codigo)}"
    elif filtro_nivel not in (None, "region", "comuna"):
        raise ValueError("El saldo laboral comunal admite ámbitos de región o comuna.")

    sql = f"""
        WITH flujos AS (
            SELECT DISTINCT {clave} AS persona_id,
                   TRY_CAST(p."comuna" AS BIGINT) AS origen,
                   {destino_esp} AS destino
            FROM read_parquet('{src}') p
            WHERE ({ocupada})
              AND ({p44} = '3')
              AND ({destino_valido})
        ), movimientos AS (
            SELECT destino AS codigo, 1 AS delta FROM flujos
            UNION ALL
            SELECT origen AS codigo, -1 AS delta FROM flujos
        ), saldos AS (
            SELECT codigo, SUM(delta) AS valor
            FROM movimientos
            GROUP BY codigo
        )
        SELECT codigo, valor
        FROM saldos
        {filtro_final}
        ORDER BY codigo
    """
    return sql, ruta


def _ejecutar_movilidad_laboral_fase2(intencion, progreso, inicio):
    avisar = progreso or (lambda etapa, terminado: None)
    sql, ruta = _construir_sql_movilidad_laboral_fase2(intencion)
    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] movilidad_laboral_fase2=%.3fs cache=%s filas=%s indicador=%s",
             perf_counter() - paso, hit, len(df), intencion.get("movilidad_indicador"))
    avisar(2, True)

    indicador = intencion.get("movilidad_indicador")
    nivel = "comuna"
    avisar(3, False)
    if indicador == "flujo_comunal_cantidad" and intencion.get("movilidad_destino_codigo") is not None:
        geometria = referencia_geometria(nivel, "comuna", intencion.get("movilidad_destino_codigo"))
    else:
        geometria = referencia_geometria(
            nivel, intencion.get("filtro_geografico_nivel"),
            intencion.get("filtro_geografico_codigo"),
        )
    avisar(3, True)
    avisar(4, False)

    nombres = VARIABLES.get("geografia", {}).get("comuna", {})
    datos = []
    if "codigo" in df:
        df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    for fila in df.itertuples(index=False):
        if pd.isna(fila.codigo):
            continue
        codigo = _codigo_json(fila.codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and int(k) == int(codigo)), str(codigo))
        valor = None if pd.isna(fila.valor) else float(fila.valor)
        if valor is not None and float(valor).is_integer():
            valor = int(valor)
        datos.append({"codigo": codigo, "nombre": nombre, "valor": valor})

    validos = df["valor"].dropna() if "valor" in df else pd.Series(dtype=float)
    avisar(4, True)
    return {
        "tipo_visualizacion": "mapa", "datos": datos, "geometria": geometria,
        "nivel_geografico": nivel, "_sql_ejecutada": sql,
        "nota": intencion.get("nota_interpretacion"),
        "valores": {"min": float(validos.min()) if len(validos) else None,
                    "max": float(validos.max()) if len(validos) else None},
    }



# ---------------------------------------------------------------------------
# Movilidad laboral comunal — Fase 3: matriz OD y ranking de flujos
# ---------------------------------------------------------------------------
def _condiciones_filtros_movilidad_fase3(filtros):
    """Compila filtros personales ya validados por el resolutor determinista."""
    permitidas = {"sexo", "edad", "discapacidad", "p45_medio_transporte", "cod_caenes"}
    condiciones = []
    for filtro in filtros or []:
        variable = filtro.get("variable")
        op = filtro.get("op")
        if variable not in permitidas:
            raise ValueError("Filtro personal no admitido en movilidad laboral Fase 3.")
        expr = f'p."{variable}"'
        if variable == "edad":
            expr = f'TRY_CAST(p."{variable}" AS DOUBLE)'
            if op == "between":
                condiciones.append(f"{expr} >= {_numero_sql(filtro.get('min'), 'mínimo de edad')}")
                condiciones.append(f"{expr} <= {_numero_sql(filtro.get('max'), 'máximo de edad')}")
            elif op in {">", ">=", "<", "<="}:
                condiciones.append(f"{expr} {op} {_numero_sql(filtro.get('valor'), 'edad')}")
            else:
                raise ValueError("Operador de edad no válido en movilidad laboral.")
        else:
            if op != "=":
                raise ValueError("Operador categórico no válido en movilidad laboral.")
            valor = str(filtro.get("valor", "")).replace("'", "''")
            condiciones.append(f"CAST({expr} AS VARCHAR) = '{valor}'")
    return condiciones


def _construir_sql_movilidad_laboral_fase3(intencion):
    """Construye la matriz OD comunal con conteo y porcentajes de fila/columna."""
    indicador = intencion.get("movilidad_indicador")
    if indicador not in {"matriz_od_comunal", "ranking_flujos_comunales"}:
        raise ValueError("Indicador de movilidad laboral Fase 3 no válido.")

    ruta = _ruta_parquet("personas")
    src = ruta.as_posix().replace("'", "''")
    clave = _clave_distinta("personas")
    ocupada = 'CAST(p."sit_fuerza_trabajo" AS VARCHAR) = \'1\''
    p44 = 'CAST(p."p44_lug_trab" AS VARCHAR)'
    destino_esp = 'TRY_CAST(p."p44_lug_trab_esp" AS BIGINT)'
    _, lista_comunas = _codigos_comuna_validos_sql()
    destino_valido = f"{destino_esp} IN ({lista_comunas})"
    destino_expr = (
        f"CASE WHEN {p44} IN ('1', '2') THEN TRY_CAST(p.\"comuna\" AS BIGINT) "
        f"WHEN {p44} = '3' AND {destino_valido} THEN {destino_esp} END"
    )

    condiciones = [ocupada, f"({p44} IN ('1', '2') OR ({p44} = '3' AND {destino_valido}))"]
    condiciones.extend(_condiciones_filtros_movilidad_fase3(intencion.get("movilidad_filtros_persona")))

    # Base persona-origen-destino. La clave DISTINCT impide doble conteo.
    where_base = "WHERE " + " AND ".join(f"({c})" for c in condiciones)
    filtros_scope = ["destino IS NOT NULL", "origen IS NOT NULL"]
    if intencion.get("movilidad_origen_codigo") is not None:
        filtros_scope.append(f"origen = {int(intencion['movilidad_origen_codigo'])}")
    if intencion.get("movilidad_destino_codigo") is not None:
        filtros_scope.append(f"destino = {int(intencion['movilidad_destino_codigo'])}")
    if intencion.get("movilidad_region_origen_codigo") is not None:
        filtros_scope.append(
            f"CAST(FLOOR(origen / 1000) AS INTEGER) = {int(intencion['movilidad_region_origen_codigo'])}"
        )
    if intencion.get("movilidad_region_destino_codigo") is not None:
        filtros_scope.append(
            f"CAST(FLOOR(destino / 1000) AS INTEGER) = {int(intencion['movilidad_region_destino_codigo'])}"
        )
    if not intencion.get("movilidad_incluir_diagonal", True):
        filtros_scope.append("origen <> destino")
    where_scope = "WHERE " + " AND ".join(f"({c})" for c in filtros_scope)

    top_clause = ""
    if indicador == "ranking_flujos_comunales":
        top_n = max(1, min(100, int(intencion.get("movilidad_top_n") or 20)))
        top_clause = f"LIMIT {top_n}"

    sql = f"""
        WITH base AS (
            SELECT DISTINCT {clave} AS persona_id,
                   TRY_CAST(p."comuna" AS BIGINT) AS origen,
                   {destino_expr} AS destino
            FROM read_parquet('{src}') p
            {where_base}
        ), scoped AS (
            SELECT persona_id, origen, destino
            FROM base
            {where_scope}
        ), flujos AS (
            SELECT origen, destino, COUNT(*) AS cantidad
            FROM scoped
            GROUP BY origen, destino
        ), metricas AS (
            SELECT origen, destino, cantidad,
                   100.0 * cantidad / NULLIF(SUM(cantidad) OVER (PARTITION BY origen), 0) AS porcentaje_origen,
                   100.0 * cantidad / NULLIF(SUM(cantidad) OVER (PARTITION BY destino), 0) AS porcentaje_destino
            FROM flujos
        )
        SELECT origen, destino, cantidad, porcentaje_origen, porcentaje_destino
        FROM metricas
        ORDER BY cantidad DESC, origen, destino
        {top_clause}
    """
    return sql, ruta


def _ejecutar_movilidad_laboral_fase3(intencion, progreso, inicio):
    """Ejecuta la matriz OD y devuelve datos largos + metadatos para la UI."""
    avisar = progreso or (lambda etapa, terminado: None)
    sql, ruta = _construir_sql_movilidad_laboral_fase3(intencion)
    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] movilidad_laboral_fase3=%.3fs cache=%s filas=%s indicador=%s",
             perf_counter() - paso, hit, len(df), intencion.get("movilidad_indicador"))
    avisar(2, True)
    avisar(3, False); avisar(3, True)
    avisar(4, False)

    comunas = VARIABLES.get("geografia", {}).get("comuna", {})
    regiones = VARIABLES.get("geografia", {}).get("region", {})
    nombres_comuna = {int(k): v for k, v in comunas.items() if str(k).isdigit()}
    nombres_region = {int(k): v for k, v in regiones.items() if str(k).isdigit()}

    flujos = []
    origen_totales, destino_totales = {}, {}
    for fila in df.itertuples(index=False):
        if pd.isna(fila.origen) or pd.isna(fila.destino):
            continue
        origen, destino = int(fila.origen), int(fila.destino)
        cantidad = int(fila.cantidad)
        ro, rd = origen // 1000, destino // 1000
        item = {
            "origen_codigo": origen,
            "origen_nombre": nombres_comuna.get(origen, str(origen)),
            "origen_region_codigo": ro,
            "origen_region_nombre": nombres_region.get(ro, str(ro)),
            "destino_codigo": destino,
            "destino_nombre": nombres_comuna.get(destino, str(destino)),
            "destino_region_codigo": rd,
            "destino_region_nombre": nombres_region.get(rd, str(rd)),
            "cantidad": cantidad,
            "porcentaje_origen": None if pd.isna(fila.porcentaje_origen) else float(fila.porcentaje_origen),
            "porcentaje_destino": None if pd.isna(fila.porcentaje_destino) else float(fila.porcentaje_destino),
            "misma_comuna": origen == destino,
        }
        flujos.append(item)
        origen_totales[origen] = origen_totales.get(origen, 0) + cantidad
        destino_totales[destino] = destino_totales.get(destino, 0) + cantidad

    origenes = [
        {"codigo": c, "nombre": nombres_comuna.get(c, str(c)), "region_codigo": c // 1000,
         "region_nombre": nombres_region.get(c // 1000, str(c // 1000)), "total": total}
        for c, total in sorted(origen_totales.items(), key=lambda x: (-x[1], x[0]))
    ]
    destinos = [
        {"codigo": c, "nombre": nombres_comuna.get(c, str(c)), "region_codigo": c // 1000,
         "region_nombre": nombres_region.get(c // 1000, str(c // 1000)), "total": total}
        for c, total in sorted(destino_totales.items(), key=lambda x: (-x[1], x[0]))
    ]
    metric = intencion.get("movilidad_metrica") or "cantidad"
    avisar(4, True)
    return {
        "tipo_visualizacion": "matriz_od",
        "datos": [],
        "flujos_od": flujos,
        "origenes_od": origenes,
        "destinos_od": destinos,
        "config_od": {
            "metrica": metric,
            "incluir_diagonal": bool(intencion.get("movilidad_incluir_diagonal", True)),
            "top_n": int(intencion.get("movilidad_top_n") or 20),
            "mostrar_todas": bool(intencion.get("movilidad_mostrar_todas")),
        },
        "resumen_od": {
            "flujos_no_cero": len(flujos),
            "comunas_origen": len(origenes),
            "comunas_destino": len(destinos),
            "personas_en_flujos": int(sum(x["cantidad"] for x in flujos)),
        },
        "geometria": None,
        "nivel_geografico": "comuna",
        "_sql_ejecutada": sql,
        "nota": intencion.get("nota_interpretacion"),
        "valores": {"min": None, "max": None},
    }



# ---------------------------------------------------------------------------
# Migración interna 2019–2024 — indicadores y matrices origen-destino
# ---------------------------------------------------------------------------
def _base_migracion_interna_sql(intencion, nivel):
    """CTE base persona-origen-destino para migración interna.

    P24=2: origen = comuna actual (permanencia).
    P24=3: origen = comuna específica de P24.
    P24=1/4/NR/NA quedan fuera del universo de migración interna.
    """
    ruta = _ruta_parquet("personas")
    src = ruta.as_posix().replace("'", "''")
    clave = _clave_distinta("personas")
    _, lista_comunas = _codigos_comuna_validos_sql()
    actual = 'TRY_CAST(p."comuna" AS BIGINT)'
    p24 = 'CAST(p."p24_lug_resid5" AS VARCHAR)'
    p24esp = 'TRY_CAST(p."p24_lug_resid5_esp" AS BIGINT)'
    origen_comuna = (
        f"CASE WHEN {p24} = '2' THEN {actual} "
        f"WHEN {p24} = '3' AND {p24esp} IN ({lista_comunas}) THEN {p24esp} END"
    )
    destino_comuna = actual
    condiciones = [
        f"{actual} IN ({lista_comunas})",
        f"({p24} = '2' OR ({p24} = '3' AND {p24esp} IN ({lista_comunas})))",
    ]
    condiciones.extend(_condiciones_filtros_movilidad_fase3(intencion.get("migracion_filtros_persona")))
    where = "WHERE " + " AND ".join(f"({c})" for c in condiciones)
    if nivel == "region":
        origen = f"CAST(FLOOR(({origen_comuna}) / 1000) AS INTEGER)"
        destino = f"CAST(FLOOR(({destino_comuna}) / 1000) AS INTEGER)"
    else:
        origen, destino = origen_comuna, destino_comuna
    cte = f"""
        base AS (
            SELECT DISTINCT {clave} AS persona_id,
                   {origen} AS origen,
                   {destino} AS destino
            FROM read_parquet('{src}') p
            {where}
        )
    """
    return cte, ruta


def _construir_sql_migracion_interna_od(intencion):
    indicador = intencion.get("migracion_indicador")
    permitidos = {
        "matriz_migracion_interna", "ranking_flujos_migratorios",
        "flujo_migratorio_dirigido", "destinos_migratorios_principales",
        "origenes_migratorios_principales",
    }
    if indicador not in permitidos:
        raise ValueError("Indicador OD de migración interna no válido.")
    nivel = intencion.get("migracion_nivel") or "comuna"
    if nivel not in {"comuna", "region"}:
        raise ValueError("Nivel de migración interna no válido.")
    base_cte, ruta = _base_migracion_interna_sql(intencion, nivel)

    scope = ["origen IS NOT NULL", "destino IS NOT NULL"]
    if intencion.get("migracion_origen_codigo") is not None:
        scope.append(f"origen = {int(intencion['migracion_origen_codigo'])}")
    if intencion.get("migracion_destino_codigo") is not None:
        scope.append(f"destino = {int(intencion['migracion_destino_codigo'])}")
    if nivel == "comuna":
        if intencion.get("migracion_region_origen_codigo") is not None:
            scope.append(f"CAST(FLOOR(origen / 1000) AS INTEGER) = {int(intencion['migracion_region_origen_codigo'])}")
        if intencion.get("migracion_region_destino_codigo") is not None:
            scope.append(f"CAST(FLOOR(destino / 1000) AS INTEGER) = {int(intencion['migracion_region_destino_codigo'])}")
    if not intencion.get("migracion_incluir_diagonal", False):
        scope.append("origen <> destino")
    where_scope = "WHERE " + " AND ".join(f"({c})" for c in scope)

    top_clause = ""
    if indicador in {"ranking_flujos_migratorios", "destinos_migratorios_principales", "origenes_migratorios_principales"}:
        top_n = max(1, min(100, int(intencion.get("migracion_top_n") or 20)))
        top_clause = f"LIMIT {top_n}"

    sql = f"""
        WITH {base_cte}, scoped AS (
            SELECT persona_id, origen, destino
            FROM base
            {where_scope}
        ), flujos AS (
            SELECT origen, destino, COUNT(*) AS cantidad
            FROM scoped
            GROUP BY origen, destino
        ), metricas AS (
            SELECT origen, destino, cantidad,
                   100.0 * cantidad / NULLIF(SUM(cantidad) OVER (PARTITION BY origen), 0) AS porcentaje_origen,
                   100.0 * cantidad / NULLIF(SUM(cantidad) OVER (PARTITION BY destino), 0) AS porcentaje_destino
            FROM flujos
        )
        SELECT origen, destino, cantidad, porcentaje_origen, porcentaje_destino
        FROM metricas
        ORDER BY cantidad DESC, origen, destino
        {top_clause}
    """
    return sql, ruta


def _construir_sql_migracion_interna_indicadores(intencion):
    indicador = intencion.get("migracion_indicador")
    if indicador not in {"inmigrantes_internos", "emigrantes_internos", "saldo_migratorio_interno"}:
        raise ValueError("Indicador territorial de migración interna no válido.")
    nivel = intencion.get("migracion_nivel") or "region"
    base_cte, ruta = _base_migracion_interna_sql(intencion, nivel)
    ambito = intencion.get("migracion_ambito_region_codigo")
    filtro_salida = ""
    if nivel == "comuna" and ambito is not None:
        filtro_salida = f"WHERE CAST(FLOOR(codigo / 1000) AS INTEGER) = {int(ambito)}"

    if indicador == "inmigrantes_internos":
        cuerpo = """
            SELECT destino AS codigo, COUNT(*) AS valor
            FROM base
            WHERE origen IS NOT NULL AND destino IS NOT NULL AND origen <> destino
            GROUP BY destino
        """
    elif indicador == "emigrantes_internos":
        cuerpo = """
            SELECT origen AS codigo, COUNT(*) AS valor
            FROM base
            WHERE origen IS NOT NULL AND destino IS NOT NULL AND origen <> destino
            GROUP BY origen
        """
    else:
        cuerpo = """
            SELECT codigo, SUM(valor) AS valor
            FROM (
                SELECT destino AS codigo, COUNT(*) AS valor
                FROM base
                WHERE origen IS NOT NULL AND destino IS NOT NULL AND origen <> destino
                GROUP BY destino
                UNION ALL
                SELECT origen AS codigo, -COUNT(*) AS valor
                FROM base
                WHERE origen IS NOT NULL AND destino IS NOT NULL AND origen <> destino
                GROUP BY origen
            ) movimientos
            GROUP BY codigo
        """
    sql = f"""
        WITH {base_cte}, indicador AS (
            {cuerpo}
        )
        SELECT codigo, valor
        FROM indicador
        {filtro_salida}
        ORDER BY codigo
    """
    return sql, ruta


def _nombres_od_migracion(nivel):
    catalogo = VARIABLES.get("geografia", {}).get(nivel, {})
    return {int(k): str(v) for k, v in catalogo.items() if str(k).isdigit()}


def _ejecutar_migracion_interna_od(intencion, progreso, inicio):
    avisar = progreso or (lambda etapa, terminado: None)
    sql, ruta = _construir_sql_migracion_interna_od(intencion)
    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    LOG.info("[tiempo] migracion_interna_od=%.3fs cache=%s filas=%s indicador=%s",
             perf_counter() - paso, hit, len(df), intencion.get("migracion_indicador"))
    avisar(2, True); avisar(3, False); avisar(3, True); avisar(4, False)

    nivel = intencion.get("migracion_nivel") or "comuna"
    nombres = _nombres_od_migracion(nivel)
    regiones = _nombres_od_migracion("region")
    flujos, origen_totales, destino_totales = [], {}, {}
    for fila in df.itertuples(index=False):
        if pd.isna(fila.origen) or pd.isna(fila.destino):
            continue
        origen, destino = int(fila.origen), int(fila.destino)
        cantidad = int(fila.cantidad)
        if nivel == "comuna":
            ro, rd = origen // 1000, destino // 1000
            ron, rdn = regiones.get(ro, str(ro)), regiones.get(rd, str(rd))
        else:
            ro, rd = origen, destino
            ron, rdn = nombres.get(origen, str(origen)), nombres.get(destino, str(destino))
        flujos.append({
            "origen_codigo": origen, "origen_nombre": nombres.get(origen, str(origen)),
            "origen_region_codigo": ro, "origen_region_nombre": ron,
            "destino_codigo": destino, "destino_nombre": nombres.get(destino, str(destino)),
            "destino_region_codigo": rd, "destino_region_nombre": rdn,
            "cantidad": cantidad,
            "porcentaje_origen": None if pd.isna(fila.porcentaje_origen) else float(fila.porcentaje_origen),
            "porcentaje_destino": None if pd.isna(fila.porcentaje_destino) else float(fila.porcentaje_destino),
            "misma_comuna": origen == destino,
            "misma_unidad": origen == destino,
        })
        origen_totales[origen] = origen_totales.get(origen, 0) + cantidad
        destino_totales[destino] = destino_totales.get(destino, 0) + cantidad

    origenes = [{"codigo": c, "nombre": nombres.get(c, str(c)), "region_codigo": (c // 1000 if nivel == "comuna" else c),
                 "region_nombre": (regiones.get(c // 1000, str(c // 1000)) if nivel == "comuna" else nombres.get(c, str(c))),
                 "total": total} for c, total in sorted(origen_totales.items(), key=lambda x: (-x[1], x[0]))]
    destinos = [{"codigo": c, "nombre": nombres.get(c, str(c)), "region_codigo": (c // 1000 if nivel == "comuna" else c),
                 "region_nombre": (regiones.get(c // 1000, str(c // 1000)) if nivel == "comuna" else nombres.get(c, str(c))),
                 "total": total} for c, total in sorted(destino_totales.items(), key=lambda x: (-x[1], x[0]))]

    unidad = "comuna" if nivel == "comuna" else "región"
    unidad_plural = "comunas" if nivel == "comuna" else "regiones"
    avisar(4, True)
    return {
        "tipo_visualizacion": "matriz_od",
        "datos": [], "flujos_od": flujos, "origenes_od": origenes, "destinos_od": destinos,
        "config_od": {
            "dominio": "migracion_interna",
            "metrica": intencion.get("migracion_metrica") or "cantidad",
            "incluir_diagonal": bool(intencion.get("migracion_incluir_diagonal", False)),
            "top_n": int(intencion.get("migracion_top_n") or 20),
            "mostrar_todas": bool(intencion.get("migracion_mostrar_todas")),
            "unidad": unidad,
            "unidad_plural": unidad_plural,
            "origen_etiqueta": f"{unidad.capitalize()} de residencia en abril de 2019",
            "destino_etiqueta": f"{unidad.capitalize()} de residencia actual",
            "origen_corto": "Residencia 2019",
            "destino_corto": "Residencia actual",
            "region_origen_etiqueta": "Región de residencia en 2019",
            "region_destino_etiqueta": "Región de residencia actual",
            "diagonal_etiqueta": f"Incluir permanencia en la misma {unidad}",
            "ranking_titulo": "Principales flujos migratorios seleccionados",
        },
        "resumen_od": {"flujos_no_cero": len(flujos), "origenes": len(origenes), "destinos": len(destinos),
                       "personas_en_flujos": int(sum(x["cantidad"] for x in flujos))},
        "geometria": None, "nivel_geografico": nivel, "_sql_ejecutada": sql,
        "nota": intencion.get("nota_interpretacion"), "valores": {"min": None, "max": None},
    }


def _ejecutar_migracion_interna_indicadores(intencion, progreso, inicio):
    avisar = progreso or (lambda etapa, terminado: None)
    sql, ruta = _construir_sql_migracion_interna_indicadores(intencion)
    stat = ruta.stat()
    with _SQL_CACHE_LOCK:
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
    avisar(2, True)
    nivel = intencion.get("migracion_nivel") or "region"
    avisar(3, False)
    geometria = referencia_geometria(
        nivel,
        "region" if nivel == "comuna" and intencion.get("migracion_ambito_region_codigo") is not None else None,
        intencion.get("migracion_ambito_region_codigo") if nivel == "comuna" else None,
    )
    avisar(3, True); avisar(4, False)
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    datos = []
    if "codigo" in df:
        df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    for fila in df.itertuples(index=False):
        if pd.isna(fila.codigo):
            continue
        codigo = int(fila.codigo)
        nombre = next((v for k, v in nombres.items() if str(k).isdigit() and int(k) == codigo), str(codigo))
        datos.append({"codigo": codigo, "nombre": nombre, "valor": int(fila.valor) if not pd.isna(fila.valor) else None})
    validos = df["valor"].dropna() if "valor" in df else pd.Series(dtype=float)
    avisar(4, True)
    return {"tipo_visualizacion": "mapa", "datos": datos, "geometria": geometria,
            "nivel_geografico": nivel, "_sql_ejecutada": sql, "nota": intencion.get("nota_interpretacion"),
            "valores": {"min": float(validos.min()) if len(validos) else None,
                        "max": float(validos.max()) if len(validos) else None}}

def ejecutar_consulta(intencion: dict, progreso=None) -> dict:
    """Agrega datos y devuelve una referencia a la cartografía reutilizable."""
    inicio = perf_counter()
    # Cada notificación corresponde al inicio o término de trabajo real.
    avisar = progreso or (lambda etapa, terminado: None)
    avisar(2, False)
    if intencion.get("tipo_consulta") == "indicador_censal_v27":
        return _ejecutar_indicador_censal_v27(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "indicador_derivado_v24":
        return _ejecutar_indicador_derivado_v24(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "migracion_interna_od":
        return _ejecutar_migracion_interna_od(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "migracion_interna_indicadores":
        return _ejecutar_migracion_interna_indicadores(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "movilidad_laboral_fase3":
        return _ejecutar_movilidad_laboral_fase3(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "movilidad_laboral_fase2":
        return _ejecutar_movilidad_laboral_fase2(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "movilidad_laboral_fase1":
        return _ejecutar_movilidad_laboral_fase1(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "cruce":
        return _ejecutar_cruce(intencion, avisar, inicio)
    if intencion.get("tipo_consulta") == "dimensiones_funcionales":
        return _ejecutar_dimensiones_funcionales(intencion, avisar, inicio)
    if intencion.get("operacion") == "distribucion":
        return _ejecutar_distribucion(intencion, avisar, inicio)
    nivel = intencion.get("nivel_geografico", "comuna")
    if nivel not in NIVELES:
        raise ValueError("Nivel geográfico no válido.")
    nivel_info = NIVELES[nivel]
    ruta = _ruta_parquet(intencion["tabla"])
    sql = _construir_sql(intencion, nivel_info, ruta)
    stat = ruta.stat()
    paso = perf_counter()
    with _SQL_CACHE_LOCK:
        antes = _consultar_sql.cache_info().hits
        df = _consultar_sql(sql, str(ruta), stat.st_mtime_ns, stat.st_size).copy()
        hit = _consultar_sql.cache_info().hits > antes
    df["codigo"] = df["codigo"].astype("Int64")
    LOG.info("[tiempo] consulta_duckdb=%.3fs cache=%s filas=%s", perf_counter() - paso, hit, len(df))
    avisar(2, True)
    avisar(3, False)
    geometria = referencia_geometria(
        nivel, intencion.get("filtro_geografico_nivel"),
        intencion.get("filtro_geografico_codigo"),
    )
    avisar(3, True)
    avisar(4, False)
    paso = perf_counter()
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    datos = []
    for fila in df.itertuples(index=False):
        codigo = _codigo_json(fila.codigo)
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and str(codigo).isdigit()
                       and int(k) == int(codigo)), str(codigo))
        datos.append({"codigo": codigo, "nombre": nombre,
                      "valor": _valor_json(fila.valor)})
    validos = df["valor"].dropna()
    LOG.info("[tiempo] organizar_resultados=%.3fs motor_total=%.3fs filas_salida=%s",
             perf_counter() - paso, perf_counter() - inicio, len(datos))
    avisar(4, True)
    return {"datos": datos, "geometria": geometria,
            "nivel_geografico": nivel,
            "_sql_ejecutada": sql,
            "valores": {"min": float(validos.min()) if len(validos) else None,
                        "max": float(validos.max()) if len(validos) else None}}

# BEGIN VISOR V31 REMOTE CARTOGRAPHY
# En cinco servicios estas funciones reemplazan en runtime la lectura local de
# la GDB. Sin CARTOGRAPHY_URL se conserva el modo monolitico anterior.
if os.getenv("CARTOGRAPHY_URL", "").strip():
    from geometry_remote import (
        referencia_geometria_remota,
        obtener_geometria_serializada_remota,
        precalentar_geometrias_remoto,
        estado_precalentamiento_remoto,
    )
    referencia_geometria = referencia_geometria_remota
    obtener_geometria_serializada = obtener_geometria_serializada_remota
    precalentar_geometrias = precalentar_geometrias_remoto
    estado_precalentamiento = estado_precalentamiento_remoto
# END VISOR V31 REMOTE CARTOGRAPHY
