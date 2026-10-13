@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Instalador Visor Censo 2024

echo.
echo === Instalador del Visor Censo 2024 ===
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker no esta instalado o no esta en PATH.
  echo Instala Docker Desktop desde la guia oficial:
  echo https://docs.docker.com/desktop/setup/install/windows-install/
  start "" "https://docs.docker.com/desktop/setup/install/windows-install/"
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo ERROR: se requiere Docker Compose v2. Actualiza Docker Desktop.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop no esta iniciado o el motor no esta disponible.
  echo Inicia Docker Desktop, espera que este listo y vuelve a ejecutar INSTALAR.cmd.
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  if errorlevel 1 (
    echo ERROR: no se pudo crear .env desde .env.example.
    exit /b 1
  )
  echo Se creo .env y se abrira en el Bloc de notas.
  echo Cambia POSTGRES_PASSWORD, guarda el archivo y vuelve a ejecutar INSTALAR.cmd.
  notepad ".env"
  exit /b 2
)
findstr /x /c:"POSTGRES_PASSWORD=CAMBIAR_ESTA_CLAVE" ".env" >nul
if not errorlevel 1 (
  echo ERROR: cambia POSTGRES_PASSWORD en .env antes de iniciar el sitio.
  notepad ".env"
  exit /b 1
)

set "FALTAN_DATOS="
if not exist "datos\personas_censo2024.parquet" set "FALTAN_DATOS=1"
if not exist "datos\hogares_censo2024.parquet" set "FALTAN_DATOS=1"
if not exist "datos\viviendas_censo2024.parquet" set "FALTAN_DATOS=1"
if not exist "cartografia\Cartografia_censo2024_Pais.gdb\" set "FALTAN_DATOS=1"
if defined FALTAN_DATOS (
  echo Faltan microdatos o cartografia en las rutas esperadas.
  echo Microdatos Censo 2024: https://censo2024.ine.gob.cl/resultados/
  echo Cartografia INE: https://censo2024.ine.gob.cl/ine-publica-bases-de-datos-a-nivel-de-manzana-y-cartografia-del-censo-de-poblacion-y-vivienda-2024/
  start "" "https://censo2024.ine.gob.cl/resultados/"
  start "" "https://censo2024.ine.gob.cl/ine-publica-bases-de-datos-a-nivel-de-manzana-y-cartografia-del-censo-de-poblacion-y-vivienda-2024/"
  echo.
  echo Extrae los tres Parquet en datos\ y la carpeta Cartografia_censo2024_Pais.gdb en cartografia\.
  echo Consulta docs\00_INSTALACION.md para los nombres y pasos completos.
  exit /b 1
)

docker compose config -q
if errorlevel 1 (
  echo ERROR: configuracion Docker Compose invalida. Revisa .env.
  exit /b 1
)

echo Preparando volumenes persistentes...
docker volume create visor_censo_postgres >nul
if errorlevel 1 exit /b %errorlevel%
docker volume create visor_censo_ollama >nul
if errorlevel 1 exit /b %errorlevel%
docker volume create visor_censo_cartography_cache >nul
if errorlevel 1 exit /b %errorlevel%

echo Iniciando PostgreSQL, cartografia y Ollama...
docker compose up -d db llm cartography
if errorlevel 1 exit /b %errorlevel%

call scripts\PULL_LLM.cmd
if errorlevel 1 exit /b %errorlevel%

echo Construyendo backend y frontend...
docker compose up -d --build backend frontend
if errorlevel 1 exit /b %errorlevel%

set "PORT=8010"
for /f "tokens=1,* delims==" %%A in ('findstr /b "VISOR_PORT=" .env') do set "PORT=%%B"
echo.
echo Esperando que el sitio responda en http://localhost:%PORT%/healthz ...
set "LISTO="
for /l %%I in (1,1,60) do (
  curl.exe --fail --silent "http://localhost:%PORT%/healthz" >nul 2>&1
  if not errorlevel 1 set "LISTO=1"
  if defined LISTO goto :sitio_listo
  ping 127.0.0.1 -n 3 >nul
)
echo.
echo ERROR: el sitio no respondio dentro de 2 minutos.
echo Revisa el estado con scripts\\HEALTH.cmd y los logs con scripts\\LOGS.cmd.
exit /b 1

:sitio_listo
echo.
echo Instalacion lista: http://localhost:%PORT%/
start "" "http://localhost:%PORT%/"
exit /b 0
