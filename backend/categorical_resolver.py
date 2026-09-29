# -*- coding: utf-8 -*-
"""Resolución genérica de porcentajes y distribuciones categóricas.

El módulo solo selecciona variables y categorías existentes en el diccionario.
Cuando la evidencia textual no permite una elección única, devuelve opciones
para que la interfaz solicite una decisión al usuario.
"""
import re

from dictionary import (
    VARIABLES,
    TABLAS_PARQUET,
    _norm,
    categorias_validas,
    detectar_operacion,
    es_ambito_nacional,
)


class AmbiguedadVariable(ValueError):
    """Indica que el usuario debe escoger una variable entre alternativas."""

    def __init__(self, mensaje, opciones):
        super().__init__(mensaje)
        self.opciones = opciones


class AmbiguedadOperacion(ValueError):
    """Indica que la variable es clara, pero falta decidir qué calcular."""

    def __init__(self, mensaje, tabla, variable, opciones):
        super().__init__(mensaje)
        self.tabla = tabla
        self.variable = variable
        self.opciones = opciones


class SeleccionVariableCenso(AmbiguedadVariable):
    """Una referencia a otro censo requiere que la persona elija variable."""


_NOMBRES_TABLA = {
    "personas": (r"\bpersonas?\b", r"\bpoblacion\b"),
    "hogares": (r"\bhogares?\b",),
    # Casa/casas identifica la tabla viviendas, pero la categoría exacta se
    # obtiene después desde el diccionario; nunca se presupone su código.
    "viviendas": (r"\bviviendas?\b", r"\bcasas?\b", r"\bdomicilios?\b"),
}
_EXCLUIR_VARIABLES = {
    "region", "provincia", "comuna",
    "p24_lug_resid5_esp", "p25_lug_nacimiento_esp",
    "p27_nacionalidad_esp", "p44_lug_trab_esp",
}
_SINONIMOS = {
    "condicion": "estado",
    "condiciones": "estado",
    "desempleo": "desocupacion",
    "desempleados": "desocupado",
    "desempleadas": "desocupada",
}


def _tabla_mencionada(q):
    """Obtiene la entidad explícita; si no aparece, permite buscar en todas."""
    encontradas = [tabla for tabla, patrones in _NOMBRES_TABLA.items()
                   if any(re.search(patron, q) for patron in patrones)]
    return encontradas[0] if len(encontradas) == 1 else None


def _canon_token(token):
    """Normalización leve para género/plural sin alterar raíces sustantivas."""
    token = _SINONIMOS.get(token, token)
    if len(token) > 5 and token.endswith("es"):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("s"):
        token = token[:-1]
    return token


def _tokens_comparables(texto):
    vacias = {
        "a", "al", "de", "del", "la", "el", "los", "las", "un", "una",
        "unos", "unas", "en", "por", "para", "o", "y", "que", "es", "esta",
        "este", "cada", "segun", "principal", "principalmente", "conectado",
        "conectada", "cantidad", "numero", "total", "porcentaje",
        "proporcion", "personas", "persona", "poblacion", "hogar", "hogares",
        "vivienda", "viviendas", "muestra", "dame", "grafico", "torta",
        "distribucion", "composicion", "variable", "categoria", "categorias",
        "region", "regiones", "provincia", "provincias", "comuna", "comunas",
    }
    return {_canon_token(t) for t in re.findall(r"[a-z0-9]+", _norm(texto))
            if t not in vacias and len(t) > 1}


def _opcion(tabla, variable, puntaje=0):
    info = VARIABLES[tabla]["variables"][variable]
    etiquetas = [str(info["categorias"][codigo])
                 for codigo in categorias_validas(tabla, variable)[:6]]
    return {
        "tabla": tabla,
        "variable": variable,
        "descripcion": info["descripcion"],
        "categorias_ejemplo": etiquetas,
        "puntaje": puntaje,
    }


def _validar_variable_forzada(tabla, variable):
    if tabla not in TABLAS_PARQUET:
        raise ValueError("La tabla seleccionada no existe.")
    info = VARIABLES[tabla]["variables"].get(variable)
    if not info or len(categorias_validas(tabla, variable)) < 2:
        raise ValueError("La variable seleccionada no es categórica o no existe.")
    return variable


def _candidatos_variable(q, tabla=None, limite=5):
    """Puntúa descripciones y categorías sin pedir al LLM que invente códigos."""
    consulta_tokens = _tokens_comparables(q)
    resultados = []
    tablas = [tabla] if tabla else list(TABLAS_PARQUET)
    for nombre_tabla in tablas:
        for variable, info in VARIABLES[nombre_tabla]["variables"].items():
            if variable in _EXCLUIR_VARIABLES:
                continue
            validas = categorias_validas(nombre_tabla, variable)
            if len(validas) < 2:
                continue
            descripcion = _norm(info["descripcion"])
            tokens_desc = _tokens_comparables(descripcion)
            tokens_cat = _tokens_comparables(" ".join(
                str(info["categorias"].get(codigo, "")) for codigo in validas
            ))
            comunes_desc = consulta_tokens & tokens_desc
            comunes_cat = consulta_tokens & tokens_cat
            puntaje = 5 * len(comunes_desc) + 2 * len(comunes_cat)
            # Una descripción escrita casi literalmente debe prevalecer.
            frase = " ".join(sorted(tokens_desc))
            if tokens_desc and tokens_desc <= consulta_tokens:
                puntaje += 12
            if frase and frase in " ".join(sorted(consulta_tokens)):
                puntaje += 4
            if puntaje > 0:
                resultados.append((puntaje, nombre_tabla, variable))
    resultados.sort(key=lambda x: (-x[0], x[1], x[2]))
    return resultados[:limite]


def resolver_referencia_censo(consulta, tabla_forzada=None, variable_forzada=None):
    """Solicita una variable cuando el texto menciona un año censal.

    Expresiones como «en el Censo 2017» pueden corresponder al lugar de
    residencia anterior, período de llegada u otras variables. El año no se
    usa como categoría ni se deja a criterio del LLM.
    """
    if variable_forzada:
        return None
    q = _norm(consulta)
    patron_ano = r"\bcenso(?:\s+de)?\s+(?:19|20)\d{2}\b|\b(?:19|20)\d{2}\b"
    if not re.search(patron_ano, q):
        return None
    tabla = tabla_forzada or _tabla_mencionada(q) or "personas"
    if tabla not in TABLAS_PARQUET:
        tabla = "personas"

    preferidas = ("p24_lug_resid5_esp", "p26_llegada_periodo")
    opciones = []
    vistos = set()
    for codigo in preferidas:
        for variable in VARIABLES[tabla]["variables"]:
            if variable.lower() == codigo and variable not in vistos:
                opciones.append(_opcion(tabla, variable, 100))
                vistos.add(variable)

    texto_sin_ano = re.sub(patron_ano, " ", q)
    for puntaje, nombre_tabla, variable in _candidatos_variable(
            texto_sin_ano, tabla=tabla, limite=8):
        if variable not in vistos:
            opciones.append(_opcion(nombre_tabla, variable, puntaje))
            vistos.add(variable)

    # Completa con variables censales temporales del diccionario si la frase
    # restante no entregó suficientes señales semánticas.
    for variable, info in VARIABLES[tabla]["variables"].items():
        texto = _norm(variable + " " + info["descripcion"])
        if (re.search(r"\b(?:censo|resid|llegada|periodo|ano anterior)\b", texto)
                and variable not in vistos
                and len(categorias_validas(tabla, variable)) >= 2):
            opciones.append(_opcion(tabla, variable, 1))
            vistos.add(variable)
        if len(opciones) >= 6:
            break
    if not opciones:
        raise ValueError(
            "La consulta menciona un año censal, pero el diccionario no contiene "
            "variables categóricas relacionadas para ofrecer como alternativas."
        )
    raise SeleccionVariableCenso(
        "El año censal puede referirse a distintas variables. Selecciona la que deseas consultar.",
        opciones[:6],
    )


def resolver_operacion_omitida(consulta, tabla_forzada=None,
                               variable_forzada=None, operacion_forzada=None):
    """Pregunta por cantidad o distribución cuando la operación no aparece."""
    q = _norm(consulta)
    if re.search(
        r"\b(?:cantidad|numero|conteo|total|cuant[oa]s?|cuanto hay|hay)\b|"
        r"\b(?:porcentaje|proporcion|promedio|media|indice|razon|tasa|"
        r"distribucion|composicion|grafico de torta|grafico circular)\b|%",
        q,
    ):
        return None
    # Sin una selección previa, solo interviene cuando el texto pide una
    # variable categórica (por/según). Si la interfaz ya entregó una operación
    # y una variable, se respeta esa selección aunque la frase no contenga «por».
    tiene_por = bool(re.search(r"\b(?:por|segun)\b", q))
    if not tiene_por and not (operacion_forzada and variable_forzada):
        return None
    if tiene_por:
        resto = re.split(r"\b(?:por|segun)\b", q, maxsplit=1)[-1].strip()
        if re.match(r"^(?:la\s+|el\s+)?(?:region|provincia|comuna)s?\b", resto):
            return None

    tabla = tabla_forzada or _tabla_mencionada(q)
    if variable_forzada:
        variable = _validar_variable_forzada(tabla_forzada, variable_forzada)
        tabla = tabla_forzada
    else:
        candidatos = _candidatos_variable(q, tabla=tabla)
        if not candidatos:
            return None
        mejor = candidatos[0]
        segundo = candidatos[1] if len(candidatos) > 1 else None
        clara = ((segundo is None and mejor[0] >= 5) or
                 (segundo is not None and mejor[0] >= 10
                  and mejor[0] - segundo[0] >= 5))
        if not clara:
            raise AmbiguedadVariable(
                "La pregunta puede referirse a más de una variable. Selecciona la correcta.",
                [_opcion(t, v, p) for p, t, v in candidatos],
            )
        _, tabla, variable = mejor

    info = VARIABLES[tabla]["variables"][variable]
    entidad = {"personas": "personas", "hogares": "hogares",
               "viviendas": "viviendas"}[tabla]
    if operacion_forzada == "cantidad":
        categoria = _categoria_para_variable(q, tabla, variable)
        codigo = categoria[0] if categoria else None
        etiqueta = categoria[1] if categoria else None
        descripcion = (
            f"Cantidad de {entidad} con {etiqueta}"
            if etiqueta else f"Cantidad de {entidad}"
        )
        return {
            "tabla": tabla, "variable": variable, "categoria_valor": codigo,
            "operacion": "conteo", "_origen_interpretacion": "seleccion_usuario",
            "indicador_descripcion": descripcion,
        }
    if operacion_forzada == "distribucion":
        return {
            "tabla": tabla, "variable": variable, "categoria_valor": None,
            "categorias_validas": categorias_validas(tabla, variable),
            "operacion": "distribucion", "tipo_visualizacion": "tortas_mapa",
            "indicador_descripcion": f"Distribución de {entidad} según {info['descripcion']}",
            "_origen_interpretacion": "seleccion_usuario",
        }
    raise AmbiguedadOperacion(
        "La variable está identificada, pero falta indicar qué deseas calcular.",
        tabla, variable,
        [
            {"id": "cantidad", "titulo": f"Cantidad de {entidad}",
             "descripcion": "Contar las unidades y representarlas en el mapa."},
            {"id": "distribucion",
             "titulo": f"Gráfico de torta: {info['descripcion']}",
             "descripcion": "Mostrar las principales categorías de la variable en cada territorio."},
        ],
    )


def es_solicitud_distribucion(consulta):
    """Distingue una distribución por categorías de una agregación territorial."""
    q = _norm(consulta)
    if re.search(r"\b(?:porcentaje|proporcion|promedio|media|indice|tasa)\b|%", q):
        return False
    if re.search(r"\b(?:distribucion|composicion|grafico de torta|grafico circular)\b", q):
        return True
    if not re.search(r"\b(?:personas?|poblacion|hogares?|viviendas?)\b.*\bpor\b", q):
        return False
    # «Personas por comuna» es un mapa; «personas por sexo» es distribución.
    resto = re.split(r"\bpor\b", q, maxsplit=1)[-1].strip()
    return not re.match(r"^(?:la\s+|el\s+)?(?:region|provincia|comuna)s?\b", resto)


def resolver_distribucion(consulta, tabla_forzada=None, variable_forzada=None):
    """Crea una intención de gráfico circular o solicita desambiguación."""
    if not es_solicitud_distribucion(consulta):
        return None
    q = _norm(consulta)
    tabla = tabla_forzada or _tabla_mencionada(q)
    if variable_forzada:
        variable = _validar_variable_forzada(tabla_forzada, variable_forzada)
    else:
        candidatos = _candidatos_variable(q, tabla=tabla)
        if not candidatos:
            raise ValueError("No se encontró una variable categórica relacionada con la consulta.")
        mejor = candidatos[0]
        segundo = candidatos[1] if len(candidatos) > 1 else None
        # Exige una ventaja clara. En otro caso, el usuario decide.
        eleccion_clara = (
            (segundo is None and mejor[0] >= 5) or
            (segundo is not None and mejor[0] >= 10 and mejor[0] - segundo[0] >= 5)
        )
        if not eleccion_clara:
            opciones = [_opcion(t, v, p) for p, t, v in candidatos]
            raise AmbiguedadVariable(
                "La pregunta puede referirse a más de una variable. Selecciona la correcta.",
                opciones,
            )
        _, tabla, variable = mejor
    info = VARIABLES[tabla]["variables"][variable]
    return {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": None,
        "categorias_validas": categorias_validas(tabla, variable),
        "operacion": "distribucion",
        "tipo_visualizacion": "tortas_mapa",
        "indicador_descripcion": f"Distribución de {tabla} según {info['descripcion']}",
        "_origen_interpretacion": "catalogo_categorico",
    }


def _coincidencias_categoria(q, tabla=None):
    """Busca una categoría pedida y conserva la variable a la que pertenece."""
    texto_comparable = q
    if es_ambito_nacional(q):
        # El nombre del país es contexto territorial, no evidencia semántica
        # para escoger categorías como país de nacimiento.
        texto_comparable = re.sub(
            r"\b(?:en|de|para)\s+(?:todo\s+)?chile\b|"
            r"\b(?:todo\s+)?(?:el\s+)?pais\b|"
            r"\b(?:a\s+)?nivel\s+nacional\b|"
            r"\bambito\s+nacional\b",
            " ",
            texto_comparable,
        )
    consulta_tokens = _tokens_comparables(texto_comparable)
    resultados = []
    tablas = [tabla] if tabla else list(TABLAS_PARQUET)
    for nombre_tabla in tablas:
        for variable, info in VARIABLES[nombre_tabla]["variables"].items():
            if variable in _EXCLUIR_VARIABLES:
                continue
            descripcion_tokens = _tokens_comparables(info["descripcion"])
            for codigo in categorias_validas(nombre_tabla, variable):
                etiqueta = str(info["categorias"].get(codigo, ""))
                categoria_tokens = _tokens_comparables(etiqueta)
                if not categoria_tokens or not categoria_tokens <= consulta_tokens:
                    continue
                # Evita resolver «Sí/No» sin evidencia sobre la variable.
                if max(map(len, categoria_tokens), default=0) < 4 and not (
                        consulta_tokens & descripcion_tokens):
                    continue
                puntaje = 12 * len(categoria_tokens) + 6 * len(
                    consulta_tokens & descripcion_tokens
                )
                resultados.append((puntaje, nombre_tabla, variable, str(codigo), etiqueta))
    resultados.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    return resultados



def _categoria_para_variable(q, tabla, variable):
    """Devuelve una categoría inequívoca de la variable solicitada, si existe."""
    coincidencias = [
        c for c in _coincidencias_categoria(q, tabla=tabla)
        if c[1] == tabla and c[2] == variable
    ]
    if not coincidencias:
        return None
    mejor = coincidencias[0]
    segundo = coincidencias[1] if len(coincidencias) > 1 else None
    if segundo and mejor[0] - segundo[0] < 4 and mejor[3] != segundo[3]:
        return None
    return mejor[3], mejor[4]



def _descripcion_sin_numero(texto):
    """Retira solo el número inicial de una pregunta censal (p.ej. 8., 11.1.)."""
    q = _norm(texto)
    return re.sub(r"^\s*\d+(?:\.\d+)?[a-z]?\.?\s*", "", q).strip()


def resolver_variable_por_descripcion(consulta, tabla_forzada=None,
                                       variable_forzada=None):
    """Reconoce una pregunta/variable cuando su descripción está casi literal.

    Esta ruta antecede a aliases, categorías parciales y rangos para impedir que
    una frase oficial como «material de construcción en las paredes exteriores»
    sea capturada por una categoría incidental de otra variable.
    """
    q = _descripcion_sin_numero(consulta)
    q_tokens = _tokens_comparables(q)
    if len(q_tokens) < 2:
        return None

    tablas = [tabla_forzada] if tabla_forzada else list(TABLAS_PARQUET)
    candidatos = []
    for tabla in tablas:
        if tabla not in TABLAS_PARQUET:
            continue
        for variable, info in VARIABLES[tabla]["variables"].items():
            if variable in _EXCLUIR_VARIABLES:
                continue
            if variable_forzada and variable != variable_forzada:
                continue
            validas = categorias_validas(tabla, variable)
            if len(validas) < 2:
                continue
            desc = _descripcion_sin_numero(info["descripcion"])
            d_tokens = _tokens_comparables(desc)
            if len(d_tokens) < 2:
                continue
            comunes = q_tokens & d_tokens
            cobertura_desc = len(comunes) / len(d_tokens)
            cobertura_q = len(comunes) / len(q_tokens)
            exacta = q == desc
            # Acepta redacción literal, una frase breve que identifica la
            # descripción, o una descripción contenida casi por completo.
            fuerte = (
                exacta
                or (len(q_tokens) >= 2 and q_tokens <= d_tokens)
                or (len(d_tokens) >= 2 and d_tokens <= q_tokens)
                or (len(comunes) >= 3 and cobertura_desc >= 0.72 and cobertura_q >= 0.72)
            )
            if not fuerte:
                continue
            puntaje = (100 if exacta else 0) + 40 * cobertura_desc + 40 * cobertura_q + len(comunes)
            candidatos.append((puntaje, tabla, variable))

    if not candidatos:
        return None
    candidatos.sort(key=lambda x: (-x[0], x[1], x[2]))
    mejor = candidatos[0]
    segundo = candidatos[1] if len(candidatos) > 1 else None
    if segundo is not None and mejor[0] - segundo[0] < 8:
        raise AmbiguedadVariable(
            "La expresión coincide con más de una pregunta censal. "
            "Selecciona la variable correcta.",
            [_opcion(t, v, round(p, 1)) for p, t, v in candidatos[:5]],
        )

    _, tabla, variable = mejor
    # Si además hay una categoría de esta variable escrita en la consulta,
    # se deja continuar al resolver de categorías para conservar el filtro.
    if _categoria_para_variable(q, tabla, variable) is not None:
        return None
    info = VARIABLES[tabla]["variables"][variable]
    return {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": None,
        "categorias_validas": categorias_validas(tabla, variable),
        "operacion": "distribucion",
        "tipo_visualizacion": "tortas_mapa",
        "indicador_descripcion": f"Distribución de {tabla} según {info['descripcion']}",
        "_origen_interpretacion": "descripcion_censal",
    }


def resolver_variable_categorica_explicita(consulta, tabla_forzada=None,
                                             variable_forzada=None):
    """Resuelve una variable categórica nombrada sin categoría ni operación.

    Ejemplos: «servicio higiénico», «Tipología de hogar» o la redacción casi
    literal de una pregunta censal. En estos casos contar todas las filas no
    describe la variable; la respuesta natural es su distribución por categorías.
    """
    q = _norm(consulta)
    if re.search(
        r"\b(?:cantidad|numero|conteo|total|cuant[oa]s?|cuanto hay|hay|"
        r"porcentaje|proporcion|promedio|media|indice|razon|tasa|"
        r"distribucion|composicion|grafico de torta|grafico circular)\b|%",
        q,
    ):
        return None
    if es_solicitud_distribucion(q):
        return None

    tabla = tabla_forzada or _tabla_mencionada(q)
    if variable_forzada:
        variable = _validar_variable_forzada(tabla_forzada, variable_forzada)
        tabla = tabla_forzada
    else:
        candidatos = _candidatos_variable(q, tabla=tabla)
        if not candidatos:
            return None
        mejor = candidatos[0]
        segundo = candidatos[1] if len(candidatos) > 1 else None
        # Sin palabras de operación exigimos evidencia semántica fuerte.
        if mejor[0] < 12:
            return None
        if segundo is not None and mejor[0] - segundo[0] < 5:
            raise AmbiguedadVariable(
                "La expresión puede referirse a más de una pregunta censal. "
                "Selecciona la variable correcta.",
                [_opcion(t, v, p) for p, t, v in candidatos],
            )
        _, tabla, variable = mejor

    # Si el texto sí contiene una categoría de la variable, este resolver no
    # debe convertirla en distribución. La categoría se resuelve como conteo.
    if _categoria_para_variable(q, tabla, variable) is not None:
        return None

    info = VARIABLES[tabla]["variables"][variable]
    validas = categorias_validas(tabla, variable)
    if len(validas) < 2:
        return None
    return {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": None,
        "categorias_validas": validas,
        "operacion": "distribucion",
        "tipo_visualizacion": "tortas_mapa",
        "indicador_descripcion": f"Distribución de {tabla} según {info['descripcion']}",
        "_origen_interpretacion": "variable_categorica_explicita",
    }


def resolver_conteo_categoria(consulta, tabla_forzada=None, variable_forzada=None):
    """Resuelve conteos de categorías literales antes de consultar al LLM.

    Ejemplo: «cantidad de casas en Chile» se vincula con la categoría Casa de
    la variable Tipo de vivienda particular usando el código del diccionario.
    """
    if detectar_operacion(consulta) != "conteo" or es_solicitud_distribucion(consulta):
        return None
    q = _norm(consulta)
    tabla = tabla_forzada or _tabla_mencionada(q)
    coincidencias = _coincidencias_categoria(q, tabla=tabla)
    if variable_forzada:
        _validar_variable_forzada(tabla_forzada, variable_forzada)
        coincidencias = [c for c in coincidencias
                         if c[1] == tabla_forzada and c[2] == variable_forzada]
    if not coincidencias:
        return None

    mejor = coincidencias[0]
    segundo = coincidencias[1] if len(coincidencias) > 1 else None
    if segundo and mejor[0] - segundo[0] < 4 and (mejor[1], mejor[2]) != (segundo[1], segundo[2]):
        opciones = []
        vistos = set()
        for puntaje, nombre_tabla, variable, _, _ in coincidencias:
            if (nombre_tabla, variable) not in vistos:
                opciones.append(_opcion(nombre_tabla, variable, puntaje))
                vistos.add((nombre_tabla, variable))
            if len(opciones) == 5:
                break
        raise AmbiguedadVariable(
            "La expresión coincide con categorías de más de una variable. Selecciona la correcta.",
            opciones,
        )

    _, tabla, variable, codigo, _ = mejor
    return {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": codigo,
        "operacion": "conteo",
        "_origen_interpretacion": "categoria_diccionario",
    }


def resolver_porcentaje_generico(consulta, tabla_forzada=None, variable_forzada=None):
    """Resuelve categoría / total válido para porcentajes no predefinidos."""
    q = _norm(consulta)
    # Las tasas requieren una fórmula propia; no se generalizan aquí.
    if not re.search(r"\b(?:porcentaje|proporcion)\b|%", q) or "tasa" in q:
        return None
    tabla = tabla_forzada or _tabla_mencionada(q)
    coincidencias = _coincidencias_categoria(q, tabla=tabla)
    if variable_forzada:
        _validar_variable_forzada(tabla_forzada, variable_forzada)
        coincidencias = [c for c in coincidencias
                         if c[1] == tabla_forzada and c[2] == variable_forzada]
    if not coincidencias:
        return None
    mejor = coincidencias[0]
    segundo = coincidencias[1] if len(coincidencias) > 1 else None
    if segundo and mejor[0] - segundo[0] < 4 and (mejor[1], mejor[2]) != (segundo[1], segundo[2]):
        variables = []
        vistos = set()
        for puntaje, nombre_tabla, variable, _, _ in coincidencias:
            if (nombre_tabla, variable) not in vistos:
                variables.append(_opcion(nombre_tabla, variable, puntaje))
                vistos.add((nombre_tabla, variable))
            if len(variables) == 5:
                break
        raise AmbiguedadVariable(
            "La categoría aparece en más de una variable. Selecciona la variable correcta.",
            variables,
        )
    _, tabla, variable, codigo, etiqueta = mejor
    info = VARIABLES[tabla]["variables"][variable]
    return {
        "tabla": tabla,
        "variable": variable,
        "categoria_valor": codigo,
        "denominador_valores": categorias_validas(tabla, variable),
        "operacion": "porcentaje",
        "indicador_descripcion": f"Porcentaje de {etiqueta} ({info['descripcion']})",
        "_origen_interpretacion": "porcentaje_generico",
    }
