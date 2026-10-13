@echo off
setlocal EnableExtensions

REM Cambia esta ruta si el repositorio esta en otra carpeta.
set "PROJECT_DIR=C:\mapa_censo_interactivo_github"

REM Verifica que la carpeta indicada exista.
if not exist "%PROJECT_DIR%\" (
    echo No existe la carpeta del proyecto:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

REM Verifica que Git este instalado y disponible en PATH.
where git >nul 2>&1
if errorlevel 1 (
    echo No se encontro Git en PATH. Instala Git o abre Git Bash desde el proyecto.
    pause
    exit /b 1
)

REM Entra al repositorio y verifica que tenga metadatos Git.
cd /d "%PROJECT_DIR%"
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo La carpeta no parece ser un repositorio Git:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

echo Repositorio:
git remote -v
echo.
echo Rama actual:
git branch --show-current
echo.
echo Cambios detectados:
git status --short

echo.
set /p "CONFIRMAR=Se agregaran todos los cambios del repositorio. Continuar? (S/N): "
if /I not "%CONFIRMAR%"=="S" (
    echo Operacion cancelada.
    pause
    exit /b 0
)

REM Incorpora los cambios nuevos, modificados y eliminados al area de preparacion.
git add -A
if errorlevel 1 (
    echo No fue posible preparar los cambios.
    pause
    exit /b 1
)

REM Si no hay cambios preparados, termina sin crear un commit.
git diff --cached --quiet
if not errorlevel 1 (
    echo No hay cambios para guardar. El repositorio ya esta sincronizado localmente.
    pause
    exit /b 0
)

echo.
set /p "MENSAJE=Escribe el mensaje del commit: "
if "%MENSAJE%"=="" set "MENSAJE=Actualizacion del visor censal"

REM Guarda los cambios en la rama actual.
git commit -m "%MENSAJE%"
if errorlevel 1 (
    echo No se pudo crear el commit. Revisa el mensaje y el estado de Git.
    pause
    exit /b 1
)

REM Obtiene cambios remotos y los integra antes de publicar el commit local.
git pull --rebase
if errorlevel 1 (
    echo.
    echo No se pudo integrar la version de GitHub.
    echo Revisa los conflictos indicados por Git; no se realizo el push.
    pause
    exit /b 1
)

REM Publica la rama actual en el remoto configurado.
git push
if errorlevel 1 (
    echo.
    echo No se pudo publicar en GitHub. Revisa la conexion, credenciales y rama remota.
    pause
    exit /b 1
)

echo.
echo Sincronizacion completada.
pause
endlocal
