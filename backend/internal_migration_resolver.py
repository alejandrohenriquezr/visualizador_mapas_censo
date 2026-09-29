# -*- coding: utf-8 -*-
"""Resolución determinista de migración interna 2019–2024.

Origen: comuna/región de residencia en abril de 2019 (P24).
Destino: comuna/región de residencia actual en Censo 2024.

Se excluyen del universo de migración interna:
- aún no nacía en abril de 2019;
- residencia en otro país;
- No respuesta / No aplica;
- códigos no identificables como comuna chilena.
"""
from __future__ import annotations

import re

from dictionary import _norm
from labor_mobility_resolver import (
    _resolver_comuna,
    _resolver_region_fragmento,
    _top_n_fase3,
)

TIPO_IND = "migracion_interna_indicadores"
TIPO_OD = "migracion_interna_od"

IND_INMIGRANTES = "inmigrantes_internos"
IND_EMIGRANTES = "emigrantes_internos"
IND_SALDO = "saldo_migratorio_interno"
IND_MATRIZ = "matriz_migracion_interna"
IND_RANKING = "ranking_flujos_migratorios"
IND_FLUJO = "flujo_migratorio_dirigido"
IND_DESTINOS = "destinos_migratorios_principales"
IND_ORIGENES = "origenes_migratorios_principales"


def _nivel(q: str, defecto: str = "comuna") -> str:
    if re.search(r"\b(?:entre|por|segun|matriz\s+de).*\bregiones?\b|\bflujos?.*\bregiones?\b", q):
        return "region"
    if re.search(r"\b(?:entre|por|segun|matriz\s+de).*\bcomunas?\b|\bflujos?.*\bcomunas?\b", q):
        return "comuna"
    return defecto


def _metrica(q: str) -> str:
    if not re.search(r"\b(?:porcentaje|proporcion|proporción)\b|%", q):
        return "cantidad"
    if re.search(r"\b(?:por|segun)\s+(?:comuna|region)?\s*(?:de\s+)?(?:origen|residencia\s+2019|residencia\s+en\s+2019|fila)\b|\bporcentaje\s+(?:de|por)\s+(?:fila|origen)\b", q):
        return "porcentaje_origen"
    if re.search(r"\b(?:por|segun)\s+(?:comuna|region)?\s*(?:de\s+)?(?:destino|residencia\s+actual|columna)\b|\bporcentaje\s+(?:de|por)\s+(?:columna|destino)\b", q):
        return "porcentaje_destino"
    raise ValueError(
        "Para una matriz porcentual de migración interna indica la base: porcentaje por territorio de origen "
        "(residencia en 2019) o porcentaje por territorio de destino (residencia actual)."
    )


def _incluir_diagonal(q: str, por_defecto: bool = False) -> bool:
    if re.search(r"\b(?:incluir|incluyendo|con)\s+(?:la\s+)?(?:diagonal|permanencia|misma\s+comuna|misma\s+region)\b", q):
        return True
    if re.search(r"\b(?:sin|no\s+incluir|excluir|excluyendo)\s+(?:la\s+)?(?:diagonal|permanencia|misma\s+comuna|misma\s+region)\b", q):
        return False
    return por_defecto


def _filtros_persona(q: str):
    filtros = []
    if re.search(r"\b(?:mujer|mujeres|femenin[oa]s?)\b", q):
        filtros.append({"variable": "sexo", "op": "=", "valor": "2", "etiqueta": "mujeres"})
    elif re.search(r"\b(?:hombre|hombres|masculin[oa]s?)\b", q):
        filtros.append({"variable": "sexo", "op": "=", "valor": "1", "etiqueta": "hombres"})

    m = re.search(r"\bentre\s+(\d{1,3})\s+y\s+(\d{1,3})\s+anos?\b", q)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        filtros.append({"variable": "edad", "op": "between", "min": a, "max": b,
                        "etiqueta": f"entre {a} y {b} años"})
    else:
        for patron, op, plantilla in (
            (r"\b(\d{1,3})\s+anos?\s+o\s+mas\b", ">=", "de {n} años o más"),
            (r"\b(\d{1,3})\s+anos?\s+o\s+menos\b", "<=", "de {n} años o menos"),
            (r"\bmayores?\s+(?:de|a)\s+(\d{1,3})\s+anos?\b", ">", "mayores de {n} años"),
            (r"\bmenores?\s+(?:de|a)\s+(\d{1,3})\s+anos?\b", "<", "menores de {n} años"),
        ):
            m = re.search(patron, q)
            if m:
                n = int(m.group(1))
                filtros.append({"variable": "edad", "op": op, "valor": n, "etiqueta": plantilla.format(n=n)})
                break

    if re.search(r"\b(?:con\s+discapacidad|discapacitad[oa]s?)\b", q):
        filtros.append({"variable": "discapacidad", "op": "=", "valor": "1", "etiqueta": "con discapacidad"})
    return filtros


def _base_od(indicador: str, consulta: str, nivel: str, **kwargs) -> dict:
    q = _norm(consulta)
    metrica = _metrica(q)
    salida = {
        "tabla": "personas",
        "variable": "p24_lug_resid5",
        "categoria_valor": None,
        "operacion": "porcentaje" if metrica != "cantidad" else "conteo",
        "tipo_consulta": TIPO_OD,
        "migracion_indicador": indicador,
        "migracion_nivel": nivel,
        "migracion_metrica": metrica,
        "migracion_incluir_diagonal": _incluir_diagonal(q, False),
        "migracion_top_n": _top_n_fase3(q, 20),
        "migracion_mostrar_todas": bool(re.search(r"\b(?:tod[oa]s?|completa|completo)\b", q)),
        "migracion_filtros_persona": _filtros_persona(q),
        "nivel_geografico": nivel,
        "migracion_controla_geografia": True,
        "_origen_interpretacion": "migracion_interna_2019_2024",
        "nota_interpretacion": (
            "Migración interna 2019–2024. Universo: personas que ya habían nacido en abril de 2019 y residían en Chile, "
            "con comuna de residencia 2019 identificable. P24='En esta comuna' asigna como origen la comuna actual; "
            "P24='En otra comuna' usa el código específico de P24. Se excluyen quienes aún no nacían, residían en otro país, "
            "No respuesta, No aplica y códigos no identificables como comuna chilena. La residencia actual es el destino."
        ),
    }
    salida.update(kwargs)
    return salida


def _base_ind(indicador: str, nivel: str, **kwargs) -> dict:
    salida = {
        "tabla": "personas",
        "variable": "p24_lug_resid5",
        "categoria_valor": None,
        "operacion": "suma" if indicador == IND_SALDO else "conteo",
        "tipo_consulta": TIPO_IND,
        "migracion_indicador": indicador,
        "migracion_nivel": nivel,
        "nivel_geografico": nivel,
        "migracion_controla_geografia": True,
        "_origen_interpretacion": "migracion_interna_2019_2024",
        "nota_interpretacion": (
            "Migración interna 2019–2024. Se consideran únicamente personas con residencia en Chile en abril de 2019 "
            "y territorio de origen identificable. Los movimientos internacionales, quienes aún no nacían, No respuesta y No aplica se excluyen."
        ),
    }
    salida.update(kwargs)
    return salida


def _resolver_territorio(fragmento: str, nivel: str):
    return _resolver_comuna(fragmento) if nivel == "comuna" else _resolver_region_fragmento(fragmento)


def _ambito_region_comunal(q: str):
    m = re.search(r"\bpor\s+comunas?\s+de\s+(?:la\s+)?region\s+(?:de\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q)
    if not m:
        return None
    return _resolver_region_fragmento(m.group("r"))


def resolver_migracion_interna(consulta: str):
    q = _norm(consulta)
    es_migracion_explicita = bool(re.search(r"\b(?:migracion\s+interna|migratorio|migratorios|inmigrantes?\s+internos?|emigrantes?\s+internos?|saldo\s+migratorio)\b", q))
    es_flujo_temporal = bool(re.search(r"\b(?:vivia|vivian|residia|residian)\b.*\b2019\b", q) and re.search(r"\b(?:ahora|actualmente)\s+(?:vive|viven|reside|residen)\b", q))
    es_destino_temporal = bool(re.search(r"\b(?:destinos?|se\s+fueron)\b.*\b(?:vivia|vivian|residia|residian)\b.*\b2019\b", q))
    es_origen_temporal = bool(re.search(r"\b(?:provienen|origenes?)\b.*\b(?:ahora|actualmente)\b.*\b(?:vive|viven|reside|residen)\b", q))
    if not (es_migracion_explicita or es_flujo_temporal or es_destino_temporal or es_origen_temporal):
        return None

    # Indicadores simples por territorio.
    for patron, indicador in (
        (r"\binmigrantes?\s+internos?\b", IND_INMIGRANTES),
        (r"\bemigrantes?\s+internos?\b", IND_EMIGRANTES),
        (r"\bsaldo\s+(?:de\s+)?migratorio\s+interno\b|\bsaldo\s+de\s+migracion\s+interna\b", IND_SALDO),
    ):
        if re.search(patron, q):
            nivel = _nivel(q, "region")
            extra = {"migracion_filtros_persona": _filtros_persona(q)}
            if nivel == "comuna":
                reg = _ambito_region_comunal(q)
                if reg:
                    extra.update(migracion_ambito_region_codigo=reg["codigo"], migracion_ambito_region_nombre=reg["nombre"])
            return _base_ind(indicador, nivel, **extra)

    # Flujo dirigido: residencia 2019 X -> residencia actual Y.
    flujo = re.search(
        r"\b(?:personas?|quienes)\b.*?\b(?:vivian?|residian?)\s+en\s+(?P<origen>.+?)\s+en\s+(?:abril\s+de\s+)?2019\s+y\s+"
        r"(?:ahora|actualmente)\s+(?:viven?|residen?)\s+en\s+(?P<destino>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q
    )
    if flujo:
        # Por defecto nombres sueltos son comunas; "región de" fuerza región.
        nivel = "region" if ("region" in flujo.group("origen") or "region" in flujo.group("destino")) else "comuna"
        origen = _resolver_territorio(flujo.group("origen"), nivel)
        destino = _resolver_territorio(flujo.group("destino"), nivel)
        if not origen or not destino:
            raise ValueError("No se pudieron identificar de forma única los territorios de origen 2019 y destino actual.")
        return _base_od(
            IND_FLUJO, consulta, nivel,
            migracion_origen_codigo=origen["codigo"], migracion_origen_nombre=origen["nombre"],
            migracion_destino_codigo=destino["codigo"], migracion_destino_nombre=destino["nombre"],
            migracion_incluir_diagonal=(int(origen["codigo"]) == int(destino["codigo"])),
        )

    # Destinos desde un territorio de origen 2019.
    m = re.search(
        r"\b(?:principales?\s+)?destinos?\s+(?:migratorios?\s+)?(?:de|para)\s+(?:quienes|las?\s+personas\s+que)\s+"
        r"(?:vivian?|residian?)\s+en\s+(?P<origen>.+?)\s+en\s+(?:abril\s+de\s+)?2019(?=$|\s+(?:por|segun|con|sin)\b)", q
    ) or re.search(
        r"\ba\s+que\s+(?P<nivel>comunas?|regiones?)\s+se\s+fueron\s+(?:las?\s+)?personas\s+que\s+(?:vivian?|residian?)\s+en\s+"
        r"(?P<origen>.+?)\s+en\s+(?:abril\s+de\s+)?2019", q
    )
    if m:
        nivel = "region" if (m.groupdict().get("nivel") or "").startswith("region") or "region" in m.group("origen") else "comuna"
        origen = _resolver_territorio(m.group("origen"), nivel)
        if not origen:
            raise ValueError("No se pudo identificar el territorio de residencia en 2019.")
        return _base_od(IND_DESTINOS, consulta, nivel,
                        migracion_origen_codigo=origen["codigo"], migracion_origen_nombre=origen["nombre"])

    # Orígenes hacia territorio actual.
    m = re.search(
        r"\bde\s+que\s+(?P<nivel>comunas?|regiones?)\s+provienen\s+(?:quienes|las?\s+personas\s+que)\s+(?:ahora|actualmente)\s+"
        r"(?:viven?|residen?)\s+en\s+(?P<destino>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q
    ) or re.search(
        r"\b(?:principales?\s+)?origenes?\s+(?:migratorios?\s+)?(?:de|para)\s+(?:quienes|las?\s+personas\s+que)\s+"
        r"(?:ahora|actualmente)\s+(?:viven?|residen?)\s+en\s+(?P<destino>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q
    )
    if m:
        nivel = "region" if (m.groupdict().get("nivel") or "").startswith("region") or "region" in m.group("destino") else "comuna"
        destino = _resolver_territorio(m.group("destino"), nivel)
        if not destino:
            raise ValueError("No se pudo identificar el territorio de residencia actual.")
        return _base_od(IND_ORIGENES, consulta, nivel,
                        migracion_destino_codigo=destino["codigo"], migracion_destino_nombre=destino["nombre"])

    es_ranking = bool(re.search(r"\b(?:principales?|top\s*\d*|\d+\s+principales?)\s+flujos?\s+migratorios?\b", q))
    es_matriz = bool(
        re.search(r"\bmatriz\b.*\b(?:migracion|migratoria|residencia)\b", q)
        or re.search(r"\bmigracion\s+interna\s+entre\s+(?:comunas?|regiones?)\b", q)
    )
    if es_matriz or es_ranking:
        nivel = _nivel(q, "comuna")
        extra = {}

        # Ámbito regional para matrices comunales.
        # "por comunas de la región X" describe el dominio de la matriz completa,
        # por lo que se restringen origen (residencia 2019) y destino (residencia actual).
        reg = _ambito_region_comunal(q)
        if reg:
            extra.update(
                migracion_region_origen_codigo=reg["codigo"], migracion_region_origen_nombre=reg["nombre"],
                migracion_region_destino_codigo=reg["codigo"], migracion_region_destino_nombre=reg["nombre"],
            )
        else:
            m = re.search(r"\bentre\s+comunas?\s+de\s+(?:la\s+)?region\s+(?:de\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q)
            if m:
                reg = _resolver_region_fragmento(m.group("r"))
                if reg:
                    extra.update(
                        migracion_region_origen_codigo=reg["codigo"], migracion_region_origen_nombre=reg["nombre"],
                        migracion_region_destino_codigo=reg["codigo"], migracion_region_destino_nombre=reg["nombre"],
                    )
            else:
                m = re.search(r"\bde\s+las?\s+comunas?\s+de\s+(?:la\s+)?region\s+(?:de\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q)
                if m:
                    reg = _resolver_region_fragmento(m.group("r"))
                    if reg:
                        extra.update(migracion_region_origen_codigo=reg["codigo"], migracion_region_origen_nombre=reg["nombre"])

        return _base_od(IND_RANKING if es_ranking else IND_MATRIZ, consulta, nivel, **extra)

    if re.search(r"\bmigracion\s+interna\s+por\s+(?:comuna|region)\b", q):
        raise ValueError(
            "La migración interna puede analizarse como inmigrantes internos, emigrantes internos, saldo migratorio interno o matriz origen–destino. "
            "Especifica el indicador que deseas analizar."
        )
    return None
