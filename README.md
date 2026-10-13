# Visor Censo 2024

Versión del proyecto: **32.3.1** (`VERSION`).

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

- Windows 10/11 con Docker Desktop y Docker Compose v2, o Linux con Docker Engine y Compose v2.
- Los microdatos Parquet y la FileGDB oficial del Censo 2024. No se distribuyen en Git.
- Conexión a Internet durante la primera instalación para descargar imágenes Docker, la cartografía y el modelo de lenguaje.
- Espacio en disco y memoria suficientes para los datos, Docker y el modelo Ollama. El tamaño depende de los archivos oficiales y del modelo elegido.

En Windows instala Docker Desktop desde [la guía oficial](https://docs.docker.com/desktop/setup/install/windows-install/). La instalación requiere aceptar sus términos y puede requerir WSL 2 y virtualización habilitada. **No necesitas instalar Ollama en Windows**: el servicio `llm` lo ejecuta dentro de Docker.

## Instalación en Windows

1. Descarga los microdatos y la cartografía siguiendo [Instalación y requisitos](docs/00_INSTALACION.md). Extrae los tres Parquet en `datos\` y la carpeta `Cartografia_censo2024_Pais.gdb` en `cartografia\`.
2. Abre Docker Desktop y espera a que indique que está ejecutándose.
3. Ejecuta `INSTALAR.cmd`. El instalador crea `.env` si hace falta, comprueba los archivos requeridos, prepara los volúmenes, descarga el modelo Ollama, construye los servicios y valida el sitio.

El puerto predeterminado es 8010: abre [http://localhost:8010](http://localhost:8010). Si faltan datos, el instalador abre las páginas oficiales del INE y te muestra los nombres esperados. Las descargas grandes se hacen manualmente desde esas páginas oficiales; Docker, las imágenes y el modelo se descargan desde el instalador.

Para iniciar después una instalación ya configurada, ejecuta `scripts\ARRANCAR.cmd`.

## Instalación en Linux

Consulta [Instalación y requisitos](docs/00_INSTALACION.md) y usa los comandos Docker Compose allí descritos.

## Datos no incluidos

Los microdatos y la cartografía se excluyen deliberadamente de Git. Consulta [datos/README.md](datos/README.md) y [cartografia/README.md](cartografia/README.md).

## Documentación

- [Instalación y requisitos](docs/00_INSTALACION.md)
- [Índice documental](docs/00_INDICE.md)
- [Arquitectura](docs/01_ARQUITECTURA.md)
- [Modelo de datos](docs/02_MODELO_DATOS.md)
- [Motor de consultas](docs/03_MOTOR_CONSULTAS.md)
- [Reglas e indicadores](docs/04_REGLAS_INDICADORES.md)
- [LLM](docs/05_LLM.md)
- [Cartografía](docs/06_CARTOGRAFIA.md)
- [PostgreSQL](docs/07_POSTGRESQL.md)
- [Operación Docker](docs/08_OPERACION_DOCKER.md)
- [GitHub y CI](docs/09_GITHUB.md)
- [Seguridad y gobernanza](docs/10_SEGURIDAD_GOBERNANZA.md)

## Validación antes de GitHub

```cmd
python scripts\validate_repo.py .
```

El repositorio no incluye una licencia por defecto. Defina la licencia institucional antes de hacerlo público.

## Operación segura

La operación incluye respaldo PostgreSQL, actualización transaccional,
rollback automático, migraciones SQL versionadas y controles de salud.

Antes del primer arranque manual:

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

El backend registra tiempos por consulta y usa compresión cacheada de GeoJSON.
Para medir la transferencia cartográfica real:

```cmd
python scripts\benchmark_cartografia.py --base http://localhost:8010
```

Las respuestas estadísticas incluyen `diagnostico.consulta_id` y tiempos por
etapa; los endpoints HTTP agregan cabeceras de trazabilidad y `Server-Timing`.

### Benchmark de simplificación cartográfica

```cmd
python scripts\benchmark_simplificacion.py
```

Use sus resultados para elegir tolerancias que reduzcan coordenadas y tamaño
manteniendo bajo el error de área y cero geometrías inválidas.
