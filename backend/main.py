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
from contextlib import asynccontextmanager
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
from denominator_resolver import AmbiguedadDenominador
from approved_cache import buscar as buscar_aprobada, guardar as guardar_aprobada

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona la inicialización y el cierre del servidor."""
    configuracion = os.getenv(
        "CENSO_PRECALENTAR_GEOMETRIAS", "region,comuna,provincia"
    ).strip()

    if configuracion.lower() in ("", "0", "false", "no"):
        logging.getLogger("uvicorn.error").info(
            "[precalentamiento] desactivado por configuración"
        )
    else:
        niveles = [
            nivel.strip().lower()
            for nivel in configuracion.split(",")
            if nivel.strip()
        ]

        # Mantiene el comportamiento anterior: el precalentamiento se ejecuta
        # en segundo plano y no bloquea el inicio del servidor HTTP.
        Thread(
            target=precalentar_geometrias,
            args=(niveles,),
            daemon=True,
        ).start()

    yield

    # Actualmente no hay recursos persistentes que requieran cierre explícito.


app = FastAPI(
    title="Visor Censo 2024 Chile (local)",
    lifespan=lifespan,
)

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
    # Se permite texto porque los selectores internos también usan ids como
    # __pct_total. Cada resolutor valida sus propios identificadores.
    operacion_seleccionada: Optional[str] = None
    denominador_seleccionado: Optional[str] = None


class RetroalimentacionRequest(BaseModel):
    feedback_id: str
    valor: Literal["positivo", "negativo"]


_PENDIENTES = OrderedDict()
_PENDIENTES_LOCK = RLock()
_PENDIENTES_MAX = 64
_PENDIENTES_TTL = 30 * 60
PLANTILLA_EXCEL = Path(os.getenv("CENSO_PLANTILLA_EXCEL", str(BASE_DIR / "datos" / "plantilla_de_salida.xlsx")))


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



# BEGIN VISOR V31 POSTGRES STATE
# Permite multiples workers/instancias: feedback y Excel ya no dependen de RAM.
if os.getenv("DATABASE_URL", "").strip():
    from state_store import pending_save as _pg_pending_save, pending_get as _pg_pending_get
    from state_store import feedback_save as _pg_feedback_save

    def _registrar_resultado(pregunta, sql, respuesta):
        return _pg_pending_save(pregunta, sql, respuesta)

    def _obtener_resultado(identificador):
        return _pg_pending_get(identificador)
# END VISOR V31 POSTGRES STATE

from presentation import descripcion_cotidiana as _descripcion_cotidiana

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
            or req.operacion_seleccionada or req.denominador_seleccionado):
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
            req.operacion_seleccionada, req.denominador_seleccionado,
        )
        avisar(1, True)
        resultado = ejecutar_consulta(intencion, progreso=avisar)
    except _ConsultaCancelada:
        raise
    except (AmbiguedadVariable, AmbiguedadOperacion, AmbiguedadDenominador):
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
            "categoria_valores": intencion.get("categoria_valores"),
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
            "universo": intencion.get("universo"),
            "formula": intencion.get("formula"),
            "denominador_id": intencion.get("denominador_id"),
            "denominador_descripcion": intencion.get("denominador_descripcion"),
            "denominador_confirmacion": intencion.get("denominador_confirmacion"),
            "denominador_requirio_confirmacion": intencion.get("denominador_requirio_confirmacion", False),
            "indicador_id": intencion.get("indicador_id"),
            "consulta_normalizada": intencion.get("_consulta_normalizada"),
            "correcciones_ortograficas": intencion.get("_correcciones_ortograficas", []),
            "aliases_aplicados": intencion.get("_aliases_aplicados", []),
            "terminos_ambiguos": intencion.get("_terminos_ambiguos", []),
            "tipo_consulta": intencion.get("tipo_consulta"),
            "metrica_dimensiones": intencion.get("metrica_dimensiones"),
            "variables_dimensiones": intencion.get("variables_dimensiones"),
            "plan_cruce": intencion.get("plan_cruce"),
            "entidad_objetivo": (
                intencion.get("entidad_objetivo")
                or (intencion.get("plan_cruce") or {}).get("entidad_objetivo")
                or intencion.get("tabla")
            ),
            "movilidad_indicador": intencion.get("movilidad_indicador"),
            "movilidad_geografia": intencion.get("movilidad_geografia"),
            "movilidad_origen_codigo": intencion.get("movilidad_origen_codigo"),
            "movilidad_origen_nombre": intencion.get("movilidad_origen_nombre"),
            "movilidad_destino_codigo": intencion.get("movilidad_destino_codigo"),
            "movilidad_destino_nombre": intencion.get("movilidad_destino_nombre"),
            "movilidad_top_n": intencion.get("movilidad_top_n"),
            "movilidad_solo_externos": intencion.get("movilidad_solo_externos"),
            "movilidad_metrica": intencion.get("movilidad_metrica"),
            "movilidad_incluir_diagonal": intencion.get("movilidad_incluir_diagonal"),
            "movilidad_mostrar_todas": intencion.get("movilidad_mostrar_todas"),
            "movilidad_region_origen_codigo": intencion.get("movilidad_region_origen_codigo"),
            "movilidad_region_origen_nombre": intencion.get("movilidad_region_origen_nombre"),
            "movilidad_region_destino_codigo": intencion.get("movilidad_region_destino_codigo"),
            "movilidad_region_destino_nombre": intencion.get("movilidad_region_destino_nombre"),
            "movilidad_filtros_persona": intencion.get("movilidad_filtros_persona"),
            "migracion_indicador": intencion.get("migracion_indicador"),
            "migracion_nivel": intencion.get("migracion_nivel"),
            "migracion_origen_codigo": intencion.get("migracion_origen_codigo"),
            "migracion_origen_nombre": intencion.get("migracion_origen_nombre"),
            "migracion_destino_codigo": intencion.get("migracion_destino_codigo"),
            "migracion_destino_nombre": intencion.get("migracion_destino_nombre"),
            "migracion_top_n": intencion.get("migracion_top_n"),
            "migracion_metrica": intencion.get("migracion_metrica"),
            "migracion_incluir_diagonal": intencion.get("migracion_incluir_diagonal"),
            "migracion_mostrar_todas": intencion.get("migracion_mostrar_todas"),
            "migracion_region_origen_codigo": intencion.get("migracion_region_origen_codigo"),
            "migracion_region_origen_nombre": intencion.get("migracion_region_origen_nombre"),
            "migracion_region_destino_codigo": intencion.get("migracion_region_destino_codigo"),
            "migracion_region_destino_nombre": intencion.get("migracion_region_destino_nombre"),
            "migracion_ambito_region_codigo": intencion.get("migracion_ambito_region_codigo"),
            "migracion_ambito_region_nombre": intencion.get("migracion_ambito_region_nombre"),
            "migracion_filtros_persona": intencion.get("migracion_filtros_persona"),
        },
    }
    if respuesta["tipo_visualizacion"] == "matriz_od":
        respuesta.update({
            "flujos_od": resultado.get("flujos_od", []),
            "origenes_od": resultado.get("origenes_od", []),
            "destinos_od": resultado.get("destinos_od", []),
            "config_od": resultado.get("config_od", {}),
            "resumen_od": resultado.get("resumen_od", {}),
            "nivel_geografico": resultado.get("nivel_geografico", "comuna"),
            "nota": resultado.get("nota"),
        })
    elif respuesta["tipo_visualizacion"] == "barras_mapa":
        respuesta.update({
            "datos": resultado["datos"],
            "geometria": resultado["geometria"],
            "metrica": resultado["metrica"],
            "severidad_codigo": resultado["severidad_codigo"],
            "severidad_etiqueta": resultado["severidad_etiqueta"],
            "dimensiones": resultado.get("dimensiones", []),
            "nivel_geografico": resultado["nivel_geografico"],
            "nota": resultado.get("nota"),
        })
    elif respuesta["tipo_visualizacion"] == "tortas_mapa":
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
            "nota": resultado.get("nota"),
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
    except AmbiguedadDenominador as exc:
        return JSONResponse(status_code=409, content={
            "tipo": "seleccion_denominador", "mensaje": str(exc),
            "opciones": exc.opciones,
            "seleccion_previa": {
                "tabla_seleccionada": req.tabla_seleccionada,
                "variable_seleccionada": req.variable_seleccionada,
                "operacion_seleccionada": req.operacion_seleccionada,
            },
        })
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
        except AmbiguedadDenominador as exc:
            enviar("alternativas", {
                "tipo": "seleccion_denominador", "mensaje": str(exc),
                "opciones": exc.opciones,
                "seleccion_previa": {
                    "tabla_seleccionada": req.tabla_seleccionada,
                    "variable_seleccionada": req.variable_seleccionada,
                    "operacion_seleccionada": req.operacion_seleccionada,
                },
            })
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
    # VISOR_V31_FEEDBACK_AUDIT
    if os.getenv("DATABASE_URL", "").strip():
        _pg_feedback_save(req.feedback_id, req.valor)
    if req.valor == "positivo":
        interp = entrada["respuesta"].get("interpretacion") or {}
        # Una pregunta cuyo denominador fue escogido en un diálogo no puede
        # cachearse bajo el texto ambiguo original: en la próxima ejecución
        # debe volver a consultarse, salvo que la pregunta se reformule con el
        # denominador explícito.
        if not interp.get("denominador_requirio_confirmacion"):
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
