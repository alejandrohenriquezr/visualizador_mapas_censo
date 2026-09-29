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


## Operación segura

La versión 32.1 incorpora respaldo PostgreSQL, actualización transaccional,
rollback automático, migraciones SQL versionadas y salud detallada.

Antes del primer arranque:

```cmd
scripts\PREPARAR_VOLUMENES.cmd
```

Operación habitual:

```cmd
scripts\BACKUP.cmd
scripts\ACTUALIZAR.cmd
scripts\HEALTH.cmd
```

Restauración explícita:

```cmd
scripts\RESTAURAR_BACKUP.cmd backups\visor_censo_YYYYMMDD_HHMMSS.dump
```

Las migraciones se encuentran en `database/migrations/` y el backend las
aplica antes de iniciar Uvicorn.


## Diagnóstico de rendimiento

La v32.2 agrega métricas de tiempo por consulta y compresión cacheada de GeoJSON.
Para medir la transferencia cartográfica real:

```cmd
python scripts\benchmark_cartografia.py --base http://localhost:8010
```

Las respuestas estadísticas incluyen `diagnostico.consulta_id` y tiempos por
etapa; los endpoints HTTP agregan cabeceras de trazabilidad y `Server-Timing`.


### Benchmark de simplificación cartográfica

La v32.3 permite evaluar tolerancias distintas para región, provincia y comuna
sin modificar el código. Ejecute:

```cmd
python scripts\benchmark_simplificacion.py
```

Use sus resultados para elegir tolerancias que reduzcan coordenadas y tamaño
manteniendo bajo el error de área y cero geometrías inválidas.
