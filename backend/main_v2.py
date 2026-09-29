# -*- coding: utf-8 -*-
"""
Servidor local del Visor Censo 2024.

Ejecutar con:
    cd backend
    uvicorn main:app --reload --port 8000

Luego abre frontend/index.html en el navegador (o entra a
http://localhost:8000/ si dejaste el frontend dentro de /frontend
y esta app lo sirve como estático, ver más abajo).

Todo corre en tu computador: los parquet, la cartografía y el LLM
(vía Ollama) se acceden en localhost, sin depender de internet.
"""
from pathlib import Path
import logging
import asyncio
import json
import os
from collections import OrderedDict
from copy import deepcopy
from threading import Thread, Event, BoundedSemaphore, RLock
from time import perf_counter, monotonic
from uuid import uuid4
from typing import Optional, Literal
from fastapi.responses import JSONResponse, StreamingResponse, Response

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nl_parser import interpretar_consulta
from data_engine import (
    ejecutar_consulta,
    obtener_geometria_serializada,
    precalentar_geometrias,
    estado_precalentamiento,
)
from dictionary import VARIABLES
from categorical_resolver import (
    AmbiguedadVariable,
    AmbiguedadOperacion,
    SeleccionVariableCenso,
)
from approved_cache import buscar as buscar_aprobada, guardar as guardar_aprobada

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Visor Censo 2024 Chile (local)")

# Reduce el volumen transferido cuando el navegador acepta gzip. El nivel 1
# prioriza velocidad de compresión; no altera geometrías ni valores.
class GZipSinProgreso(GZipMiddleware):
    """Los eventos deben llegar inmediatamente, sin acumularse para comprimir."""
    async def __call__(self, scope, receive, send):
        if scope.get("path") == "/api/consulta/progreso":
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


app.add_middleware(GZipSinProgreso, minimum_size=1000, compresslevel=1)

# Habilitado para poder abrir frontend/index.html directamente con
# doble clic (file://) y que igual pueda llamar a este servidor.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConsultaRequest(BaseModel):
    pregunta: str
    tabla_seleccionada: Optional[str] = None
    variable_seleccionada: Optional[str] = None
    operacion_seleccionada: Optional[Literal["cantidad", "distribucion"]] = None


class RetroalimentacionRequest(BaseModel):
    feedback_id: str
    valor: Literal["positivo", "negativo"]


_PENDIENTES = OrderedDict()
_PENDIENTES_LOCK = RLock()
_PENDIENTES_MAX = 64
_PENDIENTES_TTL = 30 * 60
PLANTILLA_EXCEL = BASE_DIR / "datos" / "plantilla_de_salida.xlsx"


@app.on_event("startup")
def iniciar_precalentamiento_geografico():
    """Prepara las capas en segundo plano sin retrasar el inicio HTTP."""
    configuracion = os.getenv(
        "CENSO_PRECALENTAR_GEOMETRIAS", "region,comuna,provincia"
    ).strip()
    if configuracion.lower() in ("", "0", "false", "no"):
        logging.getLogger("uvicorn.error").info(
            "[precalentamiento] desactivado por configuración"
        )
        return
    niveles = [nivel.strip().lower() for nivel in configuracion.split(",")
               if nivel.strip()]
    Thread(target=precalentar_geometrias, args=(niveles,), daemon=True).start()


def _registrar_resultado(pregunta, sql, respuesta):
    ahora = monotonic()
    identificador = uuid4().hex
    copia = deepcopy(respuesta)
    copia.pop("feedback_id", None)
    with _PENDIENTES_LOCK:
        vencidos = [clave for clave, valor in _PENDIENTES.items()
                    if ahora - valor["instante"] > _PENDIENTES_TTL]
        for clave in vencidos:
            _PENDIENTES.pop(clave, None)
        _PENDIENTES[identificador] = {
            "instante": ahora, "pregunta": pregunta, "sql": sql,
            "respuesta": copia,
        }
        while len(_PENDIENTES) > _PENDIENTES_MAX:
            _PENDIENTES.popitem(last=False)
    return identificador


def _obtener_resultado(identificador):
    with _PENDIENTES_LOCK:
        entrada = _PENDIENTES.get(identificador)
        if not entrada or monotonic() - entrada["instante"] > _PENDIENTES_TTL:
            _PENDIENTES.pop(identificador, None)
            return None
        _PENDIENTES.move_to_end(identificador)
        return deepcopy(entrada)


def _descripcion_cotidiana(intencion):
    """Texto para la interfaz, sin nombres internos como p46b_hijas_nac."""
    nombres = {"conteo": "Cantidad", "porcentaje": "Porcentaje",
               "porcentaje_rango": "Porcentaje", "promedio": "Promedio",
               "razon": "Índice", "distribucion": "Distribución"}
    operacion = intencion.get("operacion", "conteo")
    tabla = intencion["tabla"]
    info = VARIABLES[tabla]["variables"][intencion["variable"]]
    grupo = intencion.get("_grupo_personas")
    categoria = str(intencion.get("categoria_valor"))
    etiqueta = info["categorias"].get(categoria)
    if intencion.get("indicador_descripcion"):
        texto = intencion["indicador_descripcion"]
    elif grupo:
        texto = f"{nombres[operacion]} de {grupo}"
    elif operacion == "promedio":
        texto = f"Promedio de {info['descripcion']}"
    else:
        texto = f"{nombres[operacion]} de {tabla}"
    texto += f" por {intencion['nivel_geografico']}."
    if etiqueta and not grupo:
        texto += f" Selección: {info['descripcion']} — {etiqueta}."
    if intencion.get("edad_minima") is not None:
        texto += f" Población de {intencion['edad_minima']} años o más."
    filtro = intencion.get("filtro_geografico_nivel")
    codigo = intencion.get("filtro_geografico_codigo")
    if filtro and codigo is not None:
        lugares = VARIABLES["geografia"][filtro]
        nombre = next((v for k, v in lugares.items() if str(k).isdigit() and int(k) == int(codigo)), str(codigo))
        texto += f" Territorio: {nombre}."
    if intencion.get("nota_interpretacion"):
        texto += f" Nota: {intencion['nota_interpretacion']}"
    return texto


def _procesar_consulta(req: ConsultaRequest, progreso=None):
    pregunta = (req.pregunta or "").strip()
    if not pregunta:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")
    inicio = perf_counter()
    consulta_id = uuid4().hex[:8]
    logging.getLogger("uvicorn.error").info("[consulta %s] inicio", consulta_id)
    avisar = progreso or (lambda etapa, terminado: None)
    # Solo una pregunta sin decisiones pendientes puede resolverse desde la
    # caché aprobada. Las selecciones del diálogo conservan su propio flujo.
    cache = None
    if not (req.tabla_seleccionada or req.variable_seleccionada
            or req.operacion_seleccionada):
        cache = buscar_aprobada(pregunta)
    if cache:
        for etapa in range(1, 6):
            avisar(etapa, False)
            avisar(etapa, True)
        respuesta = cache["respuesta"]
        respuesta["cache_aprobada"] = True
        respuesta.setdefault("interpretacion", {})["origen"] = "cache_aprobada"
        respuesta["feedback_id"] = _registrar_resultado(
            pregunta, cache["sql"], respuesta
        )
        response = JSONResponse(content=respuesta)
        logging.getLogger("uvicorn.error").info(
            "[consulta %s] cache_aprobada=True total_servidor=%.3fs bytes=%s",
            consulta_id, perf_counter() - inicio, len(response.body))
        return response
    try:
        avisar(1, False)
        intencion = interpretar_consulta(
            pregunta, req.tabla_seleccionada, req.variable_seleccionada,
            req.operacion_seleccionada,
        )
        avisar(1, True)
        resultado = ejecutar_consulta(intencion, progreso=avisar)
    except _ConsultaCancelada:
        raise
    except (AmbiguedadVariable, AmbiguedadOperacion):
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado: {e}")

    avisar(5, False)
    respuesta = {
        "tipo_visualizacion": resultado.get("tipo_visualizacion", "mapa"),
        "interpretacion": {
            "descripcion": _descripcion_cotidiana(intencion),
            "tabla": intencion["tabla"],
            "variable": intencion["variable"],
            "categoria_valor": intencion.get("categoria_valor"),
            "denominador_valores": intencion.get("denominador_valores"),
            "operacion": intencion.get("operacion"),
            "nivel_geografico": intencion["nivel_geografico"],
            "filtro_geografico_nivel": intencion.get("filtro_geografico_nivel"),
            "filtro_geografico_codigo": intencion.get("filtro_geografico_codigo"),
            "edad_minima": intencion.get("edad_minima"),
            "filtros_numericos": intencion.get("filtros_numericos"),
            "rango_objetivo": intencion.get("rango_objetivo"),
            "origen": intencion.get("_origen_interpretacion"),
            "nota": intencion.get("nota_interpretacion"),
        },
    }
    if respuesta["tipo_visualizacion"] == "tortas_mapa":
        respuesta.update({
            "datos": resultado["datos"],
            "geometria": resultado["geometria"],
            "nivel_geografico": resultado["nivel_geografico"],
            "categorias_grafico": resultado["categorias_grafico"],
        })

    else:
        respuesta.update({
            "datos": resultado["datos"],
            "geometria": resultado["geometria"],
            "nivel_geografico": resultado["nivel_geografico"],
            "min": resultado["valores"]["min"],
            "max": resultado["valores"]["max"],
        })

    respuesta["feedback_id"] = _registrar_resultado(
        pregunta, resultado.get("_sql_ejecutada", ""), respuesta
    )

    # La respuesta contiene datos agregados y una referencia; la cartografía
    # estable se descarga por separado y se reutiliza en el navegador.
    paso = perf_counter()
    response = JSONResponse(content=respuesta)
    logging.getLogger("uvicorn.error").info(
        "[consulta %s] serializacion=%.3fs total_servidor=%.3fs bytes=%s",
        consulta_id, perf_counter() - paso, perf_counter() - inicio, len(response.body))
    avisar(5, True)
    return response


@app.post("/api/consulta")
def consulta(req: ConsultaRequest):
    """Conserva el contrato del frontend anterior."""
    try:
        return _procesar_consulta(req)
    except AmbiguedadOperacion as exc:
        return JSONResponse(status_code=409, content={
            "tipo": "seleccion_operacion", "mensaje": str(exc),
            "tabla": exc.tabla, "variable": exc.variable,
            "opciones": exc.opciones,
        })
    except AmbiguedadVariable as exc:
        return JSONResponse(status_code=409, content={
            "tipo": ("seleccion_variable_censo"
                     if isinstance(exc, SeleccionVariableCenso)
                     else "seleccion_variable"),
            "mensaje": str(exc), "opciones": exc.opciones,
        })


# Cinco etapas del servidor. El navegador puede agregar una sexta al dibujar
# el mapa. Cada evento de término incrementa el avance; no usa tiempos fingidos.
_ETAPAS = (
    ("Entendiendo la pregunta", "Pregunta interpretada"),
    ("Calculando los resultados", "Resultados calculados"),
    ("Identificando la cartografía", "Cartografía identificada"),
    ("Organizando los resultados", "Resultados organizados"),
    ("Preparando la respuesta", "Respuesta lista"),
)
_STREAMS = BoundedSemaphore(4)


class _ConsultaCancelada(Exception):
    """Detiene el trabajo entre etapas si el navegador abandona la consulta."""


@app.post("/api/consulta/progreso")
async def consulta_con_progreso(req: ConsultaRequest):
    """Emite eventos SSE por POST: progreso, resultado o error."""
    if not req.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")
    if not _STREAMS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Hay varias consultas en curso. Intentar nuevamente en unos segundos.")
    cola = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancelada = Event()

    def enviar(tipo, contenido):
        # La cola vive en el bucle HTTP; el cálculo se ejecuta fuera de él.
        if not cancelada.is_set():
            loop.call_soon_threadsafe(cola.put_nowait, (tipo, contenido))

    def informar(etapa, terminado):
        if cancelada.is_set():
            raise _ConsultaCancelada()
        completados = etapa if terminado else etapa - 1
        enviar("progreso", {"etapa": etapa, "total": len(_ETAPAS),
               "completados": completados, "porcentaje": 100 * completados // len(_ETAPAS),
               "estado": "completado" if terminado else "en_curso",
               "mensaje": _ETAPAS[etapa - 1][1 if terminado else 0]})

    def trabajar():
        try:
            respuesta = _procesar_consulta(req, progreso=informar)
            enviar("resultado", respuesta.body.decode("utf-8"))
        except _ConsultaCancelada:
            pass
        except AmbiguedadOperacion as exc:
            enviar("alternativas", {
                "tipo": "seleccion_operacion", "mensaje": str(exc),
                "tabla": exc.tabla, "variable": exc.variable,
                "opciones": exc.opciones,
            })
        except AmbiguedadVariable as exc:
            enviar("alternativas", {
                "tipo": ("seleccion_variable_censo"
                         if isinstance(exc, SeleccionVariableCenso)
                         else "seleccion_variable"),
                "mensaje": str(exc), "opciones": exc.opciones,
            })
        except HTTPException as exc:
            enviar("error", {"mensaje": str(exc.detail), "codigo": exc.status_code})
        except Exception as exc:
            enviar("error", {"mensaje": str(exc), "codigo": 500})
        finally:
            _STREAMS.release()

    async def eventos():
        Thread(target=trabajar, daemon=True).start()
        try:
            while True:
                try:
                    tipo, contenido = await asyncio.wait_for(cola.get(), timeout=15)
                except asyncio.TimeoutError:
                    # Mantiene la conexión abierta; no incrementa el progreso.
                    yield ": esperando\n\n"
                    continue
                datos = contenido if tipo == "resultado" else json.dumps(contenido, ensure_ascii=False)
                yield f"event: {tipo}\ndata: {datos}\n\n"
                if tipo in ("resultado", "error", "alternativas"):
                    break
        finally:
            cancelada.set()

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/salud")
def salud():
    return {"estado": "ok", "geometrias": estado_precalentamiento()}


@app.get("/api/geometrias/{nivel}")
def geometria(nivel: str, request: Request,
              filtro_nivel: Optional[str] = None,
              filtro_codigo: Optional[int] = None):
    """Entrega polígonos estables, separados de los valores estadísticos."""
    try:
        contenido, version = obtener_geometria_serializada(
            nivel, filtro_nivel, filtro_codigo
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    etag = f'"{version}-{filtro_nivel or "pais"}-{filtro_codigo or "todos"}"'
    version_solicitada = request.query_params.get("v")
    encabezados = {
        "ETag": etag,
        "Cache-Control": ("public, max-age=31536000, immutable"
                          if version_solicitada == version else "no-cache"),
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=encabezados)
    return Response(content=contenido, media_type="application/geo+json",
                    headers=encabezados)


@app.post("/api/retroalimentacion")
def retroalimentacion(req: RetroalimentacionRequest):
    entrada = _obtener_resultado(req.feedback_id)
    if entrada is None:
        raise HTTPException(status_code=404, detail="El resultado ya no está disponible.")
    if req.valor == "positivo":
        guardar_aprobada(
            entrada["pregunta"], entrada["sql"], entrada["respuesta"]
        )
    return {"estado": "guardado" if req.valor == "positivo" else "recibido"}


@app.get("/api/consulta/{feedback_id}/excel")
def descargar_excel(feedback_id: str):
    entrada = _obtener_resultado(feedback_id)
    if entrada is None:
        raise HTTPException(status_code=404, detail="El resultado ya no está disponible para descargar.")
    try:
        from excel_export import crear_excel
        archivo, nombre = crear_excel(
            PLANTILLA_EXCEL, entrada["respuesta"], entrada["pregunta"], entrada["sql"]
        )
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="Falta instalar openpyxl en el entorno del backend: pip install openpyxl",
        ) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return StreamingResponse(
        archivo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# Sirve el frontend estático en http://localhost:8000/
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
