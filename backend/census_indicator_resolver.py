# -*- coding: utf-8 -*-
"""Catálogo determinista de tasas, indicadores y consultas compuestas censales (v28).

El módulo reconoce expresiones habituales de análisis censal antes del LLM y
las traduce a intenciones con universo y fórmula explícitos. Los cálculos
utilizan únicamente variables presentes en el diccionario del proyecto.
"""
from __future__ import annotations

import re

from dictionary import VARIABLES, _norm, categorias_validas

TIPO = "indicador_censal_v27"
TIPO_DISTRIBUCION = "distribucion_censal_v27"


def _existe(variable: str) -> None:
    if variable not in VARIABLES["personas"]["variables"]:
        raise ValueError(f"La variable requerida ({variable}) no existe en el diccionario censal.")


def _base(indicador_id: str, variable: str, descripcion: str, universo: str,
          formula: str, *, operacion: str = "razon", nota: str | None = None,
          tipo: str = TIPO) -> dict:
    _existe(variable)
    salida = {
        "tabla": "personas",
        "variable": variable,
        "categoria_valor": None,
        "operacion": operacion,
        "tipo_consulta": tipo,
        "indicador_id": indicador_id,
        "indicador_descripcion": descripcion,
        "universo": universo,
        "formula": formula,
        "_origen_interpretacion": "catalogo_indicadores_censales_v28",
    }
    if nota:
        salida["nota_interpretacion"] = nota
    return salida


def _distribucion(indicador_id: str, variable: str, descripcion: str,
                  universo: str, formula: str) -> dict:
    salida = _base(
        indicador_id, variable, descripcion, universo, formula,
        operacion="distribucion", tipo=TIPO_DISTRIBUCION,
    )
    salida["categorias_validas"] = categorias_validas("personas", variable)
    return salida




def _filtro_categoria(tabla: str, variable: str, valores, etiqueta: str | None = None) -> dict:
    """Filtro categórico validado para QueryPlan v2."""
    if tabla not in VARIABLES or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError(f"La variable requerida ({tabla}.{variable}) no existe en el diccionario censal.")
    codigos = {str(c) for c in VARIABLES[tabla]["variables"][variable].get("categorias", {})}
    valores = [str(v) for v in valores]
    if not valores or any(v not in codigos for v in valores):
        raise ValueError(f"Una categoría requerida de {tabla}.{variable} no existe en el diccionario censal.")
    return {
        "tipo": "categoria", "tabla": tabla, "variable": variable,
        "valores": valores, "etiqueta": etiqueta, "origen": "catalogo_v28",
    }


def _filtro_rango(tabla: str, variable: str, *, minimo=None, maximo=None,
                  incluir_minimo=True, incluir_maximo=True) -> dict:
    """Filtro numérico para QueryPlan v2."""
    if tabla not in VARIABLES or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError(f"La variable requerida ({tabla}.{variable}) no existe en el diccionario censal.")
    return {
        "tipo": "rango", "tabla": tabla, "variable": variable,
        "minimo": minimo, "maximo": maximo,
        "incluir_minimo": incluir_minimo, "incluir_maximo": incluir_maximo,
        "dominio_minimo": 0 if variable == "edad" else None,
        "dominio_maximo": 120 if variable == "edad" else None,
        "origen": "catalogo_v28",
    }


def _and(*filtros) -> dict:
    items = [f for f in filtros if f]
    if len(items) == 1:
        return items[0]
    return {"op": "and", "args": items}


def _plan_cruce(*, tabla: str, variable: str, objetivo: str, filtros,
                dimensiones=None, porcentaje=False, descripcion: str,
                universo: str, formula: str, operacion: str = "conteo") -> dict:
    """Construye una intención QueryPlan v2 sin depender del LLM."""
    if objetivo not in {"personas", "hogares", "viviendas"}:
        raise ValueError("Entidad objetivo censal no válida.")
    salida = {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": None,
        "operacion": operacion,
        "tipo_consulta": "cruce",
        "entidad_objetivo": objetivo,
        "descripcion_personalizada": descripcion,
        "universo": universo,
        "formula": formula,
        "plan_cruce": {
            "version": 2,
            "entidad_objetivo": objetivo,
            "dimensiones": list(dimensiones or []),
            "filtro_ast": filtros,
            "medida": {"operacion": "conteo_distinto", "entidad": objetivo},
        },
        "_origen_interpretacion": "catalogo_consultas_compuestas_v28",
    }
    if porcentaje:
        salida["plan_cruce"]["porcentaje"] = {"base": "total"}
    return salida


def _dimension(tabla: str, variable: str, etiqueta: str) -> dict:
    return {
        "tabla": tabla, "variable": variable,
        "categorias_validas": categorias_validas(tabla, variable),
        "etiqueta": etiqueta,
    }


def _distribucion_tabla(tabla: str, variable: str, indicador_id: str,
                        descripcion: str, universo: str, formula: str) -> dict:
    if tabla not in VARIABLES or variable not in VARIABLES[tabla]["variables"]:
        raise ValueError(f"La variable requerida ({tabla}.{variable}) no existe en el diccionario censal.")
    return {
        "tabla": tabla, "variable": variable, "categoria_valor": None,
        "operacion": "distribucion", "tipo_consulta": TIPO_DISTRIBUCION,
        "indicador_id": indicador_id, "indicador_descripcion": descripcion,
        "categorias_validas": categorias_validas(tabla, variable),
        "universo": universo, "formula": formula,
        "_origen_interpretacion": "catalogo_indicadores_censales_v28",
    }


def _resolver_consultas_compuestas_v28(q: str):
    """Casos frecuentes que combinan entidades, universos y varias variables.

    Estas reglas se ejecutan antes de los planificadores genéricos para impedir
    falsos positivos como interpretar «vivienda ocupada de hecho» como persona
    ocupada en el mercado laboral.
    """
    # Tenencia precaria/irregular: categorías exactas de P12 solicitadas.
    valores_tenencia = []
    if re.search(r"\barrendad[oa]s?\s+sin\s+contrato\b", q):
        valores_tenencia.append("4")
    if re.search(r"\bocupad[oa]s?\s+de\s+hecho\b", q):
        valores_tenencia.append("8")
    if re.search(r"\b(?:propiedad|perteneciente?s?)\s+(?:en|a\s+una\s+propiedad\s+en)?\s*sucesion\s+o\s+litigio\b|\bsucesion\s+o\s+litigio\b", q):
        valores_tenencia.append("9")
    if len(set(valores_tenencia)) >= 2 and re.search(r"\b(?:personas?|hogares?)\b", q):
        valores_tenencia = list(dict.fromkeys(valores_tenencia))
        objetivo = "hogares" if re.search(r"^\s*(?:cantidad|numero|total)?\s*(?:de\s+)?hogares\b|\bhogares\s+con\b", q) else "personas"
        etiqueta = "Arrendada sin contrato / Ocupada de hecho / Propiedad en sucesión o litigio"
        filtro = _filtro_categoria("hogares", "p12_tenencia_viv", valores_tenencia, etiqueta)
        if objetivo == "personas":
            return _plan_cruce(
                tabla="personas", variable="tipo_operativo", objetivo="personas",
                filtros=filtro,
                descripcion="Personas que viven en viviendas arrendadas sin contrato, ocupadas de hecho o en propiedad en sucesión o litigio",
                universo="Personas vinculadas a hogares con respuesta de tenencia igual a arrendada sin contrato, ocupada de hecho o propiedad en sucesión o litigio.",
                formula="Cantidad = conteo de personas distintas que pertenecen a hogares cuya tenencia corresponde a las categorías seleccionadas de P12.",
            )
        return _plan_cruce(
            tabla="hogares", variable="p12_tenencia_viv", objetivo="hogares",
            filtros=filtro,
            descripcion="Hogares en viviendas arrendadas sin contrato, ocupadas de hecho o en propiedad en sucesión o litigio",
            universo="Hogares con respuesta de tenencia igual a arrendada sin contrato, ocupada de hecho o propiedad en sucesión o litigio.",
            formula="Cantidad = conteo de hogares distintos cuya tenencia corresponde a las categorías seleccionadas de P12.",
        )

    # Personas mayores: en este visor se adopta 60 años o más cuando la frase
    # no trae un umbral numérico explícito. Para porcentajes compuestos el
    # numerador y el denominador se modelan por separado: si la pregunta no
    # nombra la base, denominator_resolver abrirá el diálogo correspondiente.
    es_personas_mayores = bool(re.search(r"\b(?:personas?|adultos?)\s+mayores\b", q))
    sin_internet = bool(re.search(r"\bsin\s+(?:acceso\s+a\s+)?internet(?:\s+en\s+el\s+hogar)?\b", q))
    pide_sexo_edad5 = bool(re.search(r"\bsexo\b", q) and re.search(r"\bedad\s+quinquenal\b|\bgrupos?\s+quinquenales?\s+de\s+edad\b", q))
    solicita_porcentaje = bool(re.search(r"\b(?:porcentaje|proporcion)\b", q))
    distribucion_relativa = bool(re.search(r"\bdistribucion\s+relativa\b", q))
    if es_personas_mayores and sin_internet and (pide_sexo_edad5 or solicita_porcentaje or distribucion_relativa):
        relativa = bool(distribucion_relativa or solicita_porcentaje)
        filtro_edad = _filtro_rango("personas", "edad", minimo=60, incluir_minimo=True)
        filtros = _and(
            filtro_edad,
            _filtro_categoria("personas", "tipo_operativo", ["2"], "Vivienda particular"),
            _filtro_categoria("hogares", "p15d_serv_internet_fija", ["2"], "Sin internet fija"),
            _filtro_categoria("hogares", "p15e_serv_internet_movil", ["2"], "Sin internet móvil"),
            _filtro_categoria("hogares", "p15f_serv_internet_satelital", ["2"], "Sin internet satelital"),
        )
        dimensiones = ([
            _dimension("personas", "sexo", "Sexo"),
            _dimension("personas", "edad_quinquenal", "Edad quinquenal"),
        ] if pide_sexo_edad5 else [])
        salida = _plan_cruce(
            tabla="personas", variable="sexo" if pide_sexo_edad5 else "edad",
            objetivo="personas", filtros=filtros, dimensiones=dimensiones,
            porcentaje=relativa,
            operacion="porcentaje" if relativa else "distribucion",
            descripcion=(
                "Distribución relativa de personas de 60 años o más en viviendas particulares sin acceso a internet en el hogar, por sexo y edad quinquenal"
                if relativa and pide_sexo_edad5 else
                "Distribución de personas de 60 años o más en viviendas particulares sin acceso a internet en el hogar, por sexo y edad quinquenal"
                if pide_sexo_edad5 else
                "Porcentaje de personas de 60 años o más en viviendas particulares sin acceso a internet en el hogar"
            ),
            universo="Personas de 60 años o más en viviendas particulares sin acceso a internet en el hogar.",
            formula=(
                "Porcentaje = (personas de 60 años o más en viviendas particulares sin acceso a internet / denominador seleccionado) × 100"
                if relativa else
                "Distribución = conteo de personas distintas por combinación de sexo y edad quinquenal."
            ),
        )
        if relativa:
            # «Distribución relativa del total de ...» ya contiene su propio
            # denominador: el total del universo descrito antes de «según».
            if distribucion_relativa and re.search(r"\bdel\s+total\s+de\b", q) and pide_sexo_edad5:
                salida["denominador_definido"] = True
                salida["universo"] = (
                    "Personas de 60 años o más en viviendas particulares cuyos hogares no disponen de internet fija, móvil ni satelital."
                )
                salida["formula"] = (
                    "Porcentaje de cada combinación sexo × edad quinquenal = "
                    "(personas de la combinación / total de personas de 60 años o más en viviendas particulares sin acceso a internet del territorio) × 100"
                )
            else:
                salida["numerador_descripcion"] = (
                    "personas de 60 años o más en viviendas particulares sin acceso a internet"
                )
                salida["denominador_candidatos"] = [
                    {
                        "id": "total_personas_mayores",
                        "titulo": "Sobre el total de personas mayores",
                        "descripcion": "Denominador: todas las personas de 60 años o más del territorio.",
                        "universo": "Personas de 60 años o más del territorio.",
                        "denominador_ast": filtro_edad,
                        "aliases": ["personas mayores", "adultos mayores", "personas de 60 anos o mas"],
                        "formula": "Porcentaje = (personas de 60 años o más en viviendas particulares sin acceso a internet / total de personas de 60 años o más) × 100",
                    },
                    {
                        "id": "total_personas",
                        "titulo": "Sobre el total de personas",
                        "descripcion": "Denominador: todas las personas del territorio.",
                        "universo": "Total de personas del territorio.",
                        "denominador_ast": None,
                        "aliases": ["personas", "poblacion", "total de personas", "poblacion total"],
                        "formula": "Porcentaje = (personas de 60 años o más en viviendas particulares sin acceso a internet / total de personas) × 100",
                    },
                ]
        return salida

    # Composición del hogar se representa mediante la tipología de hogar.
    if re.search(r"\bdistribucion(?:\s+relativa)?\b", q) and re.search(r"\bhogares?\b", q) and re.search(r"\bcomposicion\s+(?:del|de\s+los?)\s+hogar", q):
        return _distribucion_tabla(
            "hogares", "tipologia_hogar", "distribucion_composicion_hogar",
            "Distribución de hogares según composición del hogar",
            "Hogares con tipología de hogar válida.",
            "Porcentaje de cada composición = (hogares de la tipología / hogares con tipología válida) × 100",
        )

    # Porcentaje de personas mayores que son jefas o jefes de hogar.
    if re.search(r"\b(?:porcentaje|proporcion)\b", q) and re.search(r"\bjef(?:e|a|es|as)\s+de\s+hogar\b", q):
        m_estricto = re.search(r"\bmayores?\s+de\s+(\d{1,3})\s+anos?\b", q)
        m_inclusivo = re.search(r"\b(\d{1,3})\s+anos?\s+o\s+mas\b", q)
        if m_estricto or m_inclusivo or es_personas_mayores:
            if m_estricto:
                umbral, inclusiva = int(m_estricto.group(1)), False
            elif m_inclusivo:
                umbral, inclusiva = int(m_inclusivo.group(1)), True
            else:
                umbral, inclusiva = 60, True
            operador_txt = "o más" if inclusiva else "mayores de"
            edad_txt = f"{umbral} años o más" if inclusiva else f"mayores de {umbral} años"
            salida = _base(
                "porcentaje_personas_mayores_jefatura", "parentesco",
                f"Porcentaje de personas {edad_txt} que son jefas o jefes de hogar",
                f"Personas {edad_txt} en viviendas particulares con edad válida.",
                f"Porcentaje = (personas {edad_txt} que son jefas o jefes de hogar / personas {edad_txt} en viviendas particulares) × 100",
            )
            salida["edad_umbral"] = umbral
            salida["edad_inclusiva"] = inclusiva
            # El numerador está claro, pero la frase no determina si la base
            # debe ser el subgrupo de personas mayores o toda la población.
            salida["denominador_candidatos"] = [
                {
                    "id": "total_personas_mayores",
                    "titulo": f"Sobre el total de personas {edad_txt}",
                    "descripcion": f"Denominador: todas las personas {edad_txt} del territorio.",
                    "universo": f"Personas {edad_txt} del territorio.",
                    "aliases": [f"personas {edad_txt}", "personas mayores", "adultos mayores"],
                    "formula": f"Porcentaje = (personas {edad_txt} que son jefas o jefes de hogar / total de personas {edad_txt}) × 100",
                },
                {
                    "id": "total_personas",
                    "titulo": "Sobre el total de personas",
                    "descripcion": "Denominador: todas las personas del territorio.",
                    "universo": "Total de personas del territorio.",
                    "aliases": ["personas", "poblacion", "total de personas", "poblacion total"],
                    "formula": f"Porcentaje = (personas {edad_txt} que son jefas o jefes de hogar / total de personas) × 100",
                },
            ]
            return salida

    return None

def resolver_indicador_censal_v27(consulta: str):
    q = _norm(consulta)

    compuesta = _resolver_consultas_compuestas_v28(q)
    if compuesta is not None:
        return compuesta

    # Mercado laboral. Se usan las categorías válidas de la variable de fuerza
    # de trabajo para que No respuesta/No aplica no entren en el denominador.
    if re.search(r"\b(?:tasa|porcentaje|proporcion)\s+(?:de\s+)?(?:participacion\s+economica|participacion\s+laboral|actividad\s+economica|actividad)\b", q):
        return _base(
            "tasa_participacion_economica", "sit_fuerza_trabajo", "Tasa de participación económica",
            "Personas de 15 años o más con situación en la fuerza de trabajo válida.",
            "Tasa de participación económica = ((personas ocupadas + personas desocupadas) / (ocupadas + desocupadas + fuera de la fuerza de trabajo)) × 100",
        )
    if re.search(r"\b(?:distribucion|composicion)\s+(?:por|segun|de)\s+(?:la\s+)?categoria\s+ocupacional\b|\bcategoria\s+ocupacional\b", q):
        return _distribucion(
            "distribucion_categoria_ocupacional", "p40_cise_rec", "Distribución por categoría ocupacional",
            "Personas ocupadas con categoría ocupacional válida.",
            "Porcentaje de cada categoría ocupacional = (personas de la categoría / personas ocupadas con categoría ocupacional válida) × 100",
        )

    # Alfabetismo y logro educativo.
    if re.search(r"\b(?:tasa|porcentaje|proporcion)\s+(?:de\s+)?alfabet(?:ismo|izacion)\b|\btasa\s+de\s+alfabetizacion\b", q):
        return _base(
            "tasa_alfabetismo", "p37_alfabet", "Tasa de alfabetismo",
            "Personas de 5 años o más con respuesta válida a la pregunta sobre saber leer y escribir.",
            "Tasa de alfabetismo = (personas de 5 años o más que saben leer y escribir / personas de 5 años o más con respuesta válida) × 100",
        )
    if re.search(r"\b(?:tasa|porcentaje|proporcion)\s+(?:de\s+)?analfabet(?:ismo|izacion)\b", q):
        return _base(
            "tasa_analfabetismo", "p37_alfabet", "Tasa de analfabetismo",
            "Personas de 5 años o más con respuesta válida a la pregunta sobre saber leer y escribir.",
            "Tasa de analfabetismo = (personas de 5 años o más que no saben leer y escribir / personas de 5 años o más con respuesta válida) × 100",
        )
    if re.search(r"\bnivel\s+(?:de\s+)?(?:instruccion|educacional|educativo)\b|\bescolaridad\s+alcanzada\b|\blogro\s+educativo\b", q):
        return _distribucion(
            "nivel_instruccion", "cine11", "Nivel de instrucción o escolaridad alcanzada",
            "Personas con nivel educacional CINE-11 válido.",
            "Porcentaje por nivel de instrucción = (personas del nivel / personas con nivel CINE-11 válido) × 100",
        )

    # Pueblos indígenas y afrodescendencia.
    if re.search(r"\b(?:porcentaje|proporcion|tasa)\s+(?:de\s+)?poblacion\s+(?:indigena\s+o\s+afrodescendiente|afrodescendiente\s+o\s+indigena)\b", q):
        return _base(
            "porcentaje_poblacion_indigena_o_afro", "p28_autoid_pueblo", "Porcentaje de población indígena o afrodescendiente",
            "Personas con respuesta válida tanto a autoidentificación indígena como a afrodescendencia.",
            "Porcentaje indígena o afrodescendiente = (personas indígenas o afrodescendientes, sin duplicar a quienes cumplen ambas condiciones / personas con ambas respuestas válidas) × 100",
        )
    if re.search(r"\b(?:porcentaje|proporcion|tasa)\s+(?:de\s+)?poblacion\s+(?:indigena|perteneciente\s+a\s+pueblos?\s+indigenas?)\b", q):
        return _base(
            "porcentaje_poblacion_indigena", "p28_autoid_pueblo", "Porcentaje de población indígena u originaria",
            "Personas con respuesta válida a la autoidentificación como perteneciente a un pueblo indígena u originario.",
            "Porcentaje de población indígena = (personas que se consideran pertenecientes a un pueblo indígena u originario / personas con respuesta válida) × 100",
        )
    if re.search(r"\b(?:porcentaje|proporcion|tasa)\s+(?:de\s+)?poblacion\s+afrodescendiente\b", q):
        return _base(
            "porcentaje_poblacion_afrodescendiente", "p29_afrodescendencia_rec", "Porcentaje de población afrodescendiente",
            "Personas con respuesta válida a la variable de afrodescendencia.",
            "Porcentaje de población afrodescendiente = (personas afrodescendientes / personas con respuesta válida) × 100",
        )

    # Migración internacional e interna reciente.
    if re.search(r"\b(?:porcentaje|proporcion|tasa)\s+(?:de\s+)?poblacion\s+(?:inmigrante\s+internacional|nacida\s+en\s+el\s+extranjero|nacida\s+fuera\s+de\s+chile)\b", q):
        return _base(
            "porcentaje_inmigrante_internacional", "p25_lug_nacimiento", "Porcentaje de población inmigrante internacional",
            "Personas con lugar de nacimiento válido.",
            "Porcentaje de inmigrantes internacionales = (personas nacidas en otro país / personas con lugar de nacimiento válido) × 100",
        )
    if re.search(r"\btasa\s+(?:de\s+)?migracion\s+neta\s+interna\b|\btasa\s+neta\s+(?:de\s+)?migracion\s+interna\b", q):
        return _base(
            "tasa_migracion_neta_interna", "p24_lug_resid5", "Tasa neta de migración interna 2019–2024",
            "Personas que ya habían nacido en abril de 2019, residían en Chile en 2019 y tienen comuna de residencia 2019 y comuna actual identificables.",
            "Tasa neta de migración interna = ((inmigrantes internos − emigrantes internos) / (5 × ((población reconstruida en 2019 + población reconstruida en 2024) / 2))) × 1.000",
            nota="Tasa anual media del quinquenio 2019–2024, expresada por 1.000 personas-año, reconstruida a partir de residencia 2019 y residencia actual.",
        )
    if re.search(r"\btasa\s+(?:de\s+)?migracion\s+interna\b", q):
        return _base(
            "tasa_migracion_interna", "p24_lug_resid5", "Porcentaje de migración interna reciente 2019–2024",
            "Personas que ya habían nacido en abril de 2019, residían en Chile en 2019 y tienen respuesta válida de residencia 2019.",
            "Porcentaje de migración interna reciente = (personas que en 2019 residían en otra comuna de Chile / personas con residencia 2019 válida en Chile) × 100",
            nota="Indicador quinquenal de movilidad residencial interna; no es una tasa anualizada.",
        )
    if re.search(r"\btasa\s+(?:de\s+)?migracion\s+reciente\b|\bporcentaje\s+(?:de\s+)?migrantes?\s+recientes?\b", q):
        return _base(
            "tasa_migracion_reciente", "p24_lug_resid5", "Porcentaje de migración reciente 2019–2024",
            "Personas que ya habían nacido en abril de 2019 y tienen respuesta válida sobre su lugar de residencia en 2019.",
            "Porcentaje de migración reciente = (personas que en 2019 residían en otra comuna o en otro país / personas con residencia 2019 válida) × 100",
            nota="Indicador quinquenal de cambio de residencia; no es una tasa anualizada.",
        )
    if re.search(r"\btasa\s+(?:de\s+)?migracion\b", q):
        return _base(
            "tasa_migracion_reciente", "p24_lug_resid5", "Porcentaje de migración reciente 2019–2024",
            "Personas que ya habían nacido en abril de 2019 y tienen respuesta válida sobre su lugar de residencia en 2019.",
            "Porcentaje de migración reciente = (personas que en 2019 residían en otra comuna o en otro país / personas con residencia 2019 válida) × 100",
            nota="La expresión genérica «tasa de migración» se interpreta como proporción de migrantes recientes 2019–2024. Es un indicador quinquenal, no una tasa anualizada.",
        )

    # Fecundidad. P48 registra la fecha de la última hija/o nacido vivo y no el
    # número exacto de nacimientos del período. Por ello se expone como una
    # aproximación censal, evitando presentarla como una TGF vital exacta.
    if re.search(r"\btasa\s+global\s+(?:de\s+)?fecundidad\b|\btgf\b", q):
        return _base(
            "tgf_aproximada_censal", "p48_anio_nac_uh", "Tasa global de fecundidad censal aproximada (referencia 2023)",
            "Mujeres de 15 a 49 años con edad válida; el numerador identifica mujeres cuya última hija o hijo nacido vivo nació en 2023.",
            "TGF censal aproximada = 5 × Σ( mujeres del grupo quinquenal de edad cuya última hija/o nació en 2023 / mujeres del mismo grupo quinquenal de edad )",
            nota=(
                "Aproximación censal: P48 informa la fecha de la última hija o hijo nacido vivo, no el número exacto de nacimientos. "
                "Por ello el resultado no reemplaza una TGF calculada con estadísticas vitales y exposición femenina por edad."
            ),
        )

    return None
