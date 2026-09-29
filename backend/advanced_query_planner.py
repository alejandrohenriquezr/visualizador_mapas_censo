# -*- coding: utf-8 -*-
"""Planificador avanzado inspirado en el modelo de consulta REDATAM.

Construye un QueryPlan declarativo con:
- entidad objetivo;
- dimensiones (hasta tres de forma explícita, sin perder información);
- universo técnico verificable;
- árbol lógico de filtros AND/OR/NOT;
- medida (COUNT DISTINCT, AVG, MEDIAN, SUM, MIN, MAX);
- base de porcentaje (total/fila/columna);
- selecciones geográficas múltiples;
- filtros jerárquicos EXISTS/COUNT/ALL sobre miembros del hogar.

Se activa solo cuando la pregunta requiere capacidades que el planificador
histórico v15 no representa. Las consultas simples continúan por las rutas ya
probadas para minimizar regresiones.
"""
from __future__ import annotations

import re
from copy import deepcopy

from dictionary import VARIABLES, TABLAS_PARQUET, _norm, categorias_validas
from categorical_resolver import _coincidencias_categoria, AmbiguedadOperacion
from cross_query_planner import (
    _detectar_variables,
    _filtros_manual,
    _filtros_co_residencia,
    _filtro_especial_resolver,
    _filtros_numericos,
    _deduplicar_filtros,
    _aplicar_categorias_genericas,
    _agregar_variable,
    _entidad_objetivo_explicita,
    _entidad_inferida,
    _es_dimension,
    _subconjunto_categorias_mencionado,
    _filtro_desde_subconjunto,
    _etiqueta_dimension,
    JERARQUIA,
)
from query_metadata import variable_metadata, condiciones_universo
from colloquial_resolver import detectar_territorio_especifico, concepto_territorio_especifico


_OP_SELECTIONS = {
    "__pct_total": "total",
    "__pct_fila": "fila",
    "__pct_columna": "columna",
}

_NUMERIC_ALIASES = (
    ("personas", "edad", (r"\bedad\b", r"\banos?\s+cumplidos\b")),
    ("personas", "escolaridad", (r"\bescolaridad\b", r"\banos?\s+de\s+estudio\b")),
    ("personas", "p46a_tot_hijs_nac", (r"\bhij[oa]s?\s+nacidos?\s+vivos?\b", r"\btotal\s+de\s+hij[oa]s?\b")),
    ("personas", "p47a_tot_hijs_sobrev", (r"\bhij[oa]s?\s+(?:que\s+)?(?:estan|siguen)\s+vivos?\b",)),
    ("viviendas", "p5_num_dormitorios", (r"\bdormitorios?\b", r"\bpiezas?\s+.*dormitorio\b")),
    ("viviendas", "p11a_num_personas", (r"\bpersonas?\s+residentes?\s+habitualmente\b", r"\bresidentes?\s+habituales\b")),
    ("viviendas", "p11c_num_hogar", (r"\bgrupos?\s+.*gastos?\s+separados?\b",)),
    ("viviendas", "cant_per", (r"\bpersonas?\s+censadas?\s+en\s+la\s+vivienda\b",)),
    ("viviendas", "cant_hog", (r"\bhogares?\s+censados?\s+en\s+la\s+vivienda\b",)),
)


def _node_and(items):
    items = [deepcopy(x) for x in items if x]
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return {"op": "and", "args": items}


def _node_or(items):
    items = [deepcopy(x) for x in items if x]
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return {"op": "or", "args": items}


def _node_not(item):
    return {"op": "not", "arg": deepcopy(item)} if item else None


def _filtro_categoria(tabla, variable, valores, etiqueta=None, modo="in", origen="avanzado"):
    return {
        "tipo": "categoria", "tabla": tabla, "variable": variable,
        "valores": [str(v) for v in valores], "etiqueta": etiqueta,
        "modo": modo, "origen": origen,
    }


def _rango(tabla, variable, minimo=None, maximo=None,
           incluir_minimo=True, incluir_maximo=True, origen="avanzado"):
    meta = variable_metadata(tabla, variable)
    return {
        "tipo": "rango", "tabla": tabla, "variable": variable,
        "minimo": minimo, "maximo": maximo,
        "incluir_minimo": incluir_minimo, "incluir_maximo": incluir_maximo,
        "dominio_minimo": meta.get("min_valido"),
        "dominio_maximo": meta.get("max_valido"), "origen": origen,
    }


def _medida_numerica(q):
    op = None
    patrones = (
        ("promedio", r"\b(?:promedio|media\s+de)\b"),
        ("mediana", r"\bmediana\b"),
        ("suma", r"\b(?:suma|sumatoria|sumar)\b"),
        ("minimo", r"\b(?:minimo|minima|valor\s+minimo)\b"),
        ("maximo", r"\b(?:maximo|maxima|valor\s+maximo)\b"),
    )
    for nombre, patron in patrones:
        if re.search(patron, q):
            op = nombre
            break
    if not op:
        return None
    candidatos = []
    for tabla, variable, patrones_var in _NUMERIC_ALIASES:
        if any(re.search(p, q) for p in patrones_var):
            candidatos.append((tabla, variable))
    if not candidatos:
        # Fallback controlado: solo variables numéricas cuyo nombre/descripción
        # aporta tokens explícitos a la consulta.
        for tabla in TABLAS_PARQUET:
            for variable, info in VARIABLES[tabla]["variables"].items():
                try:
                    meta = variable_metadata(tabla, variable)
                except KeyError:
                    continue
                if meta["tipo"] != "numerica":
                    continue
                tokens = {t for t in re.findall(r"[a-z0-9]+", _norm(info.get("descripcion", ""))) if len(t) >= 5}
                if tokens and len(tokens & set(q.split())) >= 2:
                    candidatos.append((tabla, variable))
    if len(candidatos) != 1:
        return None
    tabla, variable = candidatos[0]
    return {"operacion": op, "tabla": tabla, "variable": variable}


def _porcentaje_solicitado(q):
    return bool(re.search(r"\b(?:porcentaje|proporcion)\b|%", q))


def _base_porcentaje(q, dimensiones, seleccion_operacion=None):
    if seleccion_operacion in _OP_SELECTIONS:
        return _OP_SELECTIONS[seleccion_operacion]
    if re.search(r"\b(?:sobre|respecto\s+de)\s+(?:el\s+)?total\b|\bporcentaje\s+total\b", q):
        return "total"
    if re.search(r"\bporcentaje\s+de\s+fila\b|\bdentro\s+de\s+cada\s+(?:fila|categoria\s+de\s+la\s+primera\s+variable)\b", q):
        return "fila"
    if re.search(r"\bporcentaje\s+de\s+columna\b|\bdentro\s+de\s+cada\s+(?:columna|categoria\s+de\s+la\s+segunda\s+variable)\b", q):
        return "columna"
    # Con una sola dimensión, la distribución porcentual por territorio es
    # inequívoca: cada categoría se divide por el total válido del territorio.
    if len(dimensiones) <= 1:
        return "total"
    return None


def _rangos_or_edad(q):
    """Expresiones OR frecuentes sobre edad, sin perder precedencia."""
    m = re.search(
        r"\bmenores?\s+de\s+(\d{1,3})(?:\s+anos?)?\s+o\s+(?:personas?\s+)?"
        r"(?:de\s+)?(\d{1,3})\s+anos?\s+o\s+mas\b", q)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return _node_or([
            _rango("personas", "edad", maximo=a, incluir_maximo=False, origen="or_edad"),
            _rango("personas", "edad", minimo=b, incluir_minimo=True, origen="or_edad"),
        ])
    m = re.search(
        r"\bmenores?\s+de\s+(\d{1,3})(?:\s+anos?)?\s+o\s+mayores?\s+de\s+(\d{1,3})\s+anos?\b", q)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return _node_or([
            _rango("personas", "edad", maximo=a, incluir_maximo=False, origen="or_edad"),
            _rango("personas", "edad", minimo=b, incluir_minimo=False, origen="or_edad"),
        ])
    return None


def _filtro_laboral_or(q):
    if " o " not in q:
        return None
    tiene_ocup = bool(re.search(r"\bocupad[oa]s?\b", q))
    tiene_desocup = bool(re.search(r"\bdesocupad[oa]s?\b", q))
    tiene_fuera = bool(re.search(r"\bfuera\s+de\s+la\s+fuerza\s+de\s+trabajo\b", q))
    valores = []
    if tiene_ocup: valores.append("1")
    if tiene_desocup: valores.append("2")
    if tiene_fuera: valores.append("3")
    if len(valores) >= 2:
        return _filtro_categoria("personas", "sit_fuerza_trabajo", valores,
                                 etiqueta=" / ".join(VALUES_SIT[v] for v in valores),
                                 origen="or_categoria")
    return None


VALUES_SIT = {"1": "Ocupado", "2": "Desocupado", "3": "Fuera de la fuerza de trabajo"}


def _filtro_territorio_especifico(q, tabla_seleccionada=None, variable_seleccionada=None):
    """Convierte un país/territorio específico en filtro categórico.

    Cuando un demónimo desnudo (p.ej. ``venezolanas``) fue desambiguado por la
    interfaz, la selección de nacimiento/nacionalidad debe sobrevivir al nuevo
    intento de interpretación. Sin selección, el demónimo desnudo sigue siendo
    ambiguo y se deja al flujo histórico de selección.
    """
    territorio = detectar_territorio_especifico(q)
    if not territorio:
        return None
    concepto = concepto_territorio_especifico(q)

    seleccion = None
    if tabla_seleccionada == "personas" and variable_seleccionada in {
        "p25_lug_nacimiento_esp", "p27_nacionalidad_esp",
        "p24_lug_resid5_esp", "p44_lug_trab_esp",
    }:
        seleccion = variable_seleccionada

    if seleccion:
        variable = seleccion
    elif concepto:
        variable = {
            "nacimiento": "p25_lug_nacimiento_esp",
            "nacionalidad": "p27_nacionalidad_esp",
            "residencia_2019": "p24_lug_resid5_esp",
            "trabajo": "p44_lug_trab_esp",
        }.get(concepto)
    else:
        # Demónimo sin concepto explícito: debe abrir selector.
        return None

    if not variable or variable not in VARIABLES["personas"]["variables"]:
        return None
    codigo = str(territorio["codigo"])
    categorias = VARIABLES["personas"]["variables"][variable].get("categorias", {})
    if codigo not in {str(c) for c in categorias}:
        return None
    etiquetas = {
        "p25_lug_nacimiento_esp": territorio["etiqueta"],
        "p27_nacionalidad_esp": territorio["etiqueta"],
        "p24_lug_resid5_esp": territorio["etiqueta"],
        "p44_lug_trab_esp": territorio["etiqueta"],
    }
    return _filtro_categoria(
        "personas", variable, [codigo], etiquetas.get(variable, territorio["etiqueta"]),
        origen="territorio_especifico_avanzado",
    )


def _filtro_maternidad(q):
    """Interpreta ``mujeres con hijos`` como al menos un nacido vivo.

    El Censo 2024 dispone del total de hijas e hijos nacidos vivos (P46a). Se
    utiliza > 0; no se sustituye por hijos sobrevivientes P47, que responde a
    otra pregunta.
    """
    if not re.search(r"\b(?:mujeres?\s+con\s+hij[oa]s?|madres?)\b", q):
        return None
    filtro = _rango(
        "personas", "p46a_tot_hijs_nac", minimo=0, incluir_minimo=False,
        origen="maternidad",
    )
    filtro["etiqueta"] = "que han tenido al menos una hija o hijo nacido vivo"
    return filtro


def _or_pertenece_a_descripcion_variable(q, detectadas=None):
    """Evita interpretar como OR categórico una «o» que forma parte del nombre.

    Ejemplo: «fuente de energía o combustible que utilizan para cocinar».
    La conjunción existe en la descripción oficial de p13 y no significa que
    el usuario esté uniendo dos categorías. Se comparan ventanas léxicas a
    ambos lados de cada «o» contra las descripciones de variables detectadas.
    """
    if " o " not in q:
        return False
    descripciones = []
    for tabla, variable in (detectadas or {}):
        if tabla in TABLAS_PARQUET and variable in VARIABLES[tabla]["variables"]:
            descripciones.append(_norm(VARIABLES[tabla]["variables"][variable].get("descripcion", "")))
    if not descripciones:
        return False
    partes = q.split(" o ")
    for i in range(len(partes) - 1):
        izq = re.findall(r"[a-z0-9]+", partes[i])[-3:]
        der = re.findall(r"[a-z0-9]+", partes[i + 1])[:3]
        if not izq or not der:
            continue
        ventana = " ".join(izq) + " o " + " ".join(der)
        if any(ventana in d for d in descripciones):
            return True
    return False


def _filtro_categoria_or_generico(q, detectadas=None):
    """Une categorías de una misma variable cuando el usuario usa «o».

    Para variables ya identificadas por contexto permite que una categoría
    compuesta se mencione parcialmente (p.ej. «pozo» para «Pozo o noria»),
    siempre que haya al menos dos categorías distintas en la misma variable.
    """
    if " o " not in q:
        return None
    grupos = {}
    for puntaje, tabla, variable, codigo, etiqueta in _coincidencias_categoria(q):
        grupos.setdefault((tabla, variable), {})[str(codigo)] = (puntaje, str(etiqueta))

    for clave in (detectadas or {}):
        tabla, variable = clave
        if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
            continue
        info = VARIABLES[tabla]["variables"][variable]
        toks_desc = {t for t in re.findall(r"[a-z0-9]+", _norm(info.get("descripcion", ""))) if len(t) >= 4}
        for codigo in categorias_validas(tabla, variable):
            etiqueta = str(info.get("categorias", {}).get(str(codigo), ""))
            toks = [t for t in re.findall(r"[a-z0-9]+", _norm(etiqueta))
                    if len(t) >= 4 and t not in {"otro", "otros", "otra", "otras", "ninguna"}
                    and t not in toks_desc]
            if not toks:
                continue
            presentes = [t for t in toks if re.search(r"\b" + re.escape(t) + r"\w*\b", q)]
            if presentes:
                grupos.setdefault((tabla, variable), {}).setdefault(
                    str(codigo), (8 * len(presentes), etiqueta)
                )

    candidatos = []
    for (tabla, variable), items in grupos.items():
        if len(items) < 2:
            continue
        codigos = list(items)
        puntaje = sum(v[0] for v in items.values())
        candidatos.append((len(codigos), puntaje, tabla, variable, codigos, [items[c][1] for c in codigos]))
    if not candidatos:
        return None
    candidatos.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    mejor = candidatos[0]
    if len(candidatos) > 1 and candidatos[1][0:2] == mejor[0:2]:
        return None
    _, _, tabla, variable, codigos, etiquetas = mejor
    return _filtro_categoria(tabla, variable, codigos, " / ".join(etiquetas), origen="or_categoria_generica")


def _aplicar_negacion(q, filtros):
    salida = []
    for f in filtros:
        negar = False
        var = f.get("variable")
        etiqueta = _norm(f.get("etiqueta") or "")
        if var == "sit_fuerza_trabajo":
            if "ocupad" in etiqueta and re.search(r"\b(?:no|excepto)\s+ocupad", q):
                negar = True
            if "desocupad" in etiqueta and re.search(r"\b(?:no|excepto)\s+desocupad", q):
                negar = True
        if var == "sexo" and etiqueta:
            if etiqueta.startswith("hombre") and re.search(r"\b(?:excepto|no)\s+hombres?\b", q):
                negar = True
            if etiqueta.startswith("mujer") and re.search(r"\b(?:excepto|no)\s+mujeres?\b", q):
                negar = True
        if var == "parentesco" and re.search(r"\b(?:no|excepto)\s+(?:sean?\s+)?jef(?:e|a|es|as)\s+de\s+hogar\b", q):
            negar = True
        if var == "p31_religion" and re.search(r"\b(?:no|excepto)\s+catolic[oa]s?\b", q):
            negar = True
        if "excepto" in q and etiqueta:
            despues = q.split("excepto", 1)[1]
            toks_et = {x for x in re.findall(r"[a-z0-9]+", etiqueta) if len(x) >= 4}
            toks_q = set(re.findall(r"[a-z0-9]+", despues))
            if toks_et and len(toks_et & toks_q) >= min(2, len(toks_et)):
                negar = True
        salida.append(_node_not(f) if negar else f)
    return salida


def _recode_edad(q):
    """Detecta una agrupación explícita de edad indicada por el usuario."""
    if not re.search(r"\b(?:edad|edades|grupos?\s+de\s+edad)\b", q):
        return None
    encontrados = []
    for m in re.finditer(r"\b(\d{1,3})\s*[-a]\s*(\d{1,3})\b", q):
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi < lo:
            continue
        encontrados.append({"minimo": lo, "maximo": hi, "etiqueta": f"{lo}-{hi}"})
    m_final = re.search(r"\b(\d{1,3})\s*(?:\+(?=\s|$)|anos?\s+o\s+mas\b)", q)
    if m_final:
        lo = int(m_final.group(1))
        encontrados.append({"minimo": lo, "maximo": None, "etiqueta": f"{lo}+"})
    if len(encontrados) < 3:
        return None
    # Evita grupos superpuestos, que producirían una dimensión no exclusiva.
    orden = sorted(encontrados, key=lambda x: x["minimo"])
    anterior = -1
    for g in orden:
        if g["minimo"] <= anterior:
            return None
        if g["maximo"] is not None:
            anterior = g["maximo"]
        else:
            anterior = 10**9
    return {
        "tabla": "personas", "variable": "edad", "tipo": "recode_rangos",
        "etiqueta": "Grupo de edad", "grupos": orden,
    }


def _selecciones_geograficas(q):
    """Extrae selección múltiple explícita de regiones/provincias/comunas."""
    salida = []
    for nivel, digitos in (("region", 2), ("provincia", 3), ("comuna", 5)):
        plural = {"region":"regiones", "provincia":"provincias", "comuna":"comunas"}[nivel]
        m = re.search(rf"\b{plural}\s+((?:\d{{1,{digitos}}}\s*(?:,|y)\s*)+\d{{1,{digitos}}})\b", q)
        if m:
            codigos = [int(x) for x in re.findall(r"\d+", m.group(1))]
            validos = {int(k) for k in VARIABLES["geografia"].get(nivel, {}) if str(k).isdigit()}
            codigos = [c for c in codigos if c in validos]
            if len(codigos) >= 2:
                salida.append({"nivel": nivel, "codigos": codigos})
                continue
        # También reconoce listas por nombre cuando el nivel plural aparece.
        if re.search(rf"\b{plural}\b", q):
            encontrados = []
            for codigo, nombre in VARIABLES["geografia"].get(nivel, {}).items():
                if not str(codigo).isdigit():
                    continue
                nombre_n = _norm(nombre)
                if len(nombre_n) >= 4 and re.search(r"\b" + re.escape(nombre_n) + r"\b", q):
                    encontrados.append(int(codigo))
            if len(encontrados) >= 2:
                salida.append({"nivel": nivel, "codigos": list(dict.fromkeys(encontrados))})
    return salida


def _etiqueta_subfiltro_persona(f):
    """Redacción breve para describir condiciones de residentes/miembros."""
    if not isinstance(f, dict):
        return ""
    variable = f.get("variable")
    if f.get("tipo") == "rango" and variable == "edad":
        minimo, maximo = f.get("minimo"), f.get("maximo")
        if minimo is not None and maximo is None:
            return (f"de {minimo:g} años o más" if f.get("incluir_minimo", True)
                    else f"mayor de {minimo:g} años")
        if maximo is not None and minimo is None:
            return (f"de {maximo:g} años o menos" if f.get("incluir_maximo", True)
                    else f"menor de {maximo:g} años")
        if minimo is not None and maximo is not None:
            return f"entre {minimo:g} y {maximo:g} años"
    if f.get("tipo") == "categoria":
        valores = [str(v) for v in (f.get("valores") or [])]
        etiqueta = f.get("etiqueta")
        if not etiqueta and f.get("tabla") in TABLAS_PARQUET and variable in VARIABLES[f["tabla"]]["variables"]:
            info = VARIABLES[f["tabla"]]["variables"][variable]
            etiqueta = " / ".join(str(info.get("categorias", {}).get(v, v)) for v in valores)
        etiqueta = str(etiqueta or "").strip()
        if variable == "sexo":
            if valores == ["1"]: return "hombre"
            if valores == ["2"]: return "mujer"
        p32 = {
            "p32a_dificultad_ver": "para ver aun usando anteojos o lentes",
            "p32b_dificultad_oir": "para oír aun usando audífono",
            "p32c_dificultad_mover": "para caminar o subir escaleras",
            "p32d_dificultad_cogni": "para recordar o concentrarse",
            "p32e_dificultad_cuidado": "para realizar tareas de cuidado personal",
            "p32f_dificultad_comunic": "para comunicarse",
        }
        if variable in p32:
            limpio = re.sub(r"^(?:sí|si)\s*,?\s*", "", _norm(etiqueta)).strip()
            return f"con {limpio} {p32[variable]}"
        if variable == "discapacidad":
            return "con discapacidad" if "1" in valores else "sin discapacidad"
        if etiqueta:
            return f"con {etiqueta.lower()}"
    return ""


def _etiqueta_residentes(subfiltros, explicita):
    """Redacta naturalmente las condiciones de los residentes.

    Sexo define el sustantivo base (mujer/hombre) y no se concatena como una
    categoría adicional. El resto de condiciones se añade sobre esa persona.
    """
    subfiltros = [f for f in (subfiltros or []) if isinstance(f, dict)]
    sexo = next((f for f in subfiltros if f.get("tipo") == "categoria" and f.get("variable") == "sexo"), None)
    if sexo and [str(v) for v in (sexo.get("valores") or [])] == ["2"]:
        determinante, unidad = "una", "mujer"
    elif sexo and [str(v) for v in (sexo.get("valores") or [])] == ["1"]:
        determinante, unidad = "un", "hombre"
    else:
        determinante, unidad = "una", "persona"

    restantes = [f for f in subfiltros if f is not sexo]
    partes = [_etiqueta_subfiltro_persona(f) for f in restantes]
    partes = [p for p in partes if p]
    if not partes:
        return f"donde habita al menos {determinante} {unidad}"

    frase = ""
    for p in partes:
        if not frase:
            frase = p
        elif p.startswith(("con ", "de ", "mayor ", "menor ", "entre ")):
            frase += " " + p
        else:
            frase += " y " + p
    return f"donde habita al menos {determinante} {unidad} {frase}"


def _filtro_jerarquico(q, explicita, filtros_base=None):
    """Agregación ascendente desde personas hacia hogar o vivienda.

    Si el usuario pide contar hogares/viviendas y describe características de
    sus miembros o residentes ("donde viven/habitan/residen personas..."),
    las condiciones personales se mueven a una subconsulta EXISTS y la entidad
    superior se mantiene como unidad de conteo.
    """
    filtros_base = [f for f in (filtros_base or []) if isinstance(f, dict)]
    if explicita not in {"hogares", "viviendas", "personas"}:
        return None

    # Regla general: entidad superior con condiciones de residentes/personas.
    # No exige la palabra "personas": expresiones naturales como
    # "viviendas donde habitan mujeres" o "hogares donde viven mayores de 65"
    # deben preservar vivienda/hogar como unidad contada. También admite
    # "viviendas con personas discapacitadas" cuando existe un filtro personal.
    filtros_persona = [
        deepcopy(f) for f in filtros_base
        if f.get("tabla") == "personas" and f.get("tipo") in {"categoria", "rango"}
    ]
    relacion_personas = bool(filtros_persona) and bool(re.search(
        r"\b(?:habita[n]?|vive[n]?|reside[n]?|donde\s+hay)\b"
        r"|\bcon\s+(?:al\s+menos\s+(?:una?|dos|tres|\d+)\s+)?"
        r"(?:personas?|mujeres?|hombres?|discapacitad[oa]s?|mayores?|menores?)\b",
        q,
    ))
    if explicita in {"hogares", "viviendas"} and relacion_personas:
        subfiltros = list(filtros_persona)
        # Quita duplicados sin depender de la función avanzada definida después.
        unicos, vistos = [], set()
        for f in subfiltros:
            if f.get("tipo") == "categoria":
                clave = ("categoria", f.get("variable"), tuple(f.get("valores") or []))
            else:
                clave = ("rango", f.get("variable"), f.get("minimo"), f.get("maximo"),
                         f.get("incluir_minimo"), f.get("incluir_maximo"))
            if clave not in vistos:
                vistos.add(clave); unicos.append(f)
        if unicos:
            # Orden natural: rangos de edad/escolaridad antes de categorías.
            unicos.sort(key=lambda f: (
                0 if f.get("tipo") == "rango" and f.get("variable") in {"edad", "escolaridad"} else 1,
                str(f.get("variable") or ""),
            ))
            return {
                "tipo": "existe_en_hogar", "tabla": "personas",
                "subfiltros": unicos,
                "etiqueta": _etiqueta_residentes(unicos, explicita),
                "origen": "jerarquia_entidad_superior",
            }

    # al menos una persona con discapacidad
    if explicita in {"hogares", "viviendas"} and re.search(
        r"\b(?:con|donde\s+hay)\s+(?:al\s+menos\s+)?(?:una\s+)?personas?\s+"
        r"(?:con\s+discapacidad|discapacitad[oa]s?)\b", q
    ):
        return {
            "tipo": "existe_en_hogar", "tabla": "personas", "variable": "discapacidad",
            "subfiltros": [_filtro_categoria("personas", "discapacidad", ["1"], "Con discapacidad")],
            "etiqueta": "con al menos una persona con discapacidad", "origen": "jerarquia",
        }
    # hogares/viviendas con N o más menores de X años
    m = re.search(r"\b(?:hogares?|viviendas?)\s+con\s+(\d+)\s+o\s+mas\s+(?:personas?\s+)?menores?\s+(?:de|a)\s+(\d{1,3})", q)
    if m and explicita in {"hogares", "viviendas"}:
        n, edad = int(m.group(1)), int(m.group(2))
        return {
            "tipo": "conteo_relacionado", "relacion": "miembros_entidad",
            "tabla": "personas", "min_conteo": n,
            "subfiltros": [_rango("personas", "edad", maximo=edad, incluir_maximo=False)],
            "etiqueta": f"con {n} o más personas menores de {edad} años", "origen": "jerarquia",
        }
    # hogares/viviendas donde todas las personas son >= X: no debe existir miembro < X.
    m = re.search(r"\b(?:hogares?|viviendas?)\s+(?:donde|en\s+que)\s+todas?\s+las\s+personas\s+(?:son\s+)?(?:de\s+)?(\d{1,3})\s+anos?\s+o\s+mas", q)
    if m and explicita in {"hogares", "viviendas"}:
        edad = int(m.group(1))
        return {
            "tipo": "no_existe_en_hogar", "tabla": "personas", "variable": "edad",
            "subfiltros": [_rango("personas", "edad", maximo=edad, incluir_maximo=False)],
            "etiqueta": f"donde todas las personas tienen {edad} años o más", "origen": "jerarquia",
        }
    return None


def _universo_para_plan(dimensiones, medida, filtros):
    vars_usadas = set()
    for d in dimensiones:
        if d.get("tipo") != "recode_rangos":
            vars_usadas.add((d["tabla"], d["variable"]))
    if medida and medida.get("variable"):
        vars_usadas.add((medida["tabla"], medida["variable"]))
    for f in filtros:
        if isinstance(f, dict) and f.get("tabla") and f.get("variable") and f.get("tipo") not in {"existe_en_hogar", "no_existe_en_hogar", "conteo_relacionado"}:
            vars_usadas.add((f["tabla"], f["variable"]))
    condiciones = []
    for tabla, variable in sorted(vars_usadas):
        condiciones.extend(condiciones_universo(tabla, variable))
    return _node_and(condiciones)


def _dedup_advanced(filtros):
    salida = []
    vistos = set()
    for f in filtros:
        if not isinstance(f, dict):
            continue
        tipo = f.get("tipo") or f.get("op")
        if tipo == "categoria":
            clave = (tipo, f.get("tabla"), f.get("variable"), tuple(f.get("valores") or []), f.get("modo", "in"))
        elif tipo == "rango":
            clave = (tipo, f.get("tabla"), f.get("variable"), f.get("minimo"), f.get("maximo"), f.get("incluir_minimo"), f.get("incluir_maximo"))
        elif tipo in {"existe_en_hogar", "no_existe_en_hogar", "conteo_relacionado"}:
            subs = tuple(
                (x.get("tipo"), x.get("tabla"), x.get("variable"), x.get("minimo"), x.get("maximo"), tuple(x.get("valores") or []))
                for x in (f.get("subfiltros") or [])
            )
            clave = (tipo, f.get("relacion"), f.get("min_conteo"), f.get("max_conteo"), subs)
        else:
            clave = (tipo, repr(sorted(f.items(), key=lambda x: x[0])))
        if clave not in vistos:
            vistos.add(clave); salida.append(f)
    return salida


def _dimension_items(q, detectadas, filtros):
    filtradas = set()
    for f in filtros:
        if not isinstance(f, dict):
            continue
        if f.get("tabla") and f.get("variable") and f.get("tipo") in {"categoria", "rango"}:
            filtradas.add((f["tabla"], f["variable"]))
        # Los filtros jerárquicos (EXISTS/NOT EXISTS/COUNT relacionado) pueden
        # contener variables personales que son condición y no dimensión de
        # salida. Marcarlas aquí evita que, por ejemplo, "hogares con al menos
        # una persona con discapacidad" termine mostrando discapacidad como
        # dimensión además de usarla como filtro de miembros del hogar.
        for sub in (f.get("subfiltros") or []):
            if isinstance(sub, dict) and sub.get("tabla") and sub.get("variable"):
                filtradas.add((sub["tabla"], sub["variable"]))
    dims = []
    recode = _recode_edad(q)
    if recode:
        dims.append(recode)
        filtradas.add(("personas", "edad"))
    for clave, item in sorted(detectadas.items(), key=lambda kv: -kv[1]["puntaje"]):
        tabla, variable = clave
        if variable in {"region", "provincia", "comuna"} or clave in filtradas:
            continue
        if variable in {"edad", "escolaridad"} or (recode and variable == "edad_quinquenal"):
            # Solo como dimensión si hay recodificación explícita o la variable
            # es edad_quinquenal; una variable continua cruda no se grafica como
            # cientos de categorías.
            continue
        if not _es_dimension(q, tabla, variable, False):
            continue
        validas = [str(v) for v in categorias_validas(tabla, variable)]
        subconjunto = _subconjunto_categorias_mencionado(q, tabla, variable)
        if subconjunto:
            validas = subconjunto
        if len(validas) >= 2:
            dims.append({
                "tabla": tabla, "variable": variable, "tipo": "categoria",
                "categorias_validas": validas, "etiqueta": _etiqueta_dimension(tabla, variable),
            })
    # Mantener orden y unicidad, sin truncar silenciosamente. El motor avanzado
    # soporta tres dimensiones; si hay más, se informa explícitamente.
    unicos = []
    vistos = set()
    for d in dims:
        clave = (d.get("tabla"), d.get("variable"), d.get("tipo"))
        if clave not in vistos:
            vistos.add(clave); unicos.append(d)
    return unicos


def _hojas_filtro(nodo):
    if not isinstance(nodo, dict):
        return []
    if nodo.get("op") in {"and", "or"}:
        salida = []
        for x in nodo.get("args") or []:
            salida.extend(_hojas_filtro(x))
        return salida
    if nodo.get("op") == "not":
        return _hojas_filtro(nodo.get("arg"))
    return [nodo]


def _entidad_objetivo_avanzada(detectadas, filtros, explicita=None):
    tablas = {tabla for tabla, _ in detectadas}
    for f in filtros:
        for hoja in _hojas_filtro(f):
            tabla = hoja.get("tabla")
            if tabla in JERARQUIA and hoja.get("tipo") not in {"existe_en_hogar", "no_existe_en_hogar", "conteo_relacionado"}:
                tablas.add(tabla)
    if explicita:
        tablas.add(explicita)
    return max(tablas, key=lambda t: JERARQUIA[t]) if tablas else None


def _advanced_trigger(q, dimensiones, medida, filtros, geo_sel, categoria_or=None):
    if medida:
        return True
    if _porcentaje_solicitado(q) and (len(dimensiones) >= 1 or len([f for f in filtros if isinstance(f, dict)]) >= 2):
        # Los porcentajes con varias condiciones deben pasar por QueryPlan v2
        # para separar numerador y denominador. Una sola categoría simple
        # conserva la ruta histórica, que ya tiene un universo inequívoco.
        return True
    if len(dimensiones) >= 3:
        return True
    if re.search(r"\b(?:excepto|no\s+sean?|distint[oa]s?\s+de)\b", q):
        return True
    if any(isinstance(f, dict) and f.get("op") == "not" for f in filtros):
        return True
    if _rangos_or_edad(q) or _filtro_laboral_or(q) or categoria_or:
        return True
    if any(
        f.get("tipo") in {"existe_en_hogar", "conteo_relacionado", "no_existe_en_hogar"}
        or f.get("origen") == "maternidad"
        for f in filtros if isinstance(f, dict)
    ):
        return True
    if _recode_edad(q):
        return True
    if geo_sel:
        return True
    return False


def resolver_consulta_avanzada(consulta, seleccion_operacion=None, union_seleccion=None,
                              tabla_seleccionada=None, variable_seleccionada=None):
    q = _norm(consulta)
    if not q.strip() or union_seleccion:
        return None
    # Las preguntas oficiales/literales numeradas ya tienen una ruta de alta
    # precisión. Palabras internas como «o», «hijo» o «construcción» no deben
    # convertirlas en consultas avanzadas.
    if re.match(r"^\s*\d+(?:\.\d+)?[a-z]?\b", q):
        return None
    # El comparador de seis dimensiones P32 es una semántica multi-medida no
    # excluyente ya resuelta por disability_resolver; no se modela como cruce
    # categórico convencional.
    if re.search(r"\btipo\s+de\s+discapacidad\b|\bdimensiones?\s+(?:de\s+)?dificultad\b", q):
        return None
    # Las consultas educativas simples deben conservar la prioridad del
    # education_resolver. El motor avanzado entra solo si existe otra dimensión
    # estadística explícita o una condición de otra entidad.
    if re.search(r"\beducacion\s+(?:parvularia|preescolar|basica|media|superior)\b", q):
        cruza_educacion = bool(re.search(
            r"\b(?:segun\s+sexo|por\s+sexo|edad\s+quinquenal|tipologia\s+de\s+hogar|internet|tenencia|tipo\s+de\s+vivienda)\b", q
        ))
        if not cruza_educacion:
            return None

    detectadas = _detectar_variables(q)
    filtros = _filtros_manual(q)
    filtros.extend(_filtros_co_residencia(q))
    filtros.extend(_filtro_especial_resolver(consulta))

    territorio_filtro = _filtro_territorio_especifico(
        q, tabla_seleccionada=tabla_seleccionada,
        variable_seleccionada=variable_seleccionada,
    )
    if territorio_filtro:
        filtros.append(territorio_filtro)
        tv = territorio_filtro["variable"]
        _agregar_variable(detectadas, "personas", tv, 130, "territorio_especifico_avanzado")
        # La variable general no debe reaparecer como dimensión cuando el país
        # específico ya fue fijado como categoría.
        if tv == "p27_nacionalidad_esp":
            detectadas.pop(("personas", "p27_nacionalidad"), None)
            detectadas.pop(("personas", "p27_nacionalidad_rec"), None)
        elif tv == "p25_lug_nacimiento_esp":
            detectadas.pop(("personas", "p25_lug_nacimiento"), None)
            detectadas.pop(("personas", "p25_lug_nacimiento_rec"), None)

    maternidad = _filtro_maternidad(q)
    if maternidad:
        filtros.append(maternidad)
        _agregar_variable(detectadas, "personas", "p46a_tot_hijs_nac", 125, "maternidad")
    if re.search(r"\b(?:no|excepto)\s+(?:sean?\s+)?jef(?:e|a|es|as)\s+de\s+hogar\b", q):
        filtros.append(_filtro_categoria("personas", "parentesco", ["1"], "Jefe/a de hogar", origen="negacion_manual"))
    if re.search(r"\b(?:no|excepto)\s+catolic[oa]s?\b", q):
        filtros.append(_filtro_categoria("personas", "p31_religion", ["1"], "Católica", origen="negacion_manual"))

    numericos, conceptos_num = _filtros_numericos(q)
    # En expresiones de co-residencia ("vive con personas mayores de X")
    # el rango de edad pertenece a la persona relacionada, no a la persona
    # objetivo. La ruta histórica ya aplicaba esta distinción; se replica aquí
    # para evitar convertir EXISTS(edad>X) en edad>X AND EXISTS(edad>X).
    if any(f.get("tipo") == "existe_en_hogar" and f.get("origen") == "co_residencia"
           for f in filtros if isinstance(f, dict)):
        numericos = [f for f in numericos if not (
            f.get("tabla") == "personas" and f.get("variable") == "edad"
        )]
        conceptos_num = [c for c in conceptos_num if c != ("personas", "edad")]
    filtros.extend(numericos)
    for tabla, variable in conceptos_num:
        _agregar_variable(detectadas, tabla, variable, 100, "rango")
    for f in filtros:
        if isinstance(f, dict) and f.get("tabla") and f.get("variable"):
            _agregar_variable(detectadas, f["tabla"], f["variable"], 100, f.get("origen", "filtro"))

    # Categorías literales verificadas contra el diccionario.
    if detectadas:
        genericos = []
        _aplicar_categorias_genericas(q, detectadas, genericos)
        # En "mujeres con hijos" la palabra hijos describe maternidad (P46a),
        # no el parentesco de la propia mujer con la jefatura del hogar.
        if maternidad:
            genericos = [f for f in genericos if not (
                f.get("tabla") == "personas" and f.get("variable") == "parentesco"
                and "5" in [str(v) for v in (f.get("valores") or [])]
            )]
        filtros.extend(genericos)
        for f in genericos:
            _agregar_variable(detectadas, f["tabla"], f["variable"], 90, "categoria_generica")

    # Casos OR que el planificador histórico representa como un único filtro o
    # no puede representar con precedencia.
    edad_or = _rangos_or_edad(q)
    laboral_or = _filtro_laboral_or(q)
    categoria_or = None if (laboral_or or _or_pertenece_a_descripcion_variable(q, detectadas)) else _filtro_categoria_or_generico(q, detectadas)
    if edad_or:
        # Quita rangos de edad simples para no convertir OR en AND.
        filtros = [f for f in filtros if not (isinstance(f, dict) and f.get("tabla") == "personas" and f.get("variable") == "edad" and f.get("tipo") == "rango")]
        _agregar_variable(detectadas, "personas", "edad", 100, "or_edad")
    if laboral_or:
        filtros = [f for f in filtros if not (isinstance(f, dict) and f.get("tabla") == "personas" and f.get("variable") == "sit_fuerza_trabajo")]
        filtros.append(laboral_or)
        _agregar_variable(detectadas, "personas", "sit_fuerza_trabajo", 100, "or_categoria")
    if categoria_or:
        clave_or = (categoria_or.get("tabla"), categoria_or.get("variable"))
        filtros = [f for f in filtros if not (
            isinstance(f, dict) and f.get("tipo") == "categoria" and (
                (f.get("tabla"), f.get("variable")) == clave_or
                or f.get("origen") == "categoria_generica"
            )
        )]
        filtros.append(categoria_or)
        _agregar_variable(detectadas, clave_or[0], clave_or[1], 100, "or_categoria_generica")

    explicita = _entidad_objetivo_explicita(q)
    jerarquico = _filtro_jerarquico(q, explicita, filtros)
    if jerarquico:
        # El rango/categoría de los miembros pertenece a la subconsulta
        # jerárquica y no debe restringir directamente la entidad objetivo.
        vars_sub = {(sf.get("tabla"), sf.get("variable")) for sf in (jerarquico.get("subfiltros") or [])}
        filtros = [f for f in filtros if not (
            isinstance(f, dict) and (f.get("tabla"), f.get("variable")) in vars_sub
            and f.get("tipo") in {"rango", "categoria"}
        )]
        filtros.append(jerarquico)
        if jerarquico.get("variable"):
            _agregar_variable(detectadas, jerarquico["tabla"], jerarquico["variable"], 100, "jerarquia")

    filtros = _dedup_advanced(filtros)
    filtros = _aplicar_negacion(q, filtros)
    dimensiones = _dimension_items(q, detectadas, filtros)
    if len(dimensiones) > 3:
        raise ValueError(
            "La consulta contiene más de tres dimensiones estadísticas. El motor avanzado "
            "puede calcular hasta tres en una sola salida; convierte las dimensiones adicionales en filtros."
        )

    medida = _medida_numerica(q)
    porcentaje = _porcentaje_solicitado(q)
    geo_sel = _selecciones_geograficas(q)

    activa_avanzado = _advanced_trigger(
        q, dimensiones, medida, filtros, geo_sel, categoria_or=categoria_or
    )
    # Un país específico por sí solo conserva la ruta histórica de alta
    # precisión. El motor avanzado entra cuando debe combinarse con otro filtro
    # (edad, sexo, etc.) o cuando la interfaz acaba de resolver un demónimo
    # ambiguo y debe respetar esa selección sin reabrir el diálogo.
    filtros_estadisticos = [f for f in filtros if isinstance(f, dict)]
    if territorio_filtro and (
        variable_seleccionada in {"p25_lug_nacimiento_esp", "p27_nacionalidad_esp",
                                  "p24_lug_resid5_esp", "p44_lug_trab_esp"}
        or len(filtros_estadisticos) >= 2
    ):
        activa_avanzado = True
    if not activa_avanzado:
        return None

    # Entidad objetivo: para medidas numéricas no forzamos automáticamente la
    # entidad de la medida si el usuario pidió contar/agrupar una entidad más
    # granular. Para AVG/SUM/etc sí debe existir la tabla de la variable medida.
    if jerarquico and explicita:
        # En agregaciones ascendentes la entidad solicitada (hogar/vivienda) es
        # la unidad contada; los miembros aparecen solo dentro de EXISTS/COUNT.
        objetivo = explicita
    else:
        objetivo = _entidad_objetivo_avanzada(detectadas, [f for f in filtros if isinstance(f, dict)], explicita)
    if objetivo is None:
        objetivo = medida["tabla"] if medida else explicita or "personas"

    if medida and medida.get("tabla") != objetivo:
        tabla_medida = medida.get("tabla")
        op_medida = medida.get("operacion")
        # Una medida de una entidad superior se repetiría al expandirla hacia
        # personas/hogares. SUM es siempre inválida en ese escenario; AVG puede
        # representar una media ponderada por la entidad inferior, pero solo se
        # acepta cuando la propia frase explicita esa unidad.
        if JERARQUIA.get(tabla_medida, 0) < JERARQUIA.get(objetivo, 0):
            explicita_ponderacion = bool(re.search(r"\b(?:por\s+persona|entre\s+personas|ponderad[oa]\s+por\s+personas?)\b", q))
            if op_medida == "suma":
                raise ValueError(
                    "No se puede sumar una variable de una entidad superior después de expandirla "
                    "a una entidad inferior, porque se duplicaría el valor por cada miembro. "
                    "Indica una medida de la entidad contada o agrega primero en su entidad original."
                )
            if op_medida == "promedio" and not explicita_ponderacion:
                raise ValueError(
                    "El promedio solicitado mezcla una medida de una entidad superior con una "
                    "entidad inferior. Indica si deseas un promedio por vivienda/hogar o un "
                    "promedio ponderado por personas."
                )

    filtros_ast_items = []
    if edad_or:
        filtros_ast_items.append(edad_or)
    for f in filtros:
        filtros_ast_items.append(f)
    filtro_ast = _node_and(filtros_ast_items)

    if medida:
        medida_plan = {
            "operacion": medida["operacion"], "tabla": medida["tabla"],
            "variable": medida["variable"], "entidad": objetivo,
        }
        operacion = medida["operacion"]
    else:
        medida_plan = {"operacion": "conteo_distinto", "entidad": objetivo}
        operacion = "porcentaje" if porcentaje else "conteo"

    porcentaje_plan = None
    if porcentaje:
        base = _base_porcentaje(q, dimensiones, seleccion_operacion)
        if base is None:
            ancla = dimensiones[0] if dimensiones else {"tabla": objetivo, "variable": next(iter(VARIABLES[objetivo]["variables"]))}
            raise AmbiguedadOperacion(
                "El cruce porcentual necesita definir el denominador. Selecciona cómo calcular los porcentajes.",
                ancla["tabla"], ancla["variable"],
                [
                    {"id": "__pct_total", "titulo": "Porcentaje sobre el total", "descripcion": "Cada celda se divide por el total válido del territorio."},
                    {"id": "__pct_fila", "titulo": "Porcentaje dentro de la primera variable", "descripcion": "Cada categoría de la primera dimensión suma 100% a través de las restantes."},
                    {"id": "__pct_columna", "titulo": "Porcentaje dentro de la segunda variable", "descripcion": "Cada categoría de la segunda dimensión suma 100% a través de las restantes."},
                ],
            )
        porcentaje_plan = {"base": base, "factor": 100.0}

    universo_ast = _universo_para_plan(dimensiones, medida, filtros)
    plan = {
        "version": 2,
        "entidad_objetivo": objetivo,
        "dimensiones": deepcopy(dimensiones),
        "filtros": deepcopy([f for f in filtros if isinstance(f, dict) and not f.get("op")]),
        "filtro_ast": filtro_ast,
        "universo_ast": universo_ast,
        "medida": medida_plan,
        "porcentaje": porcentaje_plan,
        "selecciones_geograficas": geo_sel,
        "motor": "avanzado_v2",
    }

    # Ancla histórica para mantener compatibilidad con main/excel/validaciones.
    if dimensiones:
        ancla = dimensiones[0]
    elif medida:
        ancla = medida
    elif edad_or:
        ancla = {"tabla": "personas", "variable": "edad"}
    else:
        filtro_ancla = next((f for f in filtros if isinstance(f, dict) and f.get("tabla") and f.get("variable")), None)
        if not filtro_ancla:
            # Un filtro jerárquico puede no tener variable propia; usa edad si
            # sus subfiltros la contienen o una llave de la entidad objetivo.
            sub = next((sf for f in filtros for sf in (f.get("subfiltros") or []) if sf.get("tabla") and sf.get("variable")), None)
            if sub:
                ancla = sub
            else:
                ancla = {"tabla": objetivo, "variable": "id_hogar" if objetivo == "hogares" else "id_vivienda"}
        else:
            ancla = filtro_ancla

    return {
        "tabla": ancla["tabla"], "variable": ancla["variable"],
        "categoria_valor": None, "operacion": operacion,
        "tipo_consulta": "cruce", "plan_cruce": plan,
        "indicador_descripcion": "Consulta avanzada estructurada",
        "_origen_interpretacion": "planificador_avanzado_v2",
    }
