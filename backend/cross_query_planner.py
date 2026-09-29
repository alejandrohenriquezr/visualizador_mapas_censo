# -*- coding: utf-8 -*-
"""Planificador determinista de cruces entre personas, hogares y viviendas.

Convierte preguntas multivariadas en un plan declarativo. El módulo NO genera
SQL y no permite identificadores libres: todas las tablas, variables y
categorías se validan contra ``dictionary.py``.
"""
from __future__ import annotations

import re
from copy import deepcopy

from dictionary import VARIABLES, TABLAS_PARQUET, _norm, categorias_validas, detectar_operacion
from categorical_resolver import _candidatos_variable, _coincidencias_categoria
from disability_resolver import resolver_discapacidad
from education_resolver import resolver_educacion


JERARQUIA = {"viviendas": 0, "hogares": 1, "personas": 2}

# Alias que complementan las descripciones formales del diccionario. No
# sustituyen al catálogo: solo ayudan a detectar una variable dentro de una
# pregunta que menciona más de un concepto.
_ALIAS_VARIABLES = (
    ("personas", "sexo", (r"\bsexo\b",)),
    ("personas", "edad", (r"\bedad\b", r"\b\d{1,3}\s+anos?\b", r"\bpersonas?\s+mayores\b", r"\badultos?\s+mayores\b")),
    ("personas", "edad_quinquenal", (r"\bedad\s+quinquenal\b", r"\bgrupos?\s+quinquenales?\s+de\s+edad\b")),
    ("personas", "escolaridad", (r"\bescolaridad\b", r"\banos?\s+de\s+estudio\b")),
    ("personas", "discapacidad", (r"\bdiscapacidad\b", r"\bdiscapacitad[oa]s?\b")),
    ("personas", "sit_fuerza_trabajo", (
        r"\bsituacion\s+(?:en\s+la\s+)?fuerza\s+de\s+trabajo\b",
        r"\bfuerza\s+de\s+trabajo\b", r"\bocupad[oa]s?\b",
        r"\bdesocupad[oa]s?\b", r"\bfuera\s+de\s+la\s+fuerza\s+de\s+trabajo\b",
    )),
    ("personas", "parentesco", (r"\bparentesco\b", r"\bjef[ea]\s+de\s+hogar\b")),
    ("personas", "p23_est_civil", (r"\bestado\s+(?:civil|conyugal)\b",)),
    ("personas", "p27_nacionalidad", (r"\bnacionalidad\b",)),
    ("personas", "p28_autoid_pueblo", (r"\bpertenece[n]?\s+(?:a\s+)?(?:un\s+)?pueblo\s+(?:indigena|originario)\b",)),
    ("personas", "p28_pueblo_pert", (r"\b(?:segun|por)\s+pueblo\s+(?:indigena|originario)\b", r"\bcual\s+pueblo\s+(?:indigena|originario)\b")),
    ("personas", "p29_afrodescendencia_rec", (r"\bafrodescendencia\b", r"\bafrodescendientes?\b")),
    ("personas", "p30_lengua_indigena_rec", (r"\bhabla[n]?\s+(?:o\s+entiende[n]?\s+)?(?:alguna\s+)?lengua\s+(?:indigena|originaria)\b",)),
    ("personas", "p31_religion", (r"\breligion\b", r"\bcredo\b")),
    ("personas", "p37_alfabet", (r"\balfabet(?:izacion|izado|izada|izados|izadas)\b", r"\bsabe[n]?\s+leer\s+y\s+escribir\b")),
    ("personas", "p40_cise_rec", (r"\bcategoria\s+ocupacional\b", r"\btrabajador(?:a)?\s+(?:independiente|dependiente)\b")),
    ("personas", "p45_medio_transporte", (r"\bmedio\s+de\s+transporte\b", r"\btransporte\s+principal\b")),
    ("personas", "tipo_operativo", (r"\bviviendas?\s+particulares?\b", r"\ben\s+vivienda\s+particular\b")),
    ("hogares", "tipologia_hogar", (
        r"\btipologia\s+de\s+hogar\b", r"\btipo\s+de\s+hogar\b",
        r"\bhogares?\s+unipersonales?\b", r"\bvive[n]?\s+sol[oa]s?\b",
        r"\bcomposicion\s+(?:del|de\s+los?)\s+hogar",
    )),
    ("hogares", "p12_tenencia_viv", (
        r"\btenencia\b", r"\barrendad[oa]s?\b", r"\barriend[oa]\b",
        r"\bpropia?s?\b", r"\bhipoteca\b",
    )),
    ("hogares", "p15d_serv_internet_fija", (r"\binternet\s+fija\b", r"\binternet\s+de\s+casa\b")),
    ("hogares", "p15e_serv_internet_movil", (r"\binternet\s+movil\b", r"\bdatos\s+moviles\b")),
    ("hogares", "p15f_serv_internet_satelital", (r"\binternet\s+satelital\b", r"\bstarlink\b")),
    ("viviendas", "p2_tipo_vivienda", (
        r"\btipo\s+de\s+vivienda\b", r"\bcasas?\b", r"\bdepartamentos?\b", r"\bdepas?\b",
    )),
    ("viviendas", "p3a_estado_ocupacion", (r"\bestado\s+de\s+ocupacion\s+de\s+la\s+vivienda\b",)),
    ("viviendas", "p6_fuente_agua", (r"\bfuente\s+de\s+agua\b", r"\bagua\s+proviene\b")),
    ("viviendas", "p8_serv_hig", (r"\bservicio\s+higienico\b", r"\bwc\b")),
    ("viviendas", "p9_fuente_elect", (r"\bfuente\s+de\s+electricidad\b", r"\belectricidad\b")),
    ("viviendas", "p10_basura", (r"\beliminacion\s+de\s+basura\b", r"\bbasura\b")),
    ("viviendas", "indice_hacinamiento", (r"\bhacinamiento\b",)),
)


def _variable_valida(tabla, variable):
    return tabla in TABLAS_PARQUET and variable in VARIABLES[tabla]["variables"]


def _agregar_variable(destino, tabla, variable, puntaje=0, origen="catalogo"):
    if not _variable_valida(tabla, variable):
        return
    clave = (tabla, variable)
    previo = destino.get(clave)
    if previo is None or puntaje > previo["puntaje"]:
        destino[clave] = {
            "tabla": tabla, "variable": variable,
            "puntaje": puntaje, "origen": origen,
        }


def _entidad_objetivo_explicita(q):
    """Solo considera explícita una entidad cuando actúa como sujeto/medida.

    Evita tomar ``viviendas`` de «ocupados que viven en viviendas arrendadas»
    como unidad de conteo: allí el sujeto implícito son personas.
    """
    patrones = (
        r"^\s*(?:cantidad|numero|total|distribucion|porcentaje)?\s*(?:de\s+)?(?P<e>personas|hogares|viviendas)\b",
        r"\b(?:cantidad|numero|total|distribucion|porcentaje)\s+de\s+(?P<e>personas|hogares|viviendas)\b",
    )
    for patron in patrones:
        m = re.search(patron, q)
        if m:
            return m.group("e")
    return None


def _filtros_numericos(q):
    """Extrae rangos numéricos frecuentes sin convertirlos en dimensiones.

    Distingue estrictamente ``mayores de 65`` (>65) de ``65 o más`` (>=65),
    y lo mismo para límites superiores.
    """
    filtros = []
    conceptos = []

    def agregar(variable, minimo=None, maximo=None, incluir_minimo=True,
                incluir_maximo=True, dominio_minimo=0):
        filtros.append({
            "tabla": "personas", "variable": variable, "tipo": "rango",
            "minimo": minimo, "maximo": maximo,
            "incluir_minimo": incluir_minimo,
            "incluir_maximo": incluir_maximo,
            "dominio_minimo": dominio_minimo, "origen": "rango",
        })
        conceptos.append(("personas", variable))

    # Edad: primero el rango explícito; después comparadores unilaterales.
    m = re.search(r"\bentre\s+(\d{1,3})\s+y\s+(\d{1,3})\s+anos?\b", q)
    if m:
        agregar("edad", int(m.group(1)), int(m.group(2)))
    else:
        patrones_min = (
            (r"\b(\d{1,3})\s+anos?\s+o\s+mas\b", True),
            (r"\bal\s+menos\s+(\d{1,3})\s+anos?\b", True),
            (r"\bmayores?\s+(?:de|a)\s+(\d{1,3})\s+anos?\b", False),
            (r"\bmas\s+de\s+(\d{1,3})\s+anos?\b", False),
        )
        encontrado = False
        for patron, inclusivo in patrones_min:
            m = re.search(patron, q)
            if m:
                agregar("edad", minimo=int(m.group(1)), incluir_minimo=inclusivo)
                encontrado = True
                break
        if not encontrado:
            patrones_max = (
                (r"\b(\d{1,3})\s+anos?\s+o\s+menos\b", True),
                (r"\bhasta\s+(\d{1,3})\s+anos?\b", True),
                (r"\bmenores?\s+(?:de|a)\s+(\d{1,3})\s+anos?\b", False),
                (r"\bmenos\s+de\s+(\d{1,3})\s+anos?\b", False),
            )
            for patron, inclusivo in patrones_max:
                m = re.search(patron, q)
                if m:
                    agregar("edad", maximo=int(m.group(1)), incluir_maximo=inclusivo)
                    break

    # En las consultas descriptivas del visor, «personas/adultos mayores»
    # se interpreta como 60 años o más cuando no se escribió otro umbral.
    if not filtros and re.search(r"\b(?:personas?|adultos?)\s+mayores\b", q):
        agregar("edad", minimo=60, incluir_minimo=True)

    # Escolaridad conserva las formulaciones ya soportadas.
    m = re.search(r"\b(\d{1,2})\s+o\s+menos\s+anos?\s+de\s+escolaridad\b", q)
    if m:
        agregar("escolaridad", maximo=int(m.group(1)))
    m = re.search(r"\b(\d{1,2})\s+o\s+mas\s+anos?\s+de\s+escolaridad\b", q)
    if m:
        agregar("escolaridad", minimo=int(m.group(1)))
    return filtros, conceptos

def _filtros_manual(q):
    """Filtros de alto valor semántico que un matcher literal no capta bien."""
    filtros = []

    def cat(tabla, variable, valores, etiqueta=None):
        filtros.append({"tabla": tabla, "variable": variable, "tipo": "categoria",
                        "valores": [str(v) for v in valores], "etiqueta": etiqueta,
                        "origen": "manual"})

    if re.search(r"\b(?:sin\s+discapacidad|no\s+discapacitad[oa]s?)\b", q):
        cat("personas", "discapacidad", ["2"], "Sin discapacidad")
    elif (
        re.search(r"\bcon\s+discapacidad\b|\bdiscapacitad[oa]s?\b", q)
        and not re.search(r"\bsin\s+personas?\s+discapacitad[oa]s?\b", q)
    ):
        cat("personas", "discapacidad", ["1"], "Con discapacidad")

    # «Ocupada de hecho» es una categoría de tenencia de la vivienda, no
    # una condición laboral de la persona. Evita ese falso positivo.
    ocupacion_vivienda = bool(re.search(r"\bocupad[oa]s?\s+de\s+hecho\b", q))
    if re.search(r"\bocupad[oa]s?\b", q) and not ocupacion_vivienda:
        cat("personas", "sit_fuerza_trabajo", ["1"], "Ocupado")
    elif re.search(r"\bdesocupad[oa]s?\b", q):
        cat("personas", "sit_fuerza_trabajo", ["2"], "Desocupado")
    elif re.search(r"\bfuera\s+de\s+la\s+fuerza\s+de\s+trabajo\b", q):
        cat("personas", "sit_fuerza_trabajo", ["3"], "Fuera de la fuerza de trabajo")

    if re.search(r"\bvive[n]?\s+sol[oa]s?\b|\bhogares?\s+unipersonales?\b", q):
        cat("hogares", "tipologia_hogar", ["1"], "Unipersonal")

    # Tenencia: cuando se nombran categorías específicas se conserva
    # exactamente su unión, sin añadir «arrendada con contrato».
    tenencia_especifica = []
    if re.search(r"\barrendad[oa]s?\s+sin\s+contrato\b", q):
        tenencia_especifica.append("4")
    if re.search(r"\bocupad[oa]s?\s+de\s+hecho\b", q):
        tenencia_especifica.append("8")
    if re.search(r"\bsucesion\s+o\s+litigio\b", q):
        tenencia_especifica.append("9")
    if tenencia_especifica:
        etiquetas = {"4":"Arrendada sin contrato", "8":"Ocupada de hecho", "9":"Propiedad en sucesión o litigio"}
        vals = list(dict.fromkeys(tenencia_especifica))
        cat("hogares", "p12_tenencia_viv", vals, " / ".join(etiquetas[v] for v in vals))
    elif re.search(r"\barrendad[oa]s?\b|\ben\s+arriendo\b", q):
        cat("hogares", "p12_tenencia_viv", ["3", "4"], "Arrendada (con o sin contrato)")
    elif re.search(r"\bvivienda\s+propia\b|\bcasas?\s+propias?\b", q):
        cat("hogares", "p12_tenencia_viv", ["1", "2"], "Propia (pagada o pagándose)")

    # «Sin acceso a internet en el hogar» significa que el hogar declaró No
    # en las tres modalidades censales de acceso disponibles.
    if re.search(r"\bsin\s+(?:acceso\s+a\s+)?internet(?:\s+en\s+el\s+hogar)?\b", q):
        cat("hogares", "p15d_serv_internet_fija", ["2"], "Sin internet fija")
        cat("hogares", "p15e_serv_internet_movil", ["2"], "Sin internet móvil")
        cat("hogares", "p15f_serv_internet_satelital", ["2"], "Sin internet satelital")

    for variable, patron in (
        ("p15d_serv_internet_fija", r"\binternet\s+fija\b|\binternet\s+de\s+casa\b"),
        ("p15e_serv_internet_movil", r"\binternet\s+movil\b|\bdatos\s+moviles\b"),
        ("p15f_serv_internet_satelital", r"\binternet\s+satelital\b|\bstarlink\b"),
    ):
        if re.search(patron, q):
            valor = "2" if re.search(r"\bsin\s+(?:internet|starlink)\b", q) else "1"
            cat("hogares", variable, [valor])

    if re.search(r"\bjef[ea]\s+de\s+hogar\b", q):
        cat("personas", "parentesco", ["1"], "Jefe/a de hogar")
    elif re.search(r"\bservicio\s+domestico\b", q):
        cat("personas", "parentesco", ["16"], "Servicio doméstico puertas adentro")
    elif re.search(r"\bniet[oa]s?\b", q):
        cat("personas", "parentesco", ["12"], "Nieto/a")

    if re.search(r"\bconviviente(?:\s+civil)?\s+(?:con|por)\s+acuerdo\s+de\s+union\s+civil\b", q):
        cat("personas", "p23_est_civil", ["3"], "Conviviente civil (con acuerdo de unión civil)")
    elif re.search(r"\bconviviente(?:\s+o\s+pareja)?\s+sin\s+acuerdo\s+de\s+union\s+civil\b", q):
        cat("personas", "p23_est_civil", ["2"], "Conviviente o pareja sin acuerdo de unión civil")

    if re.search(r"\bhombres?\b", q):
        cat("personas", "sexo", ["1"], "Hombre")
    elif re.search(r"\bmujeres?\b", q):
        cat("personas", "sexo", ["2"], "Mujer")

    if re.search(r"\bcasas?\b", q) and not re.search(r"\bcasas?\s+propias?\b", q):
        cat("viviendas", "p2_tipo_vivienda", ["1"], "Casa")
    elif re.search(r"\b(?:departamentos?|depas?)\b", q):
        cat("viviendas", "p2_tipo_vivienda", ["3"], "Departamento")

    if re.search(r"\bviviendas?\s+particulares?\b|\ben\s+vivienda\s+particular\b", q):
        cat("personas", "tipo_operativo", ["2"], "Vivienda particular")

    # Área existe en las tres entidades. Se conserva la entidad que el usuario
    # escribió junto al adjetivo; si no, se decide más adelante según objetivo.
    m = re.search(r"\b(?P<ent>personas?|hogares?|viviendas?)\s+(?P<area>rurales?|urban[oa]s?)\b", q)
    if m:
        ent = m.group("ent")
        tabla = "personas" if ent.startswith("persona") else "hogares" if ent.startswith("hogar") else "viviendas"
        valor = "2" if m.group("area").startswith("rural") else "1"
        cat(tabla, "area", [valor], "Rural" if valor == "2" else "Urbano")

    return filtros


def _filtros_co_residencia(q):
    """Filtros existenciales en el mismo hogar.

    Ej.: "personas que viven con personas mayores de 65 años" debe contar
    a las personas objetivo en hogares donde exista al menos una persona que
    cumpla la condición, en vez de aplicar ese rango a la propia persona.
    """
    filtros = []
    m = re.search(r"\bvive[n]?\s+con\s+personas\s+mayores?\s+de\s+(\d{1,3})\s+anos?\b", q)
    if m:
        umbral = int(m.group(1))
        filtros.append({
            "tabla": "personas",
            "variable": "edad",
            "tipo": "existe_en_hogar",
            "subfiltros": [{
                "tabla": "personas", "variable": "edad", "tipo": "rango",
                "minimo": umbral, "incluir_minimo": False,
                "maximo": None, "dominio_minimo": 0,
            }],
            "etiqueta": f"vive con al menos una persona mayor de {umbral} años",
            "origen": "co_residencia",
        })
    return filtros


def _filtro_especial_resolver(consulta):
    """Aprovecha las rutas verificadas de discapacidad y educación en cruces."""
    salidas = []
    for resolver in (resolver_discapacidad, resolver_educacion):
        try:
            item = resolver(consulta)
        except Exception:
            item = None
        if not isinstance(item, dict) or item.get("tipo_consulta") == "dimensiones_funcionales":
            continue
        categoria = item.get("categoria_valor")
        valores = item.get("categoria_valores") or ([categoria] if categoria is not None else [])
        if valores:
            salidas.append({
                "tabla": item["tabla"], "variable": item["variable"],
                "tipo": "categoria", "valores": [str(v) for v in valores],
                "origen": "resolver",
            })
    return salidas


def _deduplicar_filtros(filtros):
    salida = []
    vistos = set()
    for f in filtros:
        if f["tipo"] == "categoria":
            clave = (f["tabla"], f["variable"], f["tipo"], tuple(f.get("valores") or []))
        elif f["tipo"] == "existe_en_hogar":
            sub = tuple((sf.get("tabla"), sf.get("variable"), sf.get("tipo"), sf.get("minimo"), sf.get("maximo"), sf.get("incluir_minimo"), sf.get("incluir_maximo")) for sf in (f.get("subfiltros") or []))
            clave = (f["tabla"], f["variable"], f["tipo"], sub)
        else:
            clave = (f["tabla"], f["variable"], f["tipo"], f.get("minimo"), f.get("maximo"))
        if clave not in vistos:
            salida.append(f)
            vistos.add(clave)
    return salida


def _detectar_variables(q):
    detectadas = {}
    for tabla, variable, patrones in _ALIAS_VARIABLES:
        if any(re.search(p, q) for p in patrones):
            _agregar_variable(detectadas, tabla, variable, 100, "alias_cruce")

    # El buscador general aporta variables cuyas descripciones aparecen de
    # forma clara. Se usa umbral alto para no convertir ruido léxico en cruce.
    for puntaje, tabla, variable in _candidatos_variable(q, limite=20):
        if puntaje >= 12:
            _agregar_variable(detectadas, tabla, variable, puntaje, "descripcion")

    return detectadas


def _aplicar_categorias_genericas(q, detectadas, filtros):
    """Convierte categorías literales inequívocas en filtros."""
    por_variable = {}
    for puntaje, tabla, variable, codigo, etiqueta in _coincidencias_categoria(q):
        # Área aparece con idénticas categorías en las tres entidades. Solo se
        # acepta cuando el sustantivo cercano (personas/hogares/viviendas) la
        # resolvió de forma contextual en _filtros_manual.
        if variable == "area":
            continue
        # Sí/No sin nombre de variable es demasiado ambiguo para un cruce.
        if _norm(etiqueta).strip() in {"si", "no"} and (tabla, variable) not in detectadas:
            continue
        if puntaje < 10:
            continue
        por_variable.setdefault((tabla, variable), []).append(
            (puntaje, str(codigo), str(etiqueta))
        )
    for (tabla, variable), items in por_variable.items():
        maximo = max(p for p, _, _ in items)
        mejores = [(c, e) for p, c, e in items if p == maximo]
        if len(mejores) == 1:
            codigo, etiqueta = mejores[0]
            filtros.append({"tabla": tabla, "variable": variable, "tipo": "categoria",
                            "valores": [codigo], "etiqueta": etiqueta,
                            "origen": "categoria_generica"})


_TOKENS_CATEGORIA_IGNORAR = {
    "con", "sin", "para", "del", "de", "la", "el", "los", "las",
    "hogar", "hogares", "persona", "personas", "vivienda", "viviendas",
    "tipo", "tipologia", "segun", "por", "nivel", "categoria",
}


def _tokens_significativos(texto):
    return {t for t in re.findall(r"[a-z0-9]+", _norm(texto))
            if len(t) >= 4 and t not in _TOKENS_CATEGORIA_IGNORAR}


def _subconjunto_categorias_mencionado(q, tabla, variable):
    """Detecta calificadores que restringen una dimensión a varias categorías.

    Ejemplo: ``tipología nuclear de hogar`` restringe ``tipologia_hogar`` a
    Nuclear monoparental, Nuclear pareja sin hijos y Nuclear pareja con hijos.
    El algoritmo solo actúa cuando el texto contiene tokens de categorías que
    no forman parte de la descripción de la variable y el subconjunto es menor
    que el dominio completo.
    """
    info = VARIABLES[tabla]["variables"][variable]
    validas = [str(c) for c in categorias_validas(tabla, variable)]
    if len(validas) < 2:
        return None
    desc_tokens = _tokens_significativos(info.get("descripcion", ""))
    q_tokens = _tokens_significativos(q)
    etiquetas = {
        c: _tokens_significativos(info.get("categorias", {}).get(c, ""))
        for c in validas
    }
    union_cat = set().union(*(t for t in etiquetas.values())) if etiquetas else set()
    calificadores = (q_tokens & union_cat) - desc_tokens
    if not calificadores:
        return None
    # Exige que todos los calificadores encontrados estén presentes en la
    # etiqueta. Así ``nuclear pareja`` selecciona solo las dos categorías de
    # pareja y ``nuclear`` selecciona las tres categorías nucleares.
    subconjunto = [c for c in validas if calificadores <= etiquetas[c]]
    if not subconjunto or len(subconjunto) == len(validas):
        return None
    return subconjunto


def _filtro_desde_subconjunto(tabla, variable, valores):
    info = VARIABLES[tabla]["variables"][variable]
    etiquetas = [str(info.get("categorias", {}).get(str(v), v)) for v in valores]
    return {
        "tabla": tabla, "variable": variable, "tipo": "categoria",
        "valores": [str(v) for v in valores],
        "etiqueta": " / ".join(etiquetas),
        "origen": "subconjunto_categoria",
    }


def _entidad_inferida(variables, filtros, explicita=None):
    # La unidad de análisis es siempre la entidad más granular involucrada.
    # Una entidad escrita por el usuario participa en la jerarquía, pero no
    # puede forzar el conteo de una entidad superior después de un JOIN.
    tablas = {item["tabla"] for item in variables.values()}
    tablas.update(f["tabla"] for f in filtros)
    if explicita:
        tablas.add(explicita)
    if not tablas:
        return None
    return max(tablas, key=lambda t: JERARQUIA[t])


def _es_dimension(q, tabla, variable, tiene_filtro):
    """Una categoría explícita actúa como filtro; si no, la variable es dimensión."""
    if tiene_filtro:
        return False
    info = VARIABLES[tabla]["variables"][variable]
    desc = _norm(info["descripcion"])
    # Marcadores explícitos de dimensión.
    fragmentos = [variable.replace("_", " ")]
    if variable == "sexo":
        fragmentos.append("sexo")
    elif variable == "tipologia_hogar":
        fragmentos.extend(["tipologia de hogar", "tipo de hogar"])
    elif variable == "sit_fuerza_trabajo":
        fragmentos.extend(["situacion en la fuerza de trabajo", "fuerza de trabajo"])
    elif variable == "p2_tipo_vivienda":
        fragmentos.append("tipo de vivienda")
    if any(re.search(r"\b(?:por|segun)\s+(?:la\s+|el\s+)?" + re.escape(f) + r"\b", q)
           for f in fragmentos if f):
        return True
    # Si la variable fue claramente nombrada y no tiene categoría, funciona
    # como dimensión incluso sin marcador («sexo y tipología de hogar»).
    return True


def _etiqueta_dimension(tabla, variable):
    info = VARIABLES[tabla]["variables"][variable]
    etiquetas = {
        ("personas", "sexo"): "Sexo",
        ("hogares", "tipologia_hogar"): "Tipología de hogar",
        ("personas", "sit_fuerza_trabajo"): "Situación en la fuerza de trabajo",
        ("viviendas", "p2_tipo_vivienda"): "Tipo de vivienda",
        ("personas", "p23_est_civil"): "Estado conyugal o civil",
        ("personas", "edad"): "Edad",
        ("personas", "escolaridad"): "Años de escolaridad",
        ("personas", "discapacidad"): "Discapacidad",
        ("personas", "parentesco"): "Parentesco",
        ("hogares", "p15d_serv_internet_fija"): "Internet fija",
        ("viviendas", "area"): "Área",
        ("hogares", "area"): "Área",
        ("personas", "area"): "Área",
    }
    return etiquetas.get((tabla, variable), info["descripcion"])


def resolver_cruce(consulta, union_seleccion=None):
    """Devuelve una intención de cruce o ``None`` si la consulta es univariada."""
    q = _norm(consulta)
    if not q.strip():
        return None
    # Una redacción que comienza con el número oficial de la pregunta censal
    # se deja a la ruta univariada de descripción literal. Evita interpretar
    # palabras internas como «hijo» o «abril» como un segundo concepto.
    if re.match(r"^\s*\d+(?:\.\d+)?[a-z]?\b", q):
        return None

    detectadas = _detectar_variables(q)
    filtros = _filtros_manual(q)

    # Una elección explícita sobre «Unión» tiene prioridad sobre las
    # coincidencias textuales genéricas del diccionario.
    if union_seleccion == "__union_parentesco_union_civil":
        filtros = [f for f in filtros if f.get("variable") != "p23_est_civil"]
        filtros.append({
            "tabla": "personas", "variable": "parentesco", "tipo": "categoria",
            "valores": ["3"], "etiqueta": "Conviviente por unión civil",
            "origen": "seleccion_union",
        })
        _agregar_variable(detectadas, "personas", "parentesco", 120, "seleccion_union")
        detectadas.pop(("personas", "p23_est_civil"), None)
    elif union_seleccion == "__union_estado_civil_union_civil":
        filtros = [f for f in filtros if f.get("variable") != "parentesco"]
        filtros.append({
            "tabla": "personas", "variable": "p23_est_civil", "tipo": "categoria",
            "valores": ["3"], "etiqueta": "Conviviente civil (con acuerdo de unión civil)",
            "origen": "seleccion_union",
        })
        _agregar_variable(detectadas, "personas", "p23_est_civil", 120, "seleccion_union")
        detectadas.pop(("personas", "parentesco"), None)

    filtros.extend(_filtros_co_residencia(q))
    filtros.extend(_filtro_especial_resolver(consulta))
    numericos, conceptos_num = _filtros_numericos(q)
    # Cuando el rango numérico forma parte de un filtro existencial
    # "vive con personas mayores de X años", no debe restringir a la propia
    # persona objetivo.
    if any(f.get("tipo") == "existe_en_hogar" for f in filtros):
        numericos = [f for f in numericos if not (f.get("tabla") == "personas" and f.get("variable") == "edad")]
        conceptos_num = [c for c in conceptos_num if c != ("personas", "edad")]
    filtros.extend(numericos)
    for tabla, variable in conceptos_num:
        _agregar_variable(detectadas, tabla, variable, 100, "rango")
    # Los filtros deterministas son evidencia fuerte de un concepto.
    for f in filtros:
        if f.get("origen") in {"manual", "resolver", "rango", "seleccion_union"}:
            _agregar_variable(detectadas, f["tabla"], f["variable"], 100, f["origen"])

    # Las categorías literales del diccionario solo se incorporan si ya existe
    # al menos otro concepto fuerte. Así «Red pública» o «Vivienda particular»
    # no crean falsos cruces por aparecer en varias tablas.
    if detectadas:
        filtros_genericos = []
        _aplicar_categorias_genericas(q, detectadas, filtros_genericos)
        # Conserva solo categorías cuya variable ya fue detectada o cuya
        # coincidencia es única entre las categorías genéricas.
        por_clave = {}
        for f in filtros_genericos:
            por_clave.setdefault((f["tabla"], f["variable"]), []).append(f)
        if len(por_clave) == 1:
            filtros.extend(filtros_genericos)
            for tabla, variable in por_clave:
                _agregar_variable(detectadas, tabla, variable, 90, "categoria_generica")
        else:
            filtros.extend(f for f in filtros_genericos
                           if (f["tabla"], f["variable"]) in detectadas)
    filtros = _deduplicar_filtros(filtros)

    if union_seleccion == "__union_parentesco_union_civil":
        filtros = [f for f in filtros if f.get("variable") not in {"p23_est_civil", "parentesco"}]
        filtros.append({
            "tabla": "personas", "variable": "parentesco", "tipo": "categoria",
            "valores": ["3"], "etiqueta": "Conviviente por unión civil",
            "origen": "seleccion_union",
        })
        detectadas.pop(("personas", "p23_est_civil"), None)
        _agregar_variable(detectadas, "personas", "parentesco", 120, "seleccion_union")
    elif union_seleccion == "__union_estado_civil_union_civil":
        filtros = [f for f in filtros if f.get("variable") not in {"parentesco", "p23_est_civil"}]
        filtros.append({
            "tabla": "personas", "variable": "p23_est_civil", "tipo": "categoria",
            "valores": ["3"], "etiqueta": "Conviviente civil (con acuerdo de unión civil)",
            "origen": "seleccion_union",
        })
        detectadas.pop(("personas", "parentesco"), None)
        _agregar_variable(detectadas, "personas", "p23_est_civil", 120, "seleccion_union")

    # Cuando la frase menciona explícitamente el acuerdo de unión civil, el
    # concepto primario es el estado conyugal/civil y no el parentesco dentro
    # del hogar. Se elimina el falso positivo de "Conviviente por unión civil".
    if union_seleccion is None and re.search(r"\bacuerdo\s+de\s+union\s+civil\b", q) and any(
        f.get("tabla") == "personas" and f.get("variable") == "p23_est_civil" and "3" in [str(v) for v in f.get("valores", [])]
        for f in filtros
    ):
        filtros = [f for f in filtros if not (
            f.get("tabla") == "personas" and f.get("variable") == "parentesco" and "3" in [str(v) for v in f.get("valores", [])]
        )]

    # Si una ruta educativa específica ya determinó el nivel, no dejamos que
    # la pregunta 33 general reaparezca como segunda dimensión por similitud.
    vars_educacion = {"p33_edu_asiste", "asistencia_parv", "asistencia_basica",
                      "asistencia_media", "asistencia_superior"}
    # Una resolución educativa determinista por nivel (parvularia/básica/media/
    # superior) prevalece sobre coincidencias genéricas con la pregunta 33.
    # Evita que «no asisten a educación media» se convierta en dos filtros.
    filtros_edu_resueltos = {
        (f["tabla"], f["variable"]) for f in filtros
        if f.get("origen") == "resolver" and f.get("tabla") == "personas"
        and f.get("variable") in vars_educacion
    }
    if filtros_edu_resueltos:
        filtros = [f for f in filtros if not (
            f.get("tabla") == "personas" and f.get("variable") in vars_educacion
            and (f.get("tabla"), f.get("variable")) not in filtros_edu_resueltos
        )]
        for clave in list(detectadas):
            if (clave[0] == "personas" and clave[1] in vars_educacion
                    and clave not in filtros_edu_resueltos):
                detectadas.pop(clave, None)
    else:
        filtros_edu = {(f["tabla"], f["variable"]) for f in filtros
                       if f["tabla"] == "personas" and f["variable"] in vars_educacion}
        if filtros_edu:
            for clave in list(detectadas):
                if clave[0] == "personas" and clave[1] in vars_educacion and clave not in filtros_edu:
                    detectadas.pop(clave, None)

    # El modo cruce requiere sintaxis que realmente combine conceptos.
    # «por región/comuna/provincia» por sí solo no cuenta como cruce.
    claves_fuertes = set(detectadas)
    conector_fuerte = bool(re.search(
        r"\bsegun\b|\bcruzad[oa]s?\b|\bversus\b|\bvs\b|"
        r"\bque\s+viven?\b|\bque\s+residen?\b|\by\b", q
    ))
    por_estadistico = bool(re.search(r"\bpor\s+(?!region\b|regiones\b|provincia\b|provincias\b|comuna\b|comunas\b)", q))
    explicita = _entidad_objetivo_explicita(q)
    if explicita is None and union_seleccion in {"__union_parentesco_union_civil", "__union_estado_civil_union_civil"}:
        explicita = "personas"
    tablas_conceptos = {t for t, _ in claves_fuertes}
    entidad_distinta = bool(explicita and any(t != explicita for t in tablas_conceptos))
    filtros_conceptuales = {
        (f.get("tabla"), f.get("variable"))
        for f in filtros
        if f.get("tipo") in {"categoria", "rango", "existe_en_hogar"}
    }
    # Dos o más filtros explícitos sobre la misma entidad también constituyen
    # un cruce semántico, aunque la frase no contenga «según» o «y».
    # Ejemplo: «personas mayores de 65 años con mucha dificultad visual».
    varios_filtros = len(filtros_conceptuales) >= 2
    # Un único filtro sobre la misma entidad debe seguir por la ruta
    # univariada normal, salvo casos que requieren semántica del planificador:
    # selección explícita de Unión, servicio doméstico y co-residencia.
    forzar_cruce_simple = bool(explicita and any(
        f.get("tipo") == "existe_en_hogar"
        or f.get("origen") == "seleccion_union"
        or (f.get("variable") == "parentesco" and [str(v) for v in f.get("valores", [])] == ["16"])
        for f in filtros
    ))
    if len(claves_fuertes) < 2 and not entidad_distinta and not forzar_cruce_simple and not varios_filtros:
        return None
    if not (conector_fuerte or por_estadistico or entidad_distinta or forzar_cruce_simple or varios_filtros):
        return None

    objetivo = _entidad_inferida(detectadas, filtros, explicita)
    if objetivo is None:
        return None

    # Una variable filtrada no vuelve a aparecer como dimensión. Para una
    # dimensión explícita se permite, además, restringir el dominio mediante
    # calificadores de categorías (p.ej. ``tipología nuclear``).
    filtradas = {(f["tabla"], f["variable"]) for f in filtros}
    dimensiones = []
    for clave, item in sorted(detectadas.items(), key=lambda kv: -kv[1]["puntaje"]):
        tabla, variable = clave
        if union_seleccion == "__union_parentesco_union_civil" and (tabla, variable) == ("personas", "p23_est_civil"):
            continue
        if union_seleccion == "__union_estado_civil_union_civil" and (tabla, variable) == ("personas", "parentesco"):
            continue
        if variable in {"edad", "escolaridad"} and clave in filtradas:
            continue
        tiene_filtro = clave in filtradas
        if _es_dimension(q, tabla, variable, tiene_filtro):
            if tiene_filtro:
                continue
            if re.search(r"\bacuerdo\s+de\s+union\s+civil\b", q) and tabla == "personas" and variable == "parentesco":
                continue
            validas = [str(v) for v in categorias_validas(tabla, variable)]
            subconjunto = _subconjunto_categorias_mencionado(q, tabla, variable)
            if subconjunto:
                # Un único valor deja de ser una dimensión y pasa a filtro.
                # Dos o más valores siguen siendo una dimensión restringida.
                if len(subconjunto) == 1:
                    filtros.append(_filtro_desde_subconjunto(tabla, variable, subconjunto))
                    filtradas.add(clave)
                    continue
                validas = subconjunto
            if len(validas) >= 2:
                dimensiones.append({
                    "tabla": tabla, "variable": variable,
                    "categorias_validas": validas,
                    "etiqueta": _etiqueta_dimension(tabla, variable),
                })

    # Evita que variables auxiliares repetidas entren como dimensiones por ruido.
    unicas = []
    vistos = set()
    for d in dimensiones:
        clave = (d["tabla"], d["variable"])
        if clave not in vistos:
            unicas.append(d); vistos.add(clave)
    dimensiones = unicas[:2]

    conceptos = set(detectadas)
    conceptos.update((f["tabla"], f["variable"]) for f in filtros)
    cruce_entidades = any(tabla != objetivo for tabla, _ in conceptos)
    # También se admiten conteos filtrados cuando la entidad objetivo fue
    # solicitada explícitamente (p.ej. "personas de servicio doméstico").
    if len(conceptos) < 2 and not cruce_entidades and not forzar_cruce_simple and not varios_filtros:
        return None

    # Una suma/promedio multientidad necesita semántica de medida adicional.
    # Se rechaza antes de generar un resultado engañoso; los conteos sí son
    # completamente deterministas con COUNT DISTINCT de la entidad objetivo.
    # No se usa detectar_operacion aquí porque la palabra «media» de
    # «educación media» no significa promedio.
    solicita_promedio = bool(re.search(r"\bpromedio\b|\bmedia\s+de\b", q))
    solicita_suma = bool(re.search(r"\b(?:suma|sumar|sumatoria)\b", q))
    solicita_porcentaje = bool(re.search(r"\b(?:porcentaje|proporcion)\b|%", q))
    if solicita_promedio or solicita_suma:
        raise ValueError(
            "El cruce multientidad ya permite conteos y distribuciones. Para promedios o sumas "
            "es necesario indicar explícitamente la variable numérica que se desea agregar y su "
            "unidad estadística; no se sumará automáticamente una variable de una entidad superior."
        )
    if solicita_porcentaje:
        raise ValueError(
            "En un cruce, 'porcentaje' puede significar porcentaje sobre el total, dentro de la "
            "primera variable o dentro de la segunda. Para evitar un denominador implícito, usa "
            "por ahora una consulta de cantidad/distribución y especifica luego el denominador deseado."
        )

    if len(dimensiones) > 2:
        dimensiones = dimensiones[:2]

    # Se necesita al menos una dimensión o dos filtros/conceptos para que el
    # plan aporte algo más que una consulta simple.
    if not dimensiones and len(conceptos) < 2 and not cruce_entidades and not forzar_cruce_simple and not varios_filtros:
        return None

    # Variable ancla compatible con el contrato histórico del backend.
    if dimensiones:
        ancla = dimensiones[0]
    elif filtros:
        ancla = filtros[0]
    else:
        return None

    plan = {
        "entidad_objetivo": objetivo,
        "dimensiones": deepcopy(dimensiones),
        "filtros": deepcopy(filtros),
        "medida": {"operacion": "conteo_distinto", "entidad": objetivo},
    }
    return {
        "tabla": ancla["tabla"],
        "variable": ancla["variable"],
        "categoria_valor": None,
        "operacion": "conteo",
        "tipo_consulta": "cruce",
        "plan_cruce": plan,
        "indicador_descripcion": _descripcion_plan(plan),
        "_origen_interpretacion": "planificador_cruce",
    }


def _descripcion_plan(plan):
    objetivo = plan["entidad_objetivo"]
    dims = plan.get("dimensiones") or []
    filtros = plan.get("filtros") or []
    if dims:
        nombres = " × ".join(d.get("etiqueta", d["variable"]) for d in dims)
        base = f"Cruce de {objetivo} según {nombres}"
    else:
        base = f"Cantidad de {objetivo} que cumplen los filtros solicitados"
    if filtros:
        detalles = []
        for f in filtros:
            if f.get("tipo") == "categoria":
                etiqueta = f.get("etiqueta")
                if not etiqueta:
                    info = VARIABLES[f["tabla"]]["variables"][f["variable"]]
                    etiqueta = " / ".join(
                        str(info.get("categorias", {}).get(str(v), v))
                        for v in f.get("valores", [])
                    )
                detalles.append(f"{_etiqueta_dimension(f['tabla'], f['variable'])} = {etiqueta}")
            elif f.get("tipo") == "rango":
                minimo, maximo = f.get("minimo"), f.get("maximo")
                if minimo is not None and maximo is not None:
                    etiqueta = f"{minimo} a {maximo}"
                elif minimo is not None:
                    op = "≥" if f.get("incluir_minimo", True) else ">"
                    etiqueta = f"{op} {minimo}"
                else:
                    op = "≤" if f.get("incluir_maximo", True) else "<"
                    etiqueta = f"{op} {maximo}"
                detalles.append(f"{_etiqueta_dimension(f['tabla'], f['variable'])} {etiqueta}")
            elif f.get("tipo") == "existe_en_hogar":
                detalles.append(f.get("etiqueta") or "co-residencia en el mismo hogar")
        if detalles:
            base += "; filtros: " + "; ".join(detalles)
    return base

