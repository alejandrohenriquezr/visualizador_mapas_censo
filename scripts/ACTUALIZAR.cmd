@echo off
setlocal
cd /d "%~dp0.."
python scripts\actualizar.py
if errorlevel 1 exit /b %errorlevel%
