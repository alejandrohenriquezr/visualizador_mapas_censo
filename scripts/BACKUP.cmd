@echo off
setlocal
cd /d "%~dp0.."
python scripts\backup_postgres.py
if errorlevel 1 exit /b %errorlevel%
