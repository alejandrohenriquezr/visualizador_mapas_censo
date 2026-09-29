# -*- coding: utf-8 -*-
"""Resolución determinista de movilidad laboral comunal — Fases 1 y 2.

Fase 1: indicadores simples por comuna (salientes, permanencia, porcentajes y
entrantes).
Fase 2: consultas origen-destino dirigidas, principales destinos/orígenes y
saldo de movilidad laboral comunal.
"""
from __future__ import annotations

import re

from dictionary import VARIABLES, _norm

TIPO = "movilidad_laboral_fase1"
TIPO_F2 = "movilidad_laboral_fase2"
TIPO_F3 = "movilidad_laboral_fase3"

IND_SALIENTES = "salientes_cantidad"
IND_MISMA = "misma_comuna_cantidad"
IND_PCT_SALIENTES = "salientes_porcentaje"
IND_PCT_MISMA = "misma_comuna_porcentaje"
IND_ENTRANTES = "entrantes_cantidad"

IND_FLUJO = "flujo_comunal_cantidad"
IND_DESTINOS = "destinos_principales"
IND_ORIGENES = "origenes_principales"
IND_SALDO = "saldo_comunal"

IND_MATRIZ = "matriz_od_comunal"
IND_RANKING = "ranking_flujos_comunales"


# ---------------------------------------------------------------------------
# Catálogos geográficos controlados
# ---------------------------------------------------------------------------
def _variantes_nombre(nombre: str):
    normal = _norm(nombre).strip()
    variantes = {normal}
    variantes.add(re.sub(r"^(?:comuna|region)\s+(?:de\s+)?", "", normal).strip())
    return {v for v in variantes if v}


_COMUNAS = []
for _codigo, _nombre in VARIABLES.get("geografia", {}).get("comuna", {}).items():
    if not str(_codigo).isdigit():
        continue
    for _variante in _variantes_nombre(_nombre):
        _COMUNAS.append((len(_variante), _variante, int(_codigo), str(_nombre)))
_COMUNAS.sort(reverse=True)

_REGIONES = []
for _codigo, _nombre in VARIABLES.get("geografia", {}).get("region", {}).items():
    if not str(_codigo).isdigit():
        continue
    for _variante in _variantes_nombre(_nombre):
        _REGIONES.append((len(_variante), _variante, int(_codigo), str(_nombre)))
_REGIONES.sort(reverse=True)

# Alias regionales de uso frecuente. Se resuelven contra el catálogo oficial
# para no duplicar códigos ni nombres en el código fuente.
_REGION_ALIAS_NOMBRES = {
    "metropolitana": "Metropolitana de Santiago",
    "rm": "Metropolitana de Santiago",
    "region metropolitana": "Metropolitana de Santiago",
    "aysen": "Aysén del General Carlos Ibáñez del Campo",
    "magallanes": "Magallanes y de la Antártica Chilena",
    "ohiggins": "Libertador General Bernardo O'Higgins",
    "o higgins": "Libertador General Bernardo O'Higgins",
}
_REGION_ALIASES = {}
for _alias, _nombre_objetivo in _REGION_ALIAS_NOMBRES.items():
    for _codigo, _nombre in VARIABLES.get("geografia", {}).get("region", {}).items():
        if str(_codigo).isdigit() and _norm(_nombre) == _norm(_nombre_objetivo):
            _REGION_ALIASES[_norm(_alias)] = {"codigo": int(_codigo), "nombre": str(_nombre)}
            break


def _resolver_comuna(fragmento: str):
    """Resuelve una comuna dentro de un fragmento textual por nombre completo.

    Se prioriza la coincidencia más larga para evitar que ``La Florida`` caiga
    en ``Florida`` o ``San Pedro de La Paz`` en ``San Pedro``.
    """
    q = _norm(fragmento)
    encontrados = []
    for largo, variante, codigo, nombre in _COMUNAS:
        if re.search(r"\b" + re.escape(variante) + r"\b", q):
            encontrados.append((largo, codigo, nombre))
    if not encontrados:
        return None
    max_largo = max(x[0] for x in encontrados)
    mejores = {(codigo, nombre) for largo, codigo, nombre in encontrados if largo == max_largo}
    if len(mejores) != 1:
        raise ValueError("La comuna mencionada no se pudo identificar de forma única.")
    codigo, nombre = next(iter(mejores))
    return {"codigo": codigo, "nombre": nombre}


def _resolver_region_ambito(q: str):
    """Detecta una región usada como ámbito de salida comunal."""
    m = re.search(
        r"\b(?:por|segun)\s+comunas?\s+de\s+(?:la\s+)?region\s+(?:de\s+)?"
        r"(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)",
        q,
    )
    if not m:
        return None
    return _resolver_region_fragmento(m.group("r"))


def _es_porcentaje(q: str) -> bool:
    return bool(re.search(r"\b(?:porcentaje|proporcion|proporción)\b|%", q))


def _base(indicador: str) -> dict:
    porcentaje = indicador in {IND_PCT_SALIENTES, IND_PCT_MISMA}
    destino = indicador == IND_ENTRANTES
    return {
        "tabla": "personas",
        "variable": "p44_lug_trab",
        "categoria_valor": None,
        "operacion": "porcentaje" if porcentaje else "conteo",
        "tipo_consulta": TIPO,
        "movilidad_indicador": indicador,
        "movilidad_geografia": "trabajo" if destino else "residencia",
        "movilidad_controla_geografia": True,
        "nivel_geografico": "comuna",
        "_origen_interpretacion": "movilidad_laboral_fase1",
        "nota_interpretacion": (
            "Universo: personas ocupadas. Para porcentajes, el denominador incluye "
            "personas ocupadas con un único lugar de trabajo territorialmente "
            "identificable en Chile (misma vivienda, misma comuna fuera de la vivienda "
            "u otra comuna). Se excluyen otro país, varias comunas o países, No respuesta "
            "y No aplica."
            if porcentaje else
            "Universo: personas ocupadas."
        ),
    }


def _base_f2(indicador: str, **kwargs) -> dict:
    salida = {
        "tabla": "personas",
        "variable": "p44_lug_trab",
        "categoria_valor": None,
        "operacion": "suma" if indicador == IND_SALDO else "conteo",
        "tipo_consulta": TIPO_F2,
        "movilidad_indicador": indicador,
        "movilidad_geografia": (
            "trabajo" if indicador in {IND_FLUJO, IND_DESTINOS}
            else "residencia" if indicador == IND_ORIGENES
            else "balance"
        ),
        "movilidad_controla_geografia": True,
        "nivel_geografico": "comuna",
        "_origen_interpretacion": "movilidad_laboral_fase2",
        "nota_interpretacion": (
            "Universo: personas ocupadas. Los flujos comunales utilizan residencia actual y lugar de trabajo P44. "
            "Los destinos/orígenes incluyen la misma comuna cuando corresponde; los flujos hacia otra comuna "
            "requieren un código comunal válido en P44. El saldo es entrantes desde otras comunas menos salientes "
            "hacia otras comunas. Se excluyen otro país, varias comunas o países, No respuesta y No aplica."
        ),
    }
    salida.update(kwargs)
    return salida


def _top_n(q: str, defecto: int = 10) -> int:
    patrones = (
        r"\b(?:top|principales?)\s+(\d{1,2})\b",
        r"\b(\d{1,2})\s+(?:principales?|primer[oa]s?)\b",
        r"\btop\s*(\d{1,2})\b",
    )
    for patron in patrones:
        m = re.search(patron, q)
        if m:
            return max(1, min(50, int(m.group(1))))
    return defecto



def _resolver_region_fragmento(fragmento: str):
    """Resuelve una región mencionada dentro de un fragmento libre."""
    q = _norm(fragmento).strip()
    q = re.sub(r"^(?:en|de)\s+(?:la\s+)?region\s+(?:de\s+)?", "", q).strip()
    q = re.sub(r"^(?:la|el|los|las)\s+", "", q).strip()
    if q in _REGION_ALIASES:
        return dict(_REGION_ALIASES[q])
    encontrados = []
    for largo, variante, codigo, nombre in _REGIONES:
        variantes = {variante, re.sub(r"^(?:la|el|los|las)\s+", "", variante).strip()}
        for variante_busqueda in variantes:
            if variante_busqueda and re.search(r"\b" + re.escape(variante_busqueda) + r"\b", q):
                encontrados.append((len(variante_busqueda), codigo, nombre))
    if not encontrados:
        return None
    max_largo = max(x[0] for x in encontrados)
    mejores = {(codigo, nombre) for largo, codigo, nombre in encontrados if largo == max_largo}
    if len(mejores) != 1:
        raise ValueError("La región mencionada no se pudo identificar de forma única.")
    codigo, nombre = next(iter(mejores))
    return {"codigo": codigo, "nombre": nombre}


def _resolver_region_matriz_generica(q: str):
    """Ámbito regional de una consulta genérica de movilidad laboral.

    Frases como «movilidad laboral región Metropolitana» y «movilidad laboral
    por comunas de la región de Los Lagos» se interpretan como flujos entre
    comunas de esa misma región, con origen y destino restringidos al ámbito.
    Las expresiones que asignan roles explícitos a origen/destino se excluyen.
    """
    if not re.search(r"\bmovilidad\s+laboral\b", q):
        return None
    # Indicadores ya definidos en fases anteriores conservan su semántica.
    if re.search(r"\bsaldo\s+(?:de\s+)?movilidad\s+laboral\b", q):
        return None
    if re.search(r"\bregion\s+(?:de\s+)?(?:residencia|origen|trabajo|destino)\b", q):
        return None
    patrones = (
        r"\bpor\s+comunas?\s+de\s+(?:la\s+)?region\s+(?:de\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)",
        r"\bmovilidad\s+laboral\s+(?:en\s+|de\s+)?(?:la\s+)?region\s+(?:de\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)",
    )
    for patron in patrones:
        m = re.search(patron, q)
        if m:
            return _resolver_region_fragmento(m.group("r"))
    return None


def _metrica_fase3(q: str) -> str:
    """Detecta si la matriz muestra conteos o porcentajes de fila/columna."""
    if not _es_porcentaje(q):
        return "cantidad"
    if re.search(r"\b(?:por|segun)\s+(?:comuna\s+de\s+)?(?:residencia|origen|fila)\b|\bporcentaje\s+(?:de|por)\s+(?:fila|origen)\b", q):
        return "porcentaje_origen"
    if re.search(r"\b(?:por|segun)\s+(?:comuna\s+de\s+)?(?:trabajo|destino|columna)\b|\bporcentaje\s+(?:de|por)\s+(?:columna|destino)\b", q):
        return "porcentaje_destino"
    raise ValueError(
        "Para una matriz porcentual de movilidad laboral indica la base: porcentaje por comuna de residencia "
        "o porcentaje por comuna de trabajo."
    )


def _incluir_diagonal_fase3(q: str, por_defecto: bool) -> bool:
    if re.search(r"\b(?:sin|no)\s+incluir\s+(?:la\s+)?(?:misma\s+comuna|diagonal)\b|"
                 r"\bexcluir\s+(?:la\s+)?diagonal\b|\bcomunas?\s+distintas?\b|"
                 r"\bsolo\s+(?:flujos?\s+)?intercomunales?\b", q):
        return False
    if re.search(r"\b(?:incluir|incluyendo)\s+(?:la\s+)?(?:misma\s+comuna|diagonal)\b|"
                 r"\bcon\s+(?:la\s+)?(?:misma\s+comuna|diagonal)\b", q):
        return True
    return por_defecto


def _filtros_persona_fase3(q: str):
    """Filtros deterministas compatibles con la matriz OD.

    Se limita a atributos personales claramente identificables para no inventar
    universos ni mezclar semánticas. Todos se aplican además del universo de
    personas ocupadas.
    """
    filtros = []
    if re.search(r"\b(?:mujer|mujeres|femenin[oa]s?)\b", q):
        filtros.append({"variable": "sexo", "op": "=", "valor": "2", "etiqueta": "mujeres"})
    elif re.search(r"\b(?:hombre|hombres|masculin[oa]s?)\b", q):
        filtros.append({"variable": "sexo", "op": "=", "valor": "1", "etiqueta": "hombres"})

    # Rangos de edad: entre A y B; A o más; A o menos; mayores/menores de A.
    m = re.search(r"\bentre\s+(\d{1,3})\s+y\s+(\d{1,3})\s+anos?\b", q)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        filtros.append({"variable": "edad", "op": "between", "min": a, "max": b,
                        "etiqueta": f"entre {a} y {b} años"})
    else:
        m = re.search(r"\b(\d{1,3})\s+anos?\s+o\s+mas\b", q)
        if m:
            filtros.append({"variable": "edad", "op": ">=", "valor": int(m.group(1)),
                            "etiqueta": f"de {int(m.group(1))} años o más"})
        m = re.search(r"\b(\d{1,3})\s+anos?\s+o\s+menos\b", q)
        if m:
            filtros.append({"variable": "edad", "op": "<=", "valor": int(m.group(1)),
                            "etiqueta": f"de {int(m.group(1))} años o menos"})
        m = re.search(r"\bmayores?\s+(?:de|a)\s+(\d{1,3})\s+anos?\b", q)
        if m:
            filtros.append({"variable": "edad", "op": ">", "valor": int(m.group(1)),
                            "etiqueta": f"mayores de {int(m.group(1))} años"})
        m = re.search(r"\bmenores?\s+(?:de|a)\s+(\d{1,3})\s+anos?\b", q)
        if m:
            filtros.append({"variable": "edad", "op": "<", "valor": int(m.group(1)),
                            "etiqueta": f"menores de {int(m.group(1))} años"})

    if re.search(r"\b(?:con\s+discapacidad|discapacitad[oa]s?)\b", q):
        filtros.append({"variable": "discapacidad", "op": "=", "valor": "1", "etiqueta": "con discapacidad"})

    transporte = [
        (r"\b(?:auto\s+particular|automovil|automóvil)\b", "1", "auto particular"),
        (r"\b(?:transporte\s+publico|transporte\s+público|bus|micro|metro|tren|taxi|colectivo)\b", "2", "transporte público"),
        (r"\b(?:caminando|a\s+pie)\b", "3", "caminando"),
        (r"\b(?:bicicleta|scooter)\b", "4", "bicicleta o scooter"),
        (r"\b(?:motocicleta|moto)\b", "5", "motocicleta"),
        (r"\b(?:caballo|lancha|bote)\b", "6", "caballo, lancha o bote"),
    ]
    for patron, codigo, etiqueta in transporte:
        if re.search(patron, q):
            filtros.append({"variable": "p45_medio_transporte", "op": "=", "valor": codigo, "etiqueta": etiqueta})
            break

    actividades = [
        (r"\bconstruccion\b", "F", "construcción"),
        (r"\b(?:agricultura|ganaderia|silvicultura|pesca)\b", "A", "agricultura, ganadería, silvicultura y pesca"),
        (r"\b(?:mineria|minas|canteras)\b", "B", "minería"),
        (r"\b(?:industria\s+manufacturera|manufactura)\b", "C", "industria manufacturera"),
        (r"\bcomercio\b", "G", "comercio"),
        (r"\b(?:transporte\s+y\s+almacenamiento|almacenamiento)\b", "H", "transporte y almacenamiento"),
        (r"\b(?:ensenanza|enseñanza|educacion)\b", "P", "enseñanza"),
        (r"\b(?:salud|asistencia\s+social)\b", "Q", "salud y asistencia social"),
        (r"\b(?:administracion\s+publica|administración\s+pública)\b", "O", "administración pública"),
    ]
    for patron, codigo, etiqueta in actividades:
        if re.search(patron, q):
            filtros.append({"variable": "cod_caenes", "op": "=", "valor": codigo, "etiqueta": etiqueta})
            break
    return filtros


def _top_n_fase3(q: str, defecto: int = 20) -> int:
    """Top N de Fase 3; admite hasta 100 flujos en ranking/heatmap."""
    for patron in (r"\b(?:top|principales?)\s+(\d{1,3})\b",
                   r"\b(\d{1,3})\s+(?:principales?|primer[oa]s?)\b",
                   r"\btop\s*(\d{1,3})\b"):
        m = re.search(patron, q)
        if m:
            return max(1, min(100, int(m.group(1))))
    return defecto


def _base_f3(indicador: str, consulta: str, **kwargs) -> dict:
    q = _norm(consulta)
    metrica = _metrica_fase3(q)
    # Las matrices de movilidad muestran por defecto solo desplazamientos
    # intercomunales. La permanencia en la misma comuna se incluye únicamente
    # cuando el usuario lo pide explícitamente.
    incluir = _incluir_diagonal_fase3(q, False)
    salida = {
        "tabla": "personas",
        "variable": "p44_lug_trab",
        "categoria_valor": None,
        "operacion": "porcentaje" if metrica != "cantidad" else "conteo",
        "tipo_consulta": TIPO_F3,
        "movilidad_indicador": indicador,
        "movilidad_metrica": metrica,
        "movilidad_incluir_diagonal": incluir,
        "movilidad_top_n": _top_n_fase3(q, 20),
        "movilidad_mostrar_todas": bool(re.search(r"\b(?:tod[oa]s?|completa|completo)\b", q)),
        "movilidad_geografia": "origen_destino",
        "movilidad_controla_geografia": True,
        "nivel_geografico": "comuna",
        "movilidad_filtros_persona": _filtros_persona_fase3(q),
        "_origen_interpretacion": "movilidad_laboral_fase3",
        "nota_interpretacion": (
            "Universo: personas ocupadas con un único lugar de trabajo comunal identificable en Chile. "
            "La comuna de residencia es el origen y la comuna de trabajo es el destino. P44=1/2 se asigna "
            "a la misma comuna de residencia; P44=3 usa el código comunal específico de trabajo. Se excluyen "
            "otro país, varias comunas o países, No respuesta y No aplica. Los porcentajes se calculan dentro "
            "del ámbito visible de la matriz, después de aplicar filtros territoriales y la inclusión/exclusión de la diagonal."
        ),
    }
    salida.update(kwargs)
    return salida


def resolver_movilidad_laboral_fase3(consulta: str):
    q = _norm(consulta)
    region_generica = _resolver_region_matriz_generica(q)
    es_ranking = bool(re.search(r"\b(?:principales?|top\s*\d*)\s+flujos?\s+(?:de\s+)?(?:movilidad\s+)?laboral", q))
    es_matriz = bool(
        re.search(r"\bmatriz\b.*\b(?:movilidad|residencia|trabajo)\b", q)
        or re.search(r"\bmovilidad\s+laboral\s+entre\s+comunas\b", q)
        or re.search(r"\bmovilidad\s+laboral\s+(?:desde|hacia)\b", q)
        or region_generica
    )
    if not (es_matriz or es_ranking):
        return None

    extra = {}
    if region_generica:
        extra.update(
            movilidad_region_origen_codigo=region_generica["codigo"],
            movilidad_region_origen_nombre=region_generica["nombre"],
            movilidad_region_destino_codigo=region_generica["codigo"],
            movilidad_region_destino_nombre=region_generica["nombre"],
        )

    # Comunas dirigidas: «desde Temuco» y «hacia Las Condes».
    m = re.search(r"\bdesde\s+(?P<origen>.+?)(?=$|\s+hacia\b|\s+(?:por|segun|con|sin)\b)", q)
    if m:
        comuna = _resolver_comuna(m.group("origen"))
        if comuna:
            extra.update(movilidad_origen_codigo=comuna["codigo"], movilidad_origen_nombre=comuna["nombre"])
    m = re.search(r"\bhacia\s+(?P<destino>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q)
    if m:
        comuna = _resolver_comuna(m.group("destino"))
        if comuna:
            extra.update(movilidad_destino_codigo=comuna["codigo"], movilidad_destino_nombre=comuna["nombre"])

    # Regiones explícitas por rol.
    m = re.search(r"\bregion\s+(?:de\s+)?(?:residencia|origen)\s+(?P<r>.+?)(?=$|\s+(?:y|region|por|segun|con|sin)\b)", q)
    if m:
        reg = _resolver_region_fragmento(m.group("r"))
        if reg:
            extra.update(movilidad_region_origen_codigo=reg["codigo"], movilidad_region_origen_nombre=reg["nombre"])
    m = re.search(r"\bregion\s+(?:de\s+)?(?:trabajo|destino)\s+(?P<r>.+?)(?=$|\s+(?:y|region|por|segun|con|sin)\b)", q)
    if m:
        reg = _resolver_region_fragmento(m.group("r"))
        if reg:
            extra.update(movilidad_region_destino_codigo=reg["codigo"], movilidad_region_destino_nombre=reg["nombre"])

    # «entre comunas de X» restringe origen y destino a la misma región.
    m = re.search(r"\bentre\s+comunas?\s+de\s+(?:la\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q)
    if m:
        reg = _resolver_region_fragmento(m.group("r"))
        if reg:
            extra.update(
                movilidad_region_origen_codigo=reg["codigo"], movilidad_region_origen_nombre=reg["nombre"],
                movilidad_region_destino_codigo=reg["codigo"], movilidad_region_destino_nombre=reg["nombre"],
            )
    # «matriz ... de las comunas de X» restringe solo origen; destino sigue Chile.
    elif re.search(r"\b(?:matriz|movilidad)\b", q):
        m = re.search(r"\bde\s+las?\s+comunas?\s+de\s+(?:la\s+)?(?P<r>.+?)(?=$|\s+(?:por|segun|con|sin)\b)", q)
        if m:
            reg = _resolver_region_fragmento(m.group("r"))
            if reg:
                extra.update(movilidad_region_origen_codigo=reg["codigo"], movilidad_region_origen_nombre=reg["nombre"])

    return _base_f3(IND_RANKING if es_ranking else IND_MATRIZ, consulta, **extra)

def resolver_movilidad_laboral_fase2(consulta: str):
    q = _norm(consulta)

    # 1. Saldo comunal: se resuelve antes de la regla genérica de Fase 1.
    if re.search(r"\bsaldo\s+(?:de\s+)?(?:movilidad|desplazamiento)\s+laboral\b", q):
        ambito = _resolver_region_ambito(q)
        extra = {}
        if ambito:
            extra.update({
                "filtro_geografico_nivel": "region",
                "filtro_geografico_codigo": ambito["codigo"],
                "movilidad_ambito_nombre": ambito["nombre"],
            })
        return _base_f2(IND_SALDO, **extra)

    # 2. Flujo dirigido entre dos comunas.
    flujo = re.search(
        r"\b(?:personas?|ocupad[oa]s?|trabajadores?)\b.*?"
        r"\b(?:viven?|residen?)\s+en\s+(?P<origen>.+?)\s+y\s+"
        r"(?:trabajan?|laboran?)\s+en\s+(?P<destino>.+?)"
        r"(?=$|\s+(?:por|segun)\b)",
        q,
    )
    if flujo:
        origen = _resolver_comuna(flujo.group("origen"))
        destino = _resolver_comuna(flujo.group("destino"))
        if not origen or not destino:
            raise ValueError(
                "Para calcular un flujo laboral dirigido se deben identificar una comuna de residencia y una comuna de trabajo válidas."
            )
        return _base_f2(
            IND_FLUJO,
            movilidad_origen_codigo=origen["codigo"],
            movilidad_origen_nombre=origen["nombre"],
            movilidad_destino_codigo=destino["codigo"],
            movilidad_destino_nombre=destino["nombre"],
        )

    # 3. Principales destinos desde una comuna de residencia.
    destino_patterns = (
        r"\b(?:principales?\s+)?destinos?\s+laborales?\s+(?:de|para)\s+"
        r"(?:(?:las?\s+personas\s+)?(?:que\s+)?|quienes\s+)(?:viven?|residen?)\s+en\s+(?P<origen>.+?)(?=$|\s+por\b|\s+segun\b)",
        r"\b(?:en\s+)?que\s+comunas?\s+trabajan?\s+(?:las?\s+)?personas\s+que\s+"
        r"(?:viven?|residen?)\s+en\s+(?P<origen>.+?)(?=$|\s+por\b|\s+segun\b)",
    )
    for patron in destino_patterns:
        m = re.search(patron, q)
        if not m:
            continue
        origen = _resolver_comuna(m.group("origen"))
        if not origen:
            raise ValueError("No se pudo identificar la comuna de residencia para calcular los destinos laborales.")
        solo_externos = bool(re.search(r"\b(?:otras?\s+comunas?|fuera\s+de\s+su\s+comuna)\b", q))
        return _base_f2(
            IND_DESTINOS,
            movilidad_origen_codigo=origen["codigo"],
            movilidad_origen_nombre=origen["nombre"],
            movilidad_top_n=_top_n(q),
            movilidad_solo_externos=solo_externos,
        )

    # 4. Principales orígenes de quienes trabajan en una comuna.
    origen_patterns = (
        r"\b(?:de\s+)?que\s+(?:otras?\s+)?comunas?\s+(?:provienen|vienen)\s+(?:las?\s+)?personas\s+que\s+"
        r"trabajan?\s+en\s+(?P<destino>.+?)(?=$|\s+por\b|\s+segun\b)",
        r"\b(?:principales?\s+)?(?:origenes?|comunas?\s+de\s+residencia)\s+(?:de|para)\s+"
        r"(?:(?:las?\s+personas\s+)?(?:que\s+)?|quienes\s+)trabajan?\s+en\s+(?P<destino>.+?)(?=$|\s+por\b|\s+segun\b)",
    )
    for patron in origen_patterns:
        m = re.search(patron, q)
        if not m:
            continue
        destino = _resolver_comuna(m.group("destino"))
        if not destino:
            raise ValueError("No se pudo identificar la comuna de trabajo para calcular los orígenes laborales.")
        solo_externos = bool(re.search(r"\b(?:otras?\s+comunas?|desde\s+otra\s+comuna)\b", q))
        return _base_f2(
            IND_ORIGENES,
            movilidad_destino_codigo=destino["codigo"],
            movilidad_destino_nombre=destino["nombre"],
            movilidad_top_n=_top_n(q),
            movilidad_solo_externos=solo_externos,
        )

    return None


def resolver_movilidad_laboral_fase1(consulta: str):
    q = _norm(consulta)

    # La fase 1 es comunal. Si la consulta pide explícitamente región como nivel
    # de salida, se deja a futuras fases en vez de reinterpretarla en silencio.
    if re.search(r"\bpor\s+regiones?\b", q) and not re.search(r"\bpor\s+comunas?\b", q):
        return None

    # Entrada laboral: el código geográfico de salida es la comuna de trabajo.
    if re.search(
        r"\b(?:personas?|trabajadores?|ocupad[oa]s?)\s+que\s+"
        r"(?:llegan|vienen)\s+(?:desde|de)\s+otra\s+comuna\s+(?:a|para)\s+trabajar\b",
        q,
    ) or re.search(r"\bentrantes?\s+laborales?\b", q):
        return _base(IND_ENTRANTES)

    fuera = bool(re.search(
        r"\btrabaj(?:a|an)\s+fuera\s+de\s+(?:su|la)\s+comuna\b|"
        r"\btrabaj(?:a|an)\s+en\s+otra\s+comuna\b|"
        r"\bsal(?:e|en)\s+de\s+(?:su|la)\s+comuna\s+(?:a|para)\s+trabajar\b|"
        r"\bmovilidad\s+laboral\s+intercomunal\b",
        q,
    ))
    misma = bool(re.search(
        r"\btrabaj(?:a|an)\s+en\s+(?:su\s+)?misma\s+comuna\b|"
        r"\btrabaj(?:a|an)\s+en\s+la\s+misma\s+comuna\s+(?:donde|en\s+que)\s+"
        r"(?:vive|viven|reside|residen)\b|"
        r"\btrabaj(?:a|an)\s+dentro\s+de\s+(?:su|la)\s+comuna\b|"
        r"\bautocontencion\s+laboral\b",
        q,
    ))

    if fuera:
        return _base(IND_PCT_SALIENTES if _es_porcentaje(q) else IND_SALIENTES)
    if misma:
        return _base(IND_PCT_MISMA if _es_porcentaje(q) else IND_MISMA)

    # Una consulta genérica no tiene una única definición. En vez de escoger en
    # silencio, se orienta al usuario hacia los indicadores implementados.
    if re.search(r"\b(?:movilidad|desplazamiento)\s+laboral\b", q) and re.search(r"\bcomun", q):
        raise ValueError(
            "La movilidad laboral comunal puede medirse de varias formas. Especifica una consulta como: "
            "personas ocupadas que trabajan fuera de su comuna; personas que llegan desde otra comuna a trabajar; "
            "saldo de movilidad laboral por comuna; personas que viven en Maipú y trabajan en Santiago; "
            "principales destinos laborales de quienes viven en Temuco; o de qué comunas provienen quienes trabajan en Las Condes."
        )

    return None


def resolver_movilidad_laboral(consulta: str):
    """Resuelve Fase 3, luego Fase 2 y finalmente conserva Fase 1."""
    resultado = (resolver_movilidad_laboral_fase3(consulta)
                 or resolver_movilidad_laboral_fase2(consulta)
                 or resolver_movilidad_laboral_fase1(consulta))
    if resultado:
        # El normalizador geográfico histórico se omite para movilidad porque
        # las comunas mencionadas pueden ser origen/destino. Recuperamos solo
        # un ámbito regional explícito del tipo «por comuna de la región de X».
        if resultado.get("filtro_geografico_nivel") is None:
            ambito = _resolver_region_ambito(_norm(consulta))
            if ambito:
                resultado["filtro_geografico_nivel"] = "region"
                resultado["filtro_geografico_codigo"] = ambito["codigo"]
                resultado["movilidad_ambito_nombre"] = ambito["nombre"]
        return resultado
    return None
