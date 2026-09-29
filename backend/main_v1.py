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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nl_parser import interpretar_consulta
from data_engine import ejecutar_consulta

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Visor Censo 2024 Chile (local)")

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


@app.post("/api/consulta")
def consulta(req: ConsultaRequest):
    pregunta = (req.pregunta or "").strip()
    if not pregunta:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")
    try:
        intencion = interpretar_consulta(pregunta)
        resultado = ejecutar_consulta(intencion)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado: {e}")

    return {
        "geojson": resultado["geojson"],
        "nivel_geografico": resultado["nivel_geografico"],
        "min": resultado["valores"]["min"],
        "max": resultado["valores"]["max"],
        "interpretacion": {
            "tabla": intencion["tabla"],
            "variable": intencion["variable"],
            "categoria_valor": intencion.get("categoria_valor"),
            "operacion": intencion.get("operacion"),
            "origen": intencion.get("_origen_interpretacion"),
        },
    }


@app.get("/api/salud")
def salud():
    return {"estado": "ok"}


# Sirve el frontend estático en http://localhost:8000/
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
