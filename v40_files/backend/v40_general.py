# -*- coding: utf-8 -*-
"""Reglas generales V40 para orden semántico, edad e indicadores desagregados.

Este módulo no ejecuta consultas por sí mismo. Centraliza reglas que deben ser
compartidas por el intérprete y el motor para evitar resolver ejemplos aislados.
"""
from __future__ import annotations

import re
from copy import deepcopy

from dictionary import VARIABLES, _norm, buscar_variables, categorias_validas
from categorical_resolver import AmbiguedadVariable


_TIPOS_EDAD = {"edad", "edad_quinquenal", "edad_grandes_grupos"}


def _posicion_dimension(q: str, dimension: dict) -> int:
    """Posición aproximada del concepto en la consulta para conservar su orden."""
    qn = _norm(q)
    variable = str(dimension.get("variable") or "")
    etiqueta = _norm(str(dimension.get("etiqueta") or ""))
    patrones = []
    if variable == "sexo":
        patrones += [r"\bsexo\b", r"\bsexos\b"]
    elif variable == "edad_quinquenal":
        patrones += [r"\bedad\s+quinquenal\b", r"\bedades\s+quinquenales\b", r"\bgrupos?\s+quinquenales?\s+de\s+edad\b"]
    elif variable == "edad_grandes_grupos" or dimension.get("variable_logica") == "edad_grandes_grupos":
        patrones += [r"\bedad\s+en\s+grandes\s+grupos\b", r"\bgrandes\s+grupos\s+de\s+edad\b"]
    elif variable == "edad":
        if dimension.get("tipo") == "edad_simple":
            patrones += [r"\bedad\s+simple\b", r"\bedades\s+simples\b"]
        patrones += [r"\bedad\b", r"\bedades\b"]
    else:
        desc = _norm(str(
            VARIABLES.get(dimension.get("tabla"), {})
            .get("variables", {}).get(variable, {}).get("descripcion", "")
        ))
        texto_var = _norm(variable.replace("_", " "))
        if texto_var:
            patrones.append(r"\b" + re.escape(texto_var) + r"\b")
        if etiqueta:
            patrones.append(r"\b" + re.escape(etiqueta) + r"\b")
        # Las descripciones oficiales suelen empezar con número de pregunta;
        # se usan solo fragmentos suficientemente largos y no numéricos.
        tokens = [t for t in re.findall(r"[a-z0-9]+", desc) if len(t) >= 5 and not t.isdigit()]
        if tokens:
            patrones.append(r"\b" + re.escape(" ".join(tokens[:3])) + r"\b")

    posiciones = []
    for patron in patrones:
        m = re.search(patron, qn)
        if m:
            posiciones.append(m.start())
    return min(posiciones) if posiciones else 10**9


def ordenar_dimensiones_consulta_v40(consulta: str, dimensiones: list[dict]) -> list[dict]:
    """Ordena dimensiones según aparición textual, no según puntaje del matcher."""
    enumeradas = list(enumerate(deepcopy(dimensiones or [])))
    enumeradas.sort(key=lambda par: (_posicion_dimension(consulta, par[1]), par[0]))
    return [d for _, d in enumeradas]


def recode_grandes_grupos_v40(consulta: str) -> dict | None:
    """Representa edad en grandes grupos sin exigir una columna física nueva."""
    q = _norm(consulta)
    if not re.search(r"\bedad\s+en\s+grandes\s+grupos\b|\bgrandes\s+grupos\s+de\s+edad\b", q):
        return None
    return {
        "tabla": "personas",
        "variable": "edad",
        "variable_logica": "edad_grandes_grupos",
        "tipo": "recode_rangos",
        "etiqueta": "Edad en grandes grupos",
        "grupos": [
            {"minimo": 0, "maximo": 14, "etiqueta": "0-14", "codigo": "0"},
            {"minimo": 15, "maximo": 59, "etiqueta": "15-59", "codigo": "1"},
            {"minimo": 60, "maximo": 120, "etiqueta": "60 o más", "codigo": "2"},
        ],
    }


def _edad_explicita(q: str) -> bool:
    return bool(re.search(
        r"\bedad\s+simple\b|\bedades\s+simples\b|"
        r"\bedad\s+quinquenal\b|\bedades\s+quinquenales\b|"
        r"\bgrupos?\s+quinquenales?\s+de\s+edad\b|"
        r"\bedad\s+en\s+grandes\s+grupos\b|\bgrandes\s+grupos\s+de\s+edad\b",
        q,
    ))


def _edad_es_filtro_numerico(q: str) -> bool:
    """Un rango o umbral numérico ya define edad simple y no requiere diálogo."""
    patrones = (
        r"\bentre\s+\d{1,3}\s+y\s+\d{1,3}\s+anos?\b",
        r"\b\d{1,3}\s+anos?\s+o\s+(?:mas|menos)\b",
        r"\b(?:mayores?|menores?)\s+(?:de|a)\s+\d{1,3}\b",
        r"\b(?:mas|menos)\s+de\s+\d{1,3}\s+anos?\b",
        r"\bhasta\s+\d{1,3}\s+anos?\b",
        r"\bal\s+menos\s+\d{1,3}\s+anos?\b",
    )
    return any(re.search(p, q) for p in patrones)


def requiere_tipo_edad_v40(consulta: str, variable_seleccionada: str | None = None) -> bool:
    """Detecta edad usada como dimensión, evitando rangos y medidas de edad."""
    if variable_seleccionada in _TIPOS_EDAD:
        return False
    q = _norm(consulta)
    if not re.search(r"\bedad(?:es)?\b", q) or _edad_explicita(q):
        return False
    if _edad_es_filtro_numerico(q):
        return False
    if re.search(r"\b(?:promedio|media|mediana|minimo|maximo)\s+(?:de\s+)?edad\b", q):
        return False
    # Edad como dimensión explícita o consulta distributiva.
    return bool(re.search(
        r"\b(?:por|segun)\s+(?:la\s+)?edad\b|"
        r"\bedad\s+(?:y|por|segun)\b|"
        r"\b(?:distribucion|composicion)\b[^.]{0,80}\bedad\b|"
        r"\b(?:edad|edades)\s*$",
        q,
    ))


def seleccionar_tipo_edad_v40(consulta: str, variable_seleccionada: str | None = None) -> None:
    """Abre el selector estándar cuando la consulta no define el tipo de edad."""
    if not requiere_tipo_edad_v40(consulta, variable_seleccionada):
        return
    opciones = [
        {
            "tabla": "personas", "variable": "edad",
            "descripcion": "Edad simple (años cumplidos)",
            "categorias_ejemplo": ["0", "1", "2", "…", "120"], "puntaje": 100,
        },
        {
            "tabla": "personas", "variable": "edad_quinquenal",
            "descripcion": "Edad quinquenal",
            "categorias_ejemplo": ["0-4", "5-9", "10-14", "…", "85 o más"], "puntaje": 100,
        },
        {
            "tabla": "personas", "variable": "edad_grandes_grupos",
            "descripcion": "Edad en grandes grupos",
            "categorias_ejemplo": ["0-14", "15-59", "60 o más"], "puntaje": 100,
        },
    ]
    raise AmbiguedadVariable(
        "La consulta usa edad como desagregación, pero no indica el tipo. Selecciona edad simple, quinquenal o edad en grandes grupos.",
        opciones,
    )


def consulta_con_tipo_edad_v40(consulta: str, variable_seleccionada: str | None) -> str:
    """Convierte la selección del diálogo en semántica explícita para el planificador."""
    if variable_seleccionada not in _TIPOS_EDAD:
        return consulta
    q = _norm(consulta)
    if variable_seleccionada == "edad" and not re.search(r"\bedad\s+simple\b", q):
        return consulta + " edad simple"
    if variable_seleccionada == "edad_quinquenal" and not re.search(r"\bedad\s+quinquenal\b", q):
        return consulta + " edad quinquenal"
    if variable_seleccionada == "edad_grandes_grupos" and not re.search(r"\bedad\s+en\s+grandes\s+grupos\b", q):
        return consulta + " edad en grandes grupos"
    return consulta


def _dimension_edad_explicitada(fragmento: str) -> dict | None:
    q = _norm(fragmento)
    grande = recode_grandes_grupos_v40(q)
    if grande:
        return grande
    if re.search(r"\bedad\s+quinquenal\b|\bedades\s+quinquenales\b|\bgrupos?\s+quinquenales?\s+de\s+edad\b", q):
        return {
            "tabla": "personas", "variable": "edad_quinquenal", "tipo": "categoria",
            "categorias_validas": [str(v) for v in categorias_validas("personas", "edad_quinquenal")],
            "etiqueta": "Edad quinquenal",
        }
    if re.search(r"\bedad\s+simple\b|\bedades\s+simples\b", q):
        return {"tabla": "personas", "variable": "edad", "tipo": "edad_simple", "etiqueta": "Edad simple"}
    return None


def _fragmentos_desagregacion(q: str) -> list[str]:
    """Recupera fragmentos introducidos por según/por, excluyendo geografía."""
    fragmentos = []
    for m in re.finditer(r"\b(?:segun|desagregad[oa]s?\s+por|por)\s+([^.;]+)", q):
        f = m.group(1).strip()
        if re.match(r"^(?:region(?:es)?|provincia(?:s)?|comuna(?:s)?)(?:\b|$)", f):
            continue
        fragmentos.append(f)
    return fragmentos


def aplicar_desagregaciones_indicador_v40(intencion: dict | None, consulta: str) -> dict | None:
    """Añade dimensiones solicitadas a tasas/índices ya registrados.

    La fórmula del indicador se mantiene intacta; únicamente se añade GROUP BY
    por las dimensiones explícitas. Esto evita crear reglas especiales por
    cada combinación indicador × sexo/edad/etc.
    """
    if not isinstance(intencion, dict):
        return intencion
    if intencion.get("tipo_consulta") not in {"indicador_censal_v27", "indicador_derivado_v24"}:
        return intencion
    q = _norm(consulta)
    fragmentos = _fragmentos_desagregacion(q)
    if not fragmentos:
        return intencion

    ancla = (intencion.get("tabla") or "personas", intencion.get("variable"))
    dimensiones = []
    vistos = set()

    for fragmento in fragmentos:
        edad_dim = _dimension_edad_explicitada(fragmento)
        if edad_dim:
            clave = (edad_dim.get("tabla"), edad_dim.get("variable_logica") or edad_dim.get("variable"), edad_dim.get("tipo"))
            if clave not in vistos:
                dimensiones.append(edad_dim); vistos.add(clave)

        for candidato in buscar_variables(fragmento, top_n=20) or []:
            tabla = candidato.get("tabla")
            variable = candidato.get("variable")
            if tabla != "personas" or not variable or (tabla, variable) == ancla:
                continue
            if variable in {"region", "provincia", "comuna", "edad_grandes_grupos"}:
                continue
            if variable == "edad" and edad_dim is not None:
                continue
            if variable == "edad_quinquenal" and edad_dim is not None:
                continue
            validas = [str(v) for v in categorias_validas(tabla, variable)]
            if variable == "edad":
                # Edad desnuda debe haber sido resuelta por el selector antes.
                continue
            if len(validas) < 2:
                continue
            clave = (tabla, variable, "categoria")
            if clave in vistos:
                continue
            dimensiones.append({
                "tabla": tabla, "variable": variable, "tipo": "categoria",
                "categorias_validas": validas,
                "etiqueta": VARIABLES[tabla]["variables"][variable].get("descripcion", variable),
            })
            vistos.add(clave)

    if not dimensiones:
        return intencion
    salida = deepcopy(intencion)
    salida["desagregaciones"] = ordenar_dimensiones_consulta_v40(consulta, dimensiones)[:3]
    salida["tipo_visualizacion_sugerida"] = "series_mapa"
    return salida


def _expr_dimension_sql(d: dict) -> tuple[str, list[str]]:
    """Expresión SQL segura de una dimensión ya validada contra el diccionario."""
    variable = d.get("variable")
    tipo = d.get("tipo")
    if d.get("variable_logica") == "edad_grandes_grupos":
        edad = 'TRY_CAST("edad" AS DOUBLE)'
        expr = (
            f"CASE WHEN {edad} BETWEEN 0 AND 14 THEN '0' "
            f"WHEN {edad} BETWEEN 15 AND 59 THEN '1' "
            f"WHEN {edad} BETWEEN 60 AND 120 THEN '2' END"
        )
        return expr, [f"{edad} BETWEEN 0 AND 120"]
    if variable == "edad" and tipo == "edad_simple":
        edad = 'TRY_CAST("edad" AS INTEGER)'
        return f"CAST({edad} AS VARCHAR)", [f"{edad} BETWEEN 0 AND 120"]
    if tipo == "recode_rangos" and variable == "edad":
        edad = 'TRY_CAST("edad" AS DOUBLE)'
        casos = []
        for g in d.get("grupos") or []:
            lo, hi = g.get("minimo"), g.get("maximo")
            etiqueta = str(g.get("codigo") if g.get("codigo") is not None else g.get("etiqueta")).replace("'", "''")
            if lo is None and hi is None:
                continue
            if lo is not None and hi is not None:
                cond = f"{edad} BETWEEN {int(lo)} AND {int(hi)}"
            elif lo is not None:
                cond = f"{edad} >= {int(lo)}"
            else:
                cond = f"{edad} <= {int(hi)}"
            casos.append(f"WHEN {cond} THEN '{etiqueta}'")
        expr = "CASE " + " ".join(casos) + " END"
        return expr, [f"({expr}) IS NOT NULL"]

    tabla = d.get("tabla")
    if tabla not in VARIABLES or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError("La desagregación del indicador no existe en el diccionario.")
    col = '"' + str(variable).replace('"', '""') + '"'
    validas = [str(v) for v in (d.get("categorias_validas") or categorias_validas(tabla, variable))]
    filtros = []
    if validas:
        lista = ", ".join("'" + v.replace("'", "''") + "'" for v in validas)
        filtros.append(f"CAST({col} AS VARCHAR) IN ({lista})")
    return f"CAST({col} AS VARCHAR)", filtros


def sql_desagregaciones_indicador_v40(intencion: dict) -> tuple[str, str, list[str]]:
    """Devuelve fragmentos SELECT, GROUP BY y filtros para un indicador."""
    select, group, filtros = [], [], []
    for i, d in enumerate(intencion.get("desagregaciones") or []):
        expr, conds = _expr_dimension_sql(d)
        select.append(f", {expr} AS d{i}")
        group.append(f", {expr}")
        filtros.extend(conds)
    return "".join(select), "".join(group), filtros


def _etiqueta_codigo_dimension(d: dict, codigo: str) -> str:
    codigo = str(codigo)
    if d.get("variable_logica") == "edad_grandes_grupos":
        return {"0": "0-14", "1": "15-59", "2": "60 o más"}.get(codigo, codigo)
    if d.get("variable") == "edad" and d.get("tipo") == "edad_simple":
        try:
            return f"{int(float(codigo))} años"
        except (TypeError, ValueError):
            return codigo
    if d.get("tipo") == "recode_rangos":
        for g in d.get("grupos") or []:
            clave = str(g.get("codigo") if g.get("codigo") is not None else g.get("etiqueta"))
            if clave == codigo:
                return str(g.get("etiqueta") or codigo)
        return codigo
    tabla, variable = d.get("tabla"), d.get("variable")
    return str(VARIABLES.get(tabla, {}).get("variables", {}).get(variable, {}).get("categorias", {}).get(codigo, codigo))


def _codigo_json_local(valor):
    try:
        if valor is None:
            return None
        entero = int(valor)
        if str(entero) == str(valor) or float(valor) == entero:
            return entero
    except (TypeError, ValueError):
        pass
    return str(valor)


def series_indicador_v40(df, intencion: dict, nivel: str) -> list[dict]:
    """Convierte filas GROUP BY en series por territorio conservando el orden."""
    dims = intencion.get("desagregaciones") or []
    nombres = VARIABLES.get("geografia", {}).get(nivel, {})
    por_geo = {}
    for fila in df.itertuples(index=False):
        codigo_geo = _codigo_json_local(getattr(fila, "codigo"))
        codigos = [str(getattr(fila, f"d{i}")) for i in range(len(dims))]
        partes = [
            f"{d.get('etiqueta', d.get('variable'))}: {_etiqueta_codigo_dimension(d, codigos[i])}"
            for i, d in enumerate(dims)
        ]
        valor = getattr(fila, "valor", None)
        try:
            valor = None if valor is None or valor != valor else float(valor)
        except TypeError:
            valor = None
        por_geo.setdefault(codigo_geo, []).append({
            "codigo": "|".join(codigos), "etiqueta": " · ".join(partes), "valor": valor,
        })
    salida = []
    for codigo, series in por_geo.items():
        nombre = next((v for k, v in nombres.items()
                       if str(k).isdigit() and str(codigo).isdigit() and int(k) == int(codigo)), str(codigo))
        salida.append({"codigo": codigo, "nombre": nombre, "series": series})
    return salida


def nombre_ambito_v40(intencion: dict) -> str:
    nivel = intencion.get("filtro_geografico_nivel")
    codigo = intencion.get("filtro_geografico_codigo")
    if nivel and codigo is not None:
        nombre = next((str(v) for k, v in VARIABLES.get("geografia", {}).get(nivel, {}).items()
                       if str(k).isdigit() and int(k) == int(codigo)), str(codigo))
        prefijo = {"region": "Región", "provincia": "Provincia", "comuna": "Comuna"}.get(nivel, nivel.capitalize())
        return f"{prefijo} {nombre}"
    return "Chile"


def resumen_series_indicador_v40(df, intencion: dict) -> dict:
    """Resumen exacto del ámbito a partir de una consulta agregada independiente."""
    dims = intencion.get("desagregaciones") or []
    series = []
    for fila in df.itertuples(index=False):
        codigos = [str(getattr(fila, f"d{i}")) for i in range(len(dims))]
        partes = [
            f"{d.get('etiqueta', d.get('variable'))}: {_etiqueta_codigo_dimension(d, codigos[i])}"
            for i, d in enumerate(dims)
        ]
        valor = getattr(fila, "valor", None)
        try:
            valor = None if valor is None or valor != valor else float(valor)
        except TypeError:
            valor = None
        series.append({"codigo": "|".join(codigos), "etiqueta": " · ".join(partes), "valor": valor})
    return {"tipo": "series", "nombre": nombre_ambito_v40(intencion), "series": series}


def resumen_torta_v40(datos: list[dict], nombre: str, usar_completa: bool = True) -> dict | None:
    """Agrega conteos de territorios disjuntos para la torta del ámbito completo.

    En cruces, ``usar_completa=False`` hace que el resumen replique la primera
    dimensión mostrada en el mapa, mientras Excel conserva el detalle completo.
    """
    totales = {}
    etiquetas = {}
    for territorio in datos or []:
        fuente = (territorio.get("distribucion_completa") if usar_completa else None) or territorio.get("distribucion") or []
        for item in fuente:
            codigo = str(item.get("codigo"))
            totales[codigo] = totales.get(codigo, 0) + int(item.get("valor") or 0)
            etiquetas[codigo] = str(item.get("etiqueta") or codigo)
    total = sum(totales.values())
    if not totales:
        return None
    orden = sorted(totales, key=lambda c: (-totales[c], etiquetas[c]))
    principales = orden[:4] if len(orden) > 4 else orden
    dist = []
    for c in principales:
        v = totales[c]
        dist.append({"codigo": c, "etiqueta": etiquetas[c], "valor": v,
                     "porcentaje": 100.0 * v / total if total else None})
    if len(orden) > 4:
        otros = sum(totales[c] for c in orden[4:])
        dist.append({"codigo": "otros", "etiqueta": "Otros", "valor": otros,
                     "porcentaje": 100.0 * otros / total if total else None})
    return {"tipo": "torta", "nombre": nombre, "total": total, "distribucion": dist}


def reagrupar_tortas_primera_dimension_v40(datos: list[dict], dimensiones: list[dict]) -> tuple[list[dict], list[dict]]:
    """La torta cartográfica representa solo la primera dimensión de la consulta.

    ``distribucion_completa`` permanece intacta para Excel y pirámides.
    """
    if not dimensiones:
        return datos, []
    primera = dimensiones[0]
    totales_globales = {}
    etiquetas = {}
    por_territorio = {}
    for territorio in datos or []:
        conteos = {}
        for item in territorio.get("distribucion_completa") or []:
            codigo = str(item.get("codigo") or "").split("|", 1)[0]
            valor = int(item.get("valor") or 0)
            conteos[codigo] = conteos.get(codigo, 0) + valor
            totales_globales[codigo] = totales_globales.get(codigo, 0) + valor
            etiquetas[codigo] = _etiqueta_codigo_dimension(primera, codigo)
        por_territorio[str(territorio.get("codigo"))] = conteos

    orden = sorted(totales_globales, key=lambda c: (-totales_globales[c], etiquetas.get(c, c)))
    principales = orden[:4] if len(orden) > 4 else orden
    categorias = [{"codigo": c, "etiqueta": etiquetas.get(c, c)} for c in principales]
    if len(orden) > 4:
        categorias.append({"codigo": "otros", "etiqueta": "Otros"})

    salida = []
    for territorio in datos or []:
        nuevo = deepcopy(territorio)
        conteos = por_territorio.get(str(territorio.get("codigo")), {})
        total = sum(conteos.values())
        dist = []
        for c in principales:
            v = conteos.get(c, 0)
            dist.append({"codigo": c, "etiqueta": etiquetas.get(c, c), "valor": v,
                         "porcentaje": 100.0 * v / total if total else None})
        if len(orden) > 4:
            otros = sum(v for c, v in conteos.items() if c not in principales)
            dist.append({"codigo": "otros", "etiqueta": "Otros", "valor": otros,
                         "porcentaje": 100.0 * otros / total if total else None})
        nuevo["distribucion"] = dist
        nuevo["total"] = total
        salida.append(nuevo)
    return salida, categorias
