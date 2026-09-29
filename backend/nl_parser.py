# -*- coding: utf-8 -*-
"""
Interpreta una consulta en español en lenguaje natural y la transforma en
una "intención" estructurada que el motor de datos (data_engine.py) puede
ejecutar directamente contra los parquet + la cartografía.

Usa un LLM liviano corriendo LOCALMENTE vía Ollama (http://localhost:11434).
No se hace ninguna llamada a internet ni a APIs externas: si Ollama no está
corriendo, se usa un modo de respaldo (heurístico, sin LLM) para que la
aplicación nunca quede totalmente bloqueada.

Modelos locales recomendados (livianos, con buen español):
    ollama pull qwen2.5:3b-instruct     # recomendado, ~2 GB, rápido en CPU
    ollama pull llama3.2:3b             # alternativa liviana
    ollama pull gemma2:2b               # aún más liviano si tu equipo es limitado
"""
import json
import re
import requests
import logging
import os
from time import perf_counter, monotonic
from collections import OrderedDict
from copy import deepcopy
from threading import RLock

from dictionary import (
    VARIABLES,
    _norm,
    filtro_geografico_explicito,
    nombres_geograficos,
    buscar_variables,
    buscar_geografia,
    detectar_nivel_geografico,
    detectar_operacion,
    TABLAS_PARQUET,
    categorias_validas,
    es_ambito_nacional,
)
from semantic_catalog import resolver_indicador
from range_resolver import resolver_rango_numerico
from categorical_resolver import (
    AmbiguedadVariable,
    resolver_referencia_censo,
    resolver_operacion_omitida,
    resolver_distribucion,
    resolver_porcentaje_generico,
    resolver_conteo_categoria,
    resolver_variable_categorica_explicita,
    resolver_variable_por_descripcion,
)
from language_normalizer import normalizar_consulta, terminos_ambiguos_presentes
from colloquial_resolver import resolver_rasgo_booleano, resolver_territorio_especifico
from disability_resolver import resolver_discapacidad, PREFIJO_SELECCION_SEVERIDAD
from education_resolver import resolver_educacion
from cross_query_planner import resolver_cruce
from advanced_query_planner import resolver_consulta_avanzada
from labor_mobility_resolver import resolver_movilidad_laboral
from internal_migration_resolver import resolver_migracion_interna
from priority_indicator_resolver import resolver_prioritario_v24
from census_indicator_resolver import resolver_indicador_censal_v27
from denominator_resolver import resolver_denominador
from union_resolver import (
    resolver_ambiguedad_union,
    consulta_sin_union_territorial,
    consulta_sin_union_geografica,
    UNION_COMUNA,
    UNION_PARENTESCO,
    UNION_ESTADO_CIVIL,
    CODIGO_LA_UNION,
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate").strip()
MODELO_LLM = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct").strip()
TIMEOUT_SEG = float(os.getenv("OLLAMA_TIMEOUT", "30"))
LOG = logging.getLogger("uvicorn.error")
_INTERPRETACION_LOCK = RLock()
_CACHE_INTERPRETACIONES = OrderedDict()
# Tras un timeout evita repetir inmediatamente una espera de 30 segundos.
OLLAMA_REINTENTO_SEG = max(1.0, float(os.getenv("OLLAMA_REINTENTO_SEG", "60")))
_OLLAMA_REINTENTAR_DESDE = 0.0


def _construir_prompt(consulta: str, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto):
    """Prompt restringido: el LLM elige un índice, nunca inventa identificadores."""
    lineas_var = []
    for i, c in enumerate(candidatos_var):
        cats = ""
        if c["categorias"]:
            pares = ", ".join(
                f'{k}="{v}"' for k, v in list(c["categorias"].items())[:12]
            )
            cats = f" | valores posibles: {pares}"
        lineas_var.append(
            f'{i}. {c["descripcion"]} [tabla={c["tabla"]}, variable={c["variable"]}]{cats}'
        )

    lineas_geo = [
        f'- {g["nivel"]}: "{g["nombre"]}" (codigo={g["codigo"]})'
        for g in candidatos_geo
    ]
    return f"""Traduce la pregunta del Censo de Chile a JSON. Solo JSON.
El campo candidato DEBE ser un entero de la lista y no puedes inventar variables.
Variables candidatas:
{chr(10).join(lineas_var) or "ninguna"}
Territorios candidatos:
{chr(10).join(lineas_geo) or "ninguno"}
Claves: candidato, categoria_valor, operacion,
filtro_geografico_nivel, filtro_geografico_codigo.
Operacion: conteo, porcentaje o promedio (predeterminado: {operacion_defecto}).
Categoria: usa solo un codigo mostrado para el candidato; si no corresponde, null.
Filtro: region/provincia/comuna y codigo solo si hay un lugar concreto.
"Por region/comuna/provincia" es agregacion, no filtro.
No inventes nombres de variables, categorias ni codigos.
Pregunta: {consulta}
"""


def _materializar_intencion_llm(intencion, candidatos_var):
    """Convierte el índice elegido por Ollama en identificadores ya validados."""
    if not isinstance(intencion, dict):
        raise ValueError("La respuesta del modelo no es un objeto JSON.")
    indice = intencion.get("candidato")
    try:
        indice = int(indice)
    except (TypeError, ValueError) as exc:
        raise ValueError("El modelo no seleccionó un candidato válido.") from exc
    if indice < 0 or indice >= len(candidatos_var):
        raise ValueError("El modelo seleccionó un candidato fuera de la lista permitida.")
    candidato = candidatos_var[indice]
    salida = dict(intencion)
    salida.pop("candidato", None)
    salida["tabla"] = candidato["tabla"]
    salida["variable"] = candidato["variable"]
    return salida

def _llamar_ollama(prompt: str) -> str:
    inicio = perf_counter()
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODELO_LLM,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0.0, "num_predict": 256},
        },
        timeout=TIMEOUT_SEG,
    )
    resp.raise_for_status()
    data = resp.json()
    LOG.info("[tiempo] ollama=%.3fs carga=%.3fs prompt=%.3fs generacion=%.3fs",
             perf_counter() - inicio, data.get("load_duration", 0) / 1e9,
             data.get("prompt_eval_duration", 0) / 1e9,
             data.get("eval_duration", 0) / 1e9)
    return data.get("response", "")


def _extraer_json(texto: str):
    texto = texto.strip()
    texto = re.sub(r"^```(json)?", "", texto).strip()
    texto = re.sub(r"```$", "", texto).strip()
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError("El modelo no devolvió JSON reconocible")
    return json.loads(match.group(0))


def _respaldo_heuristico(consulta: str, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto):
    """Respaldo conservador: solo usa un candidato textual claramente dominante."""
    if not candidatos_var:
        return None
    mejor = candidatos_var[0]
    score = int(mejor.get("_score", 0))
    segundo = int(candidatos_var[1].get("_score", 0)) if len(candidatos_var) > 1 else 0
    if score < 5 or (segundo and score - segundo < 2):
        return None
    categoria_valor = None
    q = _norm(consulta)
    for codigo, etiqueta in mejor["categorias"].items():
        etiqueta_norm = _norm(etiqueta).strip()
        if len(etiqueta_norm) >= 4 and re.search(r"\b" + re.escape(etiqueta_norm) + r"\b", q):
            categoria_valor = codigo
            break
    return {
        "tabla": mejor["tabla"],
        "variable": mejor["variable"],
        "categoria_valor": categoria_valor,
        "operacion": operacion_defecto,
        "nivel_geografico": nivel_defecto,
        "filtro_geografico_nivel": None,
        "filtro_geografico_codigo": None,
    }

def _resolver_promedio_explicito(consulta, nivel, operacion):
    """Ruta rápida conservadora: variable única y sin términos sin interpretar."""
    if operacion != "promedio":
        return None
    q = _norm(consulta)
    geo = filtro_geografico_explicito(consulta)
    menciones = buscar_geografia(consulta, top_n=100)
    if menciones and geo is None:
        # «Antofagasta» sin nivel puede designar más de un territorio.
        return None
    candidatos = []
    for tabla in TABLAS_PARQUET:
        for variable, info in VARIABLES[tabla]["variables"].items():
            descripcion = _norm(info["descripcion"]).strip()
            # No se deduce que una variable categórica sea continua.
            if info["categorias"]:
                continue
            frase = descripcion if len(descripcion.split()) >= 2 else ""
            if frase and re.search(r"\b" + re.escape(frase) + r"\b", q):
                candidatos.append((tabla, variable, frase))
            elif "escolaridad" in descripcion and re.search(r"\bescolaridad\b", q):
                candidatos.append((tabla, variable, "escolaridad"))
    if len(candidatos) != 1:
        return None
    tabla, variable, frase = candidatos[0]
    resto = re.sub(r"\b" + re.escape(frase) + r"\b", " ", q)
    resto = re.sub(r"\b\d{1,3}\s+anos?\s+o\s+mas\b", " ", resto)
    if geo:
        # Solo retira el nombre del filtro seleccionado, no otros lugares.
        nombre = re.sub(r"^(?:region|provincia|comuna)\s+(?:de\s+)?", "", geo["nombre_norm"])
        resto = re.sub(r"\b" + re.escape(nombre) + r"\b", " ", resto)
    permitidas = set("mapea mapa mapear muestra mostrar muestrame dame ver quiero "
                     "el la los las de del en por un una a para y promedio media "
                     "anos ano poblacion personas cada nivel comuna comunas comunal "
                     "provincia provincias provincial region regiones regional".split())
    if set(re.findall(r"[a-z0-9]+", resto)) - permitidas:
        # Por ejemplo «mujeres», «rural» o una negación requieren el LLM.
        return None
    return {"tabla": tabla, "variable": variable, "categoria_valor": None,
            "operacion": operacion, "filtro_geografico_nivel": geo["nivel"] if geo else None,
            "filtro_geografico_codigo": geo["codigo"] if geo else None}


def _resolver_total_entidad(consulta, operacion):
    """Conteo total de personas, hogares o viviendas sin inventar una categoría."""
    if operacion != "conteo":
        return None
    q = _norm(consulta)

    # Viviendas particulares es una categoría del tipo operativo, no sinónimo
    # de todas las filas de la tabla viviendas.
    if re.search(r"\bviviendas?\s+particulares?\b", q):
        info = VARIABLES["viviendas"]["variables"].get("tipo_operativo", {})
        candidatos = [str(c) for c, e in info.get("categorias", {}).items()
                      if _norm(e).strip() == "vivienda particular"]
        if len(candidatos) == 1:
            return {
                "tabla": "viviendas", "variable": "tipo_operativo",
                "categoria_valor": candidatos[0], "operacion": "conteo",
                "indicador_descripcion": "Cantidad de viviendas particulares",
                "_origen_interpretacion": "total_entidad",
            }

    patrones = {
        "personas": r"\b(?:personas?|poblacion|gente|habitantes?)\b",
        "hogares": r"\bhogares?\b",
        "viviendas": r"\bviviendas?\b",
    }
    encontradas = [tabla for tabla, patron in patrones.items() if re.search(patron, q)]
    if len(encontradas) != 1:
        return None
    tabla = encontradas[0]
    resto = re.sub(patrones[tabla], " ", q)
    # Retira primero los nombres territoriales completos. Hacerlo después de
    # borrar artículos/preposiciones rompía nombres oficiales compuestos como
    # "Magallanes y de la Antártica Chilena" o "Aysén del General...".
    for geo in buscar_geografia(consulta, top_n=100):
        for nombre in nombres_geograficos(geo):
            resto = re.sub(r"\b" + re.escape(nombre) + r"\b", " ", resto)
    resto = re.sub(r"\b(?:cantidad|numero|total|conteo|cuantos?|cuantas?|hay|de|del|la|el|los|las|en|para|por|a|nivel|cada|y)\b", " ", resto)
    resto = re.sub(r"\b(?:region|regiones|regional|provincia|provincias|provincial|comuna|comunas|comunal|rm)\b", " ", resto)
    if re.findall(r"[a-z0-9]+", resto):
        return None
    variable = {"personas": "id_persona", "hogares": "id_hogar", "viviendas": "id_vivienda"}[tabla]
    return {
        "tabla": tabla, "variable": variable, "categoria_valor": None,
        "operacion": "conteo",
        "indicador_descripcion": f"Cantidad total de {tabla}",
        "_origen_interpretacion": "total_entidad",
    }


def _normalizar_filtro_territorial(consulta, intencion):
    """Ancla el filtro a lugares del texto, nunca solo al nivel que da el LLM."""
    geo = filtro_geografico_explicito(consulta)
    if geo:
        intencion["filtro_geografico_nivel"] = geo["nivel"]
        intencion["filtro_geografico_codigo"] = geo["codigo"]
        return
    # Usa límites de palabra para descartar coincidencias parciales de nombres.
    q = _norm(consulta)
    candidatos = [g for g in buscar_geografia(consulta, top_n=100)
                  if any(re.search(r"\b" + re.escape(nombre) + r"\b", q)
                         for nombre in nombres_geograficos(g))]
    if not candidatos:
        # Si hay una solicitud territorial explícita pero desconocida, no
        # convertirla silenciosamente en una consulta nacional.
        if re.search(r"\b(?:en|para|dentro de)\s+(?:la\s+)?"
                     r"(?:region|provincia|comuna)\s+de\s+\w+", q):
            raise ValueError("No se reconoció el territorio solicitado en el diccionario geográfico.")
        # «Por región» por sí solo no restringe ninguna unidad geográfica.
        if intencion.get("filtro_geografico_nivel") is not None or intencion.get("filtro_geografico_codigo") is not None:
            LOG.info("[interpretacion] filtro del LLM descartado: no hay un lugar concreto en la pregunta")
        intencion["filtro_geografico_nivel"] = None
        intencion["filtro_geografico_codigo"] = None
        return
    # Una mención única permite completar ambos campos aun con un JSON parcial.
    unicos = {(g["nivel"], str(g["codigo"])): g for g in candidatos}
    if len(unicos) == 1:
        geo = next(iter(unicos.values()))
    else:
        # En homónimos solo acepta una elección completa compatible con el texto.
        nivel = intencion.get("filtro_geografico_nivel")
        codigo = str(intencion.get("filtro_geografico_codigo"))
        compatibles = [g for g in unicos.values() if g["nivel"] == nivel
                       and codigo.isdigit() and str(g["codigo"]).isdigit()
                       and int(codigo) == int(g["codigo"])]
        if len(compatibles) != 1:
            raise ValueError("El lugar mencionado es ambiguo; indicar región, provincia o comuna y su nombre.")
        geo = compatibles[0]
    intencion["filtro_geografico_nivel"] = geo["nivel"]
    intencion["filtro_geografico_codigo"] = geo["codigo"]


def _asegurar_categoria_nacimiento(consulta, intencion):
    """Impide contar toda la población al omitirse la categoría de nacimiento."""
    q = _norm(consulta)
    if not re.search(r"\bnacid[oa]s?\s+(?:fuera de chile|en (?:el )?extranjero|en otro pais)\b", q):
        return
    opciones = []
    # Los códigos salen del diccionario del usuario, no se presupone un valor.
    for variable, info in VARIABLES["personas"]["variables"].items():
        descripcion = _norm(info["descripcion"])
        if not re.search(r"\b(?:nacimiento|nacer|nacio|nacid[oa]s?)\b", descripcion):
            continue
        for codigo, etiqueta in info["categorias"].items():
            etiqueta = _norm(etiqueta).strip().rstrip(".")
            if re.fullmatch(r"(?:en (?:el )?)?extranjero|(?:en )?otro pais|"
                            r"(?:nacid[oa]s? )?fuera de chile|(?:en )?un pais distinto (?:a|de) chile", etiqueta):
                opciones.append((variable, codigo))
    elegidas = [o for o in opciones if intencion.get("tabla") == "personas"
                and o[0] == intencion.get("variable")]
    if len(elegidas) == 1:
        variable, codigo = elegidas[0]
    elif len(opciones) == 1:
        variable, codigo = opciones[0]
    else:
        raise ValueError("No se identificó de forma inequívoca la categoría de personas nacidas fuera de Chile. "
                         "Revisar la variable de lugar de nacimiento y sus categorías en diccionario_variables.json.")
    intencion["tabla"] = "personas"
    intencion["variable"] = variable
    intencion["categoria_valor"] = codigo
    intencion["operacion"] = detectar_operacion(consulta)
    if intencion["operacion"] == "porcentaje":
        intencion["denominador_valores"] = categorias_validas("personas", variable)


def _resolver_nacimiento_explicito(consulta, operacion):
    """Conteo/porcentaje de nacidos fuera de Chile con condiciones reconocidas."""
    q = _norm(consulta)
    patron = r"\bnacid[oa]s?\s+(?:fuera de chile|en (?:el )?extranjero|en otro pais)\b"
    if operacion not in ("conteo", "porcentaje") or not re.search(patron, q):
        return None
    resto = re.sub(patron, " ", q)
    resto = re.sub(r"\b\d{1,3}\s+anos?\s+o\s+mas\b", " ", resto)
    geo = filtro_geografico_explicito(consulta)
    if geo:
        for nombre in nombres_geograficos(geo):
            resto = re.sub(r"\b" + re.escape(nombre) + r"\b", " ", resto)
    elif buscar_geografia(consulta, top_n=100):
        return None
    permitidas = set("cantidad numero total conteo porcentaje proporcion personas poblacion "
                     "de del la el los las por cada a nivel en para y mapea mapa "
                     "muestra muestrame dame ver quiero region regiones regional "
                     "comuna comunas comunal provincia provincias provincial".split())
    if set(re.findall(r"[a-z0-9]+", resto)) - permitidas:
        return None
    intencion = {"operacion": operacion}
    _asegurar_categoria_nacimiento(consulta, intencion)
    _normalizar_filtro_territorial(consulta, intencion)
    return intencion


def _resolver_sexo_explicito(consulta, operacion):
    """Resuelve conteos por sexo solo si todas las restricciones son reconocidas."""
    q = _norm(consulta)
    grupos = [(r"\bmujeres\b|\bmujer\b", {"mujer", "mujeres", "femenino", "femenina"}, "mujeres"),
              (r"\bhombres\b|\bhombre\b", {"hombre", "hombres", "masculino", "masculina"}, "hombres")]
    coincidencias = [(patron, etiquetas, nombre) for patron, etiquetas, nombre in grupos
                     if re.search(patron, q)]
    if operacion not in ("conteo", "porcentaje") or len(coincidencias) != 1:
        return None
    patron, etiquetas, nombre = coincidencias[0]
    resto = re.sub(patron, " ", q)
    resto = re.sub(r"\b\d{1,3}\s+anos?\s+o\s+mas\b", " ", resto)
    geo = filtro_geografico_explicito(consulta)
    if geo:
        for lugar in nombres_geograficos(geo):
            resto = re.sub(r"\b" + re.escape(lugar) + r"\b", " ", resto)
    elif buscar_geografia(consulta, top_n=100):
        return None
    permitidas = set("cantidad numero total conteo porcentaje proporcion personas poblacion "
                     "de del la el los las por cada a nivel en para dame mapea mapa "
                     "muestra muestrame ver quiero region regiones regional "
                     "comuna comunas comunal provincia provincias provincial".split())
    if set(re.findall(r"[a-z0-9]+", resto)) - permitidas:
        # No reemplaza preguntas sobre hijas, madres, nacimientos u otros filtros.
        return None
    opciones = []
    for variable, info in VARIABLES["personas"]["variables"].items():
        descripcion = _norm(info["descripcion"])
        # Solo sexo de la persona, nunca sexo/cantidad de familiares.
        if not re.search(r"\bsexo\b", descripcion):
            continue
        if re.search(r"\b(?:hij[oa]s?|madre|padre|pareja|conyuge|jef[ea]|nacimient[oa]s?)\b", descripcion):
            continue
        for codigo, etiqueta in info["categorias"].items():
            if _norm(etiqueta).strip().rstrip(".") in etiquetas:
                opciones.append((variable, codigo))
    if len(opciones) != 1:
        raise ValueError("No se identificó de forma única la variable de sexo y su categoría. "
                         "Se necesita revisar data/diccionario_variables.json para evitar un conteo incorrecto.")
    variable, codigo = opciones[0]
    intencion = {"tabla": "personas", "variable": variable, "categoria_valor": codigo,
                 "operacion": operacion, "_grupo_personas": nombre}
    if operacion == "porcentaje":
        intencion["denominador_valores"] = categorias_validas("personas", variable)
    _normalizar_filtro_territorial(consulta, intencion)
    return intencion


def _interpretar_consulta(consulta: str, tabla_seleccionada=None,
                          variable_seleccionada=None,
                          operacion_seleccionada=None,
                          denominador_seleccionado=None) -> dict:
    """Punto de entrada principal: consulta en texto -> intención estructurada."""
    inicio = perf_counter()
    normalizacion = normalizar_consulta(consulta)
    consulta_original = consulta
    consulta = normalizacion["texto"]

    # «Unión» es intrínsecamente ambigua en este dominio: puede ser la comuna
    # La Unión, el parentesco Conviviente por unión civil o el estado conyugal
    # Conviviente civil. Nunca se elige una de las tres lecturas en silencio.
    union_seleccion = resolver_ambiguedad_union(
        consulta_original, tabla_seleccionada, variable_seleccionada
    )
    union_geo_override = None
    consulta_geo = consulta
    if union_seleccion:
        # Las opciones de Unión son sintéticas y ya fueron resueltas aquí; no
        # deben entrar al mecanismo genérico de variable_forzada.
        tabla_seleccionada = None
        variable_seleccionada = None
        if union_seleccion == UNION_COMUNA:
            consulta = consulta_sin_union_territorial(consulta) or "personas"
            consulta_geo = consulta
            union_geo_override = {"nivel": "comuna", "codigo": CODIGO_LA_UNION}
        else:
            # Para las dos lecturas censales, «Unión» no debe convertirse en
            # filtro territorial de la comuna La Unión.
            consulta_geo = consulta_sin_union_geografica(consulta)

    # Si el usuario entregó un código territorial explícito, ese código es la
    # fuente de verdad. El nombre oficial añadido por el normalizador solo
    # ayuda al análisis semántico y no debe sustituir la identidad territorial
    # (hay nombres homónimos, como Florida / La Florida).
    filtro_codigo_explicito = next((
        item for item in normalizacion.get("aliases_aplicados", [])
        if item.get("tipo") == "codigo_geografico"
    ), None)
    candidatos_var = buscar_variables(consulta, top_n=6)
    if tabla_seleccionada and variable_seleccionada:
        info_forzada = VARIABLES.get(tabla_seleccionada, {}).get(
            "variables", {}).get(variable_seleccionada)
        if info_forzada:
            candidatos_var = [{
                "tabla": tabla_seleccionada, "variable": variable_seleccionada,
                "descripcion": info_forzada["descripcion"],
                "categorias": info_forzada["categorias"],
            }]
    candidatos_geo = buscar_geografia(consulta_geo, top_n=5)
    nivel_defecto = detectar_nivel_geografico(consulta)
    operacion_defecto = detectar_operacion(consulta)

    LOG.info("[tiempo] candidatos=%.3fs", perf_counter() - inicio)
    global _OLLAMA_REINTENTAR_DESDE

    # El motor avanzado antecede al planificador histórico solo cuando detecta
    # lógica compuesta, medidas, porcentajes cruzados, tercera dimensión,
    # recodificaciones o agregación jerárquica. Las consultas simples siguen
    # utilizando las rutas verificadas de versiones anteriores.
    # El motor avanzado necesita conservar puntuación significativa (p.ej.
    # rangos 0-14 o listas 5, 8 y 13), pero también debe beneficiarse de las
    # correcciones ortográficas del normalizador. Por eso aplicamos solo las
    # correcciones de tokens sobre el texto original, sin reemplazar su
    # puntuación por espacios.
    consulta_avanzada = consulta_original
    for corr in normalizacion.get("correcciones", []):
        original = str(corr.get("original") or "").strip()
        corregido = str(corr.get("corregido") or "").strip()
        if original and corregido:
            consulta_avanzada = re.sub(
                r"\b" + re.escape(original) + r"\b", corregido,
                consulta_avanzada, flags=re.I,
            )
    # Migración interna y movilidad laboral se resuelven antes del planificador
    # general porque ambas usan relaciones origen-destino cuya geografía no se
    # puede reducir a un único filtro territorial de residencia actual.
    intencion = resolver_migracion_interna(consulta_original)
    if intencion is None:
        intencion = resolver_movilidad_laboral(consulta_original)
    # Categorías específicas e indicadores derivados verificados tienen
    # prioridad sobre cruces/distribuciones genéricas.
    if intencion is None:
        intencion = resolver_indicador_censal_v27(consulta_original)
    if intencion is None:
        intencion = resolver_prioritario_v24(consulta_original)
    if intencion is None:
        intencion = resolver_consulta_avanzada(
            consulta_avanzada, seleccion_operacion=operacion_seleccionada,
            union_seleccion=union_seleccion,
            tabla_seleccionada=tabla_seleccionada,
            variable_seleccionada=variable_seleccionada,
        )
    if intencion is None and not (tabla_seleccionada or variable_seleccionada or operacion_seleccionada):
        intencion = resolver_cruce(consulta, union_seleccion=union_seleccion)

    # Discapacidad se resuelve antes del catálogo genérico porque la variable
    # derivada y las seis dimensiones P32 representan conceptos distintos.
    if intencion is None:
        intencion = resolver_discapacidad(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )

    # Educación se resuelve antes del catálogo genérico para distinguir la
    # pregunta 33 de las variables derivadas de asistencia por nivel.
    if intencion is None:
        intencion = resolver_educacion(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )

    # Si la consulta reproduce o resume claramente una pregunta censal, esa
    # descripción tiene prioridad sobre coincidencias parciales y aliases.
    if intencion is None and operacion_seleccionada is None:
        intencion = resolver_variable_por_descripcion(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )

    # Un año distinto de 2024 solo abre selección cuando la propia pregunta
    # censal no fue reconocida antes (p.ej. residencia en abril de 2019).
    if intencion is None:
        resolver_referencia_censo(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )

    # Países/territorios específicos se resuelven antes del LLM. Un demónimo
    # aislado (p.ej. "venezolanos") no permite distinguir nacimiento/nacionalidad.
    if intencion is None:
        territorio = resolver_territorio_especifico(consulta)
        if territorio and territorio.get("_ambiguedad") == "nacimiento_nacionalidad":
            opciones = []
            for variable in ("p25_lug_nacimiento_esp", "p27_nacionalidad_esp"):
                info = VARIABLES["personas"]["variables"][variable]
                opciones.append({
                    "tabla": "personas", "variable": variable,
                    "descripcion": info["descripcion"],
                    "categorias_ejemplo": [territorio["territorio"]["etiqueta"]],
                    "puntaje": 100,
                })
            raise AmbiguedadVariable(
                "La expresión puede referirse al lugar de nacimiento o a la nacionalidad. "
                "Selecciona la variable correcta.",
                opciones,
            )
        intencion = territorio if territorio and not territorio.get("_ambiguedad") else None

    # Los cálculos registrados se resuelven con el diccionario antes del LLM.
    # La prioridad es: distribución explícita -> indicadores -> categorías
    # específicas -> variable categórica nombrada -> diálogo de operación.
    # Si la interfaz ya resolvió una operación, esa decisión del usuario tiene
    # prioridad. Para «cantidad» se vuelve a extraer la categoría del texto,
    # de modo que no se pierda un filtro como «Red pública».
    if intencion is None and operacion_seleccionada and variable_seleccionada:
        intencion = resolver_operacion_omitida(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
            operacion_forzada=operacion_seleccionada,
        )

    if intencion is None:
        intencion = resolver_distribucion(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )
    if intencion is None:
        intencion = resolver_indicador(consulta)
    if intencion is None:
        intencion = resolver_rasgo_booleano(consulta)
    if intencion is None:
        intencion = resolver_porcentaje_generico(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )
    if intencion is None:
        intencion = _resolver_sexo_explicito(consulta, operacion_defecto)
    if intencion is None:
        intencion = _resolver_nacimiento_explicito(consulta, operacion_defecto)
    if intencion is None:
        intencion = resolver_rango_numerico(consulta)
    if intencion is None:
        intencion = resolver_conteo_categoria(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )
    if intencion is None:
        intencion = resolver_variable_categorica_explicita(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
        )
    if intencion is None:
        intencion = resolver_operacion_omitida(
            consulta, tabla_forzada=tabla_seleccionada,
            variable_forzada=variable_seleccionada,
            operacion_forzada=operacion_seleccionada,
        )
    if intencion is None and not (tabla_seleccionada or variable_seleccionada):
        intencion = _resolver_total_entidad(consulta, operacion_defecto)
    if intencion is None:
        intencion = _resolver_promedio_explicito(consulta, nivel_defecto, operacion_defecto)
    origen = (intencion.get("_origen_interpretacion", "reglas_verificadas")
              if intencion else "llm_local")
    if intencion is None and operacion_defecto == "razon":
        raise ValueError(
            "El índice solicitado no tiene una fórmula registrada. "
            "Agrégalo al catálogo semántico indicando numerador, denominador y factor."
        )
    if intencion is None:
        try:
            if not candidatos_var:
                raise ValueError("No hay variables candidatas válidas para consultar al modelo.")
            if monotonic() < _OLLAMA_REINTENTAR_DESDE:
                raise requests.RequestException("Ollama en pausa temporal después de un fallo")
            prompt = _construir_prompt(consulta, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto)
            texto_llm = _llamar_ollama(prompt)
            intencion = _materializar_intencion_llm(_extraer_json(texto_llm), candidatos_var)
            _OLLAMA_REINTENTAR_DESDE = 0.0
        except (requests.RequestException, ValueError, TypeError) as exc:
            # La pausa no se prolonga con cada consulta recibida.
            if monotonic() >= _OLLAMA_REINTENTAR_DESDE:
                _OLLAMA_REINTENTAR_DESDE = monotonic() + OLLAMA_REINTENTO_SEG
            LOG.warning("[tiempo] interpretacion_llm_fallida=%.3fs: %s", perf_counter() - inicio, exc)
            origen = f"respaldo_heuristico (LLM no disponible: {exc})"
            intencion = _respaldo_heuristico(consulta, candidatos_var, candidatos_geo, nivel_defecto, operacion_defecto)

    # Repara nacimiento con el diccionario ANTES de rechazar nombres del LLM.
    # En la versión anterior el error de esquema impedía llegar a esta regla.
    if isinstance(intencion, dict):
        _asegurar_categoria_nacimiento(consulta, intencion)
        if (tabla_seleccionada and variable_seleccionada
                and not str(variable_seleccionada).startswith(PREFIJO_SELECCION_SEVERIDAD)):
            info_forzada = VARIABLES.get(tabla_seleccionada, {}).get(
                "variables", {}).get(variable_seleccionada)
            if info_forzada is None:
                raise ValueError("La variable seleccionada no existe en el diccionario.")
            intencion["tabla"] = tabla_seleccionada
            intencion["variable"] = variable_seleccionada
            categoria = intencion.get("categoria_valor")
            if categoria is not None and str(categoria) not in {
                    str(c) for c in info_forzada["categorias"]}:
                intencion["categoria_valor"] = None

    if not intencion or not intencion.get("tabla") or not intencion.get("variable"):
        raise ValueError(
            "No se pudo identificar una variable del censo relacionada con la pregunta. "
            "Intenta reformularla usando términos como: sexo, edad, migración, "
            "pueblos indígenas, hacinamiento, internet, vivienda, escolaridad, etc."
        )

    # No permite que una respuesta del modelo inserte identificadores SQL.
    tabla = intencion["tabla"]
    variable = intencion["variable"]
    if tabla not in TABLAS_PARQUET or variable not in VARIABLES[tabla]["variables"]:
        LOG.warning("[interpretacion] identificadores no válidos: tabla=%r variable=%r; candidatos=%s",
                    tabla, variable, [(c["tabla"], c["variable"]) for c in candidatos_var])
        raise ValueError("El modelo seleccionó una tabla o variable que no existe en el diccionario.")
    # El nivel se fija con reglas verificables, aunque el LLM sugiera otro.
    # «Chile» sin nivel explícito produce un mapa regional y no un filtro.
    if intencion.get("migracion_controla_geografia"):
        intencion["nivel_geografico"] = intencion.get("migracion_nivel") or "comuna"
    elif intencion.get("movilidad_controla_geografia"):
        intencion["nivel_geografico"] = "comuna"
    else:
        intencion["nivel_geografico"] = (
            "region" if es_ambito_nacional(consulta)
            and detectar_nivel_geografico(consulta) == "region"
            else nivel_defecto
        )
    # Normaliza los null textuales antes de reparar el filtro del modelo.
    for campo in ("categoria_valor", "filtro_geografico_nivel", "filtro_geografico_codigo"):
        valor = intencion.get(campo)
        if isinstance(valor, str) and valor.strip().lower() in ("null", "none", ""):
            intencion[campo] = None
    selecciones_geo_plan = (intencion.get("plan_cruce") or {}).get("selecciones_geograficas") or []
    if intencion.get("migracion_controla_geografia"):
        # Los territorios mencionados son roles temporales origen/destino, no
        # un único filtro geográfico histórico.
        intencion.setdefault("filtro_geografico_nivel", None)
        intencion.setdefault("filtro_geografico_codigo", None)
    elif intencion.get("movilidad_controla_geografia"):
        # Las comunas mencionadas pueden ser origen/destino laboral y no filtros
        # del mapa. El resolutor de movilidad es la fuente de verdad geográfica.
        intencion.setdefault("filtro_geografico_nivel", None)
        intencion.setdefault("filtro_geografico_codigo", None)
    elif selecciones_geo_plan:
        # Una selección múltiple del QueryPlan avanzado es la fuente de verdad.
        # No se llama al normalizador histórico porque, ante varios nombres
        # territoriales válidos, éste intenta forzar un único lugar y puede
        # declarar la consulta ambigua antes de que el plan IN(...) se ejecute.
        intencion["filtro_geografico_nivel"] = None
        intencion["filtro_geografico_codigo"] = None
    else:
        _normalizar_filtro_territorial(consulta_geo, intencion)
    if filtro_codigo_explicito and not selecciones_geo_plan:
        intencion["filtro_geografico_nivel"] = filtro_codigo_explicito["nivel"]
        intencion["filtro_geografico_codigo"] = filtro_codigo_explicito["codigo"]
    if union_geo_override:
        intencion["filtro_geografico_nivel"] = union_geo_override["nivel"]
        intencion["filtro_geografico_codigo"] = union_geo_override["codigo"]
    # Un filtro territorial no puede ser más específico que la capa del mapa.
    # Si se pide "en la comuna de X" sin decir "por comuna", se muestra esa
    # comuna en vez de intentar filtrar una capa regional con un código comunal.
    orden_geo = {"region": 0, "provincia": 1, "comuna": 2}
    f_nivel_tmp = intencion.get("filtro_geografico_nivel")
    if f_nivel_tmp and orden_geo[f_nivel_tmp] > orden_geo[intencion["nivel_geografico"]]:
        intencion["nivel_geografico"] = f_nivel_tmp
    tabla = intencion["tabla"]
    variable = intencion["variable"]
    if intencion.get("operacion") not in (
            "conteo", "porcentaje", "porcentaje_rango", "promedio", "mediana",
            "suma", "minimo", "maximo", "razon", "distribucion"):
        intencion["operacion"] = operacion_defecto
    categorias = VARIABLES[tabla]["variables"][variable]["categorias"]
    categoria = intencion.get("categoria_valor")
    categorias_objetivo = [str(v) for v in (intencion.get("categoria_valores") or [])]
    codigos_diccionario = {str(c) for c in categorias}
    if categoria is not None and str(categoria) not in codigos_diccionario:
        raise ValueError("La categoría seleccionada no existe en el diccionario.")
    if categorias_objetivo and any(v not in codigos_diccionario for v in categorias_objetivo):
        raise ValueError("Una o más categorías seleccionadas no existen en el diccionario.")
    if intencion["operacion"] == "porcentaje" and not (
            intencion.get("tipo_consulta") in {"movilidad_laboral_fase1", "movilidad_laboral_fase2", "movilidad_laboral_fase3", "migracion_interna_od"}
            or (intencion.get("tipo_consulta") == "cruce"
                and (intencion.get("plan_cruce") or {}).get("version", 1) >= 2)
    ):
        if categoria is None and not categorias_objetivo:
            raise ValueError("Para calcular un porcentaje se necesita una categoría objetivo.")
        intencion.setdefault("denominador_valores", categorias_validas(tabla, variable))
        intencion["denominador_valores"] = list(dict.fromkeys(
            str(v) for v in intencion["denominador_valores"]
        ))
        if len(intencion["denominador_valores"]) < 2:
            raise ValueError(
                "No se puede calcular el porcentaje: la variable no tiene al menos "
                "dos categorías válidas en el diccionario."
            )
        objetivos = categorias_objetivo or [str(categoria)]
        if any(v not in intencion["denominador_valores"] for v in objetivos):
            raise ValueError(
                "No se puede calcular el porcentaje: alguna categoría objetivo no "
                "pertenece al universo válido de la variable."
            )
    if intencion["operacion"] == "porcentaje_rango":
        rango = intencion.get("rango_objetivo")
        if not isinstance(rango, dict) or rango.get("variable") != variable:
            raise ValueError("El porcentaje por rango no tiene una variable objetivo válida.")
    if intencion["operacion"] == "razon" and intencion.get("tipo_consulta") not in {"indicador_derivado_v24", "indicador_censal_v27"}:
        if not intencion.get("numerador_valores") or not intencion.get("denominador_valores"):
            raise ValueError("El índice no tiene numerador y denominador válidos.")
    if intencion["operacion"] == "distribucion":
        validas = intencion.get("categorias_validas") or categorias_validas(tabla, variable)
        if len(validas) < 2:
            raise ValueError("La distribución requiere al menos dos categorías válidas.")
        intencion["categorias_validas"] = validas
    # La restricción de edad se extrae del texto, no se deja a criterio del LLM.
    edad = (None if intencion.get("tipo_consulta") == "cruce"
            or intencion.get("rango_objetivo") or intencion.get("filtros_numericos")
            else re.search(r"\b(\d{1,3})\s+anos?\s+o\s+mas\b", _norm(consulta)))
    if edad:
        if tabla != "personas":
            raise ValueError("El filtro de edad requiere una variable de la tabla personas.")
        posibles = [v for v, info in VARIABLES[tabla]["variables"].items()
                    if _norm(v) == "edad" or _norm(info["descripcion"]).strip() in
                    ("edad", "edad en anos", "edad en anos cumplidos")]
        if len(posibles) != 1:
            raise ValueError("No se identificó de forma única la variable de edad; revisar el diccionario.")
        intencion["edad_minima"] = int(edad.group(1))
        intencion["variable_edad"] = posibles[0]

    # Rechaza códigos territoriales inventados por el modelo.
    f_nivel = intencion.get("filtro_geografico_nivel")
    f_codigo = intencion.get("filtro_geografico_codigo")
    if bool(f_nivel) != (f_codigo is not None):
        raise ValueError("El filtro territorial está incompleto.")
    if f_nivel:
        codigos = VARIABLES["geografia"].get(f_nivel, {})
        if not str(f_codigo).isdigit() or not any(
                str(c).isdigit() and int(c) == int(f_codigo) for c in codigos):
            raise ValueError("El filtro territorial no existe en el diccionario.")
    # Los porcentajes compuestos pueden requerir una confirmación explícita
    # del universo denominador. La selección del usuario se aplica después de
    # validar tabla/variable/geografía, pero antes de almacenar la intención.
    intencion = resolver_denominador(
        consulta_original, intencion, denominador_seleccionado
    )

    intencion.setdefault("operacion", operacion_defecto)
    intencion.setdefault("filtro_geografico_nivel", None)
    intencion.setdefault("filtro_geografico_codigo", None)
    intencion["_origen_interpretacion"] = origen
    intencion["_consulta_original"] = consulta_original
    intencion["_consulta_normalizada"] = consulta
    if union_seleccion:
        intencion["_seleccion_union"] = union_seleccion
    intencion["_correcciones_ortograficas"] = normalizacion["correcciones"]
    intencion["_aliases_aplicados"] = normalizacion["aliases_aplicados"]
    ambiguos = terminos_ambiguos_presentes(consulta)
    if ambiguos:
        intencion["_terminos_ambiguos"] = ambiguos
    LOG.info("[interpretacion] tabla=%s variable=%s categoria=%s operacion=%s "
             "nivel_mapa=%s filtro_nivel=%s filtro_codigo=%s",
             tabla, variable, intencion.get("categoria_valor"), intencion["operacion"],
             nivel_defecto, intencion.get("filtro_geografico_nivel"),
             intencion.get("filtro_geografico_codigo"))
    return intencion


def interpretar_consulta(consulta: str, tabla_seleccionada=None,
                         variable_seleccionada=None,
                         operacion_seleccionada=None,
                         denominador_seleccionado=None) -> dict:
    """LRU acotada: respuestas de respaldo expiran sin borrar las exitosas."""
    inicio = perf_counter()
    # Mayúsculas, tildes y espacios extra no fuerzan otra llamada al modelo.
    clave = (re.sub(r"\s+", " ", _norm(consulta)).strip(),
             tabla_seleccionada, variable_seleccionada, operacion_seleccionada,
             denominador_seleccionado)
    with _INTERPRETACION_LOCK:
        entrada = _CACHE_INTERPRETACIONES.get(clave)
        hit = entrada is not None and monotonic() < entrada[0]
        if hit:
            resultado = deepcopy(entrada[1])
            _CACHE_INTERPRETACIONES.move_to_end(clave)
        else:
            resultado = _interpretar_consulta(
                consulta.strip(), tabla_seleccionada, variable_seleccionada,
                operacion_seleccionada, denominador_seleccionado,
            )
            vencimiento = (_OLLAMA_REINTENTAR_DESDE
                           if resultado["_origen_interpretacion"].startswith("respaldo")
                           else float("inf"))
            _CACHE_INTERPRETACIONES[clave] = (vencimiento, deepcopy(resultado))
            _CACHE_INTERPRETACIONES.move_to_end(clave)
            while len(_CACHE_INTERPRETACIONES) > 128:
                _CACHE_INTERPRETACIONES.popitem(last=False)
    LOG.info("[tiempo] interpretacion_total=%.3fs cache=%s origen=%s pid=%s",
             perf_counter() - inicio, hit, resultado["_origen_interpretacion"], os.getpid())
    return resultado
