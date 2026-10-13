@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
if not exist ".env" (
  echo ERROR: falta .env. Copia .env.example a .env y configuralo primero.
  exit /b 1
)
set "MODEL="
for /f "tokens=1,* delims==" %%A in ('findstr /b "OLLAMA_MODEL=" .env') do set "MODEL=%%B"
if not defined MODEL set "MODEL=qwen2.5:3b-instruct"
echo Esperando el servicio Ollama dentro de Docker...
docker compose up -d llm
if errorlevel 1 exit /b %errorlevel%
set "READY="
for /l %%I in (1,1,30) do (
  docker compose exec -T llm ollama list >nul 2>&1
  if not errorlevel 1 set "READY=1"
  if defined READY goto :pull
  ping 127.0.0.1 -n 3 >nul
)
echo ERROR: Ollama no respondio despues de 60 segundos.
docker compose logs --tail=60 llm
exit /b 1
:pull
echo Descargando modelo: %MODEL%
docker compose exec -T llm ollama pull "%MODEL%"
if errorlevel 1 exit /b %errorlevel%
echo Modelo listo: %MODEL%
exit /b 0
