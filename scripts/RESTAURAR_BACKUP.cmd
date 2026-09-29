@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
  echo Uso: scripts\RESTAURAR_BACKUP.cmd backups\archivo.dump
  exit /b 2
)
python scripts\restore_postgres.py "%~1"
if errorlevel 1 exit /b %errorlevel%
