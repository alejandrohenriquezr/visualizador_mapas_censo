# -*- coding: utf-8 -*-
"""Resolución centralizada de denominadores para porcentajes/proporciones.

La regla de diseño es conservadora:
- si la consulta nombra explícitamente el denominador, se respeta;
- si un indicador censal tiene una definición metodológica estable, no se reabre;
- si una consulta compuesta admite más de un universo razonable, se devuelve
  una ambigüedad para que la interfaz pregunte antes de calcular;
- la selección del usuario queda registrada en la intención y, cuando se usa
  QueryPlan v2, se materializa como un AST de denominador separado del numerador.
"""
from __future__ import annotations

from copy import deepcopy
import re

from dictionary import VARIABLES, _norm


class AmbiguedadDenominador(ValueError):
    """La pregunta requiere escoger explícitamente el universo denominador."""

    def __init__(self, mensaje: str, opciones: list[dict]):
        super().__init__(mensaje)
        self.opciones = opciones


_STOP = {
    "el", "la", "los", "las", "de", "del", "al", "un", "una", "unos", "unas",
    "total", "totales", "sobre", "respecto", "entre", "como", "base", "universo",
    "en", "por", "para", "y", "o", "que", "con", "sin",
}

# Variables que suelen definir un subgrupo demográfico/estructural, no el evento
# o condición cuyo porcentaje se quiere medir. Se usa solo para generar opciones
# cuando el QueryPlan ya contiene, además, otra condición distinta.
_CONTEXTO = {
    "personas": {
        "edad", "edad_quinquenal", "sexo", "p25_lug_nacimiento", "p25_lug_nacimiento_rec",
        "p25_lug_nacimiento_esp", "p27_nacionalidad", "p27_nacionalidad_rec",
        "p27_nacionalidad_esp", "p28_autoid_pueblo", "p29_afrodescendencia_rec",
    },
    "hogares": {"tipologia_hogar"},
    "viviendas": {"p2_tipo_vivienda", "tipo_operativo"},
}

_ENTIDAD_SINGULAR = {"personas": "persona", "hogares": "hogar", "viviendas": "vivienda"}
_ENTIDAD_PLURAL = {"personas": "personas", "hogares": "hogares", "viviendas": "viviendas"}


def _and(items):
    items = [deepcopy(x) for x in items if isinstance(x, dict)]
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return {"op": "and", "args": items}


def _hojas_and(nodo):
    """Aplana solo conjunciones; OR/NOT se dejan como una hoja indivisible."""
    if not isinstance(nodo, dict):
        return []
    if nodo.get("op") == "and":
        out = []
        for item in nodo.get("args") or []:
            out.extend(_hojas_and(item))
        return out
    return [nodo]


def _texto_filtro(filtro: dict, objetivo: str) -> str:
    tabla = filtro.get("tabla")
    variable = filtro.get("variable")
    tipo = filtro.get("tipo")
    if tabla not in VARIABLES or variable not in VARIABLES[tabla].get("variables", {}):
        return "subgrupo indicado"
    info = VARIABLES[tabla]["variables"][variable]
    desc = str(info.get("descripcion") or variable)
    if tipo == "rango":
        minimo = filtro.get("minimo")
        maximo = filtro.get("maximo")
        if variable == "edad":
            if minimo is not None and maximo is None:
                op = "o más" if filtro.get("incluir_minimo", True) else "y más"
                if filtro.get("incluir_minimo", True):
                    return f"{_ENTIDAD_PLURAL.get(objetivo, objetivo)} de {int(minimo)} años o más"
                return f"{_ENTIDAD_PLURAL.get(objetivo, objetivo)} mayores de {int(minimo)} años"
            if minimo is not None and maximo is not None:
                return f"{_ENTIDAD_PLURAL.get(objetivo, objetivo)} entre {int(minimo)} y {int(maximo)} años"
        return f"{_ENTIDAD_PLURAL.get(objetivo, objetivo)} según {desc}"
    if tipo == "categoria":
        cats = info.get("categorias") or {}
        etiquetas = [str(cats.get(str(v), v)) for v in (filtro.get("valores") or [])]
        if etiquetas:
            return f"{_ENTIDAD_PLURAL.get(objetivo, objetivo)} con {desc}: {' / '.join(etiquetas)}"
    return f"{_ENTIDAD_PLURAL.get(objetivo, objetivo)} del subgrupo indicado"


def _capturar_denominador_explicito(consulta: str) -> str | None:
    q = _norm(consulta)
    cortes = r"(?=\s+(?:por|segun)\s+(?:region|regiones|comuna|comunas|provincia|provincias|sexo|edad)\b|$)"
    patrones = [
        rf"\b(?:sobre|respecto\s+(?:de|del)|entre)\s+(?:el\s+)?total\s+de\s+(.+?){cortes}",
        rf"\b(?:sobre|respecto\s+(?:de|del)|entre)\s+(.+?){cortes}",
        rf"\bdel\s+total\s+de\s+(.+?){cortes}",
    ]
    for patron in patrones:
        m = re.search(patron, q)
        if m:
            frase = re.sub(r"\s+", " ", m.group(1)).strip(" .,:;")
            if frase:
                return frase
    return None


def _tokens(texto: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", _norm(texto))
        if len(t) >= 3 and t not in _STOP
    }


def _score_candidato(frase: str, candidato: dict) -> int:
    ft = _tokens(frase)
    if not ft:
        return 0
    textos = [
        candidato.get("titulo", ""), candidato.get("descripcion", ""),
        candidato.get("universo", ""), *(candidato.get("aliases") or []),
    ]
    frase_norm = re.sub(r"\s+", " ", _norm(frase)).strip(" .,:;")
    mejor = 0
    for texto in textos:
        texto_norm = re.sub(r"\s+", " ", _norm(str(texto))).strip(" .,:;")
        if frase_norm and frase_norm == texto_norm:
            return 250
        ct = _tokens(str(texto))
        if not ct:
            continue
        inter = len(ft & ct)
        # Prioriza cobertura de la frase explícita, no longitud de la opción.
        score = int(round(100 * inter / max(1, len(ft))))
        if ft <= ct:
            score += 30
        mejor = max(mejor, score)
    return mejor


def _opciones_publicas(candidatos: list[dict]) -> list[dict]:
    return [
        {
            "id": c["id"],
            "titulo": c.get("titulo") or "Usar este denominador",
            "descripcion": c.get("descripcion") or c.get("universo") or "",
        }
        for c in candidatos
    ]


def _inferir_candidatos_queryplan(intencion: dict) -> list[dict]:
    """Genera opciones conservadoras para un porcentaje compuesto QueryPlan v2."""
    plan = intencion.get("plan_cruce") or {}
    pct = plan.get("porcentaje")
    if not pct or int(plan.get("version", 1) or 1) < 2:
        return []
    objetivo = plan.get("entidad_objetivo")
    if objetivo not in _ENTIDAD_PLURAL:
        return []
    hojas = _hojas_and(plan.get("filtro_ast"))
    if len(hojas) < 2:
        return []

    contexto = [
        f for f in hojas
        if f.get("tabla") == objetivo and f.get("variable") in _CONTEXTO.get(objetivo, set())
        and f.get("tipo") in {"categoria", "rango"}
    ]
    otros = [f for f in hojas if f not in contexto]
    candidatos = []
    if contexto and otros:
        partes = [_texto_filtro(f, objetivo) for f in contexto]
        etiqueta = " y ".join(dict.fromkeys(partes))
        candidatos.append({
            "id": "subgrupo_contexto",
            "titulo": f"Sobre el total de {etiqueta}",
            "descripcion": f"El denominador conserva solo el subgrupo de contexto: {etiqueta}.",
            "universo": etiqueta[:1].upper() + etiqueta[1:] + ".",
            "denominador_ast": _and(contexto),
            "aliases": [etiqueta],
        })

    plural = _ENTIDAD_PLURAL[objetivo]
    candidatos.append({
        "id": "total_entidad",
        "titulo": f"Sobre el total de {plural}",
        "descripcion": f"El denominador es el total de {plural} del territorio, sin aplicar las condiciones del numerador.",
        "universo": f"Total de {plural} del territorio.",
        "denominador_ast": None,
        "aliases": [plural, f"total {plural}", f"poblacion total" if objetivo == "personas" else plural],
    })
    # Sin subgrupo alternativo no hay una decisión real: se usa el único
    # denominador razonable automáticamente.
    return candidatos


def _aplicar(intencion: dict, candidato: dict, origen: str) -> dict:
    salida = deepcopy(intencion)
    salida["denominador_id"] = candidato["id"]
    salida["denominador_descripcion"] = candidato.get("descripcion") or candidato.get("universo")
    salida["denominador_confirmacion"] = origen
    salida["denominador_requirio_confirmacion"] = origen == "seleccion_usuario"
    if candidato.get("universo"):
        salida["universo"] = candidato["universo"]

    formula = candidato.get("formula")
    if not formula:
        desc = (
            salida.get("descripcion_personalizada")
            or salida.get("indicador_descripcion")
            or "casos que cumplen las condiciones del numerador"
        )
        den = candidato.get("titulo") or "el denominador seleccionado"
        formula = f"Porcentaje = ({desc} / {den.lower()}) × 100"
    salida["formula"] = formula

    plan = salida.get("plan_cruce") or {}
    if plan.get("porcentaje") is not None:
        plan = deepcopy(plan)
        pct = deepcopy(plan.get("porcentaje") or {"base": "total", "factor": 100.0})
        pct["base"] = "total"
        pct["denominador_personalizado"] = True
        pct["denominador_ast"] = deepcopy(candidato.get("denominador_ast"))
        pct["denominador_id"] = candidato["id"]
        plan["porcentaje"] = pct
        salida["plan_cruce"] = plan
    return salida


def resolver_denominador(consulta: str, intencion: dict, seleccion: str | None = None) -> dict:
    """Aplica, pregunta o infiere el denominador de una intención ya resuelta."""
    if not isinstance(intencion, dict):
        return intencion
    operacion = str(intencion.get("operacion") or "").lower()
    if operacion not in {"porcentaje", "porcentaje_rango", "razon"}:
        return intencion
    if intencion.get("denominador_definido"):
        return intencion

    candidatos = deepcopy(intencion.get("denominador_candidatos") or [])
    if not candidatos:
        # Las tasas/índices del catálogo poseen una definición metodológica
        # estable. Solo las consultas genéricas/compuestas se someten a diálogo.
        if intencion.get("tipo_consulta") == "indicador_censal_v27":
            return intencion
        candidatos = _inferir_candidatos_queryplan(intencion)

    if not candidatos:
        # Caso simple categórico: si el texto explicita "sobre el total de la
        # entidad" y no existen filtros adicionales, se respeta literalmente.
        frase = _capturar_denominador_explicito(consulta)
        tabla = intencion.get("tabla")
        if (frase and tabla in _ENTIDAD_PLURAL and operacion == "porcentaje"
                and not intencion.get("edad_minima") and not intencion.get("filtros_numericos")):
            entidad = _ENTIDAD_PLURAL[tabla]
            if _score_candidato(frase, {"titulo": entidad, "aliases": [entidad, "poblacion"]}) >= 80:
                salida = deepcopy(intencion)
                salida["denominador_entidad_total"] = True
                salida["denominador_id"] = "total_entidad"
                salida["denominador_confirmacion"] = "explicito_en_pregunta"
                salida["universo"] = f"Total de {entidad} del territorio."
                salida["formula"] = f"Porcentaje = (casos de la categoría solicitada / total de {entidad} del territorio) × 100"
                return salida
        return intencion

    # Asegura identificadores únicos y no expone el AST en la respuesta HTTP.
    vistos = set()
    candidatos = [c for c in candidatos if c.get("id") and not (c["id"] in vistos or vistos.add(c["id"]))]
    if not candidatos:
        return intencion

    if seleccion:
        elegido = next((c for c in candidatos if c["id"] == seleccion), None)
        if elegido is None:
            raise ValueError("El denominador seleccionado ya no es válido para esta consulta.")
        return _aplicar(intencion, elegido, "seleccion_usuario")

    frase = _capturar_denominador_explicito(consulta)
    if frase:
        puntuados = sorted((( _score_candidato(frase, c), c) for c in candidatos), key=lambda x: x[0], reverse=True)
        if puntuados and puntuados[0][0] >= 80 and (len(puntuados) == 1 or puntuados[0][0] - puntuados[1][0] >= 20):
            return _aplicar(intencion, puntuados[0][1], "explicito_en_pregunta")
        # Si el usuario sí nombró un denominador pero el sistema no lo puede
        # asociar con seguridad, no lo sustituye silenciosamente.
        raise AmbiguedadDenominador(
            f"Se detectó un denominador explícito («{frase}»), pero puede corresponder a más de una base. Selecciona la interpretación correcta o reformula la pregunta.",
            _opciones_publicas(candidatos),
        )

    if len(candidatos) == 1:
        return _aplicar(intencion, candidatos[0], "unico_candidato")

    raise AmbiguedadDenominador(
        "La pregunta solicita un porcentaje, pero no indica de forma inequívoca el denominador. Selecciona el universo que debe usarse o reformula la pregunta incluyendo expresiones como «sobre el total de…».",
        _opciones_publicas(candidatos),
    )
