# Visor Censo 2024

Visor web para consultas en lenguaje natural sobre personas, hogares y viviendas del Censo 2024, con mapas temáticos, matrices de migración/movilidad, indicadores derivados y exportación Excel.

## Arquitectura

El repositorio usa cinco servicios Docker:

1. **frontend**: Nginx + interfaz web/Leaflet.
2. **backend**: FastAPI + reglas semánticas + DuckDB + exportación Excel.
3. **db**: PostgreSQL para consultas aprobadas, resultados pendientes y feedback.
4. **llm**: Ollama para interpretación cuando las reglas deterministas no bastan.
5. **cartography**: FastAPI + GeoPandas/GDAL + caché de geometrías.

Solo `frontend` publica un puerto al host. Los demás servicios se comunican por la red privada de Docker.

## Requisitos

- Windows 10/11 o Linux con Docker Engine/Compose v2.
- Docker Desktop en Windows.
- Microdatos Parquet y FileGDB censal disponibles localmente.
- Recursos suficientes para Ollama y cartografía.

## Instalación rápida

```cmd
copy .env.example .env
```

Edite `.env`, especialmente `POSTGRES_PASSWORD`, rutas host y nombre de la GDB. Después:

```cmd
docker compose up -d db llm cartography
scripts\PULL_LLM.cmd
docker compose up -d --build backend frontend
python scripts\smoke_test.py http://localhost:8010
```

Abra `http://localhost:8010/`.

## Datos no incluidos

Los microdatos y la cartografía están excluidos deliberadamente de Git. Consulte `datos/README.md` y `cartografia/README.md`.

## Documentación

- `docs/01_ARQUITECTURA.md`
- `docs/02_MODELO_DATOS.md`
- `docs/03_MOTOR_CONSULTAS.md`
- `docs/04_REGLAS_INDICADORES.md`
- `docs/05_LLM.md`
- `docs/06_CARTOGRAFIA.md`
- `docs/07_POSTGRESQL.md`
- `docs/08_OPERACION_DOCKER.md`
- `docs/09_GITHUB.md`
- `docs/10_SEGURIDAD_GOBERNANZA.md`

## Validación antes de GitHub

```cmd
python scripts\validate_repo.py .
```

El repositorio no incluye una licencia por defecto. Defina la licencia institucional antes de hacerlo público.
