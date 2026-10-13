@echo off
setlocal

REM Cambia esta ruta si el proyecto está en otra carpeta.
set "PROJECT_DIR=C:\mapa_censo_interactivo_github"

if not exist "%PROJECT_DIR%\docker-compose.yml" if not exist "%PROJECT_DIR%\compose.yml" if not exist "%PROJECT_DIR%\docker-compose.yaml" if not exist "%PROJECT_DIR%\compose.yaml" (
    echo No se encontro un archivo Compose en:
    echo %PROJECT_DIR%
    echo.
    echo Edita PROJECT_DIR en este archivo y vuelve a intentarlo.
    pause
    exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
    echo No se encontro Docker en PATH. Abre Docker Desktop y vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo No se pudo acceder a la carpeta del proyecto:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

echo Levantando el visor censal...
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo Hubo un error al levantar el proyecto. Revisa Docker Desktop y los archivos del proyecto.
    pause
    exit /b 1
)

echo.
echo Estado de los servicios:
docker compose ps
echo.
echo Prueba el sitio desde este computador usando la direccion y el puerto publicados arriba.
echo Para compartirlo en la intranet, usa la IP de este computador y el mismo puerto.
pause
endlocal
