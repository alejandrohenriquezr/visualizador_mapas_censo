# -*- coding: utf-8 -*-
"""Metadatos semánticos para el motor avanzado de consultas.

No modifica el diccionario oficial cargado por ``dictionary.py``. Añade una
capa derivada y auditable con tipo de variable, códigos no válidos y roles de
consulta. Las reglas explícitas se limitan a propiedades observables del
propio diccionario (llaves, geografía, variables numéricas conocidas, códigos
NA/-99/-66, variables derivadas nominales), evitando inventar universos
metodológicos no documentados.
"""
from __future__ import annotations

from copy import deepcopy

from dictionary import VARIABLES, TABLAS_PARQUET, es_categoria_invalida


# Variables que representan cantidades/años en los microdatos. Para ellas el
# diccionario puede listar solo códigos especiales o una parte de los valores.
NUMERICAS = {
    ("personas", "edad"): {"min": 0, "max": 120, "escala": "razon"},
    ("personas", "escolaridad"): {"min": 0, "max": 40, "escala": "razon"},
    ("personas", "p46a_tot_hijs_nac"): {"min": 0, "max": None, "escala": "conteo"},
    ("personas", "p46b_hijas_nac"): {"min": 0, "max": None, "escala": "conteo"},
    ("personas", "p46c_hijos_nac"): {"min": 0, "max": None, "escala": "conteo"},
    ("personas", "p47a_tot_hijs_sobrev"): {"min": 0, "max": None, "escala": "conteo"},
    ("personas", "p47b_hijas_sobrev"): {"min": 0, "max": None, "escala": "conteo"},
    ("personas", "p47c_hijos_sobrev"): {"min": 0, "max": None, "escala": "conteo"},
    ("personas", "p48_anio_nac_uh"): {"min": 1900, "max": 2024, "escala": "anio"},
    ("personas", "p48_mes_nac_uh"): {"min": 1, "max": 12, "escala": "mes"},
    ("viviendas", "p5_num_dormitorios"): {"min": 0, "max": None, "escala": "conteo"},
    ("viviendas", "p11a_num_personas"): {"min": 0, "max": None, "escala": "conteo"},
    ("viviendas", "p11c_num_hogar"): {"min": 1, "max": None, "escala": "conteo"},
    ("viviendas", "cant_per"): {"min": 0, "max": None, "escala": "conteo"},
    ("viviendas", "cant_hog"): {"min": 0, "max": None, "escala": "conteo"},
}

GEOGRAFIA = {"region", "provincia", "comuna", "area"}
LLAVES = {"id_vivienda", "id_hogar", "id_persona"}

ORDINALES = {
    ("personas", "edad_quinquenal"),
    ("personas", "p26_llegada_periodo"),
    ("personas", "p32a_dificultad_ver"),
    ("personas", "p32b_dificultad_oir"),
    ("personas", "p32c_dificultad_mover"),
    ("personas", "p32d_dificultad_cogni"),
    ("personas", "p32e_dificultad_cuidado"),
    ("personas", "p32f_dificultad_comunic"),
    ("viviendas", "indice_hacinamiento"),
}

DERIVADAS = {
    ("personas", "discapacidad"),
    ("personas", "asistencia_parv"),
    ("personas", "asistencia_basica"),
    ("personas", "asistencia_media"),
    ("personas", "asistencia_superior"),
    ("personas", "depend_econ_deficit_hab"),
    ("personas", "div_genero"),
    ("hogares", "tipologia_hogar"),
    ("viviendas", "indice_hacinamiento"),
}

GEO_CODIFICADAS = {
    ("personas", "p24_lug_resid5_esp"),
    ("personas", "p25_lug_nacimiento_esp"),
    ("personas", "p27_nacionalidad_esp"),
    ("personas", "p44_lug_trab_esp"),
}


def _invalidos(tabla: str, variable: str):
    info = VARIABLES[tabla]["variables"][variable]
    return [
        str(codigo) for codigo, etiqueta in info.get("categorias", {}).items()
        if es_categoria_invalida(codigo, etiqueta)
    ]


def _validos(tabla: str, variable: str):
    info = VARIABLES[tabla]["variables"][variable]
    return [
        str(codigo) for codigo, etiqueta in info.get("categorias", {}).items()
        if not es_categoria_invalida(codigo, etiqueta)
    ]


def variable_metadata(tabla: str, variable: str) -> dict:
    if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
        raise KeyError(f"Variable desconocida: {tabla}.{variable}")
    info = VARIABLES[tabla]["variables"][variable]
    clave = (tabla, variable)
    if variable in LLAVES:
        tipo = "llave"
    elif variable in GEOGRAFIA:
        tipo = "geografia"
    elif clave in NUMERICAS:
        tipo = "numerica"
    elif clave in GEO_CODIFICADAS:
        tipo = "geocodigo"
    elif clave in ORDINALES:
        tipo = "ordinal"
    else:
        tipo = "categorica"

    roles = ["filtro"]
    if tipo in {"categorica", "ordinal", "geografia", "geocodigo"}:
        roles.append("dimension")
    if tipo == "numerica":
        roles += ["medida", "dimension_derivada"]
    if tipo == "llave":
        roles = ["llave"]

    meta = {
        "tabla": tabla,
        "variable": variable,
        "descripcion": info.get("descripcion", variable),
        "tipo": tipo,
        "escala": NUMERICAS.get(clave, {}).get("escala"),
        "min_valido": NUMERICAS.get(clave, {}).get("min"),
        "max_valido": NUMERICAS.get(clave, {}).get("max"),
        "categorias_validas": _validos(tabla, variable),
        "codigos_excluidos": _invalidos(tabla, variable),
        "roles_permitidos": roles,
        "es_derivada": clave in DERIVADAS,
        "dominio_geocodigo": "mixto_comuna_pais" if clave in GEO_CODIFICADAS else None,
    }
    if tipo == "numerica":
        meta["operaciones_permitidas"] = ["conteo", "promedio", "mediana", "suma", "minimo", "maximo"]
    elif tipo != "llave":
        meta["operaciones_permitidas"] = ["conteo", "distribucion", "porcentaje"]
    else:
        meta["operaciones_permitidas"] = []
    return meta


def catalogo_metadata() -> dict:
    salida = {}
    for tabla in TABLAS_PARQUET:
        salida[tabla] = {
            variable: variable_metadata(tabla, variable)
            for variable in VARIABLES[tabla]["variables"]
        }
    return salida


def condiciones_universo(tabla: str, variable: str) -> list[dict]:
    """Universo técnico verificable a partir del propio diccionario.

    No intenta reconstruir saltos del cuestionario no presentes en el JSON.
    Para variables categóricas excluye códigos de no respuesta/no aplica/
    supresión; para variables numéricas aplica límites físicos conocidos y
    excluye códigos negativos cuando existan.
    """
    meta = variable_metadata(tabla, variable)
    salida = []
    if meta["tipo"] in {"categorica", "ordinal", "geocodigo", "geografia"}:
        if meta["categorias_validas"]:
            salida.append({
                "tipo": "categoria",
                "tabla": tabla,
                "variable": variable,
                "valores": deepcopy(meta["categorias_validas"]),
                "modo": "in",
                "origen": "universo_diccionario",
            })
    elif meta["tipo"] == "numerica":
        salida.append({
            "tipo": "rango",
            "tabla": tabla,
            "variable": variable,
            "minimo": meta["min_valido"],
            "maximo": meta["max_valido"],
            "incluir_minimo": True,
            "incluir_maximo": True,
            "origen": "universo_diccionario",
        })
        for codigo in meta["codigos_excluidos"]:
            try:
                numero = float(codigo)
            except (TypeError, ValueError):
                continue
            salida.append({
                "tipo": "comparacion",
                "tabla": tabla,
                "variable": variable,
                "operador": "!=",
                "valor": numero,
                "origen": "universo_diccionario",
            })
    return salida
