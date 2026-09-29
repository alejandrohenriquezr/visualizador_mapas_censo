@echo off
setlocal
cd /d "%~dp0.."
python scripts\preparar_volumenes.py
if errorlevel 1 exit /b %errorlevel%
