@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   VISOR CENSO 2024 - REPARACION V38.1
echo ============================================================
echo.

if not exist "backend\main.py" (
  echo ERROR: copiar estos archivos en la raiz del proyecto:
  echo        C:\mapa_censo_interactivo_github
  echo.
  pause
  exit /b 1
)

python reparar_v38_1.py .
if errorlevel 1 (
  echo.
  echo ERROR: no se pudo aplicar la reparacion V38.1.
  pause
  exit /b 1
)

echo.
echo Reconstruyendo los servicios...
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo El codigo fue reparado, pero Docker no pudo reconstruir.
  echo Ejecutar manualmente: docker compose up -d --build
  pause
  exit /b 1
)

echo.
echo Ejecutando verificaciones V38.1...

echo [1/6] Resolutor directo...
docker compose exec -T backend python -c "from labor_mobility_resolver import resolver_movilidad_laboral; import json; i=resolver_movilidad_laboral('movilidad laboral por region'); print(json.dumps({k:i.get(k) for k in ('tipo_consulta','variable','movilidad_nivel','nivel_geografico','movilidad_indicador','_origen_interpretacion')}, ensure_ascii=True, sort_keys=True)); assert i.get('movilidad_nivel')=='region'; assert i.get('nivel_geografico')=='region'; assert i.get('variable')=='p44_lug_trab'"
if errorlevel 1 goto :error_movilidad

echo [2/6] Parser completo...
docker compose exec -T backend python -c "from nl_parser import interpretar_consulta; import json; i=interpretar_consulta('movilidad laboral por region'); print(json.dumps({k:i.get(k) for k in ('tipo_consulta','variable','movilidad_nivel','nivel_geografico','movilidad_indicador','_origen_interpretacion')}, ensure_ascii=True, sort_keys=True)); assert i.get('movilidad_nivel')=='region'; assert i.get('nivel_geografico')=='region'; assert i.get('variable')=='p44_lug_trab'"
if errorlevel 1 goto :error_parser

echo [3/6] Piramide auxiliar...
docker compose exec -T backend python -c "from pathlib import Path; s=Path('/app/backend/data_engine.py').read_text(encoding='utf-8'); assert 'edad_sexo_auxiliar_v38' in s; print('piramide auxiliar: OK')"
if errorlevel 1 goto :error_piramide

echo [4/6] Invalidacion de cache...
docker compose exec -T backend python -c "from pathlib import Path; s=Path('/app/backend/main.py').read_text(encoding='utf-8'); assert 'BEGIN V38.1 INVALIDACION CACHE' in s; print('cache V38.1: OK')"
if errorlevel 1 goto :error_cache

echo [5/6] Cancelacion y aprendizaje...
docker compose exec -T backend python -c "import main, state_store; assert hasattr(main,'cancelar_consulta_v38'); assert hasattr(state_store,'learning_cancel'); print('cancelacion backend: OK')"
if errorlevel 1 goto :error_cancelacion

echo [6/6] Frontend ESC/piramide...
docker compose exec -T frontend grep -q "v38-esc-y-piramide-simple" /usr/share/nginx/html/index.html
if errorlevel 1 goto :error_frontend

echo.
echo ============================================================
echo V38.1 INSTALADO Y VERIFICACIONES APROBADAS
echo ============================================================
echo.
echo Recargar el navegador con Ctrl+F5 y probar:
echo   distribucion de edad por region
echo   movilidad laboral por region
echo   una consulta lenta y luego ESC
echo.
echo Este proceso NO modifica GitHub.
pause
exit /b 0

:error_movilidad
echo.
echo ERROR en el resolutor directo. Copiar las lineas JSON mostradas arriba.
pause
exit /b 1

:error_parser
echo.
echo ERROR en el parser completo. Copiar las lineas JSON mostradas arriba.
pause
exit /b 1

:error_piramide
echo ERROR: no se encontro la piramide auxiliar V38.
pause
exit /b 1

:error_cache
echo ERROR: no se instalo la invalidacion de cache V38.1.
pause
exit /b 1

:error_cancelacion
echo ERROR: no se encontro la cancelacion ESC/aprendizaje.
pause
exit /b 1

:error_frontend
echo ERROR: el frontend V38 no esta en el contenedor.
pause
exit /b 1
